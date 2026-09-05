import logging

from django.core.management.base import BaseCommand, CommandError

from apps.github_sync.services import process_pending

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "GIT-005: worker entrypoint that drains PENDING provider events into "
        "candidate contributions (idempotent; safe to re-run on a schedule)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of PENDING events to drain in this pass.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be a positive integer")

        result = process_pending(limit=limit)
        summary = f"processed={result.processed} failed={result.failed} blocked={result.blocked}"
        for event_id in result.blocked_event_ids:
            self.stdout.write(f"blocked event stays PENDING: {event_id}")

        if result.failed:
            logger.error("process_github_events finished with failures (%s)", summary)
            self.stderr.write(summary)
            raise CommandError(f"process_github_events reported failures ({summary})")

        if result.blocked:
            logger.warning(
                "process_github_events blocked %d event(s); they stay PENDING (%s)",
                result.blocked,
                summary,
            )
        else:
            logger.info("process_github_events drained the queue (%s)", summary)
        self.stdout.write(self.style.SUCCESS(summary))
