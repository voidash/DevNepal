import datetime
import hashlib
import importlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from typing import NamedTuple, Protocol

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.audit.services import record_audit
from apps.github_sync.app_client import GithubAppClient, installation_granted_scopes
from apps.github_sync.enums import DeliverySource, ProcessingState, Provider, SyncState
from apps.github_sync.errors import (
    ConnectionNotFoundError,
    GithubAppResponseError,
    ReconciliationError,
    WebhookReplayError,
    WebhookSignatureError,
)
from apps.github_sync.models import GithubConnection, ProviderEvent, RepositoryConnection
from apps.github_sync.webhooks import (
    ParsedEvent,
    is_within_replay_window,
    parse_event,
    verify_signature,
)

logger = logging.getLogger(__name__)

SIGNATURE_NOTE_VALID = "valid"
SIGNATURE_NOTE_INVALID = "invalid"
SIGNATURE_NOTE_MISSING = "missing"

IGNORED_UNSUPPORTED_NOTE = "ignored: unsupported event type, no verified activity"
BOT_FILTER_NOTE = "ignored: bot actor, no contribution credit"


@dataclass(frozen=True)
class ContributionCalendar:
    """GIT-009: accepted-contribution day counts for one calendar year [BR-005]."""

    year: int
    counts: dict[datetime.date, int]
    total: int
    longest_streak: int
    busiest_month: datetime.date


@dataclass(frozen=True)
class RepositoryChoice:
    """GIT-003: one enrollable repository of the member's linked GitHub App installation."""

    installation_id: int
    installation_account: str
    repository_id: int
    node_id: str
    full_name: str
    private: bool
    granted_scopes: list[str]
    enrolled: bool


@dataclass(frozen=True)
class EnrollOutcome:
    """GIT-001: result of an idempotent repository enrollment."""

    connection: RepositoryConnection
    created: bool


def member_repositories(
    client: GithubAppClient, connection: GithubConnection
) -> list[RepositoryChoice]:
    """GIT-003: repositories the member may enroll, from their linked installations.

    A repository is selectable when its owner or its installation account matches
    the member's connected GitHub login. Tokens are minted per installation and
    stay in memory for the duration of this call (AUTH-008).
    """
    candidates: list[tuple[dict, str, int, list[str]]] = []
    for installation in client.list_installations():
        installation_id = _installation_id(installation)
        account = str((installation.get("account") or {}).get("login") or "")
        scopes = installation_granted_scopes(installation)
        for repository in client.list_installation_repositories(installation_id):
            candidates.append((repository, account, installation_id, scopes))

    owned = [
        (repository, account, installation_id, scopes)
        for repository, account, installation_id, scopes in candidates
        if _repository_belongs_to_member(repository, account, connection.login)
    ]
    enrolled_ids = set(
        RepositoryConnection.objects.filter(
            provider=Provider.GITHUB,
            repository_id__in=[int(repository["id"]) for repository, _, _, _ in owned],
        ).values_list("repository_id", flat=True)
    )
    choices = [
        RepositoryChoice(
            installation_id=installation_id,
            installation_account=account,
            repository_id=int(repository["id"]),
            node_id=str(repository.get("node_id") or ""),
            full_name=str(repository.get("full_name") or ""),
            private=bool(repository.get("private")),
            granted_scopes=scopes,
            enrolled=int(repository["id"]) in enrolled_ids,
        )
        for repository, account, installation_id, scopes in owned
    ]
    return sorted(choices, key=lambda choice: choice.full_name)


def enroll_repository(
    user,
    *,
    installation_id: int,
    repository_id: int,
    node_id: str,
    full_name: str,
    granted_scopes: list[str],
) -> EnrollOutcome:
    """GIT-001/GIT-003: create the single connection for a repository (idempotent).

    The unique (provider, repository_id) constraint backs the "one active
    repository connection per repository" rule; concurrent duplicates resolve to
    the existing row. No token material is involved; the audit payload carries
    non-secret provenance only (AUTH-008).
    """
    existing = RepositoryConnection.objects.filter(
        provider=Provider.GITHUB, repository_id=repository_id
    ).first()
    if existing is not None:
        return EnrollOutcome(connection=existing, created=False)
    try:
        with transaction.atomic():
            connection = RepositoryConnection.objects.create(
                provider=Provider.GITHUB,
                installation_id=installation_id,
                repository_id=repository_id,
                repository_node_id=node_id,
                full_name=full_name,
                granted_scopes=granted_scopes,
                project=None,
                activated_by=user,
                sync_state=SyncState.IDLE,
            )
            record_audit(
                actor=user,
                action="github_repository.enroll",
                obj=connection,
                after={
                    "installation_id": installation_id,
                    "repository_id": repository_id,
                    "full_name": full_name,
                    "granted_scopes": granted_scopes,
                    "sync_state": SyncState.IDLE,
                },
                correlation_id=uuid.uuid4().hex,
            )
    except IntegrityError:
        connection = RepositoryConnection.objects.get(
            provider=Provider.GITHUB, repository_id=repository_id
        )
        return EnrollOutcome(connection=connection, created=False)
    return EnrollOutcome(connection=connection, created=True)


def _installation_id(installation: dict) -> int:
    try:
        return int(installation["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GithubAppResponseError("GitHub App installation response was malformed") from exc


def _repository_belongs_to_member(repository: dict, installation_account: str, login: str) -> bool:
    owner = str((repository.get("owner") or {}).get("login") or "")
    name = login.casefold()
    return owner.casefold() == name or installation_account.casefold() == name


def annual_contribution_calendar(connection: GithubConnection, year: int) -> ContributionCalendar:
    """GIT-009/BR-005: one connection-year of verified-record activity.

    Counts ACCEPTED, non-revoked contribution records attributable to the
    connection's linked member, bucketed by calendar day in the project
    timezone. Raw provider events are never counted. The whole year is built
    from a single aggregated values query.
    """
    from apps.contributions.enums import VerificationStatus
    from apps.contributions.models import ContributionRecord

    first_day = datetime.date(year, 1, 1)
    days_in_year = (datetime.date(year, 12, 31) - first_day).days + 1
    counts = {first_day + datetime.timedelta(days=offset): 0 for offset in range(days_in_year)}
    window_start = datetime.datetime(year, 1, 1, tzinfo=datetime.UTC) - datetime.timedelta(days=2)
    window_end = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(days=2)

    per_day = (
        ContributionRecord.objects.filter(
            contributor_id=connection.user_id,
            status=VerificationStatus.ACCEPTED,
            revoked_at__isnull=True,
            verified_at__isnull=False,
            verified_at__gte=window_start,
            verified_at__lt=window_end,
        )
        .annotate(day=TruncDate("verified_at"))
        .values("day")
        .annotate(accepted=Count("id"))
    )
    for row in per_day:
        if row["day"] in counts:
            counts[row["day"]] = row["accepted"]

    longest_streak = streak = 0
    for day in sorted(counts):
        if counts[day] > 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0

    busiest = min(
        (month for month in range(1, 13) if _month_count(counts, year, month) > 0),
        key=lambda month: (-_month_count(counts, year, month), month),
        default=1,
    )
    return ContributionCalendar(
        year=year,
        counts=counts,
        total=sum(counts.values()),
        longest_streak=longest_streak,
        busiest_month=datetime.date(year, busiest, 1),
    )


def _month_count(counts: dict[datetime.date, int], year: int, month: int) -> int:
    return sum(count for day, count in counts.items() if day.year == year and day.month == month)


class ProcessPendingResult(NamedTuple):
    processed: int
    failed: int
    blocked: int
    blocked_event_ids: list[str]


@dataclass(frozen=True)
class ReconciliationEvent:
    event_type: str
    delivery_id: str
    parsed_event: ParsedEvent


@dataclass(frozen=True)
class ReconciliationPage:
    events: tuple[ReconciliationEvent, ...]
    next_cursor: str


class ReconciliationFetcher(Protocol):
    def fetch(
        self,
        repository_connection: RepositoryConnection,
        cursor: str,
        since: object,
    ) -> ReconciliationPage: ...


def ingest_webhook(
    provider: str,
    event: str,
    delivery_id: str,
    signature_header: str | None,
    timestamp_header: str | None,
    body: bytes,
) -> ProviderEvent:
    """GIT-004/GIT-005/GIT-012: verify, dedup and ledger one webhook delivery.

    Signature failures and replays record a REJECTED row (committed) and then
    raise; unsupported events resolve PROCESSED; verified events land PENDING
    for the worker. Duplicate deliveries collapse onto the existing row
    (delivery key) or are recorded as DUPLICATE evidence (event key, D6).
    """
    secret = getattr(settings, "GITHUB_WEBHOOK_SECRET", "")
    now = timezone.now()
    correlation_id = uuid.uuid4().hex
    with transaction.atomic():
        row, failure = _ingest(
            provider,
            event,
            delivery_id,
            signature_header,
            timestamp_header,
            body,
            secret=secret,
            now=now,
            correlation_id=correlation_id,
        )
    if failure is not None:
        raise failure
    return row


def _ingest(
    provider,
    event,
    delivery_id,
    signature_header,
    timestamp_header,
    body,
    *,
    secret,
    now,
    correlation_id,
):
    existing = ProviderEvent.objects.filter(provider=provider, delivery_id=delivery_id).first()
    if existing is not None:
        return existing, None

    signature_valid = verify_signature(secret, body, signature_header)
    digest = hashlib.sha256(body).hexdigest()

    if not signature_valid:
        note = SIGNATURE_NOTE_MISSING if not signature_header else SIGNATURE_NOTE_INVALID
        row = ProviderEvent.objects.create(
            provider=provider,
            event_type=event,
            delivery_id=delivery_id,
            provider_event_id=delivery_id,
            source=DeliverySource.WEBHOOK,
            signature_valid=False,
            signature_note=note,
            payload_digest=digest,
            processing_state=ProcessingState.REJECTED,
            last_error="rejected: signature validation failed",
            processed_at=now,
            correlation_id=correlation_id,
        )
        logger.warning(
            "webhook signature rejected (provider=%s event=%s delivery=%s note=%s)",
            provider,
            event,
            delivery_id,
            note,
        )
        return row, WebhookSignatureError(f"signature {note} for delivery {delivery_id}")

    if not is_within_replay_window(timestamp_header, now):
        row = ProviderEvent.objects.create(
            provider=provider,
            event_type=event,
            delivery_id=delivery_id,
            provider_event_id=delivery_id,
            source=DeliverySource.WEBHOOK,
            signature_valid=True,
            signature_note=SIGNATURE_NOTE_VALID,
            payload_digest=digest,
            processing_state=ProcessingState.REJECTED,
            last_error="rejected: delivery timestamp outside replay window",
            processed_at=now,
            correlation_id=correlation_id,
        )
        logger.warning(
            "webhook replay window rejection (provider=%s event=%s delivery=%s)",
            provider,
            event,
            delivery_id,
        )
        return row, WebhookReplayError(f"delivery {delivery_id} outside replay window")

    payload_dict = _decode_json(body)
    parsed = parse_event(event, payload_dict) if payload_dict is not None else None

    if parsed is None:
        row = ProviderEvent.objects.create(
            provider=provider,
            event_type=event,
            delivery_id=delivery_id,
            provider_event_id=delivery_id,
            source=DeliverySource.WEBHOOK,
            signature_valid=True,
            signature_note=SIGNATURE_NOTE_VALID,
            payload=None,
            payload_digest=digest,
            processing_state=ProcessingState.PROCESSED,
            last_error=IGNORED_UNSUPPORTED_NOTE,
            processed_at=now,
            correlation_id=correlation_id,
        )
        return row, None

    twin = ProviderEvent.objects.filter(
        provider=provider, provider_event_id=parsed.event_id
    ).first()
    if twin is not None:
        duplicate = ProviderEvent.objects.create(
            provider=provider,
            event_type=event,
            delivery_id=delivery_id,
            provider_event_id=delivery_id,
            repository=twin.repository,
            actor=twin.actor,
            source=DeliverySource.WEBHOOK,
            signature_valid=True,
            signature_note=SIGNATURE_NOTE_VALID,
            payload=asdict(parsed),
            payload_digest=digest,
            processing_state=ProcessingState.DUPLICATE,
            last_error=f"duplicate of provider event {parsed.event_id}",
            processed_at=now,
            correlation_id=correlation_id,
        )
        return duplicate, None

    repository = RepositoryConnection.objects.filter(
        provider=provider, repository_node_id=parsed.repository_node_id
    ).first()
    actor = _resolve_actor(provider, parsed.actor_login)
    row = ProviderEvent.objects.create(
        provider=provider,
        event_type=event,
        delivery_id=delivery_id,
        provider_event_id=parsed.event_id,
        repository=repository,
        actor=actor,
        source=DeliverySource.WEBHOOK,
        signature_valid=True,
        signature_note=SIGNATURE_NOTE_VALID,
        payload=asdict(parsed),
        payload_digest=digest,
        processing_state=ProcessingState.PENDING,
        correlation_id=correlation_id,
    )
    return row, None


def process_pending(limit: int = 50) -> ProcessPendingResult:
    """GIT-005/A5/A9: drain PENDING ledger rows into candidate contributions.

    Unmapped repositories fail loudly; bot actors are filtered before any
    contribution record (GIT-008); a missing contributions service (parallel
    build) leaves rows PENDING and is reported instead of dropping work.
    """
    events = (
        ProviderEvent.objects.select_related("repository", "repository__project")
        .filter(processing_state=ProcessingState.PENDING)
        .order_by("received_at", "id")[:limit]
    )
    processed = failed = blocked = 0
    blocked_event_ids: list[str] = []
    for event in events:
        parsed = ParsedEvent(**event.payload) if event.payload else None
        if parsed is None:
            event.processing_state = ProcessingState.FAILED
            event.last_error = "failed: stored payload missing parsed fields"
            event.processing_attempts += 1
            event.save(update_fields=["processing_state", "last_error", "processing_attempts"])
            failed += 1
            continue

        if parsed.is_bot:
            event.processing_state = ProcessingState.PROCESSED
            event.last_error = BOT_FILTER_NOTE
            event.processing_attempts += 1
            event.processed_at = timezone.now()
            event.save(
                update_fields=[
                    "processing_state",
                    "last_error",
                    "processing_attempts",
                    "processed_at",
                ]
            )
            processed += 1
            continue

        connection = (
            RepositoryConnection.objects.select_related("project")
            .filter(provider=event.provider, repository_node_id=parsed.repository_node_id)
            .first()
        )
        if connection is None:
            event.repository = None
            event.processing_state = ProcessingState.FAILED
            event.last_error = "failed: repository not mapped to a connected project"
            event.processing_attempts += 1
            event.save(
                update_fields=[
                    "repository",
                    "processing_state",
                    "last_error",
                    "processing_attempts",
                ]
            )
            failed += 1
            continue
        if connection.project is None:
            event.repository = connection
            event.processing_state = ProcessingState.FAILED
            event.last_error = "failed: repository connection has no listed project"
            event.processing_attempts += 1
            event.save(
                update_fields=[
                    "repository",
                    "processing_state",
                    "last_error",
                    "processing_attempts",
                ]
            )
            failed += 1
            continue

        try:
            from apps.contributions.services import record_candidate_from_github
        except ImportError:
            logger.warning(
                "contributions service unavailable; event stays PENDING (event=%s)", event.pk
            )
            blocked += 1
            blocked_event_ids.append(str(event.pk))
            continue

        event.repository = connection
        event.processing_attempts += 1
        try:
            record_candidate_from_github(parsed, connection.project)
        except Exception:
            logger.exception("candidate recording failed (event=%s)", event.pk)
            event.processing_state = ProcessingState.FAILED
            event.last_error = "failed: record_candidate_from_github raised"
            event.save(
                update_fields=[
                    "repository",
                    "processing_state",
                    "last_error",
                    "processing_attempts",
                ]
            )
            failed += 1
            continue
        event.processing_state = ProcessingState.PROCESSED
        event.processed_at = timezone.now()
        event.save(
            update_fields=[
                "repository",
                "processing_state",
                "processing_attempts",
                "processed_at",
            ]
        )
        processed += 1
    return ProcessPendingResult(
        processed=processed, failed=failed, blocked=blocked, blocked_event_ids=blocked_event_ids
    )


def disconnect(user) -> GithubConnection:
    """GIT-011/AUTH-008: revoke the user's connection and stop all synchronization.

    Tokens live only in the configured secret store (GITHUB_TOKEN_PURGE hook);
    they are purged here and never appear in logs or the audit payload.
    """
    connection = GithubConnection.objects.filter(user=user).first()
    if connection is None:
        raise ConnectionNotFoundError(f"no provider connection for {user!r}")
    if connection.revoked_at is not None:
        return connection

    now = timezone.now()
    repositories = RepositoryConnection.objects.filter(activated_by=user)
    with transaction.atomic():
        before = {
            "login": connection.login,
            "revoked_at": None,
            "repositories": list(repositories.values_list("pk", "sync_state")),
        }
        repositories.filter(deactivated_at__isnull=True).update(
            sync_state=SyncState.STOPPED, deactivated_at=now
        )
        connection.revoked_at = now
        connection.save(update_fields=["revoked_at"])
        tokens_deleted = delete_stored_tokens(user)
        record_audit(
            actor=user,
            action="github_connection.disconnect",
            obj=connection,
            before=before,
            after={
                "login": connection.login,
                "revoked_at": now.isoformat(),
                "sync_state": SyncState.STOPPED,
                "tokens_deleted": tokens_deleted,
            },
            source="system",
            correlation_id=uuid.uuid4().hex,
        )
    return connection


def delete_stored_tokens(user) -> int:
    """GIT-011/AUTH-008: erase provider tokens from the configured secret store.

    The hook is a callable or dotted path in settings (GITHUB_TOKEN_PURGE).
    Models never store token material, so there is nothing to clear in the DB.
    """
    purge = getattr(settings, "GITHUB_TOKEN_PURGE", None)
    if purge is None:
        logger.warning("GITHUB_TOKEN_PURGE not configured; no secret store to clear (GIT-011)")
        return 0
    if isinstance(purge, str):
        module_name, _, attribute = purge.rpartition(".")
        purge = getattr(importlib.import_module(module_name), attribute)
    return int(purge(user))


def reconcile(
    repository_connection: RepositoryConnection,
    since: object,
    fetcher: ReconciliationFetcher,
) -> int:
    """GIT-006: durably reconcile one selected repository through an injected provider client."""
    try:
        with transaction.atomic():
            connection = RepositoryConnection.objects.select_for_update().get(
                pk=repository_connection.pk
            )
            if connection.sync_state == SyncState.STOPPED:
                return 0

            connection.sync_state = SyncState.SYNCING
            connection.save(update_fields=["sync_state", "updated_at"])
            page = fetcher.fetch(connection, connection.sync_cursor, since)
            recovered = _persist_reconciliation_page(connection, page)
            connection.sync_cursor = page.next_cursor
            connection.sync_state = SyncState.IDLE
            connection.health_note = ""
            connection.last_synced_at = timezone.now()
            connection.save(
                update_fields=[
                    "sync_cursor",
                    "sync_state",
                    "health_note",
                    "last_synced_at",
                    "updated_at",
                ]
            )
            return recovered
    except Exception as exc:
        logger.exception("reconciliation fetch failed (repository=%s)", repository_connection.pk)
        _mark_reconciliation_failed(repository_connection.pk)
        raise ReconciliationError(
            f"reconciliation failed for repository connection {repository_connection.pk}"
        ) from exc


def _persist_reconciliation_page(connection: RepositoryConnection, page: ReconciliationPage) -> int:
    recovered = 0
    for event in page.events:
        if event.parsed_event.repository_node_id != connection.repository_node_id:
            raise ReconciliationError("fetched event belongs to a different repository")
        if ProviderEvent.objects.filter(
            provider=connection.provider, provider_event_id=event.parsed_event.event_id
        ).exists():
            continue
        try:
            with transaction.atomic():
                ProviderEvent.objects.create(
                    provider=connection.provider,
                    event_type=event.event_type,
                    delivery_id=event.delivery_id,
                    provider_event_id=event.parsed_event.event_id,
                    repository=connection,
                    actor=_resolve_actor(connection.provider, event.parsed_event.actor_login),
                    source=DeliverySource.RECONCILIATION,
                    signature_valid=True,
                    signature_note="provider-api",
                    payload=asdict(event.parsed_event),
                    processing_state=ProcessingState.PENDING,
                    correlation_id=uuid.uuid4().hex,
                )
        except IntegrityError:
            if ProviderEvent.objects.filter(
                provider=connection.provider, provider_event_id=event.parsed_event.event_id
            ).exists():
                continue
            raise
        recovered += 1
    return recovered


def _mark_reconciliation_failed(repository_connection_id) -> None:
    with transaction.atomic():
        connection = RepositoryConnection.objects.select_for_update().get(
            pk=repository_connection_id
        )
        if connection.sync_state == SyncState.STOPPED:
            return
        connection.sync_state = SyncState.DEGRADED
        connection.health_note = "reconciliation failed"
        connection.save(update_fields=["sync_state", "health_note", "updated_at"])


def _decode_json(body: bytes) -> dict | None:
    try:
        decoded = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _resolve_actor(provider: str, actor_login: str):
    if not actor_login:
        return None
    connection = (
        GithubConnection.objects.select_related("user")
        .filter(provider=provider, login=actor_login, revoked_at__isnull=True)
        .first()
    )
    return connection.user if connection else None
