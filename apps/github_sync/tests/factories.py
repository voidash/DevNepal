import hashlib
import hmac
import json

import factory
from factory import Sequence, SubFactory
from factory.django import DjangoModelFactory

from apps.github_sync.enums import DeliverySource, ProcessingState, Provider, SyncState
from apps.github_sync.models import GithubConnection, ProviderEvent, RepositoryConnection
from apps.ministries.tests.factories import UserFactory
from apps.projects.tests.factories import ProjectFactory

WEBHOOK_SECRET = "webhook-test-secret-0123456789abcdef"


def sign_body(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """GIT-004: compute the X-Hub-Signature-256 header value for a raw body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def pr_merged_body(
    *,
    node_id="R_kgDOKExAmPlE",
    login="cdjk",
    author_login=None,
    number=42,
    pr_id=987654,
) -> bytes:
    """GIT-007/D7: raw GitHub pull_request closed+merged webhook payload."""
    payload = {
        "action": "closed",
        "pull_request": {
            "id": pr_id,
            "number": number,
            "merged": True,
            "user": {"login": author_login or login, "type": "User"},
            "base": {"ref": "main"},
        },
        "repository": {
            "id": 555001,
            "node_id": node_id,
            "name": "gov-portal",
            "default_branch": "main",
        },
        "sender": {"login": login, "type": "User"},
    }
    return json.dumps(payload).encode("utf-8")


def parsed_payload(
    *,
    node_id,
    event_id,
    kind="pr_merged",
    action="closed",
    login="cdjk",
    actor_type="User",
    is_bot=False,
    number=42,
    name="gov-portal",
) -> dict:
    """GIT-012: the minimal parsed-field payload stored on a ProviderEvent."""
    return {
        "kind": kind,
        "action": action,
        "actor_login": login,
        "actor_type": actor_type,
        "is_bot": is_bot,
        "repository_node_id": node_id,
        "repository_name": name,
        "number": number,
        "event_id": str(event_id),
        "triggered_by_login": login,
    }


class GithubConnectionFactory(DjangoModelFactory):
    """GIT-002/AUTH-008: user-level connection with consent provenance."""

    class Meta:
        model = GithubConnection

    user = SubFactory(UserFactory)
    provider = Provider.GITHUB
    github_user_id = Sequence(lambda n: 1_000_000 + n)
    login = Sequence(lambda n: f"ghmember{n}")
    scopes = factory.LazyFunction(lambda: ["read:user", "public_repo"])
    consent_scopes = factory.LazyFunction(lambda: ["read:user", "public_repo"])
    show_annual_calendar = False


class RepositoryConnectionFactory(DjangoModelFactory):
    """GIT-003/GIT-006: enrolled repository feeding a listed project."""

    class Meta:
        model = RepositoryConnection

    provider = Provider.GITHUB
    installation_id = Sequence(lambda n: 400_000 + n)
    repository_id = Sequence(lambda n: 500_000 + n)
    repository_node_id = Sequence(lambda n: f"R_kgDOFakeNode{n:08d}")
    full_name = Sequence(lambda n: f"moit/service-repository-{n}")
    project = SubFactory(ProjectFactory, default_branch="main")
    granted_scopes = factory.LazyFunction(lambda: ["public_repo"])
    sync_state = SyncState.IDLE
    activated_by = SubFactory(UserFactory)


class ProviderEventFactory(DjangoModelFactory):
    """GIT-012: ledger row carrying minimal parsed payload and full provenance."""

    class Meta:
        model = ProviderEvent

    class Params:
        node_id = Sequence(lambda n: f"R_kgDOFakeNode{n:08d}")
        event_id = Sequence(lambda n: 900_000 + n)

    provider = Provider.GITHUB
    event_type = "pull_request"
    delivery_id = Sequence(lambda n: f"72d3162e-cc78-11e3-81ab-{n:012d}")
    provider_event_id = factory.LazyAttribute(lambda o: str(o.event_id))
    repository = SubFactory(
        RepositoryConnectionFactory,
        repository_node_id=factory.SelfAttribute("..node_id"),
    )
    source = DeliverySource.WEBHOOK
    signature_valid = True
    signature_note = "valid"
    payload = factory.LazyAttribute(
        lambda o: parsed_payload(node_id=o.node_id, event_id=o.event_id)
    )
    payload_digest = factory.LazyAttribute(
        lambda o: hashlib.sha256(str(o.delivery_id).encode("utf-8")).hexdigest()
    )
    processing_state = ProcessingState.PENDING
    correlation_id = Sequence(lambda n: f"corr-{n}")
