from dataclasses import dataclass

import pytest
from django.test import override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditEvent
from apps.github_sync.enums import DeliverySource
from apps.github_sync.services import (
    ReconciliationEvent,
    ReconciliationPage,
    preview_reconciliation,
)
from apps.github_sync.tests.factories import (
    ProviderEventFactory,
    RepositoryConnectionFactory,
    parsed_payload,
)
from apps.github_sync.webhooks import ParsedEvent
from apps.ministries.tests.factories import SuperAdminFactory, UserFactory


@dataclass
class ConsoleFetcher:
    page: ReconciliationPage

    def fetch(self, repository_connection, cursor, since):
        return self.page


class ViewFetcher:
    def fetch(self, repository_connection, cursor, since):
        payload = parsed_payload(node_id=repository_connection.repository_node_id, event_id=42001)
        return ReconciliationPage(
            events=(
                ReconciliationEvent(
                    event_type="pull_request",
                    delivery_id="reconciliation-42001",
                    parsed_event=ParsedEvent(**payload),
                ),
            ),
            next_cursor="",
        )


VIEW_FETCHER = "apps.github_sync.tests.test_reconciliation_console.ViewFetcher"


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    client.get(setup_url)
    device = TOTPDevice.objects.get(user=user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(setup_url, {"token": token})
    assert response.status_code == 302


def event_for(connection, event_id):
    payload = parsed_payload(node_id=connection.repository_node_id, event_id=event_id)
    return ReconciliationEvent(
        event_type="pull_request",
        delivery_id=f"reconciliation-{event_id}",
        parsed_event=ParsedEvent(**payload),
    )


@pytest.mark.django_db
def test_preview_is_read_only_and_marks_existing_ledger_events():
    """D5.4/GIT-006: dry-run exposes pending versus already-ledgered events without mutation."""
    repository = RepositoryConnectionFactory()
    ProviderEventFactory(
        repository=repository,
        node_id=repository.repository_node_id,
        event_id=42001,
    )
    super_admin = SuperAdminFactory()
    super_admin.is_verified = lambda: True
    preview = preview_reconciliation(
        super_admin,
        repository,
        fetcher=ConsoleFetcher(
            ReconciliationPage(
                events=(event_for(repository, 42001), event_for(repository, 42002)),
                next_cursor="cursor-2",
            )
        ),
    )

    assert preview.events_found == 2
    assert preview.qualifying == 1
    assert [row.status for row in preview.events] == ["already_recorded", "pending"]
    assert repository.sync_cursor == ""
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_console_requires_super_admin_and_verified_mfa(client):
    """D5.4/AUTH-005: reconciliation is unavailable to members and unverified Super Admins."""
    repository = RepositoryConnectionFactory()
    member = UserFactory()
    client.force_login(member)

    member_response = client.get(reverse("github_sync:reconciliation", args=[repository.pk]))

    assert member_response.status_code == 403
    super_admin = SuperAdminFactory()
    super_admin.is_verified = lambda: False
    client.force_login(super_admin)
    mfa_response = client.get(reverse("github_sync:reconciliation", args=[repository.pk]))

    assert mfa_response.status_code == 302
    assert mfa_response.url == reverse("accounts:mfa_setup")


@pytest.mark.django_db
@override_settings(GITHUB_RECONCILE_FETCHER=VIEW_FETCHER)
def test_dry_run_then_apply_is_audited_and_safe_to_retry(client):
    """D5.4/GIT-006/SEC-008: preview and apply record purpose while retries deduplicate."""
    repository = RepositoryConnectionFactory()
    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)
    url = reverse("github_sync:reconciliation", args=[repository.pk])

    preview = client.post(url, {"action": "dry_run", "purpose": "Investigate webhook gap"})

    assert preview.status_code == 200
    assert preview.context["preview"].qualifying == 1
    assert AuditEvent.objects.filter(action="github_reconciliation.preview").exists()
    assert not repository.provider_events.filter(source=DeliverySource.RECONCILIATION).exists()

    applied = client.post(url, {"action": "apply", "purpose": "Investigate webhook gap"})
    retried = client.post(url, {"action": "apply", "purpose": "Investigate webhook gap"})

    assert applied.status_code == 302
    assert retried.status_code == 302
    assert repository.provider_events.filter(source=DeliverySource.RECONCILIATION).count() == 1
    audit = AuditEvent.objects.filter(action="github_reconciliation.apply").latest("created_at")
    assert audit.after["purpose"] == "Investigate webhook gap"
    assert audit.after["recovered"] == 0


@pytest.mark.django_db
@override_settings(GITHUB_RECONCILE_FETCHER=VIEW_FETCHER)
def test_apply_requires_a_meaningful_purpose(client):
    """D5.4/SEC-008: an operational reconciliation cannot run without a stated purpose."""
    repository = RepositoryConnectionFactory()
    verify_mfa(client, SuperAdminFactory())

    response = client.post(
        reverse("github_sync:reconciliation", args=[repository.pk]),
        {"action": "apply", "purpose": ""},
    )

    assert response.status_code == 400
    assert repository.provider_events.count() == 0
