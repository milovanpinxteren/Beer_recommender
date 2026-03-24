"""
Shopify customer service.
Fetches customer order history to build taste profiles from purchase data.
"""

import logging
from typing import Optional
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
import requests

from recommendations.services.style_mapper import get_style_category

logger = logging.getLogger(__name__)


@dataclass
class PurchasedBeer:
    """Represents a beer purchased by a customer."""
    product_id: str
    variant_id: str
    title: str
    brewery: str
    quantity: int
    style: str
    style_category: str
    abv: Optional[float]
    country: str
    untappd_url: str


@dataclass
class CustomerTasteProfile:
    """
    Taste profile built from Shopify order history.
    Similar structure to UserTasteProfile from untappd_scraper.py
    """
    email: str
    customer_name: str = ""
    total_orders: int = 0
    total_items: int = 0
    unique_beers: int = 0

    # Style preferences (style_category -> count)
    style_counts: dict = field(default_factory=lambda: defaultdict(int))
    style_ratings: dict = field(default_factory=lambda: defaultdict(list))

    # Brewery preferences
    brewery_counts: dict = field(default_factory=lambda: defaultdict(int))
    brewery_ratings: dict = field(default_factory=lambda: defaultdict(list))

    # ABV preferences
    abv_values: list = field(default_factory=list)
    abv_ratings: dict = field(default_factory=lambda: defaultdict(list))

    # Country preferences
    country_counts: dict = field(default_factory=lambda: defaultdict(int))

    # Tried beers (purchased)
    tried_beers: list = field(default_factory=list)

    # For compatibility with recommendation engine
    all_ratings: list = field(default_factory=list)

    def get_preferred_styles(self, min_count: int = 1, top_n: int = 10) -> list:
        """
        Get top styles by purchase count.
        Since we don't have explicit ratings, we use purchase frequency as a proxy.
        """
        style_scores = {}
        for style, count in self.style_counts.items():
            if count >= min_count:
                # For Shopify profiles, we assume a 3.75 avg rating (slightly positive)
                # as purchasing indicates some level of preference
                avg_rating = 3.75
                style_scores[style] = {
                    "style": style,
                    "avg_rating": avg_rating,
                    "count": count,
                    "score": round(avg_rating * (1 + count * 0.1), 2)
                }

        sorted_styles = sorted(
            style_scores.values(),
            key=lambda x: x["score"],
            reverse=True
        )
        return sorted_styles[:top_n]

    def get_preferred_breweries(self, min_count: int = 1, top_n: int = 10) -> list:
        """Get top breweries by purchase count."""
        brewery_scores = {}
        for brewery, count in self.brewery_counts.items():
            if count >= min_count and brewery:
                brewery_scores[brewery] = {
                    "brewery": brewery,
                    "avg_rating": 3.75,  # Implicit positive rating from purchase
                    "count": count,
                }

        sorted_breweries = sorted(
            brewery_scores.values(),
            key=lambda x: (x["count"], x["avg_rating"]),
            reverse=True
        )
        return sorted_breweries[:top_n]

    def get_abv_preference(self) -> dict:
        """Get ABV preference range from purchased beers."""
        if not self.abv_values:
            return {
                "min": None,
                "max": None,
                "avg": None,
                "preferred_min": None,
                "preferred_max": None,
            }

        return {
            "min": round(min(self.abv_values), 1),
            "max": round(max(self.abv_values), 1),
            "avg": round(sum(self.abv_values) / len(self.abv_values), 1),
            "preferred_min": round(min(self.abv_values), 1),
            "preferred_max": round(max(self.abv_values), 1),
        }

    def get_rating_threshold(self) -> float:
        """
        For Shopify profiles, we don't have explicit ratings.
        Return a moderate threshold that allows good recommendations.
        """
        return 3.5

    def to_dict(self) -> dict:
        """Convert profile to dictionary for caching (compatible with recommendation engine)."""
        return {
            "username": self.email,  # Use email as username for compatibility
            "display_name": self.customer_name or self.email,
            "profile_type": "shopify",
            "total_checkins": self.total_items,  # Map to checkins for compatibility
            "total_orders": self.total_orders,
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


class ShopifyCustomerService:
    """
    Service to fetch customer data and order history from Shopify.
    """

    # GraphQL query to find customer by email and get their orders
    CUSTOMER_ORDERS_QUERY = """
    query getCustomerByEmail($query: String!) {
        customers(first: 1, query: $query) {
            edges {
                node {
                    id
                    email
                    firstName
                    lastName
                    numberOfOrders
                    orders(first: 100, sortKey: CREATED_AT, reverse: true) {
                        edges {
                            node {
                                id
                                name
                                createdAt
                                lineItems(first: 50) {
                                    edges {
                                        node {
                                            title
                                            quantity
                                            product {
                                                id
                                                handle
                                                title
                                                vendor
                                            }
                                            variant {
                                                id
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """

    def __init__(self):
        self.domain = settings.SHOPIFY_DOMAIN
        self.access_token = settings.SHOPIFY_ACCESS_TOKEN
        self.api_version = settings.SHOPIFY_API_VERSION
        self.endpoint = f"https://{self.domain}/admin/api/{self.api_version}/graphql.json"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token,
        }

    def _execute_query(self, query: str, variables: dict = None) -> dict:
        """Execute a GraphQL query against Shopify."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(
            self.endpoint,
            json=payload,
            headers=self.headers,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            raise Exception(f"GraphQL errors: {data['errors']}")

        return data.get("data", {})

    def get_customer_by_email(self, email: str) -> Optional[dict]:
        """
        Fetch customer data by email address.
        Returns customer dict with orders or None if not found.
        """
        try:
            data = self._execute_query(
                self.CUSTOMER_ORDERS_QUERY,
                {"query": f"email:{email}"}
            )

            customers = data.get("customers", {}).get("edges", [])
            if not customers:
                logger.info(f"No customer found with email: {email}")
                return None

            customer = customers[0]["node"]
            logger.info(
                f"Found customer {customer.get('firstName')} {customer.get('lastName')} "
                f"with {customer.get('numberOfOrders')} orders"
            )
            return customer

        except Exception as e:
            logger.error(f"Error fetching customer by email {email}: {e}")
            raise

    def build_taste_profile_from_orders(self, customer_data: dict) -> CustomerTasteProfile:
        """
        Build a taste profile from customer order history.
        Uses local Beer database to get product details (style, ABV, etc.)
        """
        from recommendations.models import Beer

        email = customer_data.get("email", "")
        first_name = customer_data.get("firstName", "")
        last_name = customer_data.get("lastName", "")
        customer_name = f"{first_name} {last_name}".strip()

        profile = CustomerTasteProfile(
            email=email,
            customer_name=customer_name,
        )

        orders = customer_data.get("orders", {}).get("edges", [])
        profile.total_orders = len(orders)

        seen_products = set()
        product_quantities = defaultdict(int)

        # First pass: collect all product IDs and quantities
        for order_edge in orders:
            order = order_edge["node"]
            line_items = order.get("lineItems", {}).get("edges", [])

            for item_edge in line_items:
                item = item_edge["node"]
                quantity = item.get("quantity", 1)
                product_data = item.get("product")

                if not product_data:
                    continue

                product_gid = product_data.get("id", "")
                product_id = product_gid.split("/")[-1] if product_gid else ""

                if product_id:
                    product_quantities[product_id] += quantity
                    profile.total_items += quantity

        # Second pass: look up products in our local database
        for product_id, quantity in product_quantities.items():
            try:
                beer = Beer.objects.get(shopify_id=product_id)

                # Track unique beers
                if product_id not in seen_products:
                    seen_products.add(product_id)
                    profile.unique_beers += 1

                    # Add to tried beers list
                    profile.tried_beers.append({
                        "name": beer.title,
                        "brewery": beer.vendor,
                        "url": beer.untappd_url or "",
                        "rating": None,  # No explicit rating from purchases
                        "shopify_id": product_id,
                    })

                # Aggregate style preferences (weighted by quantity)
                if beer.style_category:
                    profile.style_counts[beer.style_category] += quantity
                    # Use implicit rating for style_ratings
                    profile.style_ratings[beer.style_category].extend([3.75] * quantity)

                # Aggregate brewery preferences
                if beer.vendor:
                    profile.brewery_counts[beer.vendor] += quantity
                    profile.brewery_ratings[beer.vendor].extend([3.75] * quantity)

                # Aggregate ABV data
                if beer.abv:
                    profile.abv_values.extend([beer.abv] * quantity)
                    abv_bucket = round(beer.abv)
                    profile.abv_ratings[abv_bucket].extend([3.75] * quantity)

                # Aggregate country preferences
                if beer.country:
                    profile.country_counts[beer.country] += quantity

                # Track implicit ratings
                profile.all_ratings.extend([3.75] * quantity)

            except Beer.DoesNotExist:
                logger.warning(f"Product {product_id} not found in local database")
                continue

        logger.info(
            f"Built profile for {email}: {profile.total_orders} orders, "
            f"{profile.total_items} items, {profile.unique_beers} unique beers"
        )

        return profile


def get_or_create_profile_from_email(
    email: str,
    force_refresh: bool = False
) -> Optional[dict]:
    """
    Get customer profile from cache or build fresh from Shopify orders.
    Returns profile data dict or None if customer not found.
    """
    from recommendations.models import CachedUserProfile

    # Normalize email
    email = email.lower().strip()

    # Check cache first (using email as the lookup key)
    try:
        cached = CachedUserProfile.objects.get(
            email=email,
            profile_type="shopify"
        )

        if not force_refresh and not cached.is_expired() and cached.is_valid:
            logger.info(f"Using cached Shopify profile for {email}")
            return cached.profile_data

        if not cached.is_valid:
            logger.warning(f"Cached profile for {email} is invalid: {cached.error_message}")
            # Don't return None here - try to refresh

    except CachedUserProfile.DoesNotExist:
        cached = None

    # Fetch fresh from Shopify
    service = ShopifyCustomerService()

    try:
        customer_data = service.get_customer_by_email(email)

        if not customer_data:
            # Customer not found
            if cached:
                cached.is_valid = False
                cached.error_message = "Customer not found in Shopify"
                cached.save()
            else:
                CachedUserProfile.objects.create(
                    untappd_username=f"shopify_{email}",  # Unique identifier
                    email=email,
                    profile_type="shopify",
                    is_valid=False,
                    error_message="Customer not found in Shopify",
                )
            return None

        # Check if customer has any orders
        orders = customer_data.get("orders", {}).get("edges", [])
        if not orders:
            error_msg = "Customer has no orders"
            if cached:
                cached.is_valid = False
                cached.error_message = error_msg
                cached.save()
            else:
                CachedUserProfile.objects.create(
                    untappd_username=f"shopify_{email}",
                    email=email,
                    profile_type="shopify",
                    is_valid=False,
                    error_message=error_msg,
                )
            return None

        # Build taste profile from orders
        profile = service.build_taste_profile_from_orders(customer_data)
        profile_data = profile.to_dict()

        # Update or create cache entry
        CachedUserProfile.objects.update_or_create(
            email=email,
            profile_type="shopify",
            defaults={
                "untappd_username": f"shopify_{email}",  # Required field
                "profile_data": profile_data,
                "is_valid": True,
                "error_message": "",
            }
        )

        return profile_data

    except Exception as e:
        logger.error(f"Failed to build profile for {email}: {e}")
        if cached:
            cached.error_message = str(e)
            cached.save()
        return None
