from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path
from recommendations.models import Beer, CachedUserProfile, SyncLog


@admin.register(Beer)
class BeerAdmin(admin.ModelAdmin):
    list_display = ["title", "vendor", "style_category", "country", "untappd_rating", "price", "in_stock"]
    list_filter = ["style_category", "country_region", "in_stock", "price_bucket"]
    search_fields = ["title", "vendor", "handle"]
    readonly_fields = ["shopify_id", "created_at", "updated_at", "last_synced"]
    ordering = ["-untappd_rating"]
    change_list_template = "admin/beer_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('sync-shopify/', self.admin_site.admin_view(self.sync_shopify), name='sync-shopify'),
        ]
        return custom_urls + urls

    def sync_shopify(self, request):
        from recommendations.services.shopify_sync import run_sync
        try:
            stats = run_sync()
            messages.success(
                request,
                f"Sync completed! Processed: {stats['processed']}, "
                f"Created: {stats['created']}, Updated: {stats['updated']}, "
                f"Errors: {len(stats['errors'])}"
            )
        except Exception as e:
            messages.error(request, f"Sync failed: {str(e)}")
        return redirect("..")


@admin.register(CachedUserProfile)
class CachedUserProfileAdmin(admin.ModelAdmin):
    list_display = ["untappd_username", "is_valid", "updated_at"]
    list_filter = ["is_valid"]
    search_fields = ["untappd_username", "email"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ["started_at", "status", "products_processed", "products_created", "products_updated"]
    list_filter = ["status"]
    readonly_fields = ["started_at", "completed_at"]
