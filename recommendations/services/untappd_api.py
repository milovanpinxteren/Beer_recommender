"""
Official Untappd API v4 client.

Untappd made user beer lists login-only on the website — `/user/<name>/beers`
now 307-redirects to `/login`, so scraping them is no longer possible. The
official `user/beers` endpoint returns the same data and needs only application
credentials (client_id + client_secret), not a per-user OAuth login, so users
still only have to supply their username.

Rate limit: 100 calls/hour per key, max 50 beers per call. Profiles are cached
(see CachedUserProfile) and built in the background precisely because of this —
never call this from a synchronous request path without a cache check first.

Docs: https://untappd.com/api/docs#userbeers
"""

import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.untappd.com/v4"

# The API allows at most 50 per call; fewer calls per profile means more
# profiles served per hour against the 100 calls/hour budget.
PAGE_SIZE = 50


class UntappdAPIError(Exception):
    """Raised when the Untappd API returns an error we cannot recover from."""

    def __init__(self, message: str, status_code: int = None, rate_limited: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limited = rate_limited


class UntappdAPIClient:
    """Reads user beer lists from the official Untappd API."""

    def __init__(self, client_id: str = None, client_secret: str = None):
        self.client_id = client_id or getattr(settings, "UNTAPPD_CLIENT_ID", "")
        self.client_secret = client_secret or getattr(settings, "UNTAPPD_CLIENT_SECRET", "")
        self.timeout = getattr(settings, "UNTAPPD_API_TIMEOUT", 15)
        # Cap how much history we pull per user. A taste profile converges long
        # before a full 1000+ beer history, and each extra page costs one of the
        # 100 hourly calls.
        self.max_beers = getattr(settings, "UNTAPPD_API_MAX_BEERS", 300)
        self.session = requests.Session()

    def is_configured(self) -> bool:
        """True when API credentials are available."""
        return bool(self.client_id and self.client_secret)

    def _auth_params(self) -> dict:
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

    def _get(self, path: str, params: dict = None) -> dict:
        if not self.is_configured():
            raise UntappdAPIError("Untappd API credentials are not configured")

        query = self._auth_params()
        query.update(params or {})

        try:
            response = self.session.get(
                f"{API_BASE}/{path.lstrip('/')}", params=query, timeout=self.timeout
            )
        except requests.Timeout:
            raise UntappdAPIError("Untappd API request timed out")
        except requests.RequestException as e:
            raise UntappdAPIError(f"Untappd API request failed: {e}")

        # 429 is the documented rate-limit signal; surface it distinctly so
        # callers can back off rather than marking the profile invalid.
        if response.status_code == 429:
            raise UntappdAPIError(
                "Untappd API rate limit reached (100 calls/hour)",
                status_code=429,
                rate_limited=True,
            )

        try:
            payload = response.json()
        except ValueError:
            raise UntappdAPIError(
                f"Untappd API returned non-JSON response (HTTP {response.status_code})",
                status_code=response.status_code,
            )

        meta = payload.get("meta", {})
        code = meta.get("code", response.status_code)

        if code != 200:
            detail = (
                meta.get("error_detail")
                or meta.get("developer_friendly")
                or meta.get("error_type")
                or f"HTTP {code}"
            )
            # Untappd reports its own rate limiting through meta as well.
            rate_limited = code == 429 or "rate limit" in str(detail).lower()
            raise UntappdAPIError(detail, status_code=code, rate_limited=rate_limited)

        return payload.get("response", {})

    def check_user_exists(self, username: str) -> tuple[bool, str]:
        """
        Check whether a username resolves. Mirrors the scraper's contract so it
        can be swapped in directly.
        """
        try:
            self.get_user_beers(username, max_beers=1)
            return True, "OK"
        except UntappdAPIError as e:
            if e.rate_limited:
                # Do not report a rate limit as a missing profile — that would
                # get cached as permanently invalid.
                raise
            if e.status_code in (404, 500) or "not found" in str(e).lower():
                return False, "Profile not found"
            return False, str(e)

    def get_user_beers(self, username: str, max_beers: int = None) -> list:
        """
        Fetch a user's distinct beers, paging until max_beers or exhaustion.

        Returns a list of CheckIn objects, matching what the scraper produced so
        build_taste_profile() works unchanged.
        """
        from recommendations.services.untappd_scraper import CheckIn

        limit = max_beers if max_beers is not None else self.max_beers
        checkins = []
        offset = 0

        while len(checkins) < limit:
            page_size = min(PAGE_SIZE, limit - len(checkins))
            data = self._get(
                f"user/beers/{username}",
                {"limit": page_size, "offset": offset, "sort": "highest_rated_you"},
            )

            beers = data.get("beers", {}) or {}
            items = beers.get("items", []) or []
            if not items:
                break

            for item in items:
                checkin = self._parse_item(item, CheckIn)
                if checkin:
                    checkins.append(checkin)

            offset += len(items)

            total = data.get("total_count")
            if total is not None and offset >= total:
                break
            # Defensive: a short page means there is nothing more to read.
            if len(items) < page_size:
                break

        logger.info(f"Untappd API: fetched {len(checkins)} beers for {username}")
        return checkins

    def get_user_total_count(self, username: str) -> Optional[int]:
        """Total distinct beers for a user, for profile stats."""
        try:
            data = self._get(f"user/beers/{username}", {"limit": 1})
            return data.get("total_count")
        except UntappdAPIError:
            return None

    def _parse_item(self, item: dict, checkin_cls):
        """Map one API item onto the CheckIn shape used by the profile builder."""
        try:
            beer = item.get("beer", {}) or {}
            brewery = item.get("brewery", {}) or {}

            beer_name = beer.get("beer_name") or ""
            if not beer_name:
                return None

            def _num(value):
                try:
                    return float(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    return None

            # The user's own rating; 0 means "not rated" in the API.
            user_rating = _num(item.get("rating_score"))
            if not user_rating:
                user_rating = None

            ibu = _num(beer.get("beer_ibu"))
            slug = beer.get("beer_slug") or ""
            bid = beer.get("bid") or ""

            return checkin_cls(
                beer_name=beer_name,
                brewery=brewery.get("brewery_name") or "",
                style=beer.get("beer_style") or "",
                user_rating=user_rating,
                beer_rating=_num(beer.get("rating_score")),
                abv=_num(beer.get("beer_abv")),
                ibu=int(ibu) if ibu else None,
                untappd_url=f"https://untappd.com/b/{slug}/{bid}" if slug and bid else "",
            )
        except Exception as e:
            logger.warning(f"Failed to parse Untappd API item: {e}")
            return None
