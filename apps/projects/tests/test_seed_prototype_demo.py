import io

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import MemberProfile, User
from apps.blogs.enums import BlogPostType, BlogStatus
from apps.blogs.models import BlogPost
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.github_sync.models import GithubRepositoryContributor, GithubStarterTask
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.projects.enums import ProjectStatus, ProjectType
from apps.projects.models import Project, ProjectTask
from apps.recognition.enums import AwardStatus
from apps.recognition.models import Badge, BadgeAward, ScoringPolicy

pytestmark = pytest.mark.django_db


def test_seed_prototype_demo_creates_a_rich_public_demo_without_credentials(client):
    """DSC-001/GOV-004/BLG-004/REC-002: the prototype demo seeds valid public records safely."""
    out = io.StringIO()

    call_command("seed_prototype_demo", stdout=out)

    assert MinistryOrganization.objects.filter(status=OrgStatus.ACTIVE).count() >= 2
    assert MinistryPublisher.objects.filter(status=PublisherStatus.ACTIVE).exists()
    assert Project.objects.filter(
        slug="sewa-portal-accessibility-remediation",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
        current_version__isnull=False,
    ).exists()
    sewa = Project.objects.get(slug="sewa-portal-accessibility-remediation")
    assert sewa.deadline.isoformat() == "2026-11-30"
    assert sewa.maintainer_assignments.filter(user__first_name="Rajan").exists()
    assert sewa.maintainer_assignments.filter(user__first_name="Sabina").exists()
    assert Project.objects.filter(
        title_en="Unified Local Address Schema",
        ministry__abbreviation="MoFAGA",
        summary_en=(
            "An open JSON schema and validation library for addresses across all 753 local "
            "levels, wards and tole names."
        ),
    ).exists()
    assert Project.objects.filter(
        title_en="Health Facility Registry API",
        ministry__abbreviation="MoHP",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ).exists()
    open_government_projects = Project.objects.filter(
        project_type=ProjectType.GOVERNMENT,
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    )
    assert open_government_projects.count() == 6
    assert set(
        open_government_projects.filter(
            slug__in={
                "government-service-knowledge-engine",
                "constitution-of-nepal-open-data",
                "nepali-sign-language-research-portal",
            }
        ).values_list("repository_url", flat=True)
    ) == {
        "https://github.com/voidash/previllage",
        "https://github.com/voidash/civic-nepal",
        "https://github.com/voidash/nepali-sign-language-research",
    }
    home = client.get(reverse("projects:home"))
    assert home.status_code == 200
    assert len(list(home.context["featured_projects"])) == 6
    featured_section = home.content.decode().split('class="dn-featured-grid"', 1)[1]
    assert featured_section.count("dn-featured-card__head") == 6
    assert Project.objects.filter(
        slug="sajhabus-timetable",
        status=ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ).exists()
    assert Project.objects.filter(
        title_en="NepaliDate.js",
        owner__first_name="Aarati",
        ownership_verification="verified_github",
    ).exists()
    assert Project.objects.filter(
        title_en="Bhasha OCR",
        owner__first_name="Prakash",
        ownership_verification="verified_github",
    ).exists()
    assert Project.objects.filter(
        title_en="Ropani ↔ m² Converter",
        owner__first_name="Nisha",
        ownership_verification="unverified",
    ).exists()
    assert Project.objects.filter(
        slug="sewa-portal-accessibility-completed",
        status=ProjectStatus.COMPLETED,
        outcome_summary__gt="",
    ).exists()
    assert ProjectTask.objects.filter(
        project__slug="sewa-portal-accessibility-remediation"
    ).exists()
    starter_issue_numbers = list(
        GithubStarterTask.objects.filter(
            repository__project__slug="sewa-portal-accessibility-remediation"
        )
        .values_list("number", flat=True)
        .order_by("number")
        .distinct()
    )
    assert starter_issue_numbers == [7, 8, 9, 11, 13]
    people = GithubRepositoryContributor.objects.filter(
        repository__project__slug="sewa-portal-accessibility-remediation"
    )
    assert people.count() >= 1
    assert people.exclude(avatar_url="").count() == people.count()
    for login, avatar_url in people.values_list("login", "avatar_url"):
        assert avatar_url == f"https://avatars.githubusercontent.com/{login}?s=80&v=4"
    assert MemberProfile.objects.filter(directory_discoverable=True).count() >= 2
    assert User.objects.get(username="kritika-poudel").skills.exists()
    assert MemberProfile.objects.get(user__first_name="Bibek").headline == (
        "Backend engineer · Go and PostgreSQL"
    )
    assert MemberProfile.objects.get(user__first_name="Sujata").location == "Lalitpur"
    assert MemberProfile.objects.get(user__first_name="Prakash").headline == (
        "ML engineer · Devanagari OCR"
    )
    assert MemberProfile.objects.get(user__first_name="Nisha").location == "Bhaktapur"
    assert BlogPost.objects.filter(
        post_type=BlogPostType.NATIVE, status=BlogStatus.PUBLISHED
    ).exists()
    assert BlogPost.objects.filter(
        post_type=BlogPostType.EXTERNAL, status=BlogStatus.PUBLISHED
    ).exists()
    assert ContributionRecord.objects.filter(status=VerificationStatus.ACCEPTED).count() >= 2
    assert ScoringPolicy.objects.filter(is_active=True).exists()
    assert Badge.objects.filter(is_active=True).exists()
    assert BadgeAward.objects.filter(status=AwardStatus.ACTIVE).exists()
    assert User.objects.get(username="demo-pmo-admin").has_usable_password() is False
    assert User.objects.get(username="kritika-poudel").has_usable_password() is False
    assert "Seeded prototype demo" in out.getvalue()


def test_seed_prototype_demo_is_idempotent_and_preserves_the_active_policy():
    """GOV-005/GIT-005/REC-002: rerunning does not duplicate records or replace policy."""
    call_command("seed_prototype_demo")
    policy = ScoringPolicy.objects.get(is_active=True)
    before = {
        "projects": Project.objects.count(),
        "tasks": ProjectTask.objects.count(),
        "starter_tasks": GithubStarterTask.objects.count(),
        "posts": BlogPost.objects.count(),
        "contributions": ContributionRecord.objects.count(),
        "awards": BadgeAward.objects.count(),
    }

    call_command("seed_prototype_demo")

    assert ScoringPolicy.objects.get(is_active=True).pk == policy.pk
    assert {
        "projects": Project.objects.count(),
        "tasks": ProjectTask.objects.count(),
        "starter_tasks": GithubStarterTask.objects.count(),
        "posts": BlogPost.objects.count(),
        "contributions": ContributionRecord.objects.count(),
        "awards": BadgeAward.objects.count(),
    } == before
