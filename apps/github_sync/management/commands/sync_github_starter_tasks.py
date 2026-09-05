import logging

from django.core.management.base import BaseCommand, CommandError

from apps.github_sync.app_client import github_app_client
from apps.github_sync.enums import SyncState
from apps.github_sync.errors import GithubAppError
from apps.github_sync.models import RepositoryConnection
from apps.github_sync.services import refresh_starter_tasks

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "DSC-009/GIT-003: refresh bounded good-first-issue/help-wanted snapshots "
        "for public repositories attached to listed projects."
    )

    def handle(self, *args, **options):
        client = github_app_client()
        if not client.is_configured:
            raise CommandError("GitHub App is not configured; starter-task sync cannot run.")
        connections = (
            RepositoryConnection.objects.filter(project__isnull=False, is_public=True)
            .exclude(sync_state=SyncState.STOPPED)
            .order_by("pk")
        )
        failures = 0
        for connection in connections:
            try:
                result = refresh_starter_tasks(connection, client)
            except GithubAppError:
                failures += 1
                logger.warning(
                    "starter-task sync failed for repository=%s pk=%s",
                    connection.full_name,
                    connection.pk,
                )
                self.stderr.write(
                    f"starter-task sync failed: {connection.full_name} (pk={connection.pk})"
                )
                continue
            self.stdout.write(
                f"starter-task snapshot {connection.full_name}: stored={result.stored} "
                f"ignored={result.ignored}"
            )
        if failures:
            raise CommandError(f"starter-task sync failed for {failures} connection(s)")
