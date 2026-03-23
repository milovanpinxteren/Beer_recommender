"""
Celery tasks for the recommendations app.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def sync_shopify_catalog(self):
    """
    Sync beer catalog from Shopify.
    Scheduled to run nightly via Celery Beat.
    """
    from recommendations.services.shopify_sync import run_sync

    logger.info("Starting scheduled Shopify sync...")

    try:
        stats = run_sync()
        logger.info(
            f"Shopify sync completed: "
            f"processed={stats['processed']}, "
            f"created={stats['created']}, "
            f"updated={stats['updated']}, "
            f"errors={len(stats['errors'])}"
        )
        return stats
    except Exception as e:
        logger.error(f"Shopify sync failed: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task
def refresh_user_profile(username: str, force_refresh: bool = True):
    """
    Refresh a user's Untappd profile in the background.
    """
    from recommendations.services.untappd_scraper import get_or_create_profile

    logger.info(f"Refreshing profile for {username}...")

    try:
        profile = get_or_create_profile(username, force_refresh=force_refresh)
        if profile:
            logger.info(f"Profile refreshed for {username}: {profile.get('unique_beers', 0)} beers")
            return {"username": username, "success": True}
        else:
            logger.warning(f"Could not refresh profile for {username}")
            return {"username": username, "success": False}
    except Exception as e:
        logger.error(f"Profile refresh failed for {username}: {e}")
        return {"username": username, "success": False, "error": str(e)}


@shared_task(bind=True, max_retries=2)
def generate_recommendations_task(self, username: str, limit: int = 10,
                                   force_refresh: bool = False, **filters):
    """
    Generate recommendations in the background.
    Returns the full recommendation result.
    """
    from recommendations.services.recommendation_engine import get_recommendations_for_user
    from recommendations.serializers import RecommendationResultSerializer

    logger.info(f"Generating recommendations for {username}...")

    try:
        result = get_recommendations_for_user(
            username=username,
            limit=limit,
            force_refresh=force_refresh,
            **filters
        )

        if result is None:
            logger.warning(f"Could not generate recommendations for {username}")
            return {"username": username, "success": False, "error": "Profile not found"}

        # Serialize the result
        serialized = RecommendationResultSerializer(result).data
        logger.info(f"Generated {len(result.recommendations)} recommendations for {username}")

        return {
            "username": username,
            "success": True,
            "result": serialized
        }

    except Exception as e:
        logger.error(f"Recommendation generation failed for {username}: {e}")
        raise self.retry(exc=e, countdown=30 * (2 ** self.request.retries))
