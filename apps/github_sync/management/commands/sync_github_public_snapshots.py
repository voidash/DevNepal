import logging

from django.core.management.base import BaseCommand, CommandError

from apps.github_sync.app_client import github_app_client
from apps.github_sync.enums import SyncState
from apps.github_sync.errors import GithubAppError
from apps.github_sync.models import RepositoryConnection
from apps.github_sync.services import refresh_public_repository_snapshot

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "GIT-003/GIT-010: refresh bounded public GitHub issue, pull request, "
        "and contributor snapshots."
    )

    def handle(self, *args, **options):
        client = github_app_client()
        if not client.is_configured:
            raise CommandError("GitHub App is not configured; public snapshot sync cannot run.")
        failures = 0
        connections = RepositoryConnection.objects.filter(is_public=True).exclude(
            sync_state=SyncState.STOPPED
        )
        for connection in connections.order_by("pk"):
            try:
                outcome = refresh_public_repository_snapshot(connection, client)
            except GithubAppError:
                failures += 1
                logger.warning(
                    "public snapshot sync failed for repository=%s pk=%s",
                    connection.full_name,
                    connection.pk,
                )
                continue
            self.stdout.write(
                f"public snapshot {connection.full_name}: issues={outcome.issues} "
                f"pull_requests={outcome.pull_requests} contributors={outcome.contributors}"
            )
        if failures:
            raise CommandError(f"public snapshot sync failed for {failures} connection(s)")
