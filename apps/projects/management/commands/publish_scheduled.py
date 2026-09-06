import logging

from django.utils import timezone

from apps.observability.commands import InstrumentedCommand
from apps.projects.services import publish_due_scheduled

logger = logging.getLogger(__name__)


class Command(InstrumentedCommand):
    help = "GOV-004/D5: publish approved projects whose scheduled publication time has arrived."

    def handle(self, *args, **options):
        try:
            published = publish_due_scheduled(timezone.now())
        except Exception:
            logger.exception("scheduled publication sweep failed")
            raise
        self.stdout.write(self.style.SUCCESS(f"Published {len(published)} scheduled project(s)."))
