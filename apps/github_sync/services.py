import datetime
import hashlib
import importlib
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import NamedTuple, Protocol

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

from apps.audit.services import record_audit
from apps.github_sync.app_client import (
    GithubAppClient,
    github_app_client,
    installation_granted_scopes,
)
from apps.github_sync.enums import DeliverySource, ProcessingState, Provider, SyncState
from apps.github_sync.errors import (
    ConnectionNotFoundError,
    GithubAppError,
    GithubAppResponseError,
    ReconciliationError,
    RepositoryBindingError,
    WebhookReplayError,
    WebhookSignatureError,
)
from apps.github_sync.models import (
    GithubConnection,
    GithubIssueSnapshot,
    GithubPublicProfileSnapshot,
    GithubPullRequestSnapshot,
    GithubRepositoryContributor,
    GithubStarterTask,
    ProviderEvent,
    RepositoryConnection,
)
from apps.github_sync.webhooks import (
    ISSUE_LIFECYCLE_ACTIONS,
    ParsedEvent,
    ParsedIssueLifecycleEvent,
    is_within_replay_window,
    parse_event,
    parse_issue_lifecycle_event,
    verify_signature,
)

logger = logging.getLogger(__name__)

SIGNATURE_NOTE_VALID = "valid"
SIGNATURE_NOTE_INVALID = "invalid"
SIGNATURE_NOTE_MISSING = "missing"

IGNORED_UNSUPPORTED_NOTE = "ignored: unsupported event type, no verified activity"
BOT_FILTER_NOTE = "ignored: bot actor, no contribution credit"
STARTER_TASK_LABELS = frozenset({"good first issue", "help wanted"})
PUBLIC_SNAPSHOT_BODY_LIMIT = 10_000
PUBLIC_PROFILE_CONSENT = "public_profile"
DEFAULT_VERIFIED_EVENT_TYPES = frozenset(
    {"pull_request", "issues", "pull_request_review", "release"}
)
API_EVENT_TYPES = {
    "PullRequestEvent": "pull_request",
    "IssuesEvent": "issues",
    "PullRequestReviewEvent": "pull_request_review",
    "ReleaseEvent": "release",
}
INSTALLATION_DELETED = "installation_deleted"
INSTALLATION_SUSPENDED = "installation_suspended"
INSTALLATION_UNSUSPENDED_UNBOUND = "installation_unsuspended_unbound"
REPOSITORY_REMOVED = "repository_removed"


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
    connection_id: int | None
    project_id: int | None


@dataclass(frozen=True)
class EnrollOutcome:
    """GIT-001: result of an idempotent repository enrollment."""

    connection: RepositoryConnection
    created: bool


@dataclass(frozen=True)
class BindOutcome:
    """GIT-003: result of associating one enrolled repository with a project."""

    connection: RepositoryConnection
    bound: bool


@dataclass(frozen=True)
class StarterTaskSyncOutcome:
    """DSC-009: result of refreshing one repository's public task snapshot."""

    stored: int
    ignored: int
    synced_at: datetime.datetime


def member_repositories(
    client: GithubAppClient,
    connection: GithubConnection,
    *,
    actor=None,
    project=None,
) -> list[RepositoryChoice]:
    """GIT-003: repositories the member may enroll, from their linked installations.

    A repository is selectable when its owner or its installation account matches
    the member's connected GitHub login. Tokens are minted per installation and
    stay in memory for the duration of this call (AUTH-008).
    """
    target_repository = None
    if project is not None:
        authorize_repository_binding(actor, project)
        target_repository = _project_repository_name(project)

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
        if (
            _repository_matches_project(repository, target_repository)
            if target_repository is not None
            else _repository_belongs_to_member(repository, account, connection.login)
        )
    ]
    enrolled = {
        row.repository_id: row
        for row in RepositoryConnection.objects.filter(
            provider=Provider.GITHUB,
            repository_id__in=[int(repository["id"]) for repository, _, _, _ in owned],
        ).only("id", "repository_id", "project_id")
    }
    choices = [
        RepositoryChoice(
            installation_id=installation_id,
            installation_account=account,
            repository_id=int(repository["id"]),
            node_id=str(repository.get("node_id") or ""),
            full_name=str(repository.get("full_name") or ""),
            private=bool(repository.get("private")),
            granted_scopes=scopes,
            enrolled=int(repository["id"]) in enrolled,
            connection_id=(
                enrolled[int(repository["id"])].pk if int(repository["id"]) in enrolled else None
            ),
            project_id=(
                enrolled[int(repository["id"])].project_id
                if int(repository["id"]) in enrolled
                else None
            ),
        )
        for repository, account, installation_id, scopes in owned
    ]
    return sorted(choices, key=lambda choice: choice.full_name)


def binding_projects(actor):
    """AUTH-006/GIT-003: projects the actor may safely associate with a repository."""
    from django.db.models import Q

    from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
    from apps.projects.enums import ProjectType
    from apps.projects.models import Project

    if actor is None or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        return Project.objects.none()
    personal = Q(project_type=ProjectType.PERSONAL, owner=actor)
    if actor.is_superuser:
        permitted = personal | Q(project_type=ProjectType.GOVERNMENT)
    else:
        permitted = personal | Q(
            project_type=ProjectType.GOVERNMENT,
            ministry__status=OrgStatus.ACTIVE,
            ministry__publishers__user=actor,
            ministry__publishers__status=PublisherStatus.ACTIVE,
            ministry__publishers__contact_verification_status=ContactVerificationStatus.VERIFIED,
        )
    return (
        Project.objects.filter(permitted).select_related("ministry").distinct().order_by("title_en")
    )


def authorize_repository_binding(actor, project) -> None:
    """AUTH-006/GIT-003: enforce project ownership and privileged MFA boundaries."""
    from apps.accounts.services import require_privileged_mfa
    from apps.ministries.services import is_publisher_active
    from apps.projects.enums import ProjectType

    if actor is None or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise RepositoryBindingError("an active authenticated account is required")
    if project.project_type == ProjectType.PERSONAL:
        if project.owner_id != actor.pk:
            raise RepositoryBindingError("only the community project owner may bind its repository")
        return
    if project.project_type != ProjectType.GOVERNMENT or project.ministry_id is None:
        raise RepositoryBindingError("repository binding requires a supported project type")
    if actor.is_superuser or is_publisher_active(actor, project.ministry):
        require_privileged_mfa(
            actor,
            action="github_repository.bind_project",
            obj=project,
            error_type=RepositoryBindingError,
        )
        return
    raise RepositoryBindingError("the actor is not authorized for the project's ministry")


def bind_repository(actor, repository: RepositoryConnection, project) -> BindOutcome:
    """GIT-001/GIT-003/AUTH-006: bind an enrolled App repository to an authorized project."""
    from apps.projects.enums import ProjectType

    authorize_repository_binding(actor, project)
    expected = _project_repository_name(project)
    if expected is None or repository.full_name.casefold() != expected.casefold():
        raise RepositoryBindingError("the repository does not match the project's GitHub URL")

    with transaction.atomic():
        locked = RepositoryConnection.objects.select_for_update().get(pk=repository.pk)
        if locked.deactivated_at is not None or locked.sync_state == SyncState.STOPPED:
            raise RepositoryBindingError("a disconnected repository cannot be bound")
        if project.project_type == ProjectType.PERSONAL and locked.activated_by_id != actor.pk:
            raise RepositoryBindingError(
                "community owners may bind only repositories they enrolled"
            )
        if locked.project_id == project.pk:
            return BindOutcome(connection=locked, bound=False)
        if locked.project_id is not None:
            raise RepositoryBindingError("the repository is already bound to another project")
        locked.project = project
        locked.save(update_fields=["project", "updated_at"])
        record_audit(
            actor=actor,
            action="github_repository.bind_project",
            obj=locked,
            before={"project_id": None},
            after={
                "project_id": project.pk,
                "repository_id": locked.repository_id,
                "full_name": locked.full_name,
            },
            correlation_id=uuid.uuid4().hex,
        )
    return BindOutcome(connection=locked, bound=True)


def _project_repository_name(project) -> str | None:
    from apps.projects.services import parse_github_repo_slug

    return parse_github_repo_slug(project.repository_url)


def _repository_matches_project(repository: dict, expected: str | None) -> bool:
    full_name = str(repository.get("full_name") or "")
    return bool(expected and full_name.casefold() == expected.casefold())


def enroll_repository(
    user,
    *,
    installation_id: int,
    repository_id: int,
    node_id: str,
    full_name: str,
    granted_scopes: list[str],
    is_public: bool = False,
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
        if existing.sync_state == SyncState.STOPPED or existing.deactivated_at is not None:
            with transaction.atomic():
                existing = RepositoryConnection.objects.select_for_update().get(pk=existing.pk)
                before = _repository_access_snapshot(existing)
                existing.installation_id = installation_id
                existing.repository_node_id = node_id
                existing.full_name = full_name
                existing.is_public = is_public
                existing.granted_scopes = granted_scopes
                existing.activated_by = user
                existing.sync_state = SyncState.IDLE
                existing.deactivated_at = None
                existing.access_revoked_reason = ""
                existing.health_note = ""
                existing.sync_failure_count = 0
                existing.next_sync_attempt_at = None
                existing.save(
                    update_fields=[
                        "installation_id",
                        "repository_node_id",
                        "full_name",
                        "is_public",
                        "granted_scopes",
                        "activated_by",
                        "sync_state",
                        "deactivated_at",
                        "access_revoked_reason",
                        "health_note",
                        "sync_failure_count",
                        "next_sync_attempt_at",
                        "updated_at",
                    ]
                )
                record_audit(
                    actor=user,
                    action="github_repository.reenroll",
                    obj=existing,
                    before=before,
                    after=_repository_access_snapshot(existing),
                    correlation_id=uuid.uuid4().hex,
                )
        return EnrollOutcome(connection=existing, created=False)
    try:
        with transaction.atomic():
            connection = RepositoryConnection.objects.create(
                provider=Provider.GITHUB,
                installation_id=installation_id,
                repository_id=repository_id,
                repository_node_id=node_id,
                full_name=full_name,
                is_public=is_public,
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


def refresh_starter_tasks(
    connection: RepositoryConnection, client: GithubAppClient
) -> StarterTaskSyncOutcome:
    """DSC-009/GIT-003: persist a bounded public snapshot of labelled open issues.

    This explicit sync boundary is deliberately separate from public rendering.
    Only listed, public repositories are eligible. A provider failure is
    recorded for an honest public freshness state, then propagated so a
    scheduler can retry; it never affects webhook/replay state (GIT-005).
    """
    if connection.project_id is None or not connection.is_public:
        return StarterTaskSyncOutcome(stored=0, ignored=0, synced_at=timezone.now())
    try:
        raw_issues = client.list_open_issues(connection.installation_id, connection.full_name)
    except GithubAppError as exc:
        note = _("GitHub starter-task snapshot could not be refreshed.")
        RepositoryConnection.objects.filter(pk=connection.pk).update(task_snapshot_note=note)
        logger.warning(
            "starter-task snapshot failed for repository=%s pk=%s: %s",
            connection.full_name,
            connection.pk,
            exc.__class__.__name__,
        )
        raise

    records: list[dict] = []
    ignored = 0
    for issue in raw_issues:
        record = _starter_task_record(connection, issue)
        if record is None:
            ignored += 1
        else:
            records.append(record)

    now = timezone.now()
    with transaction.atomic():
        accepted_ids = []
        for record in records:
            task, _created = GithubStarterTask.objects.update_or_create(
                repository=connection,
                github_issue_id=record["github_issue_id"],
                defaults=record,
            )
            accepted_ids.append(task.github_issue_id)
        stale = GithubStarterTask.objects.filter(repository=connection)
        if accepted_ids:
            stale.exclude(github_issue_id__in=accepted_ids).delete()
        else:
            stale.delete()
        RepositoryConnection.objects.filter(pk=connection.pk).update(
            task_snapshot_at=now,
            task_snapshot_note="",
        )
    return StarterTaskSyncOutcome(stored=len(records), ignored=ignored, synced_at=now)


def starter_tasks_for_project(
    project,
) -> tuple[list[GithubStarterTask], list[RepositoryConnection]]:
    """DSC-009/GIT-010: DB-only public task hand-off and its honest sync provenance."""
    repositories = list(
        RepositoryConnection.objects.filter(project=project, is_public=True)
        .exclude(sync_state=SyncState.STOPPED)
        .only(
            "id",
            "full_name",
            "task_snapshot_at",
            "task_snapshot_note",
            "sync_state",
            "last_synced_at",
        )
        .order_by("full_name")
    )
    if not repositories:
        return [], []
    tasks = list(
        GithubStarterTask.objects.filter(repository_id__in=[item.pk for item in repositories])
        .select_related("repository")
        .order_by("repository__full_name", "number")
    )
    return tasks, repositories


def _starter_task_record(connection: RepositoryConnection, issue: object) -> dict | None:
    """GIT-010: allow only public, externally linkable labelled issue metadata."""
    if not isinstance(issue, dict) or "pull_request" in issue:
        return None
    try:
        issue_id = int(issue["id"])
        number = int(issue["number"])
    except (KeyError, TypeError, ValueError):
        return None
    title = str(issue.get("title") or "").strip()
    url = str(issue.get("html_url") or "").strip()
    expected_prefix = f"https://github.com/{connection.full_name}/issues/{number}"
    if issue_id < 1 or number < 1 or not title or len(title) > 300 or url != expected_prefix:
        return None
    labels = _starter_labels(issue.get("labels"))
    if not labels:
        return None
    source_updated_at = parse_datetime(str(issue.get("updated_at") or ""))
    if source_updated_at is not None and timezone.is_naive(source_updated_at):
        source_updated_at = timezone.make_aware(source_updated_at, datetime.UTC)
    return {
        "github_issue_id": issue_id,
        "number": number,
        "title": title,
        "url": url,
        "labels": labels,
        "source_updated_at": source_updated_at,
    }


def _starter_labels(raw_labels: object) -> list[str]:
    if not isinstance(raw_labels, list):
        return []
    labels = []
    for label in raw_labels:
        name = str(label.get("name") if isinstance(label, dict) else label).strip()
        if name.casefold() in STARTER_TASK_LABELS and name.casefold() not in {
            item.casefold() for item in labels
        }:
            labels.append(name)
    return labels


@dataclass(frozen=True)
class PublicRepositorySnapshotOutcome:
    issues: int
    pull_requests: int
    contributors: int
    synced_at: datetime.datetime


def refresh_public_repository_snapshot(
    connection: RepositoryConnection, client: GithubAppClient
) -> PublicRepositorySnapshotOutcome:
    """GIT-003/GIT-010: atomically refresh bounded public GitHub repository projections."""
    now = timezone.now()
    if not connection.is_public or connection.sync_state == SyncState.STOPPED:
        return PublicRepositorySnapshotOutcome(0, 0, 0, now)
    try:
        metadata = client.repository_metadata(connection.installation_id, connection.full_name)
        if (
            metadata.get("private") is not False
            or metadata.get("full_name") != connection.full_name
        ):
            raise GithubAppResponseError("GitHub repository is not the enrolled public repository")
        issues = client.list_open_issues(connection.installation_id, connection.full_name)
        pull_requests = client.list_open_pull_requests(
            connection.installation_id, connection.full_name
        )
        contributors = client.list_contributors(connection.installation_id, connection.full_name)
    except GithubAppError:
        RepositoryConnection.objects.filter(pk=connection.pk).update(
            public_snapshot_note=_("GitHub public repository snapshot could not be refreshed.")
        )
        logger.warning(
            "public repository snapshot failed for repository=%s pk=%s",
            connection.full_name,
            connection.pk,
        )
        raise
    issue_records = [
        record for item in issues if (record := _issue_snapshot_record(connection, item))
    ]
    pull_records = [
        record
        for item in pull_requests
        if (record := _pull_request_snapshot_record(connection, item))
    ]
    contributor_records = [
        record for item in contributors if (record := _contributor_snapshot_record(item))
    ]
    public_profiles = _public_profile_snapshots(client, contributor_records)
    with transaction.atomic():
        _replace_snapshot_rows(GithubIssueSnapshot, connection, "github_issue_id", issue_records)
        _replace_snapshot_rows(
            GithubPullRequestSnapshot, connection, "github_pull_request_id", pull_records
        )
        _replace_snapshot_rows(
            GithubRepositoryContributor, connection, "github_user_id", contributor_records
        )
        for profile in public_profiles:
            GithubPublicProfileSnapshot.objects.update_or_create(
                github_user_id=profile["github_user_id"], defaults=profile
            )
        RepositoryConnection.objects.filter(pk=connection.pk).update(
            public_snapshot_at=now, public_snapshot_note=""
        )
    return PublicRepositorySnapshotOutcome(
        len(issue_records), len(pull_records), len(contributor_records), now
    )


def _replace_snapshot_rows(model, connection, identifier: str, records: list[dict]) -> None:
    identifiers = []
    for record in records:
        value = record[identifier]
        model.objects.update_or_create(
            repository=connection, **{identifier: value}, defaults=record
        )
        identifiers.append(value)
    stale = model.objects.filter(repository=connection)
    if identifiers:
        stale.exclude(**{f"{identifier}__in": identifiers}).delete()
    else:
        stale.delete()


def _issue_snapshot_record(connection: RepositoryConnection, issue: object) -> dict | None:
    if not isinstance(issue, dict) or "pull_request" in issue:
        return None
    return _work_snapshot_record(connection, issue, "issues", "github_issue_id")


def _pull_request_snapshot_record(
    connection: RepositoryConnection, pull_request: object
) -> dict | None:
    if not isinstance(pull_request, dict):
        return None
    return _work_snapshot_record(connection, pull_request, "pull", "github_pull_request_id")


def _work_snapshot_record(connection, item, kind: str, identifier: str) -> dict | None:
    try:
        remote_id = int(item["id"])
        number = int(item["number"])
        comments = int(item.get("comments", 0))
    except (KeyError, TypeError, ValueError):
        return None
    title = str(item.get("title") or "").strip()
    state = str(item.get("state") or "").strip()
    url = str(item.get("html_url") or "").strip()
    expected_url = f"https://github.com/{connection.full_name}/{kind}/{number}"
    if (
        remote_id < 1
        or number < 1
        or comments < 0
        or not title
        or len(title) > 300
        or state not in {"open", "closed"}
        or url != expected_url
    ):
        return None
    author = item.get("user") if isinstance(item.get("user"), dict) else {}
    body = str(item.get("body") or "").strip()[:PUBLIC_SNAPSHOT_BODY_LIMIT]
    updated_at = parse_datetime(str(item.get("updated_at") or ""))
    if updated_at is not None and timezone.is_naive(updated_at):
        updated_at = timezone.make_aware(updated_at, datetime.UTC)
    record = {
        identifier: remote_id,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "comments_count": comments,
        "url": url,
        "author_login": str(author.get("login") or "").strip()[:100],
        "author_avatar_url": str(author.get("avatar_url") or "").strip(),
        "source_updated_at": updated_at,
    }
    if kind == "issues":
        record["labels"] = [
            str(label.get("name") or "").strip()[:100]
            for label in item.get("labels", [])
            if isinstance(label, dict) and str(label.get("name") or "").strip()
        ][:20]
    return record


def _contributor_snapshot_record(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        remote_id = int(item["id"])
        contributions = int(item["contributions"])
    except (KeyError, TypeError, ValueError):
        return None
    login = str(item.get("login") or "").strip()
    if remote_id < 1 or contributions < 0 or not login or len(login) > 100:
        return None
    return {
        "github_user_id": remote_id,
        "login": login,
        "avatar_url": str(item.get("avatar_url") or "").strip(),
        "profile_url": str(item.get("html_url") or "").strip(),
        "contributions": contributions,
    }


def _public_profile_snapshots(client: GithubAppClient, contributors: list[dict]) -> list[dict]:
    profiles = []
    for contributor in contributors[:20]:
        try:
            payload = client.get_public_user(contributor["login"])
        except GithubAppError:
            logger.warning(
                "public GitHub contributor profile fetch failed for login=%s",
                contributor["login"],
            )
            continue
        record = _public_profile_snapshot_record(contributor, payload)
        if record is None:
            logger.warning(
                "public GitHub contributor profile was malformed for login=%s",
                contributor["login"],
            )
            continue
        profiles.append(record)
    return profiles


def _public_profile_snapshot_record(contributor: dict, payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    login = str(payload.get("login") or "").strip()
    html_url = str(payload.get("html_url") or "").strip()
    try:
        github_user_id = int(payload["id"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        github_user_id != contributor["github_user_id"]
        or login.casefold() != contributor["login"].casefold()
        or html_url.casefold() != f"https://github.com/{login}".casefold()
    ):
        return None
    return {
        "github_user_id": github_user_id,
        "login": login[:100],
        "avatar_url": str(payload.get("avatar_url") or "").strip(),
        "html_url": html_url,
        "display_name": str(payload.get("name") or "").strip()[:255],
        "bio": str(payload.get("bio") or "").strip()[:PUBLIC_SNAPSHOT_BODY_LIMIT],
        "location": str(payload.get("location") or "").strip()[:255],
        "company": str(payload.get("company") or "").strip()[:255],
        "public_repos": _nonnegative_int(payload.get("public_repos")),
        "followers": _nonnegative_int(payload.get("followers")),
    }


def refresh_github_public_profile(connection: GithubConnection, client: GithubAppClient) -> bool:
    """GIT-002/GIT-010: refresh only a member's explicitly consented public GitHub profile."""
    if not connection.is_active or PUBLIC_PROFILE_CONSENT not in connection.consent_scopes:
        return False
    try:
        payload = client.get_public_user(connection.login)
    except GithubAppError:
        logger.warning("public GitHub profile snapshot failed for user=%s", connection.user_id)
        raise
    values = {
        "avatar_url": str(payload.get("avatar_url") or "").strip(),
        "html_url": str(payload.get("html_url") or "").strip(),
        "display_name": str(payload.get("name") or "").strip()[:255],
        "bio": str(payload.get("bio") or "").strip()[:PUBLIC_SNAPSHOT_BODY_LIMIT],
        "location": str(payload.get("location") or "").strip()[:255],
        "company": str(payload.get("company") or "").strip()[:255],
        "public_repos": _nonnegative_int(payload.get("public_repos")),
        "followers": _nonnegative_int(payload.get("followers")),
        "public_profile_fetched_at": timezone.now(),
    }
    GithubConnection.objects.filter(pk=connection.pk).update(**values)
    return True


def _nonnegative_int(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


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


class GithubReconciliationFetcher:
    """GIT-006/GIT-007: production GitHub Events API reconciliation adapter."""

    def __init__(self, client: GithubAppClient | None = None):
        self.client = client or github_app_client()

    def fetch(self, repository_connection, cursor, since):
        project = repository_connection.project
        if project is None:
            raise ReconciliationError("repository connection has no configured project")
        default_branch = str(project.default_branch or "").strip()
        if not default_branch:
            raise ReconciliationError("project default branch is not configured")
        page_number = _reconciliation_page_number(cursor)
        raw_events = self.client.list_repository_events_page(
            repository_connection.installation_id,
            repository_connection.full_name,
            page_number,
        )
        enabled = _configured_verified_event_types()
        events = []
        for raw in raw_events:
            normalized = _normalize_api_event(raw, repository_connection, default_branch, enabled)
            if normalized is not None:
                events.append(normalized)
        next_cursor = str(page_number + 1) if len(raw_events) >= 100 else ""
        return ReconciliationPage(events=tuple(events), next_cursor=next_cursor)


def _reconciliation_page_number(cursor):
    if cursor in (None, ""):
        return 1
    try:
        page = int(cursor)
    except (TypeError, ValueError) as exc:
        raise ReconciliationError("stored reconciliation cursor is malformed") from exc
    if page < 1:
        raise ReconciliationError("stored reconciliation cursor is malformed")
    return page


def _configured_verified_event_types():
    configured = getattr(settings, "GITHUB_VERIFIED_EVENT_TYPES", None)
    if configured is None:
        return DEFAULT_VERIFIED_EVENT_TYPES
    if not isinstance(configured, (list, tuple, set, frozenset)):
        raise ReconciliationError("GITHUB_VERIFIED_EVENT_TYPES must be a sequence")
    normalized = frozenset(str(item).strip() for item in configured)
    unknown = normalized - DEFAULT_VERIFIED_EVENT_TYPES
    if unknown:
        raise ReconciliationError(
            "GITHUB_VERIFIED_EVENT_TYPES contains unsupported values: " + ", ".join(sorted(unknown))
        )
    return normalized


def _matches_configured_branch(connection, event_type, payload):
    if event_type not in {"pull_request", "pull_request_review"}:
        return True
    if connection is None or connection.project_id is None:
        # Mapping-time validation remains necessary for deliveries that precede enrollment.
        return True
    default_branch = str(connection.project.default_branch or "").strip()
    pull_request = payload.get("pull_request") or {}
    base = pull_request.get("base") or {}
    return bool(default_branch) and base.get("ref") == default_branch


def _normalize_api_event(raw, connection, default_branch, enabled):
    event_type = API_EVENT_TYPES.get(raw.get("type"))
    if event_type is None or event_type not in enabled:
        return None
    raw_repository = raw.get("repo") or {}
    if raw_repository.get("name", "").casefold() != connection.full_name.casefold():
        raise ReconciliationError("provider API event belongs to a different repository")
    payload = raw.get("payload")
    actor = raw.get("actor")
    if not isinstance(payload, dict) or not isinstance(actor, dict):
        logger.warning("ignoring malformed reconciliation event (repository=%s)", connection.pk)
        return None
    webhook_payload = dict(payload)
    webhook_payload["sender"] = actor
    webhook_payload["repository"] = {
        "id": connection.repository_id,
        "node_id": connection.repository_node_id,
        "name": connection.full_name.rsplit("/", 1)[-1],
        "default_branch": default_branch,
    }
    if event_type == "pull_request_review" and webhook_payload.get("action") == "created":
        webhook_payload["action"] = "submitted"
    if event_type in {"pull_request", "pull_request_review"}:
        pull_request = webhook_payload.get("pull_request") or {}
        base = pull_request.get("base") or {}
        if base.get("ref") != default_branch:
            logger.info(
                "ignoring non-default-branch event (repository=%s event=%s)",
                connection.pk,
                raw.get("id"),
            )
            return None
    parsed = parse_event(event_type, webhook_payload)
    if parsed is None:
        return None
    return ReconciliationEvent(
        event_type=event_type,
        delivery_id=f"reconciliation-{raw.get('id') or parsed.event_id}",
        parsed_event=parsed,
    )


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
    if payload_dict is not None and event in {"installation", "installation_repositories"}:
        return _ingest_operational_event(
            provider,
            event,
            delivery_id,
            payload_dict,
            digest=digest,
            now=now,
            correlation_id=correlation_id,
        )
    parsed = parse_event(event, payload_dict) if payload_dict is not None else None
    issue_lifecycle = (
        parse_issue_lifecycle_event(event, payload_dict) if payload_dict is not None else None
    )

    if parsed is None and issue_lifecycle is not None:
        repository = RepositoryConnection.objects.filter(
            provider=provider, repository_node_id=issue_lifecycle.repository_node_id
        ).first()
        row = ProviderEvent.objects.create(
            provider=provider,
            event_type=event,
            delivery_id=delivery_id,
            provider_event_id=delivery_id,
            repository=repository,
            source=DeliverySource.WEBHOOK,
            signature_valid=True,
            signature_note=SIGNATURE_NOTE_VALID,
            payload=asdict(issue_lifecycle),
            payload_digest=digest,
            processing_state=ProcessingState.PENDING,
            correlation_id=correlation_id,
        )
        return row, None

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
    if event not in _configured_verified_event_types() or not _matches_configured_branch(
        repository, event, payload_dict
    ):
        row = ProviderEvent.objects.create(
            provider=provider,
            event_type=event,
            delivery_id=delivery_id,
            provider_event_id=delivery_id,
            repository=repository,
            source=DeliverySource.WEBHOOK,
            signature_valid=True,
            signature_note=SIGNATURE_NOTE_VALID,
            payload_digest=digest,
            processing_state=ProcessingState.PROCESSED,
            last_error="ignored: event or default branch is not configured for verified activity",
            processed_at=now,
            correlation_id=correlation_id,
        )
        return row, None
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


def process_pending(
    limit: int = 50, *, event_ids: Sequence[uuid.UUID] | None = None
) -> ProcessPendingResult:
    """GIT-005/A5/A9: drain PENDING ledger rows into candidate contributions.

    Unmapped repositories fail loudly; bot actors are filtered before any
    contribution record (GIT-008); a missing contributions service (parallel
    build) leaves rows PENDING and is reported instead of dropping work.
    """
    events_query = ProviderEvent.objects.select_related("repository", "repository__project").filter(
        processing_state=ProcessingState.PENDING
    )
    if event_ids is not None:
        events_query = events_query.filter(pk__in=event_ids)
    events = events_query.order_by("received_at", "id")[:limit]
    processed = failed = blocked = 0
    blocked_event_ids: list[str] = []
    for event in events:
        issue_lifecycle = _stored_issue_lifecycle_event(event.payload)
        if issue_lifecycle is not None:
            connection = (
                RepositoryConnection.objects.select_related("project")
                .filter(
                    provider=event.provider,
                    repository_node_id=issue_lifecycle.repository_node_id,
                )
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
            event.repository = connection
            event.processing_attempts += 1
            if not _refresh_public_snapshot_after_issue_lifecycle(connection, event):
                event.last_error = "retry: GitHub public snapshot refresh unavailable"
                event.save(update_fields=["repository", "last_error", "processing_attempts"])
                blocked += 1
                blocked_event_ids.append(str(event.pk))
                continue
            event.processing_state = ProcessingState.PROCESSED
            event.last_error = ""
            event.processed_at = timezone.now()
            event.save(
                update_fields=[
                    "repository",
                    "processing_state",
                    "last_error",
                    "processing_attempts",
                    "processed_at",
                ]
            )
            processed += 1
            continue

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
        if connection.sync_state == SyncState.STOPPED or connection.deactivated_at is not None:
            event.repository = connection
            event.processing_state = ProcessingState.FAILED
            event.last_error = "failed: repository synchronization is stopped"
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

        snapshot_refreshed = True
        if event.event_type == "issues" and parsed.action in ISSUE_LIFECYCLE_ACTIONS:
            snapshot_refreshed = _refresh_public_snapshot_after_issue_lifecycle(connection, event)

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
        if not snapshot_refreshed:
            event.repository = connection
            event.last_error = "retry: GitHub public snapshot refresh unavailable"
            event.save(update_fields=["repository", "last_error", "processing_attempts"])
            blocked += 1
            blocked_event_ids.append(str(event.pk))
            continue
        event.processing_state = ProcessingState.PROCESSED
        event.last_error = ""
        event.processed_at = timezone.now()
        event.save(
            update_fields=[
                "repository",
                "processing_state",
                "last_error",
                "processing_attempts",
                "processed_at",
            ]
        )
        processed += 1
    return ProcessPendingResult(
        processed=processed, failed=failed, blocked=blocked, blocked_event_ids=blocked_event_ids
    )


def _stored_issue_lifecycle_event(payload: object) -> ParsedIssueLifecycleEvent | None:
    if not isinstance(payload, dict):
        return None
    try:
        event = ParsedIssueLifecycleEvent(**payload)
    except TypeError:
        return None
    if event.action not in ISSUE_LIFECYCLE_ACTIONS or not event.repository_node_id:
        return None
    return event


def _refresh_public_snapshot_after_issue_lifecycle(
    connection: RepositoryConnection, event: ProviderEvent
) -> bool:
    if (
        not connection.is_public
        or connection.project_id is None
        or connection.sync_state == SyncState.STOPPED
        or connection.deactivated_at is not None
    ):
        return True
    try:
        refresh_public_repository_snapshot(connection, github_app_client())
    except GithubAppError:
        logger.warning(
            "issue lifecycle public snapshot refresh failed (repository=%s event=%s)",
            connection.pk,
            event.pk,
        )
        return False
    return True


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
            connection.sync_failure_count = 0
            connection.next_sync_attempt_at = None
            connection.last_synced_at = timezone.now()
            connection.save(
                update_fields=[
                    "sync_cursor",
                    "sync_state",
                    "health_note",
                    "sync_failure_count",
                    "next_sync_attempt_at",
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
        connection.sync_failure_count += 1
        base = max(1, int(getattr(settings, "GITHUB_SYNC_RETRY_BASE_SECONDS", 60)))
        maximum = max(base, int(getattr(settings, "GITHUB_SYNC_RETRY_MAX_SECONDS", 3600)))
        exponent = min(connection.sync_failure_count - 1, 30)
        delay = min(maximum, base * (2**exponent))
        connection.next_sync_attempt_at = timezone.now() + timedelta(seconds=delay)
        connection.save(
            update_fields=[
                "sync_state",
                "health_note",
                "sync_failure_count",
                "next_sync_attempt_at",
                "updated_at",
            ]
        )


def _ingest_operational_event(
    provider,
    event,
    delivery_id,
    payload,
    *,
    digest,
    now,
    correlation_id,
):
    """Apply authoritative GitHub App access changes in the signed request transaction."""
    action = str(payload.get("action") or "")
    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    affected = 0
    note = IGNORED_UNSUPPORTED_NOTE
    processing_state = ProcessingState.PROCESSED
    supported_action = (
        event == "installation" and action in {"deleted", "suspend", "unsuspend"}
    ) or (event == "installation_repositories" and action == "removed")
    if supported_action and not isinstance(installation_id, int):
        processing_state = ProcessingState.FAILED
        note = "failed: operational webhook has no valid installation id"
    if isinstance(installation_id, int):
        if event == "installation" and action in {"deleted", "suspend"}:
            reason = INSTALLATION_DELETED if action == "deleted" else INSTALLATION_SUSPENDED
            affected = _revoke_installation(provider, installation_id, reason, now, correlation_id)
            note = f"processed: {reason} affected {affected} repository connection(s)"
        elif event == "installation" and action == "unsuspend":
            affected = _unsuspend_installation(provider, installation_id, correlation_id)
            note = (
                f"processed: installation_unsuspended affected {affected} repository connection(s)"
            )
        elif event == "installation_repositories" and action == "removed":
            removed = payload.get("repositories_removed")
            if not isinstance(removed, list):
                processing_state = ProcessingState.FAILED
                note = "failed: repository removal webhook has no valid repository list"
            repository_ids = (
                {
                    item.get("id")
                    for item in removed
                    if isinstance(item, dict) and isinstance(item.get("id"), int)
                }
                if isinstance(removed, list)
                else set()
            )
            if processing_state != ProcessingState.FAILED:
                affected = _revoke_removed_repositories(
                    provider, installation_id, repository_ids, now, correlation_id
                )
                note = f"processed: repository_removed affected {affected} repository connection(s)"

    row = ProviderEvent.objects.create(
        provider=provider,
        event_type=event,
        delivery_id=delivery_id,
        provider_event_id=delivery_id,
        source=DeliverySource.WEBHOOK,
        signature_valid=True,
        signature_note=SIGNATURE_NOTE_VALID,
        payload={"action": action, "installation_id": installation_id, "affected": affected},
        payload_digest=digest,
        processing_state=processing_state,
        last_error=note,
        processed_at=now,
        correlation_id=correlation_id,
    )
    return row, None


def _revoke_installation(provider, installation_id, reason, now, correlation_id):
    connections = list(
        RepositoryConnection.objects.select_for_update().filter(
            provider=provider, installation_id=installation_id
        )
    )
    affected = 0
    for connection in connections:
        if (
            connection.sync_state == SyncState.STOPPED
            and connection.project_id is None
            and connection.access_revoked_reason == reason
        ):
            continue
        before = _repository_access_snapshot(connection)
        connection.sync_state = SyncState.STOPPED
        connection.project = None
        connection.deactivated_at = connection.deactivated_at or now
        connection.access_revoked_reason = reason
        connection.next_sync_attempt_at = None
        connection.save(
            update_fields=[
                "sync_state",
                "project",
                "deactivated_at",
                "access_revoked_reason",
                "next_sync_attempt_at",
                "updated_at",
            ]
        )
        record_audit(
            actor=None,
            action=f"github_repository.{reason}",
            obj=connection,
            before=before,
            after=_repository_access_snapshot(connection),
            source="github_webhook",
            correlation_id=correlation_id,
        )
        affected += 1
    logger.warning(
        "GitHub installation access revoked (installation=%s reason=%s affected=%s)",
        installation_id,
        reason,
        affected,
    )
    return affected


def _unsuspend_installation(provider, installation_id, correlation_id):
    connections = list(
        RepositoryConnection.objects.select_for_update().filter(
            provider=provider,
            installation_id=installation_id,
            access_revoked_reason=INSTALLATION_SUSPENDED,
        )
    )
    for connection in connections:
        before = _repository_access_snapshot(connection)
        # Suspension already cleared the project binding. Provider access returning
        # is not authority to restore that binding or restart synchronization.
        connection.sync_state = SyncState.STOPPED
        connection.access_revoked_reason = INSTALLATION_UNSUSPENDED_UNBOUND
        connection.health_note = "installation unsuspended; explicit re-enrollment required"
        connection.sync_failure_count = 0
        connection.next_sync_attempt_at = None
        connection.save(
            update_fields=[
                "sync_state",
                "access_revoked_reason",
                "health_note",
                "sync_failure_count",
                "next_sync_attempt_at",
                "updated_at",
            ]
        )
        record_audit(
            actor=None,
            action="github_repository.installation_unsuspended",
            obj=connection,
            before=before,
            after=_repository_access_snapshot(connection),
            source="github_webhook",
            correlation_id=correlation_id,
        )
    logger.info(
        "GitHub installation unsuspended (installation=%s affected=%s)",
        installation_id,
        len(connections),
    )
    return len(connections)


def _revoke_removed_repositories(provider, installation_id, repository_ids, now, correlation_id):
    if not repository_ids:
        return 0
    connections = list(
        RepositoryConnection.objects.select_for_update().filter(
            provider=provider,
            installation_id=installation_id,
            repository_id__in=repository_ids,
        )
    )
    affected = 0
    for connection in connections:
        if (
            connection.sync_state == SyncState.STOPPED
            and connection.project_id is None
            and connection.access_revoked_reason == REPOSITORY_REMOVED
        ):
            continue
        before = _repository_access_snapshot(connection)
        connection.sync_state = SyncState.STOPPED
        connection.project = None
        connection.deactivated_at = connection.deactivated_at or now
        connection.access_revoked_reason = REPOSITORY_REMOVED
        connection.next_sync_attempt_at = None
        connection.save(
            update_fields=[
                "sync_state",
                "project",
                "deactivated_at",
                "access_revoked_reason",
                "next_sync_attempt_at",
                "updated_at",
            ]
        )
        record_audit(
            actor=None,
            action="github_repository.repository_removed",
            obj=connection,
            before=before,
            after=_repository_access_snapshot(connection),
            source="github_webhook",
            correlation_id=correlation_id,
        )
        affected += 1
    logger.warning(
        "GitHub repository access removed (installation=%s affected=%s)",
        installation_id,
        affected,
    )
    return affected


def _repository_access_snapshot(connection):
    return {
        "project_id": connection.project_id,
        "sync_state": connection.sync_state,
        "deactivated_at": (
            connection.deactivated_at.isoformat() if connection.deactivated_at else None
        ),
        "access_revoked_reason": connection.access_revoked_reason,
    }


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
