import datetime
import logging
from math import ceil

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.permissions import privileged_mfa_required
from apps.github_sync.app_client import github_app_client
from apps.github_sync.errors import (
    ConnectionNotFoundError,
    GithubAppError,
    RepositoryBindingError,
    WebhookReplayError,
    WebhookSignatureError,
)
from apps.github_sync.models import GithubConnection, RepositoryConnection
from apps.github_sync.services import (
    annual_contribution_calendar,
    bind_repository,
    binding_projects,
    disconnect,
    enroll_repository,
    ingest_webhook,
    member_repositories,
)

MAX_WEBHOOK_BODY_BYTES = 1_048_576

logger = logging.getLogger(__name__)

WEEKDAY_LABELS = (
    gettext_lazy("Sun"),
    gettext_lazy("Mon"),
    gettext_lazy("Tue"),
    gettext_lazy("Wed"),
    gettext_lazy("Thu"),
    gettext_lazy("Fri"),
    gettext_lazy("Sat"),
)
INTENSITY_LEVELS = range(5)


@csrf_exempt
@require_POST
def github_webhook(request: HttpRequest) -> HttpResponse:
    event = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")
    signature = request.headers.get("X-Hub-Signature-256")
    timestamp = request.headers.get("X-GitHub-Delivery-Timestamp")
    if not all((event, delivery_id, signature)):
        return HttpResponse(status=400)

    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BODY_BYTES:
                return HttpResponse(status=413)
        except ValueError:
            return HttpResponse(status=400)

    try:
        body = request.body
    except RequestDataTooBig:
        return HttpResponse(status=413)
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        return HttpResponse(status=413)

    try:
        ingest_webhook("github", event, delivery_id, signature, timestamp, body)
    except WebhookSignatureError:
        return HttpResponse(status=401)
    except WebhookReplayError:
        return HttpResponse(status=409)
    return HttpResponse(status=202)


@login_required(login_url=reverse_lazy("accounts:login"))
@require_GET
def connection_status(request: HttpRequest) -> HttpResponse:
    """GIT-011/AUTH-008: member-facing provider connection record.

    Shows consent, granted scopes, connection and last synchronization times and
    the revocation state. Token material is never stored on the model and so is
    never rendered (AUTH-008). Members without a connection are routed to their
    dashboard, where the connect action lives.
    """
    connection = GithubConnection.objects.filter(user=request.user).first()
    if connection is None:
        return redirect("accounts:dashboard")
    repositories = RepositoryConnection.objects.filter(activated_by=request.user).order_by(
        "full_name"
    )
    return render(
        request,
        "github_sync/connection.html",
        {"connection": connection, "repositories": repositories},
    )


@login_required(login_url=reverse_lazy("accounts:login"))
@require_POST
def disconnect_connection(request: HttpRequest) -> HttpResponse:
    """GIT-011/AUTH-008: POST-only member disconnect.

    Delegates to services.disconnect, which stops synchronization, purges
    stored tokens and writes the audit row inside one transaction. MFA step-up
    is not required at member level; CSRF protection applies as usual.
    """
    try:
        disconnect(request.user)
    except ConnectionNotFoundError as exc:
        raise Http404("no provider connection for this member") from exc
    messages.success(
        request,
        _("GitHub disconnected. Synchronization stopped and stored tokens deleted."),
    )
    return redirect("github_sync:connection")


@login_required(login_url=reverse_lazy("accounts:login"))
@privileged_mfa_required
@require_http_methods(["GET", "POST"])
def connect_repository(request: HttpRequest) -> HttpResponse:
    """GIT-001/GIT-003/AUTH-008: member enrollment of App-accessible repositories.

    GET lists the repositories of the member's linked installations with a
    freshly minted in-memory token; POST enrolls exactly one repository. The
    route is disabled (404) when the GitHub App is unconfigured, mirroring the
    connect flow. Enrollments are idempotent and audited; token material is
    never stored, rendered or logged.
    """
    client = github_app_client()
    if not client.is_configured:
        raise Http404("GitHub App is not configured")
    connection = GithubConnection.objects.filter(user=request.user, revoked_at__isnull=True).first()
    if connection is None:
        raise Http404("no provider connection for this member")
    project = _binding_project(request)
    if request.method == "POST":
        return _enroll_repository(request, client, connection, project)
    return _render_connect_repository(request, client, connection, project)


def _binding_project(request):
    raw_project_id = request.POST.get("project_id") or request.GET.get("project_id")
    if not raw_project_id:
        return None
    project = binding_projects(request.user).filter(pk=_parse_selection_id(raw_project_id)).first()
    if project is None:
        raise Http404("project is not available for repository binding")
    return project


def _repository_context(request, connection, repositories, project=None, **extra):
    context = {
        "connection": connection,
        "repositories": repositories,
        "projects": binding_projects(request.user),
        "selected_project": project,
    }
    context.update(extra)
    return context


def _render_connect_repository(request, client, connection, project=None) -> HttpResponse:
    try:
        repositories = member_repositories(client, connection, actor=request.user, project=project)
    except GithubAppError:
        logger.exception("GitHub App repository listing failed (member=%s)", request.user.pk)
        return render(
            request,
            "github_sync/connect_repository.html",
            _repository_context(request, connection, [], project, error_banner=True),
        )
    return render(
        request,
        "github_sync/connect_repository.html",
        _repository_context(request, connection, repositories, project),
    )


def _enroll_repository(request, client, connection, project=None) -> HttpResponse:
    installation_id = _parse_selection_id(request.POST.get("installation_id"))
    repository_id = _parse_selection_id(request.POST.get("repository_id"))
    try:
        repositories = member_repositories(client, connection, actor=request.user, project=project)
    except GithubAppError:
        logger.exception("GitHub App repository enrollment failed (member=%s)", request.user.pk)
        return render(
            request,
            "github_sync/connect_repository.html",
            _repository_context(request, connection, [], project, error_banner=True),
        )
    choice = next(
        (
            repository
            for repository in repositories
            if repository.repository_id == repository_id
            and repository.installation_id == installation_id
        ),
        None,
    )
    if choice is None:
        raise Http404("repository is not available for this member")
    binding_outcome = None
    try:
        with transaction.atomic():
            outcome = enroll_repository(
                request.user,
                installation_id=choice.installation_id,
                repository_id=choice.repository_id,
                node_id=choice.node_id,
                full_name=choice.full_name,
                granted_scopes=choice.granted_scopes,
                is_public=not choice.private,
            )
            if project is not None:
                binding_outcome = bind_repository(request.user, outcome.connection, project)
    except RepositoryBindingError:
        logger.exception(
            "GitHub repository binding failed (member=%s project=%s repository_id=%s)",
            request.user.pk,
            project.pk if project is not None else None,
            choice.repository_id,
        )
        return render(
            request,
            "github_sync/connect_repository.html",
            _repository_context(
                request,
                connection,
                repositories,
                project,
                binding_error=_("This repository could not be connected to the project."),
            ),
            status=400,
        )
    if binding_outcome is not None and binding_outcome.bound:
        messages.success(request, _("Repository connected to the project."))
    elif outcome.created:
        messages.success(
            request,
            _("Repository connected. Activity for this repository can now feed listed projects."),
        )
    else:
        messages.info(request, _("Repository was already connected."))
    target = reverse("github_sync:connect_repository")
    if project is not None:
        target = f"{target}?project_id={project.pk}"
    return redirect(target)


def _parse_selection_id(raw) -> int:
    try:
        return int(str(raw))
    except (TypeError, ValueError) as exc:
        raise Http404("malformed repository selection") from exc


def calendar_context(user, year: int | None = None) -> dict:
    """GIT-009/BR-005: reusable calendar block context for profile views.

    Returns calendar=None unless the member has an active (non-revoked)
    connection with the annual-calendar consent flag on; the template renders
    nothing in that case.
    """
    connection = GithubConnection.objects.filter(
        user=user, revoked_at__isnull=True, show_annual_calendar=True
    ).first()
    if connection is None:
        return {"connection": None, "calendar": None}
    if year is None:
        year = timezone.localdate().year
    summary = annual_contribution_calendar(connection, year)
    rows, months = _calendar_grid(summary)
    return {
        "connection": connection,
        "calendar": {
            "year": year,
            "total": summary.total,
            "longest_streak": summary.longest_streak,
            "busiest_month": summary.busiest_month,
            "rows": rows,
            "months": months,
            "levels": INTENSITY_LEVELS,
            "fetched_at": connection.calendar_fetched_at or timezone.now(),
        },
    }


def _calendar_grid(summary) -> tuple[list[dict], list[dict]]:
    max_count = max(summary.counts.values(), default=0)
    leading = (datetime.date(summary.year, 1, 1).weekday() + 1) % 7
    cells: list[dict | None] = [None] * leading
    for day, count in summary.counts.items():
        cells.append({"date": day, "count": count, "level": _level(count, max_count)})
    cells.extend([None] * (-len(cells) % 7))
    weeks = [cells[offset : offset + 7] for offset in range(0, len(cells), 7)]
    rows = [
        {"label": WEEKDAY_LABELS[weekday], "cells": [week[weekday] for week in weeks]}
        for weekday in range(7)
    ]
    return rows, _month_spans(summary.year, weeks)


def _level(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    step = max(1, ceil(max_count / 4))
    return min(4, ceil(count / step))


def _month_spans(year: int, weeks: list[list[dict | None]]) -> list[dict]:
    starts: dict[int, int] = {}
    for column, week in enumerate(weeks):
        for cell in week:
            if cell is not None and cell["date"].month not in starts:
                starts[cell["date"].month] = column
    boundaries = sorted(starts)
    return [
        {
            "start": datetime.date(year, month, 1),
            "span": (
                (starts[boundaries[index + 1]] if index + 1 < len(boundaries) else len(weeks))
                - starts[month]
            ),
        }
        for index, month in enumerate(boundaries)
    ]
