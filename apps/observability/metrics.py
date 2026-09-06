import logging
from collections.abc import Callable
from datetime import timedelta

from django.utils import timezone
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_USER_REQUESTS_TOTAL = Counter(
    "http_user_requests_total",
    "User-facing HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds by method and route template.",
    ["method", "route"],
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being processed by this process.",
)

DB_QUERIES_TOTAL = Counter(
    "db_queries_total",
    "Database queries executed, by connection alias and outcome.",
    ["alias", "outcome"],
)
DB_QUERY_DURATION_SECONDS = Histogram(
    "db_query_duration_seconds",
    "Database query execution time in seconds, by connection alias.",
    ["alias"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
DB_QUERIES_PER_REQUEST = Histogram(
    "db_queries_per_request",
    "Number of database queries issued while handling one HTTP request.",
    buckets=(0, 1, 2, 5, 10, 20, 50, 100, 200),
)

DB_PENDING_MIGRATIONS = Gauge(
    "db_pending_migrations",
    "Unapplied Django migrations against the configured default database.",
)

JOB_RUNS_TOTAL = Counter(
    "background_job_runs_total",
    "Background management-command runs by command and terminal status.",
    ["command", "status"],
)
JOB_RUN_DURATION_SECONDS = Histogram(
    "background_job_duration_seconds",
    "Background management-command run duration in seconds.",
    ["command"],
)

JOB_SECONDS_SINCE_LAST_SUCCESS = Gauge(
    "background_job_seconds_since_last_success",
    "Seconds since the command last finished successfully; +Inf if it never has.",
    ["command"],
)
JOB_LAST_RUN_SUCCESS = Gauge(
    "background_job_last_run_success",
    "1 if the most recent run of this command succeeded, else 0.",
    ["command"],
)

QUEUE_DEPTH = Gauge(
    "queue_depth",
    "Depth of an operationally-relevant backlog, by queue name.",
    ["queue"],
)

RECURRING_JOB_COMMANDS = (
    "process_github_events",
    "reconcile_repositories",
    "send_pending_notifications",
    "publish_scheduled",
    "flag_stale_projects",
    "purge_observability_job_runs",
)

NON_USER_FACING_ROUTES = frozenset({"healthz", "readyz", "metrics"})


def is_user_facing_route(route: str) -> bool:
    return route not in NON_USER_FACING_ROUTES


def _safe(name: str, fn: Callable[[], float]) -> float:
    try:
        return float(fn())
    except Exception:
        logger.exception("observability: failed to compute gauge %s", name)
        return float("nan")


def _seconds_since_last_success(command: str) -> float:
    from apps.observability.models import JobRun, JobStatus

    last_success = (
        JobRun.objects.filter(command=command, status=JobStatus.SUCCESS)
        .order_by("-finished_at")
        .values_list("finished_at", flat=True)
        .first()
    )
    if last_success is None:
        return float("inf")
    return (timezone.now() - last_success).total_seconds()


def _last_run_succeeded(command: str) -> float:
    from apps.observability.models import JobRun, JobStatus

    last_run = JobRun.objects.filter(command=command).order_by("-started_at").first()
    if last_run is None:
        return float("nan")
    return 1.0 if last_run.status == JobStatus.SUCCESS else 0.0


def _github_sync_pending_events() -> float:
    from apps.github_sync.enums import ProcessingState
    from apps.github_sync.models import ProviderEvent

    return ProviderEvent.objects.filter(processing_state=ProcessingState.PENDING).count()


def _notifications_pending() -> float:
    from apps.notifications.enums import DeliveryStatus
    from apps.notifications.models import Notification

    return Notification.objects.filter(
        delivery_status__in=(DeliveryStatus.PENDING, DeliveryStatus.FAILED)
    ).count()


def _moderation_aging_cases() -> float:
    from apps.moderation.enums import CaseStatus
    from apps.moderation.models import ModerationCase

    threshold = timezone.now() - timedelta(days=5)
    return ModerationCase.objects.filter(
        status__in=(CaseStatus.NEW, CaseStatus.UNDER_REVIEW),
        created_at__lt=threshold,
    ).count()


def _stale_projects() -> float:
    from apps.projects.enums import ProjectStatus
    from apps.projects.models import Project

    return Project.objects.filter(
        status__in=(ProjectStatus.PAUSED, ProjectStatus.OPEN_FOR_CONTRIBUTION),
        deadline__lt=timezone.localdate(),
    ).count()


def _audit_failures_24h() -> float:
    from apps.audit.models import AuditEvent

    since = timezone.now() - timedelta(hours=24)
    return AuditEvent.objects.filter(
        result__in=("failure", "denied"), created_at__gte=since
    ).count()


def _pending_migrations() -> float:
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connections["default"])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return len(plan)


QUEUE_GAUGE_SOURCES: dict[str, Callable[[], float]] = {
    "github_sync_pending_events": _github_sync_pending_events,
    "notifications_pending": _notifications_pending,
    "moderation_aging_cases": _moderation_aging_cases,
    "projects_stale": _stale_projects,
    "audit_failures_24h": _audit_failures_24h,
}


def refresh_db_backed_gauges() -> None:
    """Recompute the gauges whose value lives in the database, not in-process state.

    Called at `/metrics` scrape time rather than on a background timer: these
    processes are request/response, so "current" is only meaningful as of the
    scrape (NFR-OBS-01 dashboards; worker-monitoring evidence gate).
    """
    for command in RECURRING_JOB_COMMANDS:
        seconds_since_success = _safe(
            f"seconds_since_last_success[{command}]",
            lambda command=command: _seconds_since_last_success(command),
        )
        JOB_SECONDS_SINCE_LAST_SUCCESS.labels(command=command).set(seconds_since_success)
        last_run_success = _safe(
            f"last_run_success[{command}]",
            lambda command=command: _last_run_succeeded(command),
        )
        JOB_LAST_RUN_SUCCESS.labels(command=command).set(last_run_success)

    for queue_name, source in QUEUE_GAUGE_SOURCES.items():
        QUEUE_DEPTH.labels(queue=queue_name).set(_safe(queue_name, source))

    DB_PENDING_MIGRATIONS.set(_safe("pending_migrations", _pending_migrations))
