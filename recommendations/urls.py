"""
URL configuration for recommendations API.
"""

from django.urls import path
from recommendations.views import (
    RecommendationsView,
    BeerListView,
    BeerDetailView,
    StylesView,
    CountriesView,
    SyncStatusView,
    TriggerSyncView,
    TasteProfileView,
    health_check,
)

urlpatterns = [
    # Health check
    path("health/", health_check, name="health_check"),

    # Recommendations
    path("recommendations/", RecommendationsView.as_view(), name="recommendations"),

    # Taste profile (for visualizations)
    path("profile/<str:username>/", TasteProfileView.as_view(), name="taste_profile"),

    # Beer catalog
    path("beers/", BeerListView.as_view(), name="beer_list"),
    path("beers/<str:shopify_id>/", BeerDetailView.as_view(), name="beer_detail"),

    # Filters
    path("styles/", StylesView.as_view(), name="styles"),
    path("countries/", CountriesView.as_view(), name="countries"),

    # Sync management
    path("sync/status/", SyncStatusView.as_view(), name="sync_status"),
    path("sync/trigger/", TriggerSyncView.as_view(), name="sync_trigger"),
]
