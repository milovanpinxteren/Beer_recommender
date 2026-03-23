"""
Shopify product sync service.
Fetches all beer products and syncs to local database.
"""

import logging
import requests
from typing import Generator, Optional
from decimal import Decimal
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class ShopifySyncService:
    """Sync beer products from Shopify to local database."""

    PRODUCTS_QUERY = """
    query getProducts($cursor: String) {
        products(first: 50, after: $cursor) {
            pageInfo {
                hasNextPage
                endCursor
            }
            edges {
                node {
                    id
                    handle
                    title
                    vendor
                    productType
                    status
                    variants(first: 1) {
                        edges {
                            node {
                                price
                                inventoryQuantity
                            }
                        }
                    }
                    featuredImage {
                        url
                    }
                    metafields(first: 20) {
                        edges {
                            node {
                                namespace
                                key
                                value
                                type
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

        return data["data"]

    def fetch_all_products(self) -> Generator[dict, None, None]:
        """Fetch all products from Shopify with pagination."""
        cursor = None
        has_next = True

        while has_next:
            data = self._execute_query(
                self.PRODUCTS_QUERY,
                {"cursor": cursor}
            )

            products_data = data["products"]
            page_info = products_data["pageInfo"]

            for edge in products_data["edges"]:
                yield edge["node"]

            has_next = page_info["hasNextPage"]
            cursor = page_info["endCursor"]

            logger.info(f"Fetched page, has_next: {has_next}")

    def _parse_metafields(self, metafield_edges: list) -> dict:
        """Parse metafield edges into a flat dictionary."""
        metafields = {}
        for edge in metafield_edges:
            mf = edge["node"]
            key = f"{mf['namespace']}.{mf['key']}"
            metafields[key] = {
                "value": mf["value"],
                "type": mf["type"]
            }
        return metafields

    def _parse_rating_value(self, value: str) -> Optional[float]:
        """Parse rating metafield JSON value."""
        import json
        try:
            data = json.loads(value)
            return float(data.get("value", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _extract_numeric(self, value: str, as_int: bool = False) -> Optional[float | int]:
        """Extract numeric value from string."""
        if not value:
            return None
        try:
            num = float(value)
            return int(num) if as_int else num
        except (TypeError, ValueError):
            return None

    def _parse_link_value(self, value: str) -> str:
        """Parse link metafield JSON value to extract URL."""
        import json
        if not value:
            return ""
        try:
            data = json.loads(value)
            return data.get("url", "")
        except (json.JSONDecodeError, TypeError):
            # If not JSON, return as-is (might be plain URL)
            return value if value.startswith("http") else ""

    def transform_product(self, product: dict) -> dict:
        """Transform Shopify product data to Beer model fields."""
        metafields = self._parse_metafields(
            product.get("metafields", {}).get("edges", [])
        )

        # Get first variant for price/inventory
        variants = product.get("variants", {}).get("edges", [])
        first_variant = variants[0]["node"] if variants else {}

        # Extract Shopify numeric ID from gid
        shopify_gid = product["id"]  # gid://shopify/Product/123456
        shopify_id = shopify_gid.split("/")[-1]

        # Parse metafield values
        abv = self._extract_numeric(
            metafields.get("custom.alcoholpercentage", {}).get("value")
        )
        ibu = self._extract_numeric(
            metafields.get("custom.untappd_ibu", {}).get("value"),
            as_int=True
        )
        year = self._extract_numeric(
            metafields.get("custom.brouwjaar", {}).get("value"),
            as_int=True
        )

        # Untappd rating (special JSON format)
        untappd_rating = None
        rating_raw = metafields.get("custom.untappd_score", {}).get("value")
        if rating_raw:
            untappd_rating = self._parse_rating_value(rating_raw)

        untappd_rating_count = self._extract_numeric(
            metafields.get("custom.untappd_rating_count", {}).get("value"),
            as_int=True
        )

        # Build product URL
        product_url = f"https://{self.domain.replace('.myshopify.com', '.com')}/products/{product['handle']}"

        return {
            "shopify_id": shopify_id,
            "handle": product["handle"],
            "title": product["title"],
            "vendor": product.get("vendor", ""),
            "price": Decimal(first_variant.get("price", "0")) if first_variant.get("price") else None,
            "product_url": product_url,
            "image_url": product.get("featuredImage", {}).get("url", "") if product.get("featuredImage") else "",
            "abv": abv,
            "ibu": ibu,
            "style": metafields.get("custom.soort_bier", {}).get("value", ""),
            "untappd_style": metafields.get("custom.untappd_style", {}).get("value", ""),
            "country": metafields.get("custom.land_van_herkomst", {}).get("value", ""),
            "year": year,
            "untappd_url": self._parse_link_value(metafields.get("custom.untappd_link", {}).get("value", "")),
            "untappd_rating": untappd_rating,
            "untappd_rating_count": untappd_rating_count,
            "in_stock": (first_variant.get("inventoryQuantity", 0) or 0) > 0,
            "inventory_quantity": first_variant.get("inventoryQuantity", 0) or 0,
            "last_synced": timezone.now(),
        }

    def sync_all(self, log_entry=None) -> dict:
        """
        Sync all products from Shopify to local database.
        Returns stats about the sync operation.
        """
        from recommendations.models import Beer

        stats = {
            "processed": 0,
            "created": 0,
            "updated": 0,
            "errors": [],
        }

        for product in self.fetch_all_products():
            try:
                # Skip drafts
                if product.get("status") != "ACTIVE":
                    continue

                transformed = self.transform_product(product)

                # Upsert: update if exists, create if not
                beer, created = Beer.objects.update_or_create(
                    shopify_id=transformed["shopify_id"],
                    defaults=transformed
                )

                stats["processed"] += 1
                if created:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1

                if stats["processed"] % 100 == 0:
                    logger.info(f"Processed {stats['processed']} products...")
                    if log_entry:
                        log_entry.products_processed = stats["processed"]
                        log_entry.save(update_fields=["products_processed"])

            except Exception as e:
                error_msg = f"Error processing {product.get('handle', 'unknown')}: {str(e)}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)

        logger.info(f"Sync complete: {stats}")
        return stats


def run_sync():
    """Run a full sync and log results."""
    from recommendations.models import SyncLog

    log = SyncLog.objects.create(status="running")

    try:
        service = ShopifySyncService()
        stats = service.sync_all(log_entry=log)

        log.products_processed = stats["processed"]
        log.products_created = stats["created"]
        log.products_updated = stats["updated"]
        log.errors = "\n".join(stats["errors"]) if stats["errors"] else ""
        log.status = "completed"
        log.completed_at = timezone.now()
        log.save()

        return stats

    except Exception as e:
        log.status = "failed"
        log.errors = str(e)
        log.completed_at = timezone.now()
        log.save()
        raise
