"""
Beer recommendation engine.
Matches user taste profiles against beer catalog.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from django.db.models import Q, F, Case, When, Value, IntegerField, FloatField
from django.db.models.functions import Coalesce

from recommendations.models import Beer
from recommendations.services.style_mapper import get_style_category

logger = logging.getLogger(__name__)


@dataclass
class RecommendedBeer:
    """A recommended beer with scoring details."""
    beer: Beer
    score: float
    reasons: list = field(default_factory=list)
    is_tried: bool = False
    confidence: str = "medium"  # high, medium, low


@dataclass
class RecommendationResult:
    """Complete recommendation result for a user."""
    username: str
    recommendations: list  # List of RecommendedBeer
    tried_beers: list  # Beers user has already tried (in our catalog)
    discovery_picks: list  # New styles/breweries to explore
    profile_summary: dict
    display_name: str = ""  # Human-readable name (for email profiles)
    profile_type: str = "untappd"  # 'untappd' or 'shopify'


class RecommendationEngine:
    """
    Generates beer recommendations based on user taste profiles.

    Scoring factors:
    - Style match: User's preferred styles get high scores
    - Brewery match: Known breweries get bonus
    - ABV preference: Beers in preferred range score higher
    - Rating quality: Higher untappd ratings preferred
    - Discovery bonus: New styles get slight boost for variety
    """

    STYLE_MATCH_WEIGHT = 40
    BREWERY_MATCH_WEIGHT = 20
    ABV_MATCH_WEIGHT = 15
    RATING_WEIGHT = 20
    DISCOVERY_WEIGHT = 5

    def __init__(self, profile_data: dict):
        self.profile = profile_data
        self.preferred_styles = {
            s["style"]: s for s in profile_data.get("preferred_styles", [])
        }
        self.preferred_breweries = {
            b["brewery"]: b for b in profile_data.get("preferred_breweries", [])
        }
        self.style_counts = profile_data.get("style_counts", {})
        self.brewery_counts = profile_data.get("brewery_counts", {})
        self.abv_pref = profile_data.get("abv_preference", {})
        self.avg_rating = profile_data.get("avg_rating", 3.5)

        # Build tried beers lookup for matching
        self.tried_beers = profile_data.get("tried_beers", [])
        self.tried_beer_urls = set()
        self.tried_beer_names = {}  # normalized name -> {brewery, rating}
        for tb in self.tried_beers:
            if tb.get("url"):
                self.tried_beer_urls.add(tb["url"].lower())
            if tb.get("name"):
                # Normalize name for fuzzy matching
                key = self._normalize_beer_name(tb["name"], tb.get("brewery", ""))
                self.tried_beer_names[key] = tb

    def _score_style_match(self, beer: Beer) -> tuple[float, str]:
        """Score how well beer's style matches user preference."""
        style_cat = beer.style_category

        if style_cat in self.preferred_styles:
            pref = self.preferred_styles[style_cat]
            # Scale by how much they like this style
            score = (pref["avg_rating"] / 5.0) * self.STYLE_MATCH_WEIGHT
            return score, f"Matches preferred style: {style_cat} (avg {pref['avg_rating']})"

        # Tried but not preferred
        if style_cat in self.style_counts:
            return self.STYLE_MATCH_WEIGHT * 0.3, f"You've tried {style_cat} before"

        # Never tried - discovery opportunity
        return self.STYLE_MATCH_WEIGHT * 0.1, f"New style to explore: {style_cat}"

    def _score_brewery_match(self, beer: Beer) -> tuple[float, str]:
        """Score brewery familiarity and preference."""
        brewery = beer.vendor

        if brewery in self.preferred_breweries:
            pref = self.preferred_breweries[brewery]
            score = (pref["avg_rating"] / 5.0) * self.BREWERY_MATCH_WEIGHT
            return score, f"From preferred brewery: {brewery}"

        if brewery in self.brewery_counts:
            return self.BREWERY_MATCH_WEIGHT * 0.5, f"Known brewery: {brewery}"

        return 0, None

    def _score_abv_match(self, beer: Beer) -> tuple[float, str]:
        """Score how well ABV matches user preference."""
        if not beer.abv or not self.abv_pref.get("avg"):
            return self.ABV_MATCH_WEIGHT * 0.5, None

        pref_min = self.abv_pref.get("preferred_min", self.abv_pref.get("min", 4))
        pref_max = self.abv_pref.get("preferred_max", self.abv_pref.get("max", 10))
        pref_avg = self.abv_pref.get("avg", 6)

        if pref_min <= beer.abv <= pref_max:
            # Perfect range
            distance = abs(beer.abv - pref_avg)
            score = self.ABV_MATCH_WEIGHT * (1 - distance / 10)
            return max(score, self.ABV_MATCH_WEIGHT * 0.7), f"ABV {beer.abv}% in your preferred range"

        # Outside preferred range
        if beer.abv < pref_min:
            distance = pref_min - beer.abv
        else:
            distance = beer.abv - pref_max

        score = max(0, self.ABV_MATCH_WEIGHT * (1 - distance / 5))
        return score, None

    def _score_rating(self, beer: Beer) -> tuple[float, str]:
        """Score based on Untappd community rating."""
        if not beer.untappd_rating:
            return self.RATING_WEIGHT * 0.5, None

        # User's threshold - recommend beers above their average
        threshold = max(self.avg_rating - 0.5, 3.0)

        if beer.untappd_rating >= threshold:
            # Scale from threshold to 5.0
            score = ((beer.untappd_rating - threshold) / (5.0 - threshold)) * self.RATING_WEIGHT
            score = min(score, self.RATING_WEIGHT)

            if beer.untappd_rating >= 4.0:
                return score, f"Highly rated: {beer.untappd_rating}/5"
            return score, None

        return 0, None

    def _score_discovery(self, beer: Beer) -> tuple[float, str]:
        """Score for discovering new styles/breweries."""
        style_cat = beer.style_category
        brewery = beer.vendor

        is_new_style = style_cat not in self.style_counts
        is_new_brewery = brewery not in self.brewery_counts

        if is_new_style and is_new_brewery:
            return self.DISCOVERY_WEIGHT, "New style and brewery to discover"
        elif is_new_style:
            return self.DISCOVERY_WEIGHT * 0.7, "New style to discover"
        elif is_new_brewery:
            return self.DISCOVERY_WEIGHT * 0.5, None

        return 0, None

    def score_beer(self, beer: Beer) -> RecommendedBeer:
        """Calculate total recommendation score for a beer."""
        total_score = 0
        reasons = []

        # Style match
        style_score, style_reason = self._score_style_match(beer)
        total_score += style_score
        if style_reason:
            reasons.append(style_reason)

        # Brewery match
        brewery_score, brewery_reason = self._score_brewery_match(beer)
        total_score += brewery_score
        if brewery_reason:
            reasons.append(brewery_reason)

        # ABV match
        abv_score, abv_reason = self._score_abv_match(beer)
        total_score += abv_score
        if abv_reason:
            reasons.append(abv_reason)

        # Rating quality
        rating_score, rating_reason = self._score_rating(beer)
        total_score += rating_score
        if rating_reason:
            reasons.append(rating_reason)

        # Discovery bonus
        discovery_score, discovery_reason = self._score_discovery(beer)
        total_score += discovery_score
        if discovery_reason:
            reasons.append(discovery_reason)

        # Determine confidence
        confidence = "medium"
        if style_score > self.STYLE_MATCH_WEIGHT * 0.7:
            confidence = "high"
        elif beer.style_category not in self.style_counts:
            confidence = "low"

        # Check if user has tried this beer
        is_tried, user_rating = self._check_if_tried(beer)

        if is_tried:
            if user_rating:
                reasons.insert(0, f"You've tried this! You rated it {user_rating}/5")
            else:
                reasons.insert(0, "You've tried this beer before")

        return RecommendedBeer(
            beer=beer,
            score=round(total_score, 2),
            reasons=reasons,
            is_tried=is_tried,
            confidence=confidence,
        )

    def _normalize_beer_name(self, name: str, brewery: str = "") -> str:
        """Normalize beer name for matching."""
        # Lowercase and remove special chars
        normalized = name.lower()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # Add brewery for uniqueness
        if brewery:
            brewery_norm = re.sub(r'[^\w\s]', '', brewery.lower())
            normalized = f"{brewery_norm}|{normalized}"
        return normalized

    def _check_if_tried(self, beer: Beer) -> tuple[bool, Optional[float]]:
        """Check if user has tried this specific beer. Returns (is_tried, user_rating)."""
        # Method 1: Match by Untappd URL
        if beer.untappd_url:
            # Extract URL from JSON if needed
            url = beer.untappd_url.lower()
            if "untappd.com/b/" in url:
                for tried_url in self.tried_beer_urls:
                    if "untappd.com/b/" in tried_url:
                        # Compare beer slugs
                        beer_slug = url.split("/b/")[-1].split("/")[0] if "/b/" in url else ""
                        tried_slug = tried_url.split("/b/")[-1].split("/")[0] if "/b/" in tried_url else ""
                        if beer_slug and tried_slug and beer_slug == tried_slug:
                            # Find the rating
                            for tb in self.tried_beers:
                                if tb.get("url") and tried_slug in tb["url"].lower():
                                    return True, tb.get("rating")
                            return True, None

        # Method 2: Fuzzy match by name + brewery
        beer_key = self._normalize_beer_name(beer.title, beer.vendor)
        if beer_key in self.tried_beer_names:
            return True, self.tried_beer_names[beer_key].get("rating")

        # Method 3: Partial name matching for common patterns
        for tried_key, tried_data in self.tried_beer_names.items():
            tried_name = tried_data.get("name", "").lower()
            beer_title_lower = beer.title.lower()
            # Check if the tried beer name is substantially in our beer title
            if tried_name and len(tried_name) > 5:
                if tried_name in beer_title_lower or beer_title_lower in tried_name:
                    return True, tried_data.get("rating")

        return False, None

    def get_recommendations(
        self,
        limit: int = 10,
        include_out_of_stock: bool = False,
        style_filter: str = None,
        country_filter: str = None,
        price_max: float = None,
    ) -> RecommendationResult:
        """
        Generate personalized recommendations.

        Args:
            limit: Number of recommendations to return
            include_out_of_stock: Include out of stock beers
            style_filter: Filter to specific style category
            country_filter: Filter to specific country/region
            price_max: Maximum price filter
        """
        # Build base queryset - only include active products
        queryset = Beer.objects.filter(is_active=True)

        if not include_out_of_stock:
            queryset = queryset.filter(in_stock=True)

        if style_filter:
            queryset = queryset.filter(style_category=style_filter)

        if country_filter:
            queryset = queryset.filter(
                Q(country=country_filter) | Q(country_region=country_filter)
            )

        if price_max:
            queryset = queryset.filter(price__lte=price_max)

        # Pre-filter to likely candidates for efficiency
        # Prioritize user's known styles and highly-rated beers
        preferred_style_list = list(self.preferred_styles.keys())

        if preferred_style_list:
            # Get mix of preferred styles and top-rated
            style_matches = queryset.filter(style_category__in=preferred_style_list)
            top_rated = queryset.filter(untappd_rating__gte=4.0)
            discovery = queryset.exclude(
                style_category__in=list(self.style_counts.keys())
            ).filter(untappd_rating__gte=3.8)

            # Combine and dedupe
            candidate_ids = set(
                list(style_matches.values_list("id", flat=True)[:200]) +
                list(top_rated.values_list("id", flat=True)[:100]) +
                list(discovery.values_list("id", flat=True)[:50])
            )
            candidates = Beer.objects.filter(id__in=candidate_ids)
        else:
            # No preferences yet - use top rated
            candidates = queryset.filter(untappd_rating__gte=3.5)[:200]

        # Score all candidates
        scored_beers = []
        for beer in candidates:
            scored = self.score_beer(beer)
            scored_beers.append(scored)

        # Sort by score
        scored_beers.sort(key=lambda x: x.score, reverse=True)

        # Separate tried vs new
        tried_beers = [b for b in scored_beers if b.is_tried]
        new_beers = [b for b in scored_beers if not b.is_tried]

        # Get discovery picks (new styles)
        discovery_picks = [
            b for b in new_beers
            if b.confidence == "low" and b.beer.untappd_rating and b.beer.untappd_rating >= 4.0
        ][:3]

        # Main recommendations - mix of high confidence and some discovery
        main_recs = new_beers[:limit]

        return RecommendationResult(
            username=self.profile.get("username", ""),
            recommendations=main_recs,
            tried_beers=tried_beers[:5],
            discovery_picks=discovery_picks,
            profile_summary={
                "total_checkins": self.profile.get("total_checkins", 0),
                "unique_beers": self.profile.get("unique_beers", 0),
                "top_styles": [s["style"] for s in list(self.preferred_styles.values())[:5]],
                "avg_rating": self.avg_rating,
                "abv_range": f"{self.abv_pref.get('preferred_min', '?')}-{self.abv_pref.get('preferred_max', '?')}%",
            },
        )


def get_recommendations_for_user(
    username: str,
    limit: int = 10,
    force_refresh: bool = False,
    **filters
) -> Optional[RecommendationResult]:
    """
    Main entry point: Get recommendations for an Untappd user.

    Args:
        username: Untappd username
        limit: Number of recommendations
        force_refresh: Force re-scrape of profile
        **filters: Additional filters (style_filter, country_filter, price_max)
    """
    from recommendations.services.untappd_scraper import get_or_create_profile

    # Get or build user profile
    profile_data = get_or_create_profile(username, force_refresh=force_refresh)

    if not profile_data:
        logger.warning(f"Could not get profile for {username}")
        return None

    # Generate recommendations
    engine = RecommendationEngine(profile_data)
    return engine.get_recommendations(limit=limit, **filters)


def get_recommendations_for_email(
    email: str,
    limit: int = 10,
    force_refresh: bool = False,
    **filters
) -> Optional[RecommendationResult]:
    """
    Get recommendations for a customer based on their Shopify order history.

    Args:
        email: Customer email address
        limit: Number of recommendations
        force_refresh: Force re-fetch of order history
        **filters: Additional filters (style_filter, country_filter, price_max)
    """
    from recommendations.services.shopify_customer import get_or_create_profile_from_email

    # Get or build customer profile from order history
    profile_data = get_or_create_profile_from_email(email, force_refresh=force_refresh)

    if not profile_data:
        logger.warning(f"Could not get profile for email {email}")
        return None

    # Generate recommendations using same engine
    engine = RecommendationEngine(profile_data)
    result = engine.get_recommendations(limit=limit, **filters)

    # Set profile type info for the frontend
    result.profile_type = "shopify"
    result.display_name = profile_data.get("display_name", email)

    return result
