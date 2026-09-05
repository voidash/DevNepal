import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.github_sync.enums import ProcessingState
from apps.github_sync.models import GithubIssueSnapshot, ProviderEvent
from apps.github_sync.tests.factories import (
    WEBHOOK_SECRET,
    RepositoryConnectionFactory,
    pr_merged_body,
    sign_body,
)
from apps.github_sync.views import MAX_WEBHOOK_BODY_BYTES
from apps.projects.enums import ProjectStatus

pytestmark = [pytest.mark.integration, pytest.mark.github_webhook, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def github_sync_urlconf():
    with override_settings(
        ROOT_URLCONF="apps.github_sync.tests.urls", GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET
    ):
        yield


def webhook_headers(body, **overrides):
    headers = {
        "HTTP_X_GITHUB_EVENT": "pull_request",
        "HTTP_X_GITHUB_DELIVERY": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
        "HTTP_X_HUB_SIGNATURE_256": sign_body(body),
        "HTTP_X_GITHUB_DELIVERY_TIMESTAMP": timezone.now().isoformat(),
    }
    headers.update(overrides)
    return headers


def post_webhook(client, body, headers):
    return client.post(
        reverse("github_sync:webhook"), body, content_type="application/json", **headers
    )


class TestGithubWebhookView:
    def test_signed_issue_open_refreshes_the_public_projection_before_acknowledgement(
        self, client, monkeypatch
    ):
        """GIT-003/GIT-005: reloading after an issue webhook shows current GitHub data."""
        connection = RepositoryConnectionFactory(
            is_public=True,
            repository_node_id="R_kgDOImmediateIssue",
            full_name="voidash/civic-help-directory",
        )
        connection.project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
        connection.project.repository_url = "https://github.com/voidash/civic-help-directory"
        connection.project.save(update_fields=["status", "repository_url"])
        calls = []

        class SnapshotClient:
            def repository_metadata(self, installation_id, full_name):
                calls.append((installation_id, full_name))
                return {
                    "full_name": full_name,
                    "private": False,
                    "default_branch": "main",
                }

            def list_open_issues(self, installation_id, full_name):
                return [
                    {
                        "id": 88001,
                        "number": 18,
                        "title": "Visible without a manual refresh",
                        "body": "The signed webhook refreshed this cache.",
                        "state": "open",
                        "comments": 0,
                        "html_url": f"https://github.com/{full_name}/issues/18",
                        "updated_at": "2026-09-06T10:00:00Z",
                        "user": {
                            "login": "voidash",
                            "avatar_url": "https://avatars.githubusercontent.com/u/1",
                        },
                        "labels": [{"name": "help wanted"}],
                    }
                ]

            def list_open_pull_requests(self, installation_id, full_name):
                return []

            def list_contributors(self, installation_id, full_name):
                return []

        monkeypatch.setattr("apps.github_sync.services.github_app_client", SnapshotClient)
        body = json.dumps(
            {
                "action": "opened",
                "issue": {"id": 88001, "number": 18, "state": "open"},
                "repository": {
                    "id": 555001,
                    "node_id": connection.repository_node_id,
                    "name": "civic-help-directory",
                },
                "sender": {"login": "voidash", "type": "User"},
            }
        ).encode("utf-8")
        headers = webhook_headers(
            body,
            HTTP_X_GITHUB_EVENT="issues",
            HTTP_X_GITHUB_DELIVERY="immediate-issue-refresh",
        )

        response = post_webhook(client, body, headers)
        duplicate = post_webhook(client, body, headers)

        assert response.status_code == 202
        assert duplicate.status_code == 202
        assert calls == [(connection.installation_id, connection.full_name)]
        assert ProviderEvent.objects.get().processing_state == ProcessingState.PROCESSED
        assert GithubIssueSnapshot.objects.get(repository=connection).number == 18
        public_page = client.get(
            reverse("projects:detail", kwargs={"slug": connection.project.slug})
        )
        assert public_page.status_code == 200
        assert "Visible without a manual refresh" in public_page.content.decode()

    def test_invalid_issue_signature_never_starts_a_public_snapshot_refresh(
        self, client, monkeypatch
    ):
        """GIT-004: rejected issue payloads cannot trigger an outbound provider read."""
        calls = []
        monkeypatch.setattr(
            "apps.github_sync.services.github_app_client",
            lambda: calls.append("called"),
        )
        body = json.dumps(
            {
                "action": "opened",
                "issue": {"id": 88002, "number": 19},
                "repository": {"node_id": "R_untrusted"},
            }
        ).encode("utf-8")
        headers = webhook_headers(
            body,
            HTTP_X_GITHUB_EVENT="issues",
            HTTP_X_GITHUB_DELIVERY="invalid-issue-refresh",
            HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64,
        )

        response = post_webhook(client, body, headers)

        assert response.status_code == 401
        assert calls == []

    def test_valid_delivery_is_accepted_and_queued(self, client):
        """GIT-004/GIT-005: a signed, fresh delivery receives a quick idempotent acknowledgement."""
        body = pr_merged_body()

        response = post_webhook(client, body, webhook_headers(body))

        assert response.status_code == 202
        assert ProviderEvent.objects.get().processing_state == ProcessingState.PENDING

    def test_duplicate_delivery_is_acknowledged_without_a_second_event(self, client):
        """GIT-005: repeated GitHub delivery GUIDs receive success without duplicate processing."""
        body = pr_merged_body()
        headers = webhook_headers(body)

        first = post_webhook(client, body, headers)
        second = post_webhook(client, body, headers)

        assert first.status_code == 202
        assert second.status_code == 202
        assert ProviderEvent.objects.count() == 1

    @pytest.mark.parametrize(
        "header",
        [
            "HTTP_X_GITHUB_EVENT",
            "HTTP_X_GITHUB_DELIVERY",
            "HTTP_X_HUB_SIGNATURE_256",
        ],
    )
    def test_missing_required_header_is_rejected_before_ingestion(self, client, header):
        """GIT-004/GIT-005: event, delivery GUID, and signature headers are mandatory.

        GitHub App webhooks send no delivery-timestamp header, so its absence
        must not reject; the optional header is enforced only when present.
        """
        body = pr_merged_body()
        headers = webhook_headers(body)
        headers.pop(header)

        response = post_webhook(client, body, headers)

        assert response.status_code == 400
        assert not ProviderEvent.objects.exists()

    def test_deliveries_without_timestamp_header_are_accepted_and_ingested(self, client):
        """GIT-005: a real GitHub App delivery (no timestamp header) verifies and lands PENDING."""
        body = pr_merged_body()
        headers = webhook_headers(body)
        headers.pop("HTTP_X_GITHUB_DELIVERY_TIMESTAMP")

        response = post_webhook(client, body, headers)

        assert response.status_code == 202
        assert ProviderEvent.objects.filter(processing_state="pending").exists()

    def test_oversized_content_length_is_rejected_without_reading_or_ingesting(self, client):
        """GIT-004: oversized webhook requests are refused before signature verification."""
        body = pr_merged_body()
        headers = webhook_headers(body, CONTENT_LENGTH=str(MAX_WEBHOOK_BODY_BYTES + 1))

        response = post_webhook(client, body, headers)

        assert response.status_code == 413
        assert not ProviderEvent.objects.exists()

    def test_oversized_payload_is_rejected(self, client):
        """GIT-004: webhook payloads above the configured bound are rejected."""
        body = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
        headers = webhook_headers(body)

        response = post_webhook(client, body, headers)

        assert response.status_code == 413
        assert not ProviderEvent.objects.exists()

    def test_invalid_signature_is_unauthorized_and_does_not_expose_payload(self, client, caplog):
        """GIT-004/GIT-010: invalid signatures return unauthorized without sensitive logs."""
        body = pr_merged_body()
        headers = webhook_headers(body, HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64)

        response = post_webhook(client, body, headers)

        assert response.status_code == 401
        assert response.content == b""
        assert ProviderEvent.objects.get().processing_state == ProcessingState.REJECTED
        assert body.decode() not in caplog.text
        assert WEBHOOK_SECRET not in caplog.text

    def test_stale_delivery_is_rejected_as_a_replay(self, client):
        """GIT-005: a correctly signed stale delivery is rejected as a replay attempt."""
        body = pr_merged_body()
        headers = webhook_headers(
            body,
            HTTP_X_GITHUB_DELIVERY_TIMESTAMP=(timezone.now() - timedelta(hours=1)).isoformat(),
        )

        response = post_webhook(client, body, headers)

        assert response.status_code == 409
        assert response.content == b""
        assert ProviderEvent.objects.get().processing_state == ProcessingState.REJECTED

    def test_non_post_requests_are_not_allowed(self, client):
        """GIT-004: the webhook endpoint accepts delivery POSTs only."""
        response = client.get(reverse("github_sync:webhook"))

        assert response.status_code == 405
