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
    Generate recommendations in the background for Untappd users.
    Returns the full recommendation result.
    """
    from recommendations.services.recommendation_engine import get_recommendations_for_user
    from recommendations.serializers import RecommendationResultSerializer

    logger.info(f"Generating recommendations for Untappd user {username}...")

    try:
        result = get_recommendations_for_user(
            username=username,
            limit=limit,
            force_refresh=force_refresh,
            **filters
        )

        if result is None:
            logger.warning(f"Could not generate recommendations for {username}")
            # Check for specific error message in cache
            from recommendations.models import CachedUserProfile
            error_msg = "Profile not found"
            try:
                cached = CachedUserProfile.objects.get(
                    untappd_username=username,
                    profile_type='untappd'
                )
                if cached.error_message:
                    if "private" in cached.error_message.lower():
                        error_msg = "This Untappd profile is set to private. The profile needs to be made public in Untappd settings (Privacy → Profile Privacy), or you can try using an email address instead."
                    else:
                        error_msg = cached.error_message
            except CachedUserProfile.DoesNotExist:
                pass
            return {"username": username, "success": False, "error": error_msg}

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


@shared_task(bind=True, max_retries=2)
def generate_recommendations_email_task(self, email: str, limit: int = 10,
                                         force_refresh: bool = False, **filters):
    """
    Generate recommendations in the background for Shopify customers.
    Builds profile from order history.
    """
    from recommendations.services.recommendation_engine import get_recommendations_for_email
    from recommendations.serializers import RecommendationResultSerializer

    email = email.lower().strip()
    logger.info(f"Generating recommendations for Shopify customer {email}...")

    try:
        result = get_recommendations_for_email(
            email=email,
            limit=limit,
            force_refresh=force_refresh,
            **filters
        )

        if result is None:
            logger.warning(f"Could not generate recommendations for {email}")
            return {
                "email": email,
                "success": False,
                "error": "Customer not found or has no orders"
            }

        # Serialize the result
        serialized = RecommendationResultSerializer(result).data
        logger.info(f"Generated {len(result.recommendations)} recommendations for {email}")

        return {
            "email": email,
            "success": True,
            "result": serialized
        }

    except Exception as e:
        logger.error(f"Recommendation generation failed for {email}: {e}")
        raise self.retry(exc=e, countdown=30 * (2 ** self.request.retries))
