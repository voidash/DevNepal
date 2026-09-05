from datetime import UTC, datetime

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.contributions.models import ContributionRecord
from apps.github_sync.enums import ProcessingState, Provider
from apps.github_sync.services import ingest_webhook, process_pending
from apps.github_sync.tests.factories import (
    WEBHOOK_SECRET,
    GithubConnectionFactory,
    RepositoryConnectionFactory,
    pr_merged_body,
    sign_body,
)
from apps.projects.services import approve, publish, submit_for_review
from apps.projects.tests.factories import SuperAdminFactory, make_publishable

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def test_a09_queued_webhook_recovers_without_blocking_public_catalog(client):
    """A9/GIT-005/GIT-006: queued GitHub work recovers without duplicate credit or read outage."""
    project = make_publishable()
    super_admin = SuperAdminFactory()
    submit_for_review(project.owner, project)
    approve(super_admin, project)
    publish(super_admin, project)
    member_connection = GithubConnectionFactory(login="outage-member")
    repository = RepositoryConnectionFactory(
        project=project,
        repository_node_id="R_kgDOOutage",
    )
    body = pr_merged_body(
        node_id=repository.repository_node_id,
        login=member_connection.login,
        pr_id=804,
    )
    timestamp = str(int(datetime.now(UTC).timestamp()))

    with override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET):
        event = ingest_webhook(
            Provider.GITHUB,
            "pull_request",
            "delivery-outage-804",
            sign_body(body),
            timestamp,
            body,
        )
        duplicate = ingest_webhook(
            Provider.GITHUB,
            "pull_request",
            "delivery-outage-804",
            sign_body(body),
            timestamp,
            body,
        )

    browse = client.get(reverse("projects:list"))
    result = process_pending()

    event.refresh_from_db()
    assert browse.status_code == 200
    assert duplicate.pk == event.pk
    assert event.processing_state == ProcessingState.PROCESSED
    assert result.processed == 1
    assert ContributionRecord.objects.filter(project=project).count() == 1
