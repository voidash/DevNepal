from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from apps.audit.models import AuditEvent
from apps.github_sync.models import GithubConnection, RepositoryConnection
from apps.github_sync.services import disconnect
from apps.github_sync.tests.factories import GithubConnectionFactory, RepositoryConnectionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def test_a10_checked_in_recovery_protocol_preserves_the_staging_evidence_boundary():
    """A10/NFR-DR-01/SEC-002: a local test cannot be substituted for a timed restore drill.

    The production recovery procedure must name the isolated PostgreSQL/object-storage
    exercise, integrity checks, RPO/RTO evidence, and the explicit no-completion boundary.
    """
    root = Path(settings.BASE_DIR)
    backup_runbook = (root / "docs/operations/backup-restore-runbook.md").read_text()
    incident_runbook = (root / "docs/operations/incident-response-runbook.md").read_text()
    normalized_backup_runbook = backup_runbook.replace("\n", " ")

    for phrase in (
        "**Status:** Draft.",
        "Do not claim A10 completion",
        "isolated recovery environment",
        "RPO <= 24 hours",
        "RTO <= 8 hours",
        "audit_auditevent",
        "github_sync_providerevent",
        "Do not substitute a successful local SQLite test run",
    ):
        assert phrase in normalized_backup_runbook
    for phrase in (
        "**Status:** Draft.",
        "named on-call roster",
        "restricted incident record",
        "Executable Application Containment",
        "Exercise this runbook with security and operations contacts before launch.",
    ):
        assert phrase in incident_runbook


def test_a10_connection_containment_executes_token_purge_and_preserves_an_audit_record():
    """A10/SEC-013/GIT-011: a tested containment action stops user-scoped GitHub sync safely."""
    connection = GithubConnectionFactory()
    repository = RepositoryConnectionFactory(activated_by=connection.user)
    purged_users = []

    def purge_token(user):
        purged_users.append(user.pk)
        return 1

    with override_settings(GITHUB_TOKEN_PURGE=purge_token):
        disconnect(connection.user)

    connection.refresh_from_db()
    repository.refresh_from_db()
    assert connection.is_active is False
    assert connection.revoked_at is not None
    assert repository.deactivated_at is not None
    assert purged_users == [connection.user.pk]
    assert AuditEvent.objects.filter(
        actor=connection.user,
        action="github_connection.disconnect",
        object_id=str(connection.pk),
    ).exists()
    assert (
        GithubConnection.objects.filter(user=connection.user, revoked_at__isnull=True).count() == 0
    )
    assert (
        RepositoryConnection.objects.filter(
            activated_by=connection.user, deactivated_at__isnull=True
        ).count()
        == 0
    )
