"""
Delete old Celery task results from the django-db result backend.

Replaces celery.backend_cleanup, which was scheduled by beat; beat was
removed 2026-08-10 (nightly sync moved to dokku cron). Runs weekly via
dokku cron (see app.json).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Delete Celery task results older than 30 days'

    def handle(self, *args, **options):
        from django_celery_results.models import TaskResult

        cutoff = timezone.now() - timedelta(days=30)
        deleted, _ = TaskResult.objects.filter(date_done__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted} old task results'))
