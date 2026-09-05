from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.projects.enums import ProjectStatus
from apps.projects.services import (
    ProjectAuthorizationError,
    ProjectLifecycleError,
    approve,
    assign_reviewer,
    revoke_approval,
    submit_for_review,
)
from apps.projects.tests.factories import (
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)

pytestmark = pytest.mark.django_db


def in_review():
    project = make_publishable()
    submit_for_review(project.owner, project)
    project.refresh_from_db()
    return project


def mfa_login(client, user):
    client.force_login(user)


def test_d2_reviewer_assignment_is_version_scoped_validated_and_audited():
    """ADM-002/GOV-005: assignment, SLA, checklist and note are durable review provenance."""
    project = in_review()
    assigner = SuperAdminFactory()
    reviewer = SuperAdminFactory()
    due_at = timezone.now() + timedelta(days=5)

    assignment = assign_reviewer(
        assigner,
        project,
        reviewer=reviewer,
        due_at=due_at,
        reviewer_note="Confirm credentials are placeholders.",
        checklist={"security_exposure": True, "repository_readiness": False},
    )

    assert assignment.version == project.versions.latest("version_number")
    assert assignment.reviewer == reviewer
    assert assignment.due_at == due_at
    assert assignment.checklist["security_exposure"] is True
    assert AuditEvent.objects.filter(action="project.reviewer_assigned").exists()

    with pytest.raises(ProjectAuthorizationError):
        assign_reviewer(UserFactory(), project, reviewer=reviewer, due_at=due_at)
    with pytest.raises(ProjectLifecycleError, match="future"):
        assign_reviewer(
            assigner,
            project,
            reviewer=reviewer,
            due_at=timezone.now() - timedelta(minutes=1),
        )


def test_d2_assigned_review_can_only_be_decided_by_assignee_and_schedule_is_revocable():
    """GOV-005: assigned decisions are attributable and approval scheduling is reversible."""
    project = in_review()
    reviewer = SuperAdminFactory()
    other = SuperAdminFactory()
    assign_reviewer(
        reviewer,
        project,
        reviewer=reviewer,
        due_at=timezone.now() + timedelta(days=5),
    )
    with pytest.raises(ProjectAuthorizationError, match="assigned reviewer"):
        approve(other, project, comment="Looks ready")

    with pytest.raises(ProjectLifecycleError, match="future"):
        approve(
            reviewer,
            project,
            publish_at=timezone.now() - timedelta(minutes=1),
            comment="This must not persist",
        )
    project.refresh_from_db()
    assert project.status == ProjectStatus.IN_REVIEW
    assert not project.reviews.exists()

    scheduled = timezone.now() + timedelta(days=2)
    approve(reviewer, project, publish_at=scheduled, comment="Checklist verified")
    project.refresh_from_db()
    assert project.scheduled_publication_at == scheduled
    assert project.reviews.latest("created_at").comment == "Checklist verified"

    revoke_approval(reviewer, project, reason="Security evidence changed")
    project.refresh_from_db()
    assert project.status == ProjectStatus.CHANGES_REQUESTED
    assert project.scheduled_publication_at is None


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_d2_queue_is_superadmin_only_and_renders_real_sla_diff_and_decisions(client):
    """ADM-002/GOV-005: PMO gets a real queue/detail instead of authoring-table impersonation."""
    project = in_review()
    previous = project.versions.latest("version_number")
    project.summary_en = "Revised summary"
    project.save(update_fields=["summary_en"])
    # A second immutable version makes an honest field-level comparison available.
    from apps.projects.services import create_version

    create_version(project, project.owner)
    admin = SuperAdminFactory()
    mfa_login(client, admin)

    response = client.get(reverse("projects:review_queue"), {"project": project.slug})

    assert response.status_code == 200
    body = response.content.decode()
    assert "Review queue" in body
    assert project.title_en in body
    assert "SLA age" in body
    assert "Version comparison" in body
    assert "summary_en" in body
    assert str(previous.version_number) in body
    for action in ("request_changes", "reject", "approve"):
        assert f'value="{action}"' in body

    outsider = UserFactory()
    client.force_login(outsider)
    assert client.get(reverse("projects:review_queue")).status_code in {302, 403}


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_d2_queue_filters_state_assignment_and_keeps_selection_in_scope(client):
    """ADM-002: queue controls filter real records and cannot select a filtered-out project."""
    reviewer = SuperAdminFactory()
    mine = in_review()
    other = in_review()
    approved = in_review()
    assign_reviewer(
        reviewer,
        mine,
        reviewer=reviewer,
        due_at=timezone.now() + timedelta(days=5),
    )
    approve(SuperAdminFactory(), approved, comment="Ready")
    mfa_login(client, reviewer)
    url = reverse("projects:review_queue")

    assigned = client.get(url, {"assigned": "me", "project": other.slug})
    assert assigned.status_code == 200
    assert assigned.context["selected"] == mine
    assert [row["project"] for row in assigned.context["queue"]] == [mine]
    assert "assigned=me" in assigned.context["queue"][0]["select_url"]

    scheduled = client.get(url, {"state": ProjectStatus.APPROVED})
    assert scheduled.status_code == 200
    assert [row["project"] for row in scheduled.context["queue"]] == [approved]

    invalid = client.get(url, {"state": "not-a-state"})
    assert invalid.status_code == 200
    assert invalid.context["state_filter"] == ""


@override_settings(PRIVILEGED_MFA_BYPASS=True)
def test_c5_workflow_exposes_cancel_extend_and_approved_revocation(client):
    """GOV-004/GOV-010: prototype lifecycle controls are operable, validated POST actions."""
    live = make_publishable(status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    live.deadline = timezone.localdate() + timedelta(days=2)
    live.save(update_fields=["deadline"])
    mfa_login(client, live.owner)
    url = reverse("projects:authoring_workflow", kwargs={"slug": live.slug})

    bad = client.post(url, {"action": "extend_deadline", "new_deadline": "2020-01-01"})
    assert bad.status_code == 400
    assert "future" in bad.content.decode()
    live.refresh_from_db()
    assert live.deadline == timezone.localdate() + timedelta(days=2)

    new_deadline = timezone.localdate() + timedelta(days=30)
    assert (
        client.post(
            url, {"action": "extend_deadline", "new_deadline": new_deadline.isoformat()}
        ).status_code
        == 302
    )
    live.refresh_from_db()
    assert live.deadline == new_deadline

    assert client.post(url, {"action": "cancel", "reason": "Funding withdrawn"}).status_code == 302
    live.refresh_from_db()
    assert live.status == ProjectStatus.CANCELLED
    assert live.outcome_summary == "Funding withdrawn"
