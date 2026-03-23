"""
API views for the beer recommendation system.
"""

import logging
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count

from celery.result import AsyncResult

from recommendations.models import Beer, SyncLog, CachedUserProfile
from recommendations.serializers import (
    BeerSerializer,
    BeerMinimalSerializer,
    RecommendationRequestSerializer,
    RecommendationResultSerializer,
    SyncStatusSerializer,
    StyleCategorySerializer,
    ErrorSerializer,
)
from recommendations.services.recommendation_engine import get_recommendations_for_user
from recommendations.services.style_mapper import get_all_style_categories, get_all_country_regions
from recommendations.tasks import generate_recommendations_task

logger = logging.getLogger(__name__)


class RecommendationsView(APIView):
    """Get personalized beer recommendations. Uses async mode when profile needs scraping."""

    def post(self, request):
        serializer = RecommendationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid request", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        data = serializer.validated_data
        username = data["username"]
        force_refresh = data.get("force_refresh", False)
        async_mode = data.get("async_mode", False)

        # Check if we have a fresh cached profile
        has_cached_profile = self._has_valid_cache(username, force_refresh)

        # If no cache or force refresh, use async mode to avoid timeout
        if not has_cached_profile or async_mode:
            return self._handle_async(data)

        # Profile is cached, can respond synchronously
        return self._handle_sync(data)

    def _has_valid_cache(self, username, force_refresh):
        if force_refresh:
            return False
        try:
            cached = CachedUserProfile.objects.get(untappd_username=username)
            return cached.is_valid and not cached.is_expired(hours=24)
        except CachedUserProfile.DoesNotExist:
            return False

    def _handle_sync(self, data):
        username = data["username"]
        try:
            result = get_recommendations_for_user(
                username=username,
                limit=data.get("limit", 10),
                force_refresh=False,
                style_filter=data.get("style_filter"),
                country_filter=data.get("country_filter"),
                price_max=float(data["price_max"]) if data.get("price_max") else None,
                include_out_of_stock=data.get("include_out_of_stock", False),
            )

            if result is None:
                return Response(
                    {"error": "Profile not found", "detail": "Could not find or access Untappd profile"},
                    status=status.HTTP_404_NOT_FOUND
                )

            response_data = RecommendationResultSerializer(result).data
            return Response(response_data)

        except Exception as e:
            logger.exception("Error generating recommendations for %s", username)
            return Response(
                {"error": "Internal error", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _handle_async(self, data):
        username = data["username"]

        filters = {}
        if data.get("style_filter"):
            filters["style_filter"] = data["style_filter"]
        if data.get("country_filter"):
            filters["country_filter"] = data["country_filter"]
        if data.get("price_max"):
            filters["price_max"] = float(data["price_max"])
        if data.get("include_out_of_stock"):
            filters["include_out_of_stock"] = data["include_out_of_stock"]

        task = generate_recommendations_task.delay(
            username=username,
            limit=data.get("limit", 10),
            force_refresh=data.get("force_refresh", False),
            **filters
        )

        return Response({
            "status": "pending",
            "task_id": task.id,
            "message": "Fetching Untappd profile for " + username + ". This may take a minute..."
        }, status=status.HTTP_202_ACCEPTED)


class TaskStatusView(APIView):
    """Check status of an async recommendation task."""

    def get(self, request, task_id):
        result = AsyncResult(task_id)

        if result.state == "PENDING":
            return Response({"status": "pending", "task_id": task_id})

        elif result.state == "SUCCESS":
            task_result = result.result
            if task_result.get("success"):
                return Response({"status": "completed", "result": task_result.get("result")})
            else:
                return Response(
                    {"status": "failed", "error": task_result.get("error", "Unknown error")},
                    status=status.HTTP_404_NOT_FOUND
                )

        elif result.state == "FAILURE":
            return Response(
                {"status": "failed", "error": str(result.result)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        else:
            return Response({"status": "processing", "task_id": task_id, "state": result.state})


class BeerListView(APIView):
    """
    List all beers with optional filtering.

    GET /api/beers/?style=IPA&country=Belgium&in_stock=true&limit=50
    """

    def get(self, request):
        queryset = Beer.objects.all()

        # Apply filters
        style = request.query_params.get("style")
        if style:
            queryset = queryset.filter(style_category=style)

        country = request.query_params.get("country")
        if country:
            queryset = queryset.filter(country=country)

        region = request.query_params.get("region")
        if region:
            queryset = queryset.filter(country_region=region)

        in_stock = request.query_params.get("in_stock")
        if in_stock and in_stock.lower() == "true":
            queryset = queryset.filter(in_stock=True)

        min_rating = request.query_params.get("min_rating")
        if min_rating:
            try:
                queryset = queryset.filter(untappd_rating__gte=float(min_rating))
            except ValueError:
                pass

        # Pagination
        limit = min(int(request.query_params.get("limit", 50)), 200)
        offset = int(request.query_params.get("offset", 0))

        total = queryset.count()
        beers = queryset[offset:offset + limit]

        serializer = BeerMinimalSerializer(beers, many=True)

        return Response({
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": serializer.data
        })


class BeerDetailView(APIView):
    """
    Get details for a specific beer.

    GET /api/beers/<shopify_id>/
    """

    def get(self, request, shopify_id):
        try:
            beer = Beer.objects.get(shopify_id=shopify_id)
            serializer = BeerSerializer(beer)
            return Response(serializer.data)
        except Beer.DoesNotExist:
            return Response(
                {"error": "Beer not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class StylesView(APIView):
    """
    List all available style categories with counts.

    GET /api/styles/
    """

    def get(self, request):
        in_stock_only = request.query_params.get("in_stock", "true").lower() == "true"

        queryset = Beer.objects.all()
        if in_stock_only:
            queryset = queryset.filter(in_stock=True)

        style_counts = (
            queryset
            .exclude(style_category="")
            .values("style_category")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        results = [
            {"category": item["style_category"], "count": item["count"]}
            for item in style_counts
        ]

        return Response({"styles": results})


class CountriesView(APIView):
    """
    List all available countries with counts.

    GET /api/countries/
    """

    def get(self, request):
        in_stock_only = request.query_params.get("in_stock", "true").lower() == "true"

        queryset = Beer.objects.all()
        if in_stock_only:
            queryset = queryset.filter(in_stock=True)

        country_counts = (
            queryset
            .exclude(country="")
            .values("country")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        results = [
            {"country": item["country"], "count": item["count"]}
            for item in country_counts
        ]

        return Response({"countries": results})


class SyncStatusView(APIView):
    """
    Get current sync status and beer counts.

    GET /api/sync/status/
    """

    def get(self, request):
        last_sync = SyncLog.objects.filter(status="completed").first()

        return Response({
            "status": "ok",
            "last_sync": last_sync.completed_at if last_sync else None,
            "total_beers": Beer.objects.count(),
            "in_stock_beers": Beer.objects.filter(in_stock=True).count(),
        })


class TriggerSyncView(APIView):
    """
    Trigger a manual sync from Shopify.

    POST /api/sync/trigger/
    """

    def post(self, request):
        from recommendations.services.shopify_sync import run_sync

        try:
            stats = run_sync()
            return Response({
                "status": "completed",
                "processed": stats["processed"],
                "created": stats["created"],
                "updated": stats["updated"],
                "errors": len(stats["errors"]),
            })
        except Exception as e:
            logger.exception("Sync failed")
            return Response(
                {"error": "Sync failed", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(["GET"])
def health_check(request):
    """Simple health check endpoint."""
    return Response({"status": "healthy"})


class TasteProfileView(APIView):
    """
    Get taste profile data formatted for visualization (radar chart, etc.)

    GET /api/profile/<username>/
    GET /api/profile/<username>/?force_refresh=true
    """

    # Define the axes for the radar chart - these are the main style categories
    RADAR_AXES = [
        "IPA",
        "Stout",
        "Sour",
        "Belgian",
        "Wild/Lambic",
        "Lager",
        "Wheat",
        "Porter",
        "Barleywine",
        "Pale Ale",
    ]

    def get(self, request, username):
        from recommendations.services.untappd_scraper import get_or_create_profile

        force_refresh = request.query_params.get("force_refresh", "").lower() == "true"

        profile_data = get_or_create_profile(username, force_refresh=force_refresh)

        if not profile_data:
            return Response(
                {"error": "Profile not found or private"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Build radar chart data
        radar_data = self._build_radar_data(profile_data)

        # Build additional chart data
        style_distribution = self._build_style_distribution(profile_data)
        abv_profile = self._build_abv_profile(profile_data)
        rating_profile = self._build_rating_profile(profile_data)
        brewery_data = self._build_brewery_data(profile_data)

        return Response({
            "username": username,
            "total_checkins": profile_data.get("total_checkins", 0),
            "unique_beers": profile_data.get("unique_beers", 0),

            # Radar chart data - normalized 0-100 scores for each axis
            "radar_chart": radar_data,

            # Style distribution for pie/donut chart
            "style_distribution": style_distribution,

            # ABV preference visualization
            "abv_profile": abv_profile,

            # Rating behavior
            "rating_profile": rating_profile,

            # Top breweries
            "top_breweries": brewery_data,

            # Raw data for custom visualizations
            "raw": {
                "style_counts": profile_data.get("style_counts", {}),
                "preferred_styles": profile_data.get("preferred_styles", []),
                "abv_preference": profile_data.get("abv_preference", {}),
            }
        })

    def _build_radar_data(self, profile_data: dict) -> dict:
        """Build radar chart data with normalized scores (0-100) for each axis."""
        style_counts = profile_data.get("style_counts", {})
        preferred_styles = {
            s["style"]: s for s in profile_data.get("preferred_styles", [])
        }

        # Find max count for normalization
        max_count = max(style_counts.values()) if style_counts else 1

        axes = []
        values = []
        details = []

        for style in self.RADAR_AXES:
            count = style_counts.get(style, 0)
            pref = preferred_styles.get(style, {})

            # Calculate score based on count and rating
            if count > 0:
                # Normalize count to 0-70 range
                count_score = (count / max_count) * 70
                # Add rating bonus (0-30) if it's a preferred style
                rating_bonus = 0
                if pref:
                    avg_rating = pref.get("avg_rating", 3.0)
                    rating_bonus = ((avg_rating - 2.5) / 2.5) * 30  # 2.5-5.0 maps to 0-30

                score = min(100, count_score + rating_bonus)
            else:
                score = 0

            axes.append(style)
            values.append(round(score, 1))
            details.append({
                "style": style,
                "count": count,
                "avg_rating": pref.get("avg_rating") if pref else None,
                "score": round(score, 1),
            })

        return {
            "axes": axes,
            "values": values,
            "details": details,
        }

    def _build_style_distribution(self, profile_data: dict) -> list:
        """Build data for pie/donut chart showing style distribution."""
        style_counts = profile_data.get("style_counts", {})
        total = sum(style_counts.values()) if style_counts else 1

        distribution = []
        for style, count in sorted(style_counts.items(), key=lambda x: -x[1]):
            distribution.append({
                "style": style,
                "count": count,
                "percentage": round((count / total) * 100, 1),
            })

        return distribution

    def _build_abv_profile(self, profile_data: dict) -> dict:
        """Build ABV preference visualization data."""
        abv_pref = profile_data.get("abv_preference", {})

        return {
            "min": abv_pref.get("min"),
            "max": abv_pref.get("max"),
            "avg": abv_pref.get("avg"),
            "preferred_min": abv_pref.get("preferred_min"),
            "preferred_max": abv_pref.get("preferred_max"),
            # For a gauge/slider visualization
            "range_label": f"{abv_pref.get('preferred_min', '?')}-{abv_pref.get('preferred_max', '?')}%",
            # Categorize the drinker
            "category": self._categorize_abv_preference(abv_pref),
        }

    def _categorize_abv_preference(self, abv_pref: dict) -> str:
        """Categorize drinker by ABV preference."""
        avg = abv_pref.get("avg")
        if not avg:
            return "Unknown"
        if avg < 5:
            return "Session Sipper"
        elif avg < 7:
            return "Balanced Drinker"
        elif avg < 10:
            return "Craft Explorer"
        elif avg < 13:
            return "Bold Adventurer"
        else:
            return "Extreme Enthusiast"

    def _build_rating_profile(self, profile_data: dict) -> dict:
        """Build rating behavior data."""
        avg_rating = profile_data.get("avg_rating", 3.5)

        return {
            "average": avg_rating,
            # Categorize rating behavior
            "category": self._categorize_rater(avg_rating),
            # For gauge visualization (position on 1-5 scale)
            "position_percent": round(((avg_rating - 1) / 4) * 100, 1),
        }

    def _categorize_rater(self, avg_rating: float) -> str:
        """Categorize how the user rates beers."""
        if avg_rating < 3.0:
            return "Critical Connoisseur"
        elif avg_rating < 3.5:
            return "Discerning Taster"
        elif avg_rating < 4.0:
            return "Fair Rater"
        elif avg_rating < 4.5:
            return "Generous Scorer"
        else:
            return "Enthusiastic Fan"

    def _build_brewery_data(self, profile_data: dict) -> list:
        """Build top breweries data."""
        preferred_breweries = profile_data.get("preferred_breweries", [])

        return [
            {
                "name": b["brewery"],
                "count": b["count"],
                "avg_rating": b["avg_rating"],
            }
            for b in preferred_breweries[:10]
        ]
