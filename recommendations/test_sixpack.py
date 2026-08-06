"""
Tests for the personalized sixpack engine.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from recommendations.models import Beer
from recommendations.services.sixpack_engine import (
    SixpackEngine,
    SixpackError,
    _volume_cl,
)


def make_beer(i, style, untappd_style, price, vendor=None, rating=4.0,
              abv=8.0, year=None, in_stock=True, title=None, **kwargs):
    # Mirrors the real store: Shopify vendor is the shop itself; the actual
    # brewery lives in the merk metafield.
    return Beer.objects.create(
        shopify_id=str(1000 + i),
        variant_id=str(2000 + i),
        handle=f"beer-{i}",
        title=title or f"Beer {i} {untappd_style}",
        vendor="House Of Beers",
        merk=vendor or f"Brewery {i}",
        price=Decimal(str(price)),
        style=style,
        untappd_style=untappd_style,
        untappd_rating=rating,
        untappd_rating_count=100,
        abv=abv,
        year=year,
        in_stock=in_stock,
        inventory_quantity=10 if in_stock else 0,
        is_active=True,
        **kwargs,
    )


def stout_lover_profile():
    """Profile of a user who drinks stouts and quads."""
    return {
        "username": "tester",
        "profile_type": "shopify",
        "preferred_styles": [
            {"style": "Stout", "avg_rating": 4.3, "count": 20, "score": 90},
            {"style": "Belgian", "avg_rating": 4.0, "count": 8, "score": 60},
        ],
        "preferred_breweries": [
            {"brewery": "Brewery 1", "avg_rating": 4.2, "count": 5},
        ],
        "style_counts": {"Stout": 20, "Belgian": 8},
        "brewery_counts": {"Brewery 1": 5},
        "abv_preference": {"min": 6, "max": 13, "avg": 10,
                           "preferred_min": 8, "preferred_max": 12},
        "avg_rating": 4.0,
        "tried_beers": [],
    }


class SixpackEngineTests(TestCase):

    def setUp(self):
        # Stouts (safe territory)
        for i in range(10):
            make_beer(i, "Stout", "Stout - Imperial / Double", 9 + i * 0.5,
                      vendor=f"Stout Brewery {i % 5}")
        # Belgians (second preferred style)
        for i in range(10, 18):
            make_beer(i, "Quadrupel", "Belgian Quadrupel", 8 + (i - 10) * 0.5,
                      vendor=f"Belgian Brewery {i % 4}")
        # Adjacent to imperial stout: pastry stout / barleywine
        for i in range(18, 24):
            make_beer(i, "Stout", "Stout - Imperial / Double Pastry", 10,
                      vendor=f"Pastry Brewery {i}")
        for i in range(24, 28):
            make_beer(i, "Barleywine", "Barleywine - English", 11,
                      vendor=f"BW Brewery {i}")
        # Wildcard: styles the user never had
        for i in range(28, 34):
            make_beer(i, "IPA", "IPA - New England / Hazy", 7.5,
                      vendor=f"IPA Brewery {i}", rating=4.3)
        for i in range(34, 38):
            make_beer(i, "Lambiek/Geuze", "Lambic - Gueuze", 12,
                      vendor=f"Lambic Brewery {i}", rating=4.4)
        # Alcohol-free (must be excluded by default)
        for i in range(38, 41):
            make_beer(i, "Alcoholvrij", "Non-Alcoholic - IPA", 4,
                      vendor=f"NA Brewery {i}", rating=4.1)
        # Vintage bottle (excluded unless adventurous)
        make_beer(41, "Barleywine", "Barleywine - Other", 15,
                  vendor="Vintage Brewery", year=date.today().year - 4)
        # Out of stock (never picked)
        make_beer(42, "Stout", "Stout - Imperial / Double", 9,
                  vendor="OOS Brewery", in_stock=False)

    def build(self, engine=None, **overrides):
        engine = engine or SixpackEngine(stout_lover_profile())
        params = dict(
            budget=60,
            adventurousness="balanced",
            exclude_style_categories=[],
            include_alcohol_free=False,
            max_abv=None,
            locked=[],
            exclude_ids=[],
        )
        params.update(overrides)
        return engine.build_pack(**params)

    def test_pack_has_six_slots_with_role_plan(self):
        result = self.build()
        self.assertEqual(len(result["slots"]), 6)
        roles = [s.role for s in result["slots"]]
        self.assertEqual(roles.count("safe"), 3)
        self.assertEqual(roles.count("adjacent"), 2)
        self.assertEqual(roles.count("wildcard"), 1)
        self.assertEqual([s.position for s in result["slots"]], list(range(6)))

    def test_no_duplicate_beers_and_brand_cap(self):
        result = self.build()
        ids = [s.beer.shopify_id for s in result["slots"]]
        self.assertEqual(len(ids), len(set(ids)))
        brands = {}
        for s in result["slots"]:
            brands[s.beer.merk] = brands.get(s.beer.merk, 0) + 1
        self.assertLessEqual(max(brands.values()), 3)

    def test_sale_lots_and_auctions_never_picked(self):
        make_beer(60, "Stout", "Stout - Imperial / Double", 9,
                  vendor="Lot Brewery", title="11-2-2026 - A - A | Some Geuze")
        make_beer(61, "Stout", "Stout - Imperial / Double", 9,
                  vendor="Lot Brewery 2", title="Whatsapp sale 12 Januari - B")
        make_beer(62, "Stout", "Stout - Imperial / Double", 9,
                  vendor="Fee Brewery", product_type="Fee")
        make_beer(63, "Stout", "Stout - Imperial / Double", 9,
                  vendor="Auction Brewery", product_type="Auction")
        banned = {"1060", "1061", "1062", "1063"}
        for _ in range(5):
            result = self.build()
            picked = {s.beer.shopify_id for s in result["slots"]}
            self.assertFalse(picked & banned)

    def test_shop_branded_beers_are_not_capped(self):
        # Beers without a merk fall back to vendor (the shop) and must be
        # exempt from the diversity cap rather than blocking the pack.
        Beer.objects.all().delete()
        for i in range(70, 90):
            make_beer(i, "Stout", "Stout - Imperial / Double", 9, vendor="x")
        Beer.objects.update(merk="", vendor="House Of Beers")
        result = self.build()
        self.assertEqual(len(result["slots"]), 6)

    def test_alcohol_free_excluded_by_default(self):
        result = self.build()
        for s in result["slots"]:
            self.assertNotEqual(s.beer.style_category, "Low/No Alcohol")

    def test_vintage_excluded_unless_adventurous(self):
        for _ in range(5):
            result = self.build()
            for s in result["slots"]:
                if s.beer.year:
                    self.assertGreaterEqual(s.beer.year, date.today().year - 1)

    def test_style_exclusions_respected(self):
        result = self.build(exclude_style_categories=["Wild/Lambic", "IPA"])
        for s in result["slots"]:
            self.assertNotIn(s.beer.style_category, ["Wild/Lambic", "IPA"])

    def test_budget_within_tolerance(self):
        result = self.build()
        total = float(result["pack_value"])
        self.assertAlmostEqual(
            total, sum(float(s.beer.price) for s in result["slots"]), places=2
        )
        if result["within_budget"]:
            self.assertGreaterEqual(total, 54.0)
            self.assertLessEqual(total, 66.0)

    def test_locked_beers_kept_and_excluded_ids_skipped(self):
        first = self.build()
        keep = first["slots"][0]
        seen = [s.beer.shopify_id for s in first["slots"]]
        exclude = [i for i in seen if i != keep.beer.shopify_id]

        second = self.build(
            locked=[{"shopify_id": keep.beer.shopify_id, "role": keep.role}],
            exclude_ids=exclude,
        )
        second_ids = [s.beer.shopify_id for s in second["slots"]]
        self.assertIn(keep.beer.shopify_id, second_ids)
        for excluded in exclude:
            self.assertNotIn(excluded, second_ids)
        locked_slots = [s for s in second["slots"] if s.locked]
        self.assertEqual(len(locked_slots), 1)

    def test_unavailable_locked_beer_dropped_silently(self):
        result = self.build(locked=[{"shopify_id": "999999", "role": "safe"}])
        self.assertEqual(len(result["slots"]), 6)
        self.assertFalse(any(s.locked for s in result["slots"]))

    def test_reasons_present_with_role_reason_first(self):
        result = self.build()
        role_codes = {"safe": "preferred_style", "adjacent": "adjacent_style",
                      "wildcard": "new_style"}
        for s in result["slots"]:
            self.assertTrue(s.reasons)
            self.assertEqual(s.reasons[0]["code"], role_codes[s.role])

    def test_impossible_filters_raise(self):
        with self.assertRaises(SixpackError):
            self.build(exclude_style_categories=[
                "Stout", "Belgian", "IPA", "Wild/Lambic", "Barleywine",
                "Porter", "Sour", "Wheat", "Lager", "Pale Ale", "Bock",
                "German", "British",
            ])

    def test_cold_profile_fallback(self):
        cold = {
            "username": "new", "profile_type": "shopify",
            "preferred_styles": [], "preferred_breweries": [],
            "style_counts": {}, "brewery_counts": {},
            "abv_preference": {}, "avg_rating": 3.5, "tried_beers": [],
        }
        result = self.build(engine=SixpackEngine(cold))
        self.assertEqual(len(result["slots"]), 6)


class VolumeParseTests(TestCase):

    def test_volume_parsing(self):
        self.assertEqual(_volume_cl("33cl"), 33)
        self.assertEqual(_volume_cl("750 ml"), 75)
        self.assertEqual(_volume_cl("0,75L"), 75)
        self.assertEqual(_volume_cl("75 cl"), 75)
        self.assertIsNone(_volume_cl(""))
        self.assertIsNone(_volume_cl("groot"))
