from django.db import models


class Beer(models.Model):
    """
    Local cache of beer products from Shopify.
    Synced daily to enable fast recommendation queries.
    """
    # Shopify identifiers
    shopify_id = models.CharField(max_length=100, unique=True, db_index=True)
    variant_id = models.CharField(max_length=100, blank=True, db_index=True)  # For Add to Cart
    handle = models.CharField(max_length=255)
    
    # Basic product info
    title = models.CharField(max_length=500)
    vendor = models.CharField(max_length=255, blank=True)  # merk/brewery
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    product_url = models.CharField(max_length=500, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    
    # Beer attributes (from Shopify metafields)
    abv = models.FloatField(null=True, blank=True, db_index=True)  # alcoholpercentage
    ibu = models.IntegerField(null=True, blank=True)  # untappd_ibu
    style = models.CharField(max_length=100, blank=True, db_index=True)  # soort_bier
    untappd_style = models.CharField(max_length=200, blank=True)  # untappd_style (detailed)
    country = models.CharField(max_length=100, blank=True, db_index=True)  # land_van_herkomst
    year = models.IntegerField(null=True, blank=True)  # brouwjaar
    
    # Untappd data
    untappd_url = models.URLField(max_length=500, blank=True)
    untappd_rating = models.FloatField(null=True, blank=True, db_index=True)
    untappd_rating_count = models.IntegerField(null=True, blank=True)
    
    # Inventory and status
    in_stock = models.BooleanField(default=True, db_index=True)
    inventory_quantity = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)  # Product is active in Shopify (not draft/archived)
    
    # Derived/computed fields for recommendations
    style_category = models.CharField(max_length=50, blank=True, db_index=True)
    country_region = models.CharField(max_length=50, blank=True, db_index=True)
    price_bucket = models.CharField(max_length=20, blank=True, db_index=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-untappd_rating', '-untappd_rating_count']
        indexes = [
            models.Index(fields=['style_category', 'in_stock']),
            models.Index(fields=['country', 'in_stock']),
            models.Index(fields=['abv', 'in_stock']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.vendor})"
    
    def save(self, *args, **kwargs):
        # Auto-compute derived fields before saving
        self.style_category = self.compute_style_category()
        self.country_region = self.compute_country_region()
        self.price_bucket = self.compute_price_bucket()
        super().save(*args, **kwargs)
    
    def compute_style_category(self) -> str:
        """Map detailed style to broad category."""
        from recommendations.services.style_mapper import get_style_category
        return get_style_category(self.style, self.untappd_style)
    
    def compute_country_region(self) -> str:
        """Map country to region for broader matching."""
        from recommendations.services.style_mapper import get_country_region
        return get_country_region(self.country)
    
    def compute_price_bucket(self) -> str:
        """Categorize price into buckets."""
        if not self.price:
            return 'unknown'
        price = float(self.price)
        if price < 5:
            return 'budget'
        elif price < 10:
            return 'standard'
        elif price < 20:
            return 'premium'
        elif price < 40:
            return 'high-end'
        else:
            return 'luxury'


class CachedUserProfile(models.Model):
    """
    Cached Untappd user profiles to avoid repeated scraping.
    Expires after 24 hours.
    """
    untappd_username = models.CharField(max_length=100, unique=True, db_index=True)
    email = models.EmailField(blank=True, null=True)
    
    # Cached profile data (JSON)
    profile_data = models.JSONField(null=True, blank=True)
    
    # Status
    is_valid = models.BooleanField(default=True)  # False if profile is private
    error_message = models.CharField(max_length=500, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.untappd_username} ({'valid' if self.is_valid else 'invalid'})"
    
    def is_expired(self, hours: int = 24) -> bool:
        """Check if cached profile is older than given hours."""
        from django.utils import timezone
        from datetime import timedelta
        return self.updated_at < timezone.now() - timedelta(hours=hours)


class SyncLog(models.Model):
    """Track Shopify sync runs for monitoring."""
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    products_processed = models.IntegerField(default=0)
    products_created = models.IntegerField(default=0)
    products_updated = models.IntegerField(default=0)
    errors = models.TextField(blank=True)
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='running'
    )
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return f"Sync {self.started_at.strftime('%Y-%m-%d %H:%M')} - {self.status}"
