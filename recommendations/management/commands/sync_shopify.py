"""
Management command to sync beers from Shopify.
Can be run manually or scheduled via cron.

Usage:
    python manage.py sync_shopify
    
For nightly sync on Dokku, add to crontab:
    0 3 * * * dokku run beer-recommender python manage.py sync_shopify
"""

from django.core.management.base import BaseCommand
from recommendations.services.shopify_sync import run_sync


class Command(BaseCommand):
    help = 'Sync beer catalog from Shopify'

    def handle(self, *args, **options):
        self.stdout.write('Starting Shopify sync...')
        
        try:
            stats = run_sync()
            
            self.stdout.write(self.style.SUCCESS(
                f"Sync completed!\n"
                f"  Processed: {stats['processed']}\n"
                f"  Created: {stats['created']}\n"
                f"  Updated: {stats['updated']}\n"
                f"  Errors: {len(stats['errors'])}"
            ))
            
            if stats['errors']:
                self.stdout.write(self.style.WARNING(
                    f"\nErrors encountered:"
                ))
                for error in stats['errors'][:10]:
                    self.stdout.write(f"  - {error}")
                if len(stats['errors']) > 10:
                    self.stdout.write(f"  ... and {len(stats['errors']) - 10} more")
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Sync failed: {str(e)}"))
            raise
