import importlib
import logging

from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Q
from django.utils import timezone

from apps.github_sync import services
from apps.github_sync.enums import SyncState
from apps.github_sync.models import RepositoryConnection
from apps.observability.commands import InstrumentedCommand

logger = logging.getLogger(__name__)


def load_fetcher(dotted_path: str):
    """GIT-006: resolve the settings-configured fetcher from its dotted class path."""
    module_name, _, attribute = dotted_path.rpartition(".")
    if not module_name:
        raise ImportError(f"{dotted_path!r} is not a dotted import path")
    return getattr(importlib.import_module(module_name), attribute)


class Command(InstrumentedCommand):
    help = (
        "GIT-006: sweep every active repository connection through the configured "
        "fetcher to recover missed webhook events. Uses the production GitHub "
        "App API fetcher unless GITHUB_RECONCILE_FETCHER overrides it."
    )

    def handle(self, *args, **options):
        dotted_path = getattr(settings, "GITHUB_RECONCILE_FETCHER", "")
        if dotted_path:
            try:
                fetcher_class = load_fetcher(dotted_path)
            except (AttributeError, ImportError, ModuleNotFoundError) as exc:
                logger.exception("reconcile_repositories has an invalid fetcher path")
                raise CommandError(
                    f"GITHUB_RECONCILE_FETCHER is not importable: {dotted_path}"
                ) from exc
        else:
            fetcher_class = services.GithubReconciliationFetcher

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
                    connection, since=connection.last_synced_at, fetcher=fetcher_class()
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
