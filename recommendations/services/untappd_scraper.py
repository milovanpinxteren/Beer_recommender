"""
Untappd profile scraper.
Scrapes user check-ins to build taste profiles.
"""

import logging
import time
import re
import json
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class CheckIn:
    """Represents a single Untappd check-in."""
    beer_name: str
    brewery: str
    style: str
    user_rating: Optional[float]
    beer_rating: Optional[float]
    abv: Optional[float]
    ibu: Optional[int]
    untappd_url: str


@dataclass
class UserTasteProfile:
    """Aggregated taste profile from user check-ins."""
    username: str
    total_checkins: int = 0
    unique_beers: int = 0

    # Style preferences (style -> count, total_rating)
    style_counts: dict = field(default_factory=lambda: defaultdict(int))
    style_ratings: dict = field(default_factory=lambda: defaultdict(list))

    # Brewery preferences
    brewery_counts: dict = field(default_factory=lambda: defaultdict(int))
    brewery_ratings: dict = field(default_factory=lambda: defaultdict(list))

    # ABV preferences
    abv_values: list = field(default_factory=list)
    abv_ratings: dict = field(default_factory=lambda: defaultdict(list))

    # IBU preferences
    ibu_values: list = field(default_factory=list)

    # Country preferences (derived from brewery location if available)
    country_counts: dict = field(default_factory=lambda: defaultdict(int))

    # Rating distribution
    all_ratings: list = field(default_factory=list)

    # Raw check-ins for reference
    checkins: list = field(default_factory=list)

    def get_preferred_styles(self, min_count: int = 2, top_n: int = 10) -> list:
        """Get top styles by positive rating, filtered by min count."""
        style_scores = {}
        for style, ratings in self.style_ratings.items():
            if len(ratings) >= min_count:
                # Weight by both average rating and count
                avg_rating = sum(ratings) / len(ratings)
                # Only include styles with positive ratings (>= 3.5)
                if avg_rating >= 3.5:
                    style_scores[style] = {
                        "style": style,
                        "avg_rating": round(avg_rating, 2),
                        "count": len(ratings),
                        "score": round(avg_rating * (1 + len(ratings) * 0.1), 2)
                    }

        sorted_styles = sorted(
            style_scores.values(),
            key=lambda x: x["score"],
            reverse=True
        )
        return sorted_styles[:top_n]

    def get_preferred_breweries(self, min_count: int = 2, top_n: int = 10) -> list:
        """Get top breweries by positive rating."""
        brewery_scores = {}
        for brewery, ratings in self.brewery_ratings.items():
            if len(ratings) >= min_count:
                avg_rating = sum(ratings) / len(ratings)
                if avg_rating >= 3.5:
                    brewery_scores[brewery] = {
                        "brewery": brewery,
                        "avg_rating": round(avg_rating, 2),
                        "count": len(ratings),
                    }

        sorted_breweries = sorted(
            brewery_scores.values(),
            key=lambda x: (x["avg_rating"], x["count"]),
            reverse=True
        )
        return sorted_breweries[:top_n]

    def get_abv_preference(self) -> dict:
        """Get ABV preference range."""
        if not self.abv_values:
            return {"min": None, "max": None, "avg": None}

        # Weight by ratings - higher rated beers influence preference more
        weighted_abvs = []
        for abv_bucket, ratings in self.abv_ratings.items():
            avg_rating = sum(ratings) / len(ratings) if ratings else 3.0
            if avg_rating >= 3.5:
                weighted_abvs.extend([abv_bucket] * len(ratings))

        if not weighted_abvs:
            weighted_abvs = self.abv_values

        return {
            "min": round(min(self.abv_values), 1),
            "max": round(max(self.abv_values), 1),
            "avg": round(sum(weighted_abvs) / len(weighted_abvs), 1) if weighted_abvs else None,
            "preferred_min": round(min(weighted_abvs), 1) if weighted_abvs else None,
            "preferred_max": round(max(weighted_abvs), 1) if weighted_abvs else None,
        }

    def get_rating_threshold(self) -> float:
        """Get user's average rating to determine their quality threshold."""
        if not self.all_ratings:
            return 3.5
        return round(sum(self.all_ratings) / len(self.all_ratings), 2)

    # Tried beers - store URLs and names for matching
    tried_beers: list = field(default_factory=list)  # List of {url, name, brewery, rating}

    def to_dict(self) -> dict:
        """Convert profile to dictionary for caching."""
        return {
            "username": self.username,
            "total_checkins": self.total_checkins,
            "unique_beers": self.unique_beers,
            "preferred_styles": self.get_preferred_styles(),
            "preferred_breweries": self.get_preferred_breweries(),
            "abv_preference": self.get_abv_preference(),
            "avg_rating": self.get_rating_threshold(),
            "style_counts": dict(self.style_counts),
            "brewery_counts": dict(self.brewery_counts),
            "country_counts": dict(self.country_counts),
            "tried_beers": self.tried_beers,
        }


class UntappdProfileScraper:
    """Scrapes Untappd user profiles to build taste profiles."""

    BASE_URL = "https://untappd.com"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self.request_delay = getattr(settings, "UNTAPPD_REQUEST_DELAY", 1.5)
        self.max_checkins = getattr(settings, "UNTAPPD_MAX_CHECKINS", 500)

    def _make_request(self, url: str) -> Optional[BeautifulSoup]:
        """Make a rate-limited request and return parsed HTML."""
        time.sleep(self.request_delay)

        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 404:
                logger.warning(f"User not found: {url}")
                return None
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    def _parse_beer_item(self, item) -> Optional[CheckIn]:
        """Parse a single beer item from the /beers page."""
        try:
            # Beer name - in p.name > a
            name_elem = item.select_one("p.name a")
            if not name_elem:
                return None

            beer_name = name_elem.get_text(strip=True)
            beer_url = name_elem.get("href", "")

            # Brewery - in p.brewery > a
            brewery = ""
            brewery_elem = item.select_one("p.brewery a")
            if brewery_elem:
                brewery = brewery_elem.get_text(strip=True)

            # Style - in p.style
            style = ""
            style_elem = item.select_one("p.style")
            if style_elem:
                style = style_elem.get_text(strip=True)

            # User rating - from "Their Rating (X.XX)" text or data-rating attribute
            user_rating = None
            rating_text = item.get_text()
            rating_match = re.search(r"Their Rating\s*\(([\d.]+)\)", rating_text)
            if rating_match:
                user_rating = float(rating_match.group(1))
            else:
                # Try data-rating attribute on .caps div
                caps_elem = item.select_one(".you .caps[data-rating]")
                if caps_elem:
                    try:
                        user_rating = float(caps_elem.get("data-rating", 0))
                    except ValueError:
                        pass

            # Beer's global rating
            beer_rating = None
            global_match = re.search(r"Global Rating\s*\(([\d.]+)\)", rating_text)
            if global_match:
                beer_rating = float(global_match.group(1))

            # ABV - in p.abv
            abv = None
            abv_elem = item.select_one("p.abv")
            if abv_elem:
                abv_match = re.search(r"([\d.]+)\s*%", abv_elem.get_text())
                if abv_match:
                    abv = float(abv_match.group(1))

            # IBU - in p.ibu
            ibu = None
            ibu_elem = item.select_one("p.ibu")
            if ibu_elem:
                ibu_match = re.search(r"(\d+)\s*IBU", ibu_elem.get_text())
                if ibu_match:
                    ibu = int(ibu_match.group(1))

            return CheckIn(
                beer_name=beer_name,
                brewery=brewery,
                style=style,
                user_rating=user_rating,
                beer_rating=beer_rating,
                abv=abv,
                ibu=ibu,
                untappd_url=f"{self.BASE_URL}{beer_url}" if beer_url and not beer_url.startswith("http") else beer_url,
            )

        except Exception as e:
            logger.warning(f"Failed to parse beer item: {e}")
            return None

    def _fetch_profile_stats(self, username: str) -> dict:
        """Fetch user stats from profile page (total checkins, unique beers)."""
        url = f"{self.BASE_URL}/user/{username}"
        soup = self._make_request(url)
        if not soup:
            return {"total_checkins": 0, "unique_beers": 0}

        stats = {"total_checkins": 0, "unique_beers": 0}

        # Parse stats section - format is: Total, Unique, Badges, Friends
        stats_elem = soup.select_one(".stats")
        if stats_elem:
            stat_items = stats_elem.select(".stat")
            if len(stat_items) >= 2:
                try:
                    total_text = stat_items[0].get_text(strip=True)
                    stats["total_checkins"] = int(re.sub(r"[^\d]", "", total_text))
                except (ValueError, IndexError):
                    pass
                try:
                    unique_text = stat_items[1].get_text(strip=True)
                    stats["unique_beers"] = int(re.sub(r"[^\d]", "", unique_text))
                except (ValueError, IndexError):
                    pass

        return stats

    def _fetch_beers_page(self, username: str) -> list:
        """Fetch beers from user's beers page (first page only due to AJAX limitation)."""
        url = f"{self.BASE_URL}/user/{username}/beers"
        soup = self._make_request(url)
        if not soup:
            return []

        beers = []
        beer_items = soup.select(".beer-item")

        for item in beer_items:
            beer = self._parse_beer_item(item)
            if beer and beer.beer_name:
                beers.append(beer)

        return beers

    def fetch_user_beers(self, username: str) -> list[CheckIn]:
        """Fetch beers for a user (limited to first page due to AJAX auth requirement)."""
        beers = self._fetch_beers_page(username)
        logger.info(f"Fetched {len(beers)} beers for {username}")
        return beers

    def build_taste_profile(self, username: str) -> UserTasteProfile:
        """Build a complete taste profile from user's beers."""
        from recommendations.services.style_mapper import get_style_category

        # Get actual stats from profile page
        stats = self._fetch_profile_stats(username)

        # Get beer samples from beers page
        checkins = self.fetch_user_beers(username)

        profile = UserTasteProfile(username=username)
        # Use actual stats from profile, not scraped sample count
        profile.total_checkins = stats.get("total_checkins", len(checkins))

        seen_beers = set()

        for checkin in checkins:
            beer_key = f"{checkin.beer_name}|{checkin.brewery}"

            if beer_key not in seen_beers:
                seen_beers.add(beer_key)
                # Store tried beer info for matching
                profile.tried_beers.append({
                    "name": checkin.beer_name,
                    "brewery": checkin.brewery,
                    "url": checkin.untappd_url,
                    "rating": checkin.user_rating,
                })

            # Style analysis - map to category
            if checkin.style:
                style_category = get_style_category(untappd_style=checkin.style)
                profile.style_counts[style_category] += 1
                if checkin.user_rating:
                    profile.style_ratings[style_category].append(checkin.user_rating)

            # Brewery analysis
            if checkin.brewery:
                profile.brewery_counts[checkin.brewery] += 1
                if checkin.user_rating:
                    profile.brewery_ratings[checkin.brewery].append(checkin.user_rating)

            # ABV analysis
            if checkin.abv:
                profile.abv_values.append(checkin.abv)
                # Bucket ABV for analysis
                abv_bucket = round(checkin.abv)
                if checkin.user_rating:
                    profile.abv_ratings[abv_bucket].append(checkin.user_rating)

            # IBU analysis
            if checkin.ibu:
                profile.ibu_values.append(checkin.ibu)

            # Overall ratings
            if checkin.user_rating:
                profile.all_ratings.append(checkin.user_rating)

            profile.checkins.append(checkin)

        # Use actual unique count from profile stats
        profile.unique_beers = stats.get("unique_beers", len(seen_beers))

        return profile

    def check_profile_exists(self, username: str) -> tuple[bool, str]:
        """Check if a profile exists and is public."""
        url = f"{self.BASE_URL}/user/{username}"
        soup = self._make_request(url)

        if not soup:
            return False, "Profile not found"

        # Check for private profile indicator
        private_msg = soup.select_one(".private-user")
        if private_msg:
            return False, "Profile is private"

        return True, "OK"


def get_or_create_profile(username: str, force_refresh: bool = False) -> Optional[dict]:
    """
    Get user profile from cache or scrape fresh.
    Returns profile data dict or None if profile is invalid.
    """
    from recommendations.models import CachedUserProfile

    # Check cache first
    try:
        cached = CachedUserProfile.objects.get(untappd_username=username)

        if not force_refresh and not cached.is_expired() and cached.is_valid:
            logger.info(f"Using cached profile for {username}")
            return cached.profile_data

        if not cached.is_valid:
            logger.warning(f"Cached profile for {username} is invalid: {cached.error_message}")
            return None

    except CachedUserProfile.DoesNotExist:
        cached = None

    # Scrape fresh profile
    scraper = UntappdProfileScraper()

    # Check profile exists first
    exists, message = scraper.check_profile_exists(username)
    if not exists:
        if cached:
            cached.is_valid = False
            cached.error_message = message
            cached.save()
        else:
            CachedUserProfile.objects.create(
                untappd_username=username,
                is_valid=False,
                error_message=message,
            )
        return None

    # Build profile
    try:
        profile = scraper.build_taste_profile(username)
        profile_data = profile.to_dict()

        # Update or create cache entry
        CachedUserProfile.objects.update_or_create(
            untappd_username=username,
            defaults={
                "profile_data": profile_data,
                "is_valid": True,
                "error_message": "",
            }
        )

        return profile_data

    except Exception as e:
        logger.error(f"Failed to build profile for {username}: {e}")
        if cached:
            cached.error_message = str(e)
            cached.save()
        return None
