import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.tests.factories import MemberProfileFactory, MemberSkillFactory
from apps.contributions.enums import VerificationStatus
from apps.contributions.tests.factories import ContributionRecordFactory, contribution_type
from apps.ministries.tests.factories import MinistryOrganizationFactory
from apps.projects.enums import ApplicationStatus, ProjectStatus
from apps.projects.services import recommended_projects
from apps.projects.tests.factories import (
    ApplicationFactory,
    ProjectBookmarkFactory,
    ProjectFactory,
    UserFactory,
)
from apps.taxonomy.models import Skill

pytestmark = pytest.mark.django_db


def open_project(title_en, **kwargs):
    return ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION, title_en=title_en, **kwargs)


def member_with_skill(skill_name="Django"):
    member = UserFactory()
    MemberSkillFactory(user=member, skill=skill(skill_name))
    return member


def skill(name):
    return Skill.objects.get(name=name)


@pytest.mark.unit
def test_recommendations_empty_for_anonymous_and_missing_user():
    """DSC-010: recommendations are member-only; anonymous visitors and missing users get none."""
    member = member_with_skill()
    candidate = open_project("Open candidate")
    candidate.skills.add(skill("Django"))

    assert recommended_projects(AnonymousUser()) == []
    assert recommended_projects(None) == []
    assert recommended_projects(member) != []


@pytest.mark.unit
def test_reasons_cite_only_explicit_profile_attributes():
    """DSC-010: each reason cites a real profile attribute; no opaque score is exposed."""
    member = UserFactory()
    MemberProfileFactory(user=member, experience_band="intermediate")
    MemberSkillFactory(user=member, skill=skill("Django"))
    engineering = contribution_type("engineering")
    ContributionRecordFactory(
        contributor=member,
        contribution_type=engineering,
        status=VerificationStatus.ACCEPTED,
    )
    ministry = MinistryOrganizationFactory()
    ProjectBookmarkFactory(user=member, project=open_project("Saved project", ministry=ministry))

    target = open_project("Target project", ministry=ministry, experience_band="intermediate")
    target.skills.add(skill("Django"))
    target.contribution_types.add(engineering)

    recommendations = recommended_projects(member)

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.project == target
    assert "Matches your Django skill" in recommendation.reasons
    assert "Matches your Engineering contribution history" in recommendation.reasons
    assert "Similar to a project you saved" in recommendation.reasons
    assert "Matches your intermediate experience level" in recommendation.reasons
    assert not hasattr(recommendation, "score")


@pytest.mark.unit
def test_candidate_without_profile_signals_is_not_recommended():
    """DSC-010: no cold-start filler; only explained matches are returned."""
    member = UserFactory()
    open_project("Unrelated project")

    assert recommended_projects(member) == []


@pytest.mark.unit
def test_recommendations_exclude_own_saved_private_and_applied_projects():
    """DSC-010/BR-004: own, saved, non-public, and applied projects are never recommended."""
    member = member_with_skill()

    own = open_project("Own listing", owner=member)
    own.skills.add(skill("Django"))
    saved = open_project("Already saved")
    saved.skills.add(skill("Django"))
    ProjectBookmarkFactory(user=member, project=saved)
    draft = ProjectFactory(status=ProjectStatus.DRAFT, title_en="Secret draft")
    draft.skills.add(skill("Django"))
    in_review = ProjectFactory(status=ProjectStatus.IN_REVIEW, title_en="Under review")
    in_review.skills.add(skill("Django"))
    paused = ProjectFactory(status=ProjectStatus.PAUSED, title_en="Paused work")
    paused.skills.add(skill("Django"))
    applied = open_project("Already applied")
    applied.skills.add(skill("Django"))
    ApplicationFactory(project=applied, applicant=member)
    withdrawn = open_project("Withdrawn application")
    withdrawn.skills.add(skill("Django"))
    ApplicationFactory(project=withdrawn, applicant=member, status=ApplicationStatus.WITHDRAWN)
    candidate = open_project("Open candidate")
    candidate.skills.add(skill("Django"))

    recommendations = recommended_projects(member)

    assert [recommendation.project for recommendation in recommendations] == [candidate]


@pytest.mark.unit
def test_recommendations_order_is_deterministic_score_then_title():
    """DSC-010: ordering is score descending then title, stable across repeated calls."""
    member = UserFactory()
    MemberSkillFactory(user=member, skill=skill("Django"))
    MemberSkillFactory(user=member, skill=skill("PostgreSQL"))

    both = open_project("Both skills")
    both.skills.add(skill("Django"), skill("PostgreSQL"))
    zeta = open_project("Zeta one skill")
    zeta.skills.add(skill("Django"))
    alpha = open_project("Alpha one skill")
    alpha.skills.add(skill("Django"))

    first = recommended_projects(member)
    second = recommended_projects(member)

    assert [recommendation.project.title_en for recommendation in first] == [
        "Both skills",
        "Alpha one skill",
        "Zeta one skill",
    ]
    assert first == second
    limited = recommended_projects(member, limit=1)
    assert [recommendation.project.title_en for recommendation in limited] == ["Both skills"]


@pytest.mark.unit
def test_recommendation_query_count_is_constant_as_candidates_grow():
    """DSC-010: recommendation queries stay bounded as candidates grow (no N+1)."""
    member = member_with_skill()
    for index in range(6):
        open_project(f"Candidate {index}").skills.add(skill("Django"))

    recommended_projects(member)
    with CaptureQueriesContext(connection) as small:
        recommended_projects(member)

    for index in range(6, 12):
        open_project(f"Candidate {index}").skills.add(skill("Django"))

    with CaptureQueriesContext(connection) as large:
        recommended_projects(member)

    assert len(large) == len(small)
    assert len(large) <= 10


@pytest.mark.unit
def test_projects_home_hides_legacy_recommendations_for_signed_in_member(client):
    """DSC-010: legacy identity does not expand the minimal public home surface."""
    member = member_with_skill()
    candidate = open_project("Open candidate")
    candidate.skills.add(skill("Django"))

    client.force_login(member)
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Recommended for you" not in content
    assert "Open candidate" in content
    assert "Matches your Django skill" not in content
    assert 'class="tag' in content
    assert 'aria-labelledby="recommended-heading"' not in content


@pytest.mark.unit
def test_projects_home_hides_recommendations_but_features_public_work_for_anonymous(client):
    """DSC-001/DSC-010/BR-004: anonymous visitors see public work, never matching reasons."""
    candidate = open_project("Open candidate")
    candidate.skills.add(skill("Django"))

    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Recommended for you" not in content
    assert "Open candidate" in content
    assert "Matches your Django skill" not in content
