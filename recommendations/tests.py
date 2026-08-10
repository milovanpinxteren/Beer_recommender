"""
Tests for the beer recommendation service.

All external I/O (Shopify GraphQL, Untappd, Celery brokers) is mocked —
the suite runs offline. Written alongside the Django 4.2 → 5.2 upgrade
to pin down user-facing behavior.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from io import StringIO

from recommendations.models import Beer, CachedUserProfile, SyncLog
from recommendations.services.style_mapper import (
    get_style_category,
    get_country_region,
    get_all_style_categories,
    get_all_country_regions,
)
from recommendations.services.shopify_sync import ShopifySyncService, run_sync
from recommendations.services.recommendation_engine import RecommendationEngine


def make_beer(**overrides):
    """Create a Beer with sensible defaults; derived fields auto-compute on save."""
    defaults = {
        "shopify_id": overrides.get("shopify_id", str(make_beer._next_id)),
        "handle": "test-beer",
        "title": "Test Beer",
        "vendor": "Test Brewery",
        "style": "IPA",
        "country": "Belgium",
        "price": Decimal("8.50"),
        "abv": 6.5,
        "untappd_rating": 3.9,
        "untappd_rating_count": 100,
        "in_stock": True,
        "is_active": True,
    }
    defaults.update(overrides)
    make_beer._next_id += 1
    return Beer.objects.create(**defaults)


make_beer._next_id = 1000


def make_profile_data(**overrides):
    """A minimal but realistic taste profile as the scrapers produce it."""
    data = {
        "username": "testuser",
        "total_checkins": 250,
        "unique_beers": 180,
        "avg_rating": 3.8,
        "preferred_styles": [{"style": "Stout", "avg_rating": 4.4, "count": 30}],
        "preferred_breweries": [{"brewery": "Test Brewery", "avg_rating": 4.2, "count": 10}],
        "style_counts": {"Stout": 30, "IPA": 12},
        "brewery_counts": {"Test Brewery": 10},
        "abv_preference": {"avg": 8.0, "preferred_min": 6.0, "preferred_max": 11.0,
                           "min": 4.0, "max": 13.0},
        "tried_beers": [],
    }
    data.update(overrides)
    return data


class StyleMapperTests(TestCase):
    def test_soort_bier_takes_priority(self):
        self.assertEqual(get_style_category("Imperial Stout", "IPA - New England"), "Stout")

    def test_untappd_style_fallback(self):
        self.assertEqual(get_style_category(None, "IPA - New England / Hazy"), "IPA")

    def test_untappd_style_unmapped_uses_first_part(self):
        self.assertEqual(get_style_category(None, "Mead - Braggot"), "Mead")

    def test_unmapped_soort_bier_returned_verbatim(self):
        self.assertEqual(get_style_category("Vruchtenbier", None), "Vruchtenbier")

    def test_nothing_known(self):
        self.assertEqual(get_style_category(None, None), "Unknown")

    def test_country_exact_and_case_insensitive(self):
        self.assertEqual(get_country_region("Belgium"), "Western Europe")
        self.assertEqual(get_country_region("belgium"), "Western Europe")

    def test_country_unknown_and_empty(self):
        self.assertEqual(get_country_region("Atlantis"), "Other")
        self.assertEqual(get_country_region(""), "Unknown")

    def test_category_and_region_lists_are_sorted_unique(self):
        cats = get_all_style_categories()
        self.assertEqual(cats, sorted(set(cats)))
        regions = get_all_country_regions()
        self.assertEqual(regions, sorted(set(regions)))


class BeerModelTests(TestCase):
    def test_save_computes_derived_fields(self):
        beer = make_beer(style="Imperial Stout", country="Belgium", price=Decimal("15.00"))
        self.assertEqual(beer.style_category, "Stout")
        self.assertEqual(beer.country_region, "Western Europe")
        self.assertEqual(beer.price_bucket, "premium")

    def test_price_buckets(self):
        cases = [
            (Decimal("4.99"), "budget"),
            (Decimal("5.00"), "standard"),
            (Decimal("10.00"), "premium"),
            (Decimal("20.00"), "high-end"),
            (Decimal("40.00"), "luxury"),
            (None, "unknown"),
        ]
        for price, bucket in cases:
            beer = make_beer(price=price)
            self.assertEqual(beer.price_bucket, bucket, f"price {price}")


class CachedProfileTests(TestCase):
    def _age(self, profile, hours):
        # updated_at is auto_now; backdate it via queryset update
        CachedUserProfile.objects.filter(pk=profile.pk).update(
            updated_at=timezone.now() - timedelta(hours=hours)
        )
        profile.refresh_from_db()

    def test_is_expired_explicit_hours(self):
        p = CachedUserProfile.objects.create(
            untappd_username="alice", profile_type="untappd", is_valid=True
        )
        self.assertFalse(p.is_expired(hours=24))
        self._age(p, 25)
        self.assertTrue(p.is_expired(hours=24))

    def test_is_expired_default_uses_setting(self):
        p = CachedUserProfile.objects.create(
            untappd_username="bob", profile_type="untappd", is_valid=True
        )
        self._age(p, 48)
        with override_settings(UNTAPPD_PROFILE_CACHE_HOURS=24):
            self.assertTrue(p.is_expired())
        with override_settings(UNTAPPD_PROFILE_CACHE_HOURS=168):
            self.assertFalse(p.is_expired())

    def test_cache_helpers(self):
        from recommendations.views import (
            has_valid_cache_username,
            has_valid_cache_email,
            has_fresh_invalid_cache_username,
        )

        self.assertFalse(has_valid_cache_username("nobody"))

        CachedUserProfile.objects.create(
            untappd_username="alice", profile_type="untappd", is_valid=True
        )
        self.assertTrue(has_valid_cache_username("alice"))
        self.assertFalse(has_valid_cache_username("alice", force_refresh=True))

        CachedUserProfile.objects.create(
            untappd_username="private_guy", profile_type="untappd", is_valid=False,
            error_message="Profile is private",
        )
        self.assertTrue(has_fresh_invalid_cache_username("private_guy"))

        CachedUserProfile.objects.create(
            untappd_username="", email="a@b.nl", profile_type="shopify", is_valid=True
        )
        self.assertTrue(has_valid_cache_email("a@b.nl"))


def shopify_product_node(**overrides):
    """A realistic Shopify GraphQL product node."""
    node = {
        "id": "gid://shopify/Product/123456",
        "handle": "westvleteren-12",
        "title": "Westvleteren 12",
        "vendor": "House of Beers",
        "productType": "Beer",
        "status": "ACTIVE",
        "variants": {"edges": [{"node": {
            "id": "gid://shopify/ProductVariant/777",
            "price": "12.50",
            "inventoryQuantity": 6,
        }}]},
        "featuredImage": {"url": "https://cdn.shopify.com/img.jpg"},
        "metafields": {"edges": [
            {"node": {"namespace": "custom", "key": "alcoholpercentage", "value": "10.2", "type": "number_decimal"}},
            {"node": {"namespace": "custom", "key": "soort_bier", "value": "Quadrupel", "type": "single_line_text_field"}},
            {"node": {"namespace": "custom", "key": "land_van_herkomst", "value": "Belgium", "type": "single_line_text_field"}},
            {"node": {"namespace": "custom", "key": "untappd_rating", "value": "4.42", "type": "number_decimal"}},
            {"node": {"namespace": "custom", "key": "untappd_rating_count", "value": "150000", "type": "number_integer"}},
            {"node": {"namespace": "custom", "key": "rijpingsmethode", "value": '["Oak barrel", "Bourbon"]', "type": "list.single_line_text_field"}},
            {"node": {"namespace": "custom", "key": "untappd_link", "value": '{"url": "https://untappd.com/b/westvleteren-12/5678"}', "type": "link"}},
            {"node": {"namespace": "custom", "key": "merk", "value": "Westvleteren", "type": "single_line_text_field"}},
        ]},
    }
    node.update(overrides)
    return node


@override_settings(SHOPIFY_DOMAIN="test.myshopify.com", SHOPIFY_ACCESS_TOKEN="x",
                   SHOPIFY_API_VERSION="2026-04")
class ShopifySyncTransformTests(TestCase):
    def setUp(self):
        self.service = ShopifySyncService()

    def test_transform_product_full(self):
        data = self.service.transform_product(shopify_product_node())
        self.assertEqual(data["shopify_id"], "123456")
        self.assertEqual(data["variant_id"], "777")
        self.assertEqual(data["price"], Decimal("12.50"))
        self.assertEqual(data["abv"], 10.2)
        self.assertEqual(data["style"], "Quadrupel")
        self.assertEqual(data["country"], "Belgium")
        self.assertEqual(data["untappd_rating"], 4.42)
        self.assertEqual(data["untappd_rating_count"], 150000)
        self.assertEqual(data["rijpingsmethode"], "Oak barrel, Bourbon")
        self.assertEqual(data["merk"], "Westvleteren")
        self.assertEqual(data["untappd_url"], "https://untappd.com/b/westvleteren-12/5678")
        self.assertTrue(data["in_stock"])
        self.assertEqual(data["product_url"], "https://houseofbeers.nl/products/westvleteren-12")
        self.assertTrue(data["is_active"])

    def test_transform_out_of_stock_and_missing_bits(self):
        node = shopify_product_node(
            variants={"edges": [{"node": {"id": "gid://shopify/ProductVariant/9",
                                          "price": "5.00", "inventoryQuantity": 0}}]},
            featuredImage=None,
            metafields={"edges": []},
        )
        data = self.service.transform_product(node)
        self.assertFalse(data["in_stock"])
        self.assertEqual(data["image_url"], "")
        self.assertIsNone(data["abv"])
        self.assertIsNone(data["untappd_rating"])

    def test_rating_value_formats(self):
        self.assertEqual(self.service._parse_rating_value("4.37"), 4.37)
        self.assertEqual(self.service._parse_rating_value('{"value": 4.37}'), 4.37)
        self.assertIsNone(self.service._parse_rating_value("not-a-number"))
        self.assertIsNone(self.service._parse_rating_value(None))

    def test_link_value_formats(self):
        self.assertEqual(
            self.service._parse_link_value('{"url": "https://x.nl"}'), "https://x.nl")
        self.assertEqual(self.service._parse_link_value("https://plain.nl"), "https://plain.nl")
        self.assertEqual(self.service._parse_link_value("garbage"), "")
        self.assertEqual(self.service._parse_link_value(""), "")


@override_settings(SHOPIFY_DOMAIN="test.myshopify.com", SHOPIFY_ACCESS_TOKEN="x",
                   SHOPIFY_API_VERSION="2026-04")
class ShopifySyncRunTests(TestCase):
    def test_sync_creates_updates_and_deactivates(self):
        # An existing beer that will be updated, and one that disappears
        make_beer(shopify_id="123456", title="Old title")
        gone = make_beer(shopify_id="999", title="Vanished beer")

        with patch.object(ShopifySyncService, "fetch_all_products",
                          return_value=iter([shopify_product_node()])):
            service = ShopifySyncService()
            stats = service.sync_all()

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["deactivated"], 1)

        updated = Beer.objects.get(shopify_id="123456")
        self.assertEqual(updated.title, "Westvleteren 12")
        self.assertEqual(updated.style_category, "Belgian")  # Quadrupel → Belgian
        gone.refresh_from_db()
        self.assertFalse(gone.is_active)

    def test_sync_records_error_and_continues(self):
        bad = shopify_product_node()
        del bad["handle"]  # transform will raise KeyError
        good = shopify_product_node(id="gid://shopify/Product/2", handle="ok-beer")

        with patch.object(ShopifySyncService, "fetch_all_products",
                          return_value=iter([bad, good])):
            stats = ShopifySyncService().sync_all()

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(len(stats["errors"]), 1)
        self.assertTrue(Beer.objects.filter(handle="ok-beer").exists())

    def test_run_sync_writes_completed_log(self):
        with patch.object(ShopifySyncService, "fetch_all_products",
                          return_value=iter([shopify_product_node()])):
            stats = run_sync()

        log = SyncLog.objects.latest("started_at")
        self.assertEqual(log.status, "completed")
        self.assertEqual(log.products_processed, stats["processed"])
        self.assertIsNotNone(log.completed_at)

    def test_run_sync_failure_writes_failed_log_and_raises(self):
        with patch.object(ShopifySyncService, "sync_all", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                run_sync()

        log = SyncLog.objects.latest("started_at")
        self.assertEqual(log.status, "failed")
        self.assertIn("boom", log.errors)


class RecommendationEngineTests(TestCase):
    def setUp(self):
        self.stout = make_beer(
            title="Midnight Velvet", vendor="Dark Arts", style="Imperial Stout",
            abv=10.0, untappd_rating=4.3, price=Decimal("9.00"))
        self.lager = make_beer(
            title="Sunny Fields", vendor="Nobody Brew", style="Pilsner",
            abv=4.8, untappd_rating=3.6, price=Decimal("3.00"))
        self.out_of_stock = make_beer(
            title="Ghost Bottle", vendor="Dark Arts", style="Imperial Stout",
            abv=11.0, untappd_rating=4.6, in_stock=False)
        self.unrated = make_beer(
            title="Mystery Can", vendor="Unknown", style="IPA", untappd_rating=None)

    def test_preferred_style_outranks_unknown_style(self):
        engine = RecommendationEngine(make_profile_data())
        result = engine.get_recommendations(limit=10)
        titles = [r.beer.title for r in result.recommendations]
        self.assertIn("Midnight Velvet", titles)
        stout_score = next(r.score for r in result.recommendations if r.beer.title == "Midnight Velvet")
        for r in result.recommendations:
            if r.beer.title == "Sunny Fields":
                self.assertLess(r.score, stout_score)

    def test_out_of_stock_and_unrated_excluded_by_default(self):
        engine = RecommendationEngine(make_profile_data())
        result = engine.get_recommendations(limit=10)
        titles = [r.beer.title for r in result.recommendations]
        self.assertNotIn("Ghost Bottle", titles)
        self.assertNotIn("Mystery Can", titles)

    def test_include_out_of_stock_filter(self):
        engine = RecommendationEngine(make_profile_data())
        result = engine.get_recommendations(limit=10, include_out_of_stock=True)
        titles = [r.beer.title for r in result.recommendations]
        self.assertIn("Ghost Bottle", titles)

    def test_style_and_price_filters(self):
        engine = RecommendationEngine(make_profile_data())
        result = engine.get_recommendations(limit=10, style_filter="Stout")
        for r in result.recommendations:
            self.assertEqual(r.beer.style_category, "Stout")

        result = engine.get_recommendations(limit=10, price_max=5.0)
        for r in result.recommendations:
            self.assertLessEqual(float(r.beer.price), 5.0)

    def test_tried_beer_separated_from_main_recommendations(self):
        profile = make_profile_data(tried_beers=[
            {"name": "Midnight Velvet", "brewery": "Dark Arts", "rating": 4.5,
             "url": "https://untappd.com/b/midnight-velvet/1"},
        ])
        engine = RecommendationEngine(profile)
        result = engine.get_recommendations(limit=10)
        main_titles = [r.beer.title for r in result.recommendations]
        tried_titles = [r.beer.title for r in result.tried_beers]
        self.assertNotIn("Midnight Velvet", main_titles)
        self.assertIn("Midnight Velvet", tried_titles)

    def test_profile_summary_shape(self):
        engine = RecommendationEngine(make_profile_data())
        result = engine.get_recommendations(limit=5)
        summary = result.profile_summary
        self.assertEqual(summary["total_checkins"], 250)
        self.assertIn("Stout", summary["top_styles"])
        self.assertEqual(summary["abv_range"], "6.0-11.0%")


class CatalogApiTests(TestCase):
    def setUp(self):
        self.belgian = make_beer(title="Quad Royale", style="Quadrupel",
                                 country="Belgium", untappd_rating=4.2)
        self.german = make_beer(title="Kellerbier Krug", style="Kellerbier",
                                country="Germany", untappd_rating=3.4)
        self.hidden = make_beer(title="Sold Out Special", style="Quadrupel",
                                country="Belgium", in_stock=False)

    def test_health(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "healthy")

    def test_beer_list_and_filters(self):
        resp = self.client.get("/api/beers/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 3)

        resp = self.client.get("/api/beers/", {"style": "Belgian"})
        titles = [b["title"] for b in resp.json()["results"]]
        self.assertIn("Quad Royale", titles)
        self.assertNotIn("Kellerbier Krug", titles)

        resp = self.client.get("/api/beers/", {"in_stock": "true"})
        self.assertEqual(resp.json()["total"], 2)

        resp = self.client.get("/api/beers/", {"min_rating": "4.0"})
        self.assertEqual(resp.json()["total"], 1)

        # Bad min_rating is ignored, not an error
        resp = self.client.get("/api/beers/", {"min_rating": "high"})
        self.assertEqual(resp.status_code, 200)

    def test_beer_list_pagination_and_limit_cap(self):
        resp = self.client.get("/api/beers/", {"limit": "1", "offset": "1"})
        body = resp.json()
        self.assertEqual(body["limit"], 1)
        self.assertEqual(len(body["results"]), 1)

        resp = self.client.get("/api/beers/", {"limit": "9999"})
        self.assertEqual(resp.json()["limit"], 200)

    def test_beer_detail(self):
        resp = self.client.get(f"/api/beers/{self.belgian.shopify_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "Quad Royale")

        resp = self.client.get("/api/beers/000000/")
        self.assertEqual(resp.status_code, 404)

    def test_styles_and_countries_default_in_stock(self):
        resp = self.client.get("/api/styles/")
        styles = {s["category"]: s["count"] for s in resp.json()["styles"]}
        self.assertEqual(styles.get("Belgian"), 1)  # sold-out quad not counted

        resp = self.client.get("/api/countries/")
        countries = {c["country"]: c["count"] for c in resp.json()["countries"]}
        self.assertEqual(countries.get("Belgium"), 1)

        resp = self.client.get("/api/styles/", {"in_stock": "false"})
        styles = {s["category"]: s["count"] for s in resp.json()["styles"]}
        self.assertEqual(styles.get("Belgian"), 2)

    def test_sync_status(self):
        resp = self.client.get("/api/sync/status/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["last_sync"])
        self.assertEqual(resp.json()["total_beers"], 3)

        SyncLog.objects.create(status="completed", completed_at=timezone.now())
        resp = self.client.get("/api/sync/status/")
        self.assertIsNotNone(resp.json()["last_sync"])


class RecommendationsApiTests(TestCase):
    def test_invalid_request_400(self):
        resp = self.client.post("/api/recommendations/", {}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    @patch("recommendations.views.generate_recommendations_email_task")
    def test_uncached_email_dispatches_async_task(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="task-123")
        resp = self.client.post(
            "/api/recommendations/", {"email": "new@customer.nl"},
            content_type="application/json")
        self.assertEqual(resp.status_code, 202)
        body = resp.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["task_id"], "task-123")
        self.assertEqual(body["profile_type"], "shopify")
        mock_task.delay.assert_called_once()

    @patch("recommendations.views.generate_recommendations_task")
    def test_uncached_username_dispatches_async_task(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="task-456")
        resp = self.client.post(
            "/api/recommendations/", {"username": "hopdrinker"},
            content_type="application/json")
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["profile_type"], "untappd")

    def test_cached_email_returns_recommendations_synchronously(self):
        make_beer(title="Midnight Velvet", vendor="Dark Arts",
                  style="Imperial Stout", abv=10.0, untappd_rating=4.3)
        CachedUserProfile.objects.create(
            untappd_username="", email="known@customer.nl",
            profile_type="shopify", is_valid=True,
        )
        profile = make_profile_data(username="known@customer.nl",
                                    display_name="Known Customer")

        with patch("recommendations.services.shopify_customer.get_or_create_profile_from_email",
                   return_value=profile):
            resp = self.client.post(
                "/api/recommendations/", {"email": "known@customer.nl"},
                content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["profile_type"], "shopify")
        rec_titles = [r["beer"]["title"] for r in body["recommendations"]]
        self.assertIn("Midnight Velvet", rec_titles)
        self.assertIn("profile_summary", body)

    def test_cached_but_unbuildable_profile_404(self):
        CachedUserProfile.objects.create(
            untappd_username="", email="ghost@customer.nl",
            profile_type="shopify", is_valid=True,
        )
        with patch("recommendations.services.shopify_customer.get_or_create_profile_from_email",
                   return_value=None):
            resp = self.client.post(
                "/api/recommendations/", {"email": "ghost@customer.nl"},
                content_type="application/json")
        self.assertEqual(resp.status_code, 404)


@override_settings(RECOMMENDER_API_KEY="")
class SixpackApiTests(TestCase):
    def _post(self, body, **extra):
        return self.client.post("/api/sixpack/", body,
                                content_type="application/json", **extra)

    def test_budget_out_of_range_400(self):
        resp = self._post({"email": "a@b.nl", "budget": 10})
        self.assertEqual(resp.status_code, 400)
        resp = self._post({"email": "a@b.nl", "budget": 500})
        self.assertEqual(resp.status_code, 400)

    @patch("recommendations.tasks.generate_sixpack_task.delay")
    def test_uncached_profile_dispatches_task(self, mock_delay):
        mock_delay.return_value = MagicMock(id="six-1")
        resp = self._post({"email": "new@b.nl", "budget": 60})
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["task_id"], "six-1")
        mock_delay.assert_called_once()

    def test_known_invalid_profile_fails_fast_404(self):
        CachedUserProfile.objects.create(
            untappd_username="", email="noorders@b.nl",
            profile_type="shopify", is_valid=False,
        )
        resp = self._post({"email": "noorders@b.nl", "budget": 60})
        self.assertEqual(resp.status_code, 404)

    @patch("recommendations.services.sixpack_engine.get_sixpack_for_email")
    def test_cached_profile_returns_pack(self, mock_pack):
        CachedUserProfile.objects.create(
            untappd_username="", email="known@b.nl",
            profile_type="shopify", is_valid=True,
        )
        beer = make_beer(title="Pack Beer")
        mock_pack.return_value = {
            "profile_type": "shopify",
            "slots": [{"position": 1, "role": "anchor", "locked": False,
                       "beer": beer, "reasons": [{"text": "Matches your taste"}]}],
            "pack_value": Decimal("12.50"),
            "budget": Decimal("60.00"),
            "within_budget": True,
        }
        resp = self._post({"email": "known@b.nl", "budget": 60})
        self.assertEqual(resp.status_code, 200)
        mock_pack.assert_called_once()

    @patch("recommendations.services.sixpack_engine.get_sixpack_for_email")
    def test_not_enough_beers_422(self, mock_pack):
        from recommendations.services.sixpack_engine import SixpackError
        CachedUserProfile.objects.create(
            untappd_username="", email="known@b.nl",
            profile_type="shopify", is_valid=True,
        )
        mock_pack.side_effect = SixpackError("Not enough beers under budget")
        resp = self._post({"email": "known@b.nl", "budget": 60})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"], "not_enough_beers")

    @override_settings(RECOMMENDER_API_KEY="sekrit")
    def test_api_key_enforced_when_configured(self):
        resp = self._post({"email": "a@b.nl", "budget": 60})
        self.assertEqual(resp.status_code, 403)
        with patch("recommendations.tasks.generate_sixpack_task.delay",
                   return_value=MagicMock(id="six-2")):
            resp = self._post({"email": "a@b.nl", "budget": 60},
                              HTTP_X_RECOMMENDER_KEY="sekrit")
        self.assertEqual(resp.status_code, 202)


class ManagementCommandTests(TestCase):
    def test_sync_shopify_command_reports_stats(self):
        out = StringIO()
        with patch("recommendations.management.commands.sync_shopify.run_sync",
                   return_value={"processed": 5, "created": 2, "updated": 3, "errors": []}):
            call_command("sync_shopify", stdout=out)
        self.assertIn("Sync completed", out.getvalue())
        self.assertIn("Processed: 5", out.getvalue())

    def test_sync_shopify_command_propagates_failure(self):
        out = StringIO()
        with patch("recommendations.management.commands.sync_shopify.run_sync",
                   side_effect=RuntimeError("api down")):
            with self.assertRaises(RuntimeError):
                call_command("sync_shopify", stdout=out)
        self.assertIn("Sync failed", out.getvalue())

    def test_prune_task_results(self):
        from django_celery_results.models import TaskResult

        old = TaskResult.objects.create(task_id="old-task", status="SUCCESS")
        TaskResult.objects.filter(pk=old.pk).update(
            date_done=timezone.now() - timedelta(days=40))
        TaskResult.objects.create(task_id="new-task", status="SUCCESS")

        out = StringIO()
        call_command("prune_task_results", stdout=out)

        self.assertFalse(TaskResult.objects.filter(task_id="old-task").exists())
        self.assertTrue(TaskResult.objects.filter(task_id="new-task").exists())
        self.assertIn("Deleted 1", out.getvalue())
