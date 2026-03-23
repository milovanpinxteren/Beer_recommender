"""Script to update scraper with profile stats fetching."""

import re

# Read the current scraper file
with open('recommendations/services/untappd_scraper.py', 'r') as f:
    content = f.read()

# Replace the _fetch_beers_initial and related methods
old_code = '''    def _fetch_beers_initial(self, username: str) -> tuple:
        """
        Fetch initial beers page from /user/{username}/beers.
        Returns (beers, total_count).
        """
        url = f"{self.BASE_URL}/user/{username}/beers"
        soup = self._make_request(url)
        if not soup:
            return [], 0

        beers = []
        beer_items = soup.select(".beer-item")

        for item in beer_items:
            beer = self._parse_beer_item(item)
            if beer and beer.beer_name:
                beers.append(beer)

        # Try to get total count from stats
        total_count = len(beers)
        stats_elem = soup.select_one(".stats .count, .beer-stats .total")
        if stats_elem:
            try:
                total_count = int(re.sub(r"[^\\d]", "", stats_elem.get_text()))
            except ValueError:
                pass

        return beers, total_count

    def _fetch_beers_ajax(self, username: str, offset: int) -> tuple:
        """
        Fetch more beers via AJAX endpoint /profile/more_beer/{username}.
        Returns (beers, has_more).
        """
        url = f"{self.BASE_URL}/profile/more_beer/{username}?offset={offset}"

        time.sleep(self.request_delay)

        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            # This endpoint returns HTML fragment
            soup = BeautifulSoup(response.text, "html.parser")

            beers = []
            beer_items = soup.select(".beer-item")

            for item in beer_items:
                beer = self._parse_beer_item(item)
                if beer and beer.beer_name:
                    beers.append(beer)

            # If we got beers, there might be more
            has_more = len(beers) > 0

            return beers, has_more

        except requests.RequestException as e:
            logger.error(f"AJAX request failed for {username} offset {offset}: {e}")
            return [], False

    def fetch_user_beers(self, username: str) -> list[CheckIn]:
        """Fetch all beers for a user using initial page + AJAX pagination."""
        all_beers = []

        # First, get initial page
        beers, total_count = self._fetch_beers_initial(username)
        all_beers.extend(beers)
        logger.info(f"Initial fetch: {len(beers)} beers for {username}")

        if not beers:
            return []

        # Then paginate via AJAX endpoint
        offset = len(beers)
        while len(all_beers) < self.max_checkins:
            beers, has_more = self._fetch_beers_ajax(username, offset)

            if not beers:
                break

            all_beers.extend(beers)
            offset += len(beers)
            logger.info(f"Fetched {len(all_beers)} beers for {username}")

            if not has_more:
                break

        return all_beers[:self.max_checkins]

    def build_taste_profile(self, username: str) -> UserTasteProfile:
        """Build a complete taste profile from user's beers."""
        from recommendations.services.style_mapper import get_style_category

        checkins = self.fetch_user_beers(username)

        profile = UserTasteProfile(username=username)
        profile.total_checkins = len(checkins)'''

new_code = '''    def _fetch_profile_stats(self, username: str) -> dict:
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
                    stats["total_checkins"] = int(re.sub(r"[^\\d]", "", total_text))
                except (ValueError, IndexError):
                    pass
                try:
                    unique_text = stat_items[1].get_text(strip=True)
                    stats["unique_beers"] = int(re.sub(r"[^\\d]", "", unique_text))
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
        profile.total_checkins = stats.get("total_checkins", len(checkins))'''

if old_code in content:
    content = content.replace(old_code, new_code)

    # Also update the unique_beers assignment
    old_unique = '''        profile.unique_beers = len(seen_beers)

        return profile'''
    new_unique = '''        # Use actual unique count from profile stats
        profile.unique_beers = stats.get("unique_beers", len(seen_beers))

        return profile'''

    content = content.replace(old_unique, new_unique)

    with open('recommendations/services/untappd_scraper.py', 'w') as f:
        f.write(content)
    print('Scraper updated successfully!')
else:
    print('Old code not found. Current file structure may be different.')
    # Try to find what pattern exists
    if '_fetch_beers_initial' in content:
        print('Found _fetch_beers_initial')
    if '_fetch_profile_stats' in content:
        print('Found _fetch_profile_stats - already updated?')
