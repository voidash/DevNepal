import logging

from django.core.management.base import CommandError

from apps.notifications.services import send_pending_notifications
from apps.observability.commands import InstrumentedCommand

logger = logging.getLogger(__name__)


class Command(InstrumentedCommand):
    help = (
        "NTF-002/NTF-003/NTF-004: worker entrypoint that drains queued notification "
        "emails through the configured Django email backend. Schedule it with cron or "
        "a systemd timer (e.g. every 15 minutes); it is idempotent and safe to re-run — "
        "sent rows leave the queue and failed rows are retried within the retry budget. "
        "Emails carry only the generic allowlisted subject plus an internal link "
        "(NTF-003); member opt-outs are honored while mandatory security and "
        "administrative notices always send (NTF-002)."
    )

    def handle(self, *args, **options):
        result = send_pending_notifications()
        summary = f"sent={result.sent} failed={result.failed} suppressed={result.suppressed}"

        if result.failed:
            logger.error("send_pending_notifications finished with failures (%s)", summary)
            self.stderr.write(summary)
            raise CommandError(f"send_pending_notifications reported failures ({summary})")

        if result.suppressed:
            logger.info(
                "send_pending_notifications suppressed %d opted-out row(s) (%s)",
                result.suppressed,
                summary,
            )
        else:
            logger.info("send_pending_notifications drained the queue (%s)", summary)
        self.stdout.write(self.style.SUCCESS(summary))
