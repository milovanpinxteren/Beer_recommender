"""
DRF Serializers for the recommendations API.
"""

from rest_framework import serializers
from recommendations.models import Beer


class BeerSerializer(serializers.ModelSerializer):
    """Serializer for Beer model."""

    class Meta:
        model = Beer
        fields = [
            "id",
            "shopify_id",
            "variant_id",
            "handle",
            "title",
            "vendor",
            "price",
            "product_url",
            "image_url",
            "abv",
            "ibu",
            "style",
            "untappd_style",
            "country",
            "year",
            "untappd_url",
            "untappd_rating",
            "untappd_rating_count",
            "in_stock",
            "style_category",
            "country_region",
            "price_bucket",
        ]


class BeerMinimalSerializer(serializers.ModelSerializer):
    """Minimal serializer for beer lists."""

    class Meta:
        model = Beer
        fields = [
            "shopify_id",
            "handle",
            "title",
            "vendor",
            "price",
            "image_url",
            "abv",
            "untappd_rating",
            "style_category",
            "in_stock",
        ]


class RecommendedBeerSerializer(serializers.Serializer):
    """Serializer for a recommended beer with scoring."""
    beer = BeerSerializer()
    score = serializers.FloatField()
    reasons = serializers.ListField(child=serializers.CharField())
    is_tried = serializers.BooleanField()
    confidence = serializers.CharField()


class ProfileSummarySerializer(serializers.Serializer):
    """Serializer for user profile summary."""
    total_checkins = serializers.IntegerField()
    unique_beers = serializers.IntegerField()
    top_styles = serializers.ListField(child=serializers.CharField())
    avg_rating = serializers.FloatField()
    abv_range = serializers.CharField()


class RecommendationResultSerializer(serializers.Serializer):
    """Serializer for complete recommendation response."""
    username = serializers.CharField()
    display_name = serializers.CharField(required=False, allow_blank=True)
    profile_type = serializers.CharField(required=False, default='untappd')
    recommendations = RecommendedBeerSerializer(many=True)
    tried_beers = RecommendedBeerSerializer(many=True)
    discovery_picks = RecommendedBeerSerializer(many=True)
    profile_summary = ProfileSummarySerializer()


class RecommendationRequestSerializer(serializers.Serializer):
    """
    Serializer for recommendation request parameters.
    Accepts either 'username' (Untappd) or 'email' (Shopify customer).
    """
    username = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Untappd username"
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        help_text="Customer email address (for Shopify order-based recommendations)"
    )
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
        help_text="Number of recommendations to return"
    )
    force_refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Force re-fetch of user profile"
    )
    style_filter = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Filter to specific style category"
    )
    country_filter = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Filter to specific country or region"
    )
    price_max = serializers.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        help_text="Maximum price filter"
    )
    include_out_of_stock = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Include out of stock beers"
    )
    async_mode = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Return task ID immediately instead of waiting"
    )

    def validate(self, attrs):
        """Ensure either username or email is provided, but not both."""
        username = attrs.get('username', '').strip()
        email = attrs.get('email', '').strip()

        if not username and not email:
            raise serializers.ValidationError(
                "Either 'username' (Untappd) or 'email' (for order history) must be provided."
            )

        if username and email:
            raise serializers.ValidationError(
                "Please provide either 'username' or 'email', not both."
            )

        # Clean up empty strings
        if not username:
            attrs.pop('username', None)
        if not email:
            attrs.pop('email', None)

        return attrs


class SyncStatusSerializer(serializers.Serializer):
    """Serializer for sync status response."""
    status = serializers.CharField()
    last_sync = serializers.DateTimeField(allow_null=True)
    total_beers = serializers.IntegerField()
    in_stock_beers = serializers.IntegerField()


class StyleCategorySerializer(serializers.Serializer):
    """Serializer for style category list."""
    category = serializers.CharField()
    count = serializers.IntegerField()


class ErrorSerializer(serializers.Serializer):
    """Serializer for error responses."""
    error = serializers.CharField()
    detail = serializers.CharField(required=False)
