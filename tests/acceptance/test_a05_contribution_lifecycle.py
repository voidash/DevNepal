"""A5 — Merged-PR webhook → single candidate → verification → reversible recognition.

Signature validation, delivery deduplication, and the provider-event ledger
belong to apps/github_sync (their tests cover GIT-004/GIT-005 transport);
this slice owns the contribution lifecycle from the parsed event onward.
The contributor link stands in for the GithubConnection actor mapping that
apps/github_sync will provide (record starts pending_mapping until then).
"""

import pytest

from apps.audit.models import AuditEvent
from apps.contributions.enums import VerificationStatus
from apps.contributions.services import (
    accepted_contributions,
    record_candidate_from_github,
    revoke,
    verify,
)
from apps.github_sync.webhooks import parse_event
from apps.projects.tests.factories import (
    ProjectFactory,
    ProjectMaintainerFactory,
    SuperAdminFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def merged_pr(event_id=501, login="shanker"):
    return parse_event(
        "pull_request",
        {
            "action": "closed",
            "sender": {"login": login, "type": "User"},
            "repository": {"node_id": "R_1", "name": "service-directory"},
            "pull_request": {"id": event_id, "number": 7, "merged": True},
        },
    )


def test_a05_merged_pr_webhook_creates_single_candidate_then_verifies_then_revokes():
    """A5/GIT-008/BR-006/REC-005: candidate→verify→credit basis→reversal with audit reason."""
    project = ProjectFactory()
    maintainer = ProjectMaintainerFactory(project=project).user

    record = record_candidate_from_github(merged_pr(), project)
    assert record is not None
    assert record.status == VerificationStatus.CANDIDATE
    assert record.pending_mapping is True
    assert project.contributions.count() == 1

    replay = record_candidate_from_github(merged_pr(), project)
    assert replay.pk == record.pk
    assert project.contributions.count() == 1

    record.contributor = UserFactory()
    record.pending_mapping = False
    record.save(update_fields=["contributor", "pending_mapping"])

    verified = verify(maintainer, record, VerificationStatus.ACCEPTED, "Reviewed and merged")
    assert verified.status == VerificationStatus.ACCEPTED
    assert list(accepted_contributions(record.contributor)) == [record]

    revoked = revoke(SuperAdminFactory(), record, "Reverted after audit finding")
    assert revoked.status == VerificationStatus.REVOKED
    audit_actions = set(
        AuditEvent.objects.filter(
            content_type__app_label="contributions", object_id=str(record.pk)
        ).values_list("action", flat=True)
    )
    assert {"contribution.accepted", "contribution.revoked"} <= audit_actions
