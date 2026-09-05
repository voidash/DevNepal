import logging

from django.core.management.base import CommandError
from django.db.models import Q
from django.utils import timezone

from apps.github_sync import services
from apps.github_sync.enums import SyncState
from apps.github_sync.models import RepositoryConnection
from apps.observability.commands import InstrumentedCommand

logger = logging.getLogger(__name__)


class Command(InstrumentedCommand):
    help = (
        "GIT-006: sweep every active repository connection through the configured "
        "fetcher to recover missed webhook events. Uses the production GitHub "
        "App API fetcher unless GITHUB_RECONCILE_FETCHER overrides it."
    )

    def handle(self, *args, **options):
        try:
            fetcher = services.configured_reconciliation_fetcher()
        except services.ReconciliationError as exc:
            logger.exception("reconcile_repositories has an invalid fetcher path")
            raise CommandError("GITHUB_RECONCILE_FETCHER is not importable") from exc

        connections = (
            RepositoryConnection.objects.exclude(sync_state=SyncState.STOPPED)
            .filter(project__isnull=False, deactivated_at__isnull=True)
            .filter(
                Q(next_sync_attempt_at__isnull=True) | Q(next_sync_attempt_at__lte=timezone.now())
            )
            .order_by("pk")
        )
        failures = 0
        for connection in connections:
            try:
                recovered = services.reconcile(
                    connection, since=connection.last_synced_at, fetcher=fetcher
                )
            except services.ReconciliationError:
                failures += 1
                logger.warning(
                    "reconcile_repositories failed for %s (pk=%s)",
                    connection.full_name,
                    connection.pk,
                )
                self.stderr.write(f"reconcile failed: {connection.full_name} (pk={connection.pk})")
                continue
            logger.info(
                "reconcile_repositories recovered %d event(s) for %s (pk=%s)",
                recovered,
                connection.full_name,
                connection.pk,
            )
            self.stdout.write(f"reconciled {connection.full_name}: recovered={recovered}")

        if failures:
            raise CommandError(f"reconciliation failed for {failures} connection(s)")
