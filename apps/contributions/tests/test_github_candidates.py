import pytest

from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.services import record_candidate_from_github
from apps.contributions.tests.factories import contribution_type
from apps.github_sync.enums import VerifiedEventKind
from apps.github_sync.webhooks import parse_event
from apps.projects.tests.factories import ProjectFactory

pytestmark = [pytest.mark.django_db]


def merged_pr_payload(event_id=901, login="shanker", actor_type="User", merged=True):
    return {
        "action": "closed",
        "sender": {"login": login, "type": actor_type},
        "repository": {"node_id": "R_1", "name": "service-directory"},
        "pull_request": {"id": event_id, "number": 7, "merged": merged},
    }


@pytest.mark.unit
def test_d7_merged_pr_creates_exactly_one_candidate():
    """GIT-007/BR-006: a qualifying provider event creates one CANDIDATE, not accepted credit."""
    project = ProjectFactory()
    parsed = parse_event("pull_request", merged_pr_payload())
    assert parsed is not None and parsed.kind == VerifiedEventKind.PR_MERGED

    record = record_candidate_from_github(parsed, project)

    assert record is not None
    assert record.project == project
    assert record.source == ContributionSource.PROVIDER_EVENT
    assert record.status == VerificationStatus.CANDIDATE
    assert record.verified_at is None
    assert record.provider_event_ref == f"github:{parsed.event_id}"
    assert record.contribution_type == contribution_type("engineering")
    assert "service-directory" in record.title


@pytest.mark.unit
@pytest.mark.parametrize(
    ("login", "actor_type"),
    [
        ("dependabot[bot]", "User"),
        ("github-actions", "Bot"),
        ("renovate[bot]", "Bot"),
    ],
)
def test_bot_events_never_create_contribution_records(login, actor_type):
    """GIT-008: automated/bot authors generate no contribution record at all."""
    project = ProjectFactory()
    parsed = parse_event("pull_request", merged_pr_payload(login=login, actor_type=actor_type))
    assert parsed is not None and parsed.is_bot

    assert record_candidate_from_github(parsed, project) is None
    assert project.contributions.count() == 0


@pytest.mark.unit
def test_raw_commit_event_generates_no_candidate():
    """GIT-008/D7: raw/direct commits are not qualifying events and create no record."""
    project = ProjectFactory()
    push = parse_event(
        "push", {"sender": {"login": "shanker", "type": "User"}, "commits": [{"id": "abc"}]}
    )
    unmerged = parse_event("pull_request", merged_pr_payload(merged=False))

    assert push is None
    assert unmerged is None
    assert record_candidate_from_github(push, project) is None
    assert record_candidate_from_github(unmerged, project) is None
    assert project.contributions.count() == 0


@pytest.mark.unit
def test_replayed_provider_event_creates_no_duplicate():
    """GIT-005/GIT-008/A5: a redelivered event resolves to the existing record, not a second one."""
    project = ProjectFactory()
    parsed = parse_event("pull_request", merged_pr_payload(event_id=4242))

    first = record_candidate_from_github(parsed, project)
    replay = record_candidate_from_github(
        parse_event("pull_request", merged_pr_payload(event_id=4242)), project
    )

    assert replay.pk == first.pk
    assert project.contributions.count() == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("pull_request", merged_pr_payload()),
        (
            "issues",
            {
                "action": "closed",
                "sender": {"login": "shanker", "type": "User"},
                "repository": {"node_id": "R_1", "name": "service-directory"},
                "issue": {"id": 555, "number": 12, "state_reason": "completed"},
            },
        ),
        (
            "pull_request_review",
            {
                "action": "submitted",
                "sender": {"login": "shanker", "type": "User"},
                "repository": {"node_id": "R_1", "name": "service-directory"},
                "review": {"id": 777, "state": "approved"},
                "pull_request": {"id": 901, "number": 7},
            },
        ),
        (
            "release",
            {
                "action": "published",
                "sender": {"login": "shanker", "type": "User"},
                "repository": {"node_id": "R_1", "name": "service-directory"},
                "release": {"id": 888},
            },
        ),
    ],
)
def test_every_d7_kind_qualifies_as_a_candidate(event, payload):
    """D7/GIT-007: PR merged, issue completed, approved review, and release published qualify."""
    parsed = parse_event(event, payload)
    assert parsed is not None
    record = record_candidate_from_github(parsed, ProjectFactory())
    assert record is not None
    assert record.status == VerificationStatus.CANDIDATE


@pytest.mark.integration
def test_unmapped_github_actor_is_flagged_pending_mapping():
    """GIT-012 actor mapping: without a resolvable member the record waits with a pending flag."""
    project = ProjectFactory()
    parsed = parse_event("pull_request", merged_pr_payload(login="lonely-contributor"))

    record = record_candidate_from_github(parsed, project)

    assert record.contributor is None
    assert record.pending_mapping is True
    assert "lonely-contributor" in record.description


@pytest.mark.integration
def test_connected_github_actor_maps_to_the_member():
    """GIT-012: an active GithubConnection.login resolves the candidate's contributor."""
    from django.utils import timezone as dj_timezone

    from apps.github_sync.tests.factories import GithubConnectionFactory

    project = ProjectFactory()
    connection = GithubConnectionFactory(login="shanker")
    GithubConnectionFactory(login="ghost", revoked_at=dj_timezone.now())
    parsed = parse_event("pull_request", merged_pr_payload(login="shanker"))

    record = record_candidate_from_github(parsed, project)

    assert record.contributor == connection.user
    assert record.pending_mapping is False

    revoked_actor = record_candidate_from_github(
        parse_event("pull_request", merged_pr_payload(event_id=9999, login="ghost")),
        project,
    )
    assert revoked_actor.contributor is None
    assert revoked_actor.pending_mapping is True
