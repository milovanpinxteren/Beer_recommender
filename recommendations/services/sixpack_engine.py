"""
Personalized sixpack generator.

Builds a 6-beer pack from a user's taste profile with slot roles
(safe / adjacent / wildcard), brand diversity and a budget target.
Stateless: re-spins send locked slots + already-seen ids back in.
"""

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Q, Count

from recommendations.models import Beer
from recommendations.services.recommendation_engine import RecommendationEngine

logger = logging.getLogger(__name__)


class SixpackError(Exception):
    """Raised when a pack cannot be built (e.g. filters leave too few beers)."""


# Fine-grained style adjacency: lowercase keyword -> adjacent keywords.
# Matched as substrings against Beer.untappd_style.
ADJACENT_STYLES = {
    "imperial stout": ["pastry stout", "barleywine", "baltic porter"],
    "stout": ["porter", "imperial stout", "brown ale"],
    "porter": ["stout", "baltic porter", "schwarzbier"],
    "ipa": ["double ipa", "pale ale", "cold ipa", "black ipa"],
    "hazy": ["milkshake ipa", "new england"],
    "pale ale": ["ipa", "session ipa", "kolsch"],
    "tripel": ["belgian strong golden", "saison", "quadrupel"],
    "quadrupel": ["barleywine", "belgian strong dark", "dubbel"],
    "dubbel": ["quadrupel", "belgian strong dark", "brown ale"],
    "saison": ["farmhouse", "wild ale", "gueuze"],
    "sour": ["fruited sour", "gose", "berliner weisse", "wild ale"],
    "lambic": ["gueuze", "flanders", "wild ale"],
    "gueuze": ["lambic", "flanders", "wild ale"],
    "pilsner": ["helles", "kellerbier", "kolsch"],
    "lager": ["bock", "vienna lager", "altbier"],
    "witbier": ["hefeweizen", "saison"],
    "hefeweizen": ["witbier", "dunkelweizen", "weizenbock"],
    "barleywine": ["quadrupel", "old ale", "imperial stout"],
}

ROLE_SAFE = "safe"
ROLE_ADJACENT = "adjacent"
ROLE_WILDCARD = "wildcard"

ROLE_PLANS = {
    "safe": [ROLE_SAFE] * 4 + [ROLE_ADJACENT, ROLE_WILDCARD],
    "balanced": [ROLE_SAFE] * 3 + [ROLE_ADJACENT] * 2 + [ROLE_WILDCARD],
    "adventurous": [ROLE_SAFE] * 3 + [ROLE_ADJACENT] * 2 + [ROLE_WILDCARD],
}

PACK_SIZE = 6
VENDOR_CAP = 2
VENDOR_CAP_RELAXED = 3
# The store's Shopify vendor is the shop itself, not the brewery; the real
# brewery lives in the custom.merk metafield. Brands matching these names
# (or missing entirely) are exempt from the diversity cap.
SHOP_BRAND_NAMES = {"house of beers"}
MIN_RATING = 3.6
BUDGET_TOLERANCE = 0.10
MAX_SWAP_ITERATIONS = 24
ALCOHOL_FREE_CATEGORY = "Low/No Alcohol"


@dataclass
class SixpackSlot:
    position: int
    role: str
    locked: bool
    beer: Beer
    reasons: list = field(default_factory=list)


def _brand_key(beer) -> Optional[str]:
    """
    Diversity key for the max-beers-per-brewery cap. None means "unknown or
    shop-branded" — those beers are never capped against each other.
    """
    brand = (getattr(beer, "merk", "") or "").strip() or (beer.vendor or "").strip()
    if not brand or brand.lower() in SHOP_BRAND_NAMES:
        return None
    return brand.lower()


def _volume_cl(inhoud: str) -> Optional[float]:
    """Parse an inhoud string like '33cl' / '750 ml' / '0,75L' to centiliters."""
    if not inhoud:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", inhoud)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    lowered = inhoud.lower()
    if "ml" in lowered:
        return value / 10.0
    if "l" in lowered and "cl" not in lowered:
        return value * 100.0
    return value


class SixpackEngine(RecommendationEngine):
    """Builds personalized sixpacks on top of the recommendation scoring."""

    def build_pack(
        self,
        budget: float,
        adventurousness: str = "balanced",
        exclude_style_categories: list = None,
        include_alcohol_free: bool = False,
        max_abv: float = None,
        locked: list = None,
        exclude_ids: list = None,
    ) -> dict:
        budget = float(budget)
        exclude_style_categories = exclude_style_categories or []
        locked = locked or []
        exclude_ids = set(exclude_ids or [])
        locked_ids = {item["shopify_id"] for item in locked}
        adventurous = adventurousness == "adventurous"

        base_qs = self._base_queryset(
            exclude_style_categories, include_alcohol_free, max_abv,
            adventurous, exclude_ids | locked_ids,
        )

        locked_slots, roles_to_fill, vendor_counts, locked_value = (
            self._resolve_locked(locked, adventurousness)
        )

        n_fill = len(roles_to_fill)
        if n_fill == 0:
            slots = locked_slots
            total = locked_value
        else:
            avg = max((budget - locked_value) / n_fill, 1.0)
            price_band = (avg * 0.4, avg * 2.2)
            pools = self._build_pools(base_qs, price_band, adventurous)
            picked = self._select(
                locked_slots, roles_to_fill, pools, vendor_counts
            )
            total = sum(float(s.beer.price) for s in picked)
            total = self._fit_budget(picked, pools, budget, total)
            slots = picked

        if len(slots) < PACK_SIZE:
            raise SixpackError(
                f"Only {len(slots)} of {PACK_SIZE} slots could be filled "
                "with the current filters."
            )

        for position, slot in enumerate(slots):
            slot.position = position
            if not slot.locked:
                slot.reasons = self._build_reasons(slot, adventurous)

        total = round(sum(float(s.beer.price) for s in slots), 2)
        low = budget * (1 - BUDGET_TOLERANCE)
        high = budget * (1 + BUDGET_TOLERANCE)

        return {
            "profile_type": self.profile.get("profile_type", "untappd"),
            "slots": slots,
            "pack_value": Decimal(str(total)),
            "budget": Decimal(str(round(budget, 2))),
            "within_budget": low <= total <= high,
        }

    # ------------------------------------------------------------------
    # Query building

    def _base_queryset(self, exclude_style_categories, include_alcohol_free,
                       max_abv, adventurous, excluded_ids):
        qs = Beer.objects.filter(
            is_active=True,
            in_stock=True,
            price__isnull=False,
            price__gt=0,
            untappd_rating__isnull=False,
            untappd_rating__gte=MIN_RATING,
        )
        # Non-beer and sale-lot products: auction/fee types and the
        # WhatsApp-sale lots (date-prefixed or "Whatsapp sale ..." titles).
        qs = qs.exclude(product_type__in=["Auction", "Fee"])
        qs = qs.exclude(title__iregex=r"whatsapp")
        qs = qs.exclude(title__regex=r"^\d{1,2}-\d{1,2}-\d{4}")
        excluded_cats = set(exclude_style_categories)
        if not include_alcohol_free:
            excluded_cats.add(ALCOHOL_FREE_CATEGORY)
        qs = qs.exclude(style_category__in=excluded_cats)
        if max_abv is not None:
            qs = qs.filter(Q(abv__isnull=True) | Q(abv__lte=max_abv))
        if not adventurous:
            # Vintage bottles (notably old brew years) only in adventurous mode.
            qs = qs.exclude(year__isnull=False, year__lt=date.today().year - 1)
        if excluded_ids:
            qs = qs.exclude(shopify_id__in=excluded_ids)
        return qs

    def _resolve_locked(self, locked, adventurousness):
        locked_slots = []
        roles_remaining = list(ROLE_PLANS.get(adventurousness, ROLE_PLANS["balanced"]))
        vendor_counts = {}
        locked_value = 0.0

        for item in locked:
            beer = Beer.objects.filter(
                shopify_id=item["shopify_id"], is_active=True, in_stock=True,
            ).first()
            if beer is None or beer.price is None:
                # Unavailable locked beer: silently drop; its role re-fills.
                continue
            role = item.get("role", ROLE_SAFE)
            if role in roles_remaining:
                roles_remaining.remove(role)
            elif roles_remaining:
                roles_remaining.pop()
            locked_slots.append(
                SixpackSlot(position=0, role=role, locked=True, beer=beer)
            )
            brand = _brand_key(beer)
            if brand:
                vendor_counts[brand] = vendor_counts.get(brand, 0) + 1
            locked_value += float(beer.price)

        return locked_slots, roles_remaining, vendor_counts, locked_value

    # ------------------------------------------------------------------
    # Candidate pools

    def _top_styles(self, base_qs):
        top = [
            s for s in self.preferred_styles.keys()
            if s and s not in (ALCOHOL_FREE_CATEGORY,)
        ][:3]
        if top:
            return top
        # Cold profile: most represented in-stock categories with good beers.
        rows = (
            base_qs.filter(untappd_rating__gte=4.0)
            .exclude(style_category="")
            .values("style_category")
            .annotate(n=Count("id"))
            .order_by("-n")[:3]
        )
        return [r["style_category"] for r in rows]

    def _user_fine_styles(self) -> set:
        """Lowercase untappd_style values of beers the user has tried."""
        tried_shopify_ids = [
            str(tb["shopify_id"]) for tb in self.tried_beers if tb.get("shopify_id")
        ]
        fine = set()
        if tried_shopify_ids:
            for value in Beer.objects.filter(
                shopify_id__in=tried_shopify_ids
            ).exclude(untappd_style="").values_list("untappd_style", flat=True):
                fine.add(value.lower())
        return fine

    def _score_pool(self, queryset, limit):
        scored = []
        for beer in queryset:
            rec = self.score_beer(beer)
            if rec.is_tried:
                continue
            scored.append(rec)
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:limit]

    def _build_pools(self, base_qs, price_band, adventurous):
        low, high = price_band
        priced = base_qs.filter(price__gte=low, price__lte=high)
        top_styles = self._top_styles(base_qs)
        fine_styles = self._user_fine_styles()

        # SAFE: user's top style categories.
        safe = self._score_pool(
            priced.filter(style_category__in=top_styles)[:300], 40
        )

        # ADJACENT: fine styles bordering what the user drinks.
        targets = set()
        matched_from = {}  # target keyword -> user keyword it came from
        for keyword, adjacents in ADJACENT_STYLES.items():
            if any(keyword in fs for fs in fine_styles):
                for adj in adjacents:
                    targets.add(adj)
                    matched_from.setdefault(adj, keyword)
                if adventurous:
                    # One hop further: adjacents of the adjacents.
                    for adj in adjacents:
                        for extra in ADJACENT_STYLES.get(adj, []):
                            targets.add(extra)
                            matched_from.setdefault(extra, keyword)
        adjacent = []
        if targets:
            q = Q()
            for target in targets:
                q |= Q(untappd_style__icontains=target)
            candidates = priced.filter(q)[:300]
            pool = self._score_pool(candidates, 60)
            for rec in pool:
                candidate_fine = rec.beer.untappd_style.lower()
                if candidate_fine and candidate_fine in fine_styles:
                    continue
                rec._adjacent_from = next(
                    (matched_from[tgt] for tgt in targets
                     if tgt in candidate_fine), None,
                )
                adjacent.append(rec)
            adjacent = adjacent[:30]
        if not adjacent:
            # Fallback: unseen fine styles inside familiar categories.
            pool = self._score_pool(
                priced.filter(style_category__in=top_styles)[:300], 60
            )
            adjacent = [
                rec for rec in pool
                if rec.beer.untappd_style.lower() not in fine_styles
            ][:30]
            for rec in adjacent:
                rec._adjacent_from = None

        # WILDCARD: categories the user has never had, high floor.
        known_cats = [c for c in self.style_counts.keys() if c]
        wildcard = self._score_pool(
            priced.exclude(style_category__in=known_cats)
            .filter(untappd_rating__gte=4.0)[:300],
            30,
        )
        if not wildcard:
            wildcard = self._score_pool(
                priced.filter(untappd_rating__gte=4.2)
                .exclude(style_category__in=top_styles)[:300],
                30,
            )
        if adventurous:
            random.shuffle(wildcard)

        # Last-resort pool shared by all roles when their own pool runs dry.
        general = self._score_pool(priced[:400], 60)

        return {
            ROLE_SAFE: safe,
            ROLE_ADJACENT: adjacent,
            ROLE_WILDCARD: wildcard,
            "general": general,
        }

    # ------------------------------------------------------------------
    # Selection

    def _select(self, locked_slots, roles_to_fill, pools, vendor_counts):
        picked = list(locked_slots)
        picked_ids = {s.beer.shopify_id for s in picked}

        for role in roles_to_fill:
            rec = self._pick_from_pool(
                pools, role, picked_ids, vendor_counts, VENDOR_CAP
            )
            if rec is None:
                rec = self._pick_from_pool(
                    pools, role, picked_ids, vendor_counts, VENDOR_CAP_RELAXED
                )
            if rec is None:
                continue
            slot = SixpackSlot(position=0, role=role, locked=False, beer=rec.beer)
            slot._rec = rec
            picked.append(slot)
            picked_ids.add(rec.beer.shopify_id)
            brand = _brand_key(rec.beer)
            if brand:
                vendor_counts[brand] = vendor_counts.get(brand, 0) + 1

        return picked

    def _pick_from_pool(self, pools, role, picked_ids, vendor_counts, cap):
        def allowed(rec):
            if rec.beer.shopify_id in picked_ids:
                return False
            brand = _brand_key(rec.beer)
            return brand is None or vendor_counts.get(brand, 0) < cap

        for pool in (pools.get(role, []), pools.get("general", [])):
            eligible = [rec for rec in pool[:12] if allowed(rec)]
            if not eligible:
                eligible = [rec for rec in pool if allowed(rec)]
            if eligible:
                weights = [max(rec.score, 1.0) for rec in eligible]
                return random.choices(eligible, weights=weights, k=1)[0]
        return None

    # ------------------------------------------------------------------
    # Budget fitting

    def _fit_budget(self, picked, pools, budget, total):
        low = budget * (1 - BUDGET_TOLERANCE)
        high = budget * (1 + BUDGET_TOLERANCE)

        for _ in range(MAX_SWAP_ITERATIONS):
            if low <= total <= high:
                break
            picked_ids = {s.beer.shopify_id for s in picked}
            best = None  # (new_total, slot, candidate_rec)
            for slot in picked:
                if slot.locked:
                    continue
                vendor_counts = {}
                for other in picked:
                    if other is slot:
                        continue
                    brand = _brand_key(other.beer)
                    if brand:
                        vendor_counts[brand] = vendor_counts.get(brand, 0) + 1
                for rec in pools.get(slot.role, []):
                    if rec.beer.shopify_id in picked_ids:
                        continue
                    cand_brand = _brand_key(rec.beer)
                    if cand_brand and vendor_counts.get(cand_brand, 0) >= VENDOR_CAP:
                        continue
                    new_total = total - float(slot.beer.price) + float(rec.beer.price)
                    if best is None or abs(new_total - budget) < abs(best[0] - budget):
                        best = (new_total, slot, rec)
            if best is None or abs(best[0] - budget) >= abs(total - budget):
                break
            new_total, slot, rec = best
            slot.beer = rec.beer
            slot._rec = rec
            total = new_total

        return round(total, 2)

    # ------------------------------------------------------------------
    # Reasons

    def _build_reasons(self, slot, adventurous) -> list:
        beer = slot.beer
        reasons = []

        if slot.role == ROLE_SAFE:
            pref = self.preferred_styles.get(beer.style_category)
            reasons.append({
                "code": "preferred_style",
                "params": {
                    "style": beer.style_category,
                    "avg_rating": pref["avg_rating"] if pref else None,
                },
            })
        elif slot.role == ROLE_ADJACENT:
            rec = getattr(slot, "_rec", None)
            from_style = getattr(rec, "_adjacent_from", None) if rec else None
            reasons.append({
                "code": "adjacent_style",
                "params": {
                    "from_style": from_style or beer.style_category,
                    "to_style": beer.untappd_style or beer.style_category,
                },
            })
        else:
            reasons.append({
                "code": "new_style",
                "params": {"style": beer.style_category or beer.style},
            })

        if beer.rijpingsmethode:
            reasons.append({
                "code": "barrel_aged",
                "params": {"method": beer.rijpingsmethode},
            })
        if beer.untappd_rating and beer.untappd_rating >= 4.2:
            reasons.append({
                "code": "highly_rated",
                "params": {"rating": beer.untappd_rating},
            })
        brand = (getattr(beer, "merk", "") or "").strip() or (beer.vendor or "").strip()
        if (
            brand
            and brand.lower() not in SHOP_BRAND_NAMES
            and brand in self.brewery_counts
        ):
            reasons.append({
                "code": "known_brewery",
                "params": {"brewery": brand},
            })
        if adventurous and beer.year and beer.year <= date.today().year - 2:
            reasons.append({
                "code": "vintage",
                "params": {"year": beer.year},
            })
        volume = _volume_cl(beer.inhoud)
        if volume and volume >= 50:
            reasons.append({
                "code": "big_bottle",
                "params": {"inhoud": beer.inhoud},
            })

        return reasons


def _build_params(params: dict) -> dict:
    return {
        "budget": float(params["budget"]),
        "adventurousness": params.get("adventurousness", "balanced"),
        "exclude_style_categories": params.get("exclude_style_categories", []),
        "include_alcohol_free": params.get("include_alcohol_free", False),
        "max_abv": params.get("max_abv"),
        "locked": params.get("locked", []),
        "exclude_ids": params.get("exclude", []),
    }


def get_sixpack_for_user(username: str, params: dict,
                         force_refresh: bool = False) -> Optional[dict]:
    """Build a sixpack for an Untappd user."""
    from recommendations.services.untappd_scraper import get_or_create_profile

    profile_data = get_or_create_profile(username, force_refresh=force_refresh)
    if not profile_data:
        logger.warning(f"Could not get profile for {username}")
        return None

    profile_data = dict(profile_data)
    profile_data.setdefault("profile_type", "untappd")
    engine = SixpackEngine(profile_data)
    return engine.build_pack(**_build_params(params))


def get_sixpack_for_email(email: str, params: dict,
                          force_refresh: bool = False) -> Optional[dict]:
    """Build a sixpack for a Shopify customer by order history."""
    from recommendations.services.shopify_customer import get_or_create_profile_from_email

    profile_data = get_or_create_profile_from_email(email, force_refresh=force_refresh)
    if not profile_data:
        logger.warning(f"Could not get profile for email {email}")
        return None

    profile_data = dict(profile_data)
    profile_data["profile_type"] = "shopify"
    engine = SixpackEngine(profile_data)
    return engine.build_pack(**_build_params(params))
