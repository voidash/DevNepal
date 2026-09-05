import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.projects.enums import (
    ContributionMode,
    DifficultyLevel,
    EffortBand,
    ProjectStatus,
    ProjectType,
    TaskStatus,
)
from apps.projects.models import Project, ProjectBookmark
from apps.projects.tests.factories import (
    ProjectFactory,
    ProjectLinkFactory,
    ProjectMaintainerFactory,
    ProjectTaskFactory,
    ProjectVersionFactory,
    UserFactory,
)
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.tests.factories import SkillFactory, TaxonomyTermFactory

pytestmark = pytest.mark.django_db


def make_public_project(**kwargs):
    project = ProjectFactory(status=ProjectStatus.OPEN_FOR_CONTRIBUTION, **kwargs)
    version = ProjectVersionFactory(project=project)
    project.current_version = version
    project.save(update_fields=["current_version"])
    return project


@pytest.mark.unit
def test_public_catalog_excludes_drafts_and_lists_open_projects(client):
    """DSC-001: unauthenticated visitors can browse public projects, never drafts."""
    public_project = make_public_project()
    draft = ProjectFactory(status=ProjectStatus.DRAFT)

    response = client.get(reverse("projects:list"))

    assert response.status_code == 200
    assert public_project in response.context["projects"]
    assert draft not in response.context["projects"]


@pytest.mark.unit
def test_home_features_recent_open_government_opportunities_only(client):
    """DSC-001/GOV-011: the public home features real open official opportunities only."""
    featured = make_public_project(title_en="Featured civic service", published_at=timezone.now())
    community = make_public_project(
        project_type=ProjectType.PERSONAL,
        ministry=None,
        title_en="Community work that is not official",
        published_at=timezone.now(),
    )
    paused = ProjectFactory(
        status=ProjectStatus.PAUSED,
        title_en="Paused government work that is not featured",
    )

    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert list(response.context["featured_projects"]) == [featured]
    assert featured.title_en.encode() in response.content
    assert community.title_en.encode() not in response.content
    assert paused.title_en.encode() not in response.content


@pytest.mark.unit
def test_home_explains_the_verified_empty_state_without_inventing_opportunities(client):
    """DSC-001/GOV-011: an empty official catalog explains its publication safeguard."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert b"Government opportunities are being prepared." in response.content
    assert (
        b"only after a named owner, contribution guidance, and suitability review"
        in response.content
    )
    assert b'role="status"' in response.content


@pytest.mark.unit
def test_home_hero_sets_a_grounded_contribution_expectation(client):
    """DSC-001/GOV-007: the public home promises named ownership and a clear route, not hype."""
    response = client.get(reverse("projects:home"))

    assert response.status_code == 200
    assert b"Public technology," in response.content
    assert b"built in public." in response.content
    assert b"Code stays on GitHub" in response.content
    assert b"Browse government projects" in response.content
    assert b"Government of Nepal" in response.content
    assert b"Collaborate on Nepal's digital future" not in response.content


@pytest.mark.unit
def test_home_exposes_the_prototype_trust_sheet_and_contribution_model(client):
    """DSC-001/GOV-011/REC-001: home reproduces the approved trust and work model."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "DevNepal — platform at a glance" in content
    assert "Ministries publishing" in content
    assert "Projects open for contribution" in content
    assert "Verified contributions" in content
    assert "Code is one of nine ways in" in content
    assert "Community projects — listed by members" in content
    assert "No government endorsement" in content
    assert "Recognition counts only work accepted by a named maintainer" in content
    assert 'class="blueprint' in content
    reference_image = Path(settings.BASE_DIR) / "static/images/devnepal-hydropower-reference.jpg"
    assert reference_image.is_file()
    assert reference_image.stat().st_size == 289216
    assert 'width="1600" height="1187"' in content


@pytest.mark.unit
def test_home_empty_state_uses_a_bounded_editorial_image_without_misrepresenting_open_work(client):
    """DSC-001/NFR-A11Y-01/NFR-PERF-01: empty-state imagery is contextual, labelled, optional."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    asset = Path(settings.BASE_DIR) / "static/images/devnepal-public-work-illustrations-v1.png"
    modern_asset = (
        Path(settings.BASE_DIR) / "static/images/devnepal-public-work-illustrations-v1.webp"
    )

    assert response.status_code == 200
    assert asset.is_file()
    assert asset.stat().st_size > 0
    assert modern_asset.is_file()
    assert modern_asset.stat().st_size > 0
    assert modern_asset.stat().st_size < asset.stat().st_size
    assert 'class="dn-public-work-illustration"' in content
    assert (
        'type="image/webp" srcset="/static/images/devnepal-public-work-illustrations-v1.webp"'
        in content
    )
    assert 'src="/static/images/devnepal-public-work-illustrations-v1.png"' in content
    assert 'loading="lazy"' in content
    assert 'decoding="async"' in content
    assert 'width="1774" height="887"' in content
    assert 'alt="Eight grayscale public-service scenes' in content
    assert "Illustrated public-interest work areas, not a list of open projects." in content


@pytest.mark.unit
def test_about_page_lays_out_a_grounded_contribution_flow_in_both_languages(client):
    """DSC-001/NFR-I18N-01/NFR-A11Y-01: bilingual public how-to guidance is structured."""
    english = client.get(reverse("projects:about"))
    nepali = client.get("/ne/about/")

    assert english.status_code == 200
    assert b"How to contribute" in english.content
    assert b"Find a fit" in english.content
    assert b"Read before acting" in english.content
    assert b"Close the loop" in english.content
    assert b"What DevNepal verifies" in english.content
    assert b"Safety and reporting" in english.content
    assert b"confidential report" in english.content
    assert b"Frequently asked questions" in english.content
    assert b"How are contributions verified?" in english.content
    assert b"Support and next steps" in english.content
    assert b'aria-labelledby="about-heading"' in english.content
    assert nepali.status_code == 200
    assert "कसरी योगदान गर्ने" in nepali.content.decode()


@pytest.mark.unit
def test_about_page_uses_the_a1_2_process_and_policy_sheets(client):
    """A1.2/DSC-001/GOV-007: public guidance makes process and reporting scannable."""
    response = client.get(reverse("projects:about"))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="blueprint dn-sheet"' in content
    assert "01 · The process" in content
    assert "A ministry lists a project" in content
    assert "PMO approves" in content
    assert "You contribute" in content
    assert "Work is verified and recognised" in content
    assert "What DevNepal is — and is not" in content
    assert "Security and reporting" in content
    assert "Report content confidentially" in content


@pytest.mark.unit
def test_catalog_searches_english_and_nepali_nfc_normalized_text(client):
    """DSC-002/DSC-003: search finds English and NFC-normalized Devanagari project text."""
    english = make_public_project(title_en="Open Health Registry")
    nepali = make_public_project(title_en="Different", title_ne="नागरिक सेवा पोर्टल")
    make_public_project(title_en="Unrelated project")

    english_response = client.get(reverse("projects:list"), {"q": "health"})
    nepali_response = client.get(
        reverse("projects:list"),
        {"q": unicodedata.normalize("NFD", nepali.title_ne)},
    )

    assert list(english_response.context["projects"]) == [english]
    assert list(nepali_response.context["projects"]) == [nepali]


@pytest.mark.unit
def test_catalog_filters_by_project_type_and_status(client):
    """DSC-002: project type and lifecycle status filters narrow public catalog results."""
    government = make_public_project(project_type=ProjectType.GOVERNMENT)
    community = make_public_project(project_type=ProjectType.PERSONAL, ministry=None)
    paused = ProjectFactory(status=ProjectStatus.PAUSED)

    response = client.get(
        reverse("projects:list"),
        {"type": ProjectType.GOVERNMENT, "status": ProjectStatus.OPEN_FOR_CONTRIBUTION},
    )

    assert government in response.context["projects"]
    assert community not in response.context["projects"]
    assert paused not in response.context["projects"]


@pytest.mark.unit
def test_catalog_filters_by_all_structured_project_metadata(client):
    """DSC-002: catalog filters match ministry, taxonomy, status, effort, deadline, and language."""
    technology = TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="Django")
    contribution_type = TaxonomyTermFactory(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE,
        label="Catalog documentation",
    )
    skill = SkillFactory(name="Catalog metadata writing")
    matching = make_public_project(
        difficulty=DifficultyLevel.INTERMEDIATE,
        estimated_effort=EffortBand.MEDIUM,
        deadline=date.today() + timedelta(days=14),
    )
    matching.technologies.add(technology)
    matching.contribution_types.add(contribution_type)
    matching.skills.add(skill)
    make_public_project(
        difficulty=DifficultyLevel.BEGINNER,
        estimated_effort=EffortBand.SMALL,
        deadline=date.today() + timedelta(days=30),
    )

    response = client.get(
        reverse("projects:list"),
        {
            "ministry": matching.ministry.slug,
            "technology": technology.slug,
            "contribution_type": contribution_type.slug,
            "skill": skill.slug,
            "status": ProjectStatus.OPEN_FOR_CONTRIBUTION,
            "difficulty": DifficultyLevel.INTERMEDIATE,
            "effort": EffortBand.MEDIUM,
            "deadline_from": (date.today() + timedelta(days=7)).isoformat(),
            "deadline_to": (date.today() + timedelta(days=21)).isoformat(),
            "language": "ne",
        },
    )

    assert list(response.context["projects"]) == [matching]


@pytest.mark.unit
def test_catalog_normalizes_filter_query_input_and_ignores_invalid_deadlines(client):
    """DSC-002/DSC-003: catalog filter input is NFC-normalized and invalid dates are safe."""
    technology = TaxonomyTermFactory(
        vocabulary=TermVocabulary.TECHNOLOGY,
        label="देवनागरी प्रविधि",
    )
    project = make_public_project()
    project.technologies.add(technology)

    response = client.get(
        reverse("projects:list"),
        {
            "technology": f"  {unicodedata.normalize('NFD', technology.slug)}  ",
            "deadline_from": "not-a-date",
            "deadline_to": "2026-99-99",
        },
    )

    assert list(response.context["projects"]) == [project]
    assert response.context["filters"]["technology"] == technology.slug
    assert response.context["filters"]["deadline_from"] == ""
    assert response.context["filters"]["deadline_to"] == ""


@pytest.mark.unit
def test_catalog_exposes_accessible_supported_filters_and_preserves_them_in_pagination(client):
    """DSC-002/NFR-A11Y-01: all catalog filters are labelled and retained across pages."""
    technology = TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="Django")
    project = make_public_project(deadline=date.today() + timedelta(days=14))
    project.technologies.add(technology)
    for _ in range(24):
        matching_project = make_public_project(deadline=date.today() + timedelta(days=14))
        matching_project.technologies.add(technology)

    response = client.get(
        reverse("projects:list"),
        {
            "technology": technology.slug,
            "deadline_from": (date.today() + timedelta(days=7)).isoformat(),
        },
    )

    content = response.content.decode()
    assert 'id="technology"' in content
    assert 'for="technology"' in content
    assert 'id="deadline-from"' in content
    assert 'for="deadline-from"' in content
    assert f"technology={technology.slug}" in content
    assert "deadline_from=" in content
    assert "page=2" in content


@pytest.mark.unit
def test_catalog_uses_the_a2_1_blueprint_filter_and_project_sheet(client):
    """A2.1/DSC-002/GOV-011/PPR-003: cards preserve filters and official/community status."""
    government = make_public_project(
        contribution_mode=ContributionMode.APPLICATION,
        estimated_effort=EffortBand.MEDIUM,
    )
    community = make_public_project(
        project_type=ProjectType.PERSONAL,
        ministry=None,
        contribution_mode=ContributionMode.OPEN_DIRECT,
    )

    response = client.get(reverse("projects:list"))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="blueprint dn-sheet catalog-filter"' in content
    assert "Project catalog" in content
    assert "Filters" in content
    assert 'class="card blueprint"' in content
    assert government.title_en in content
    assert community.title_en in content
    assert "Official" in content
    assert "Community" in content
    assert "Contribution mode" in content
    assert "First response" in content


@pytest.mark.unit
def test_project_slug_is_generated_on_any_save_path_when_blank():
    """DSC-003/DSC-001: a project saved without a slug always gets a stable unique slug."""
    first = Project.objects.create(
        title_en="Neighbourhood Works",
        summary_en="Local fixes.",
        project_type="personal",
        owner=UserFactory(),
    )
    second = Project.objects.create(
        title_en="Neighbourhood Works",
        summary_en="Another ward.",
        project_type="personal",
        owner=UserFactory(),
    )

    assert first.slug == "neighbourhood-works"
    assert second.slug == "neighbourhood-works-2"
    assert reverse("projects:detail", kwargs={"slug": second.slug}) is not None


@pytest.mark.unit
def test_project_detail_resolves_nfd_nepali_slug_and_displays_official_status(client):
    """DSC-003/GOV-011: an NFC-normalized Nepali slug resolves with an official label."""
    project = make_public_project(slug="नागरिक-सेवा")

    response = client.get(
        reverse("projects:detail", kwargs={"slug": unicodedata.normalize("NFD", project.slug)})
    )

    assert response.status_code == 200
    assert response.context["project"] == project
    content = response.content.decode()
    assert "Official" in content
    assert "Label--outline" in content


@pytest.mark.unit
def test_direct_project_detail_shows_only_open_tasks_and_contribution_guidance(client):
    """DSC-005: direct projects expose actionable open tasks and their published guidance."""
    project = make_public_project(
        contribution_mode=ContributionMode.OPEN_DIRECT,
        prerequisites="Read the contribution guide before claiming a task.",
        communication_channel="https://matrix.to/#/#service-directory:matrix.org",
        repository_url="https://github.com/moit/service-directory",
        issue_tracker_url="https://github.com/moit/service-directory/issues",
        governance_model="maintainer_consensus",
        signoff_model="dco",
    )
    open_task = ProjectTaskFactory(project=project, title="Translate service labels")
    ProjectLinkFactory(
        project=project,
        label="Contribution handbook",
        url="https://docs.example.gov.np/contribute",
    )
    ProjectTaskFactory(
        project=project,
        title="Completed private task",
        status=TaskStatus.DONE,
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert list(response.context["open_tasks"]) == [open_task]
    assert "Open direct contribution" in content
    assert "Translate service labels" in content
    assert "Completed private task" not in content
    assert "Read the contribution guide before claiming a task." in content
    assert "https://matrix.to/#/#service-directory:matrix.org" in content
    assert "https://github.com/moit/service-directory" in content
    assert "Contribution handbook" in content
    assert "Maintainer consensus" in content
    assert "DCO-style sign-off" in content
    assert "Apply to contribute" not in content


@pytest.mark.unit
def test_project_detail_uses_the_a1_3_a2_2_project_sheet_with_real_accountability_data(client):
    """A1.3/A2.2/GOV-007/GOV-011: sheets disclose maintainers, route, SLA, governance, security."""
    project = make_public_project(
        contribution_mode=ContributionMode.HYBRID,
        estimated_effort=EffortBand.MEDIUM,
        governance_model="maintainer_consensus",
        signoff_model="dco",
        security_contact="security@example.gov.np",
        vulnerability_disclosure_url="https://example.gov.np/security",
        prohibited_data_statement="Do not submit personal data.",
    )
    first = ProjectMaintainerFactory(project=project, user=UserFactory(username="ramesh"))
    second = ProjectMaintainerFactory(project=project, user=UserFactory(username="sita"))
    task = ProjectTaskFactory(project=project, title="Improve accessible labels")

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert 'class="blueprint dn-sheet"' in content
    assert "Project sheet" in content
    assert "Maintainers" in content
    assert first.user.username in content
    assert second.user.username in content
    assert "Contribution mode" in content
    assert "Expected effort" in content
    assert "First response" in content
    assert "Open tasks" in content
    assert task.title in content
    assert "Governance and sign-off" in content
    assert "Security and reporting" in content
    assert "security@example.gov.np" in content
    assert "https://example.gov.np/security" in content


@pytest.mark.unit
def test_application_project_detail_shows_application_without_direct_task_section(client):
    """DSC-005/DSC-006: application projects show their controlled-workstream entry point."""
    project = make_public_project(contribution_mode=ContributionMode.APPLICATION)
    ProjectTaskFactory(project=project, title="Task reserved for assignment")

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Application required" in content
    assert "Sign in to apply" in content
    assert "Open tasks" not in content
    assert "Task reserved for assignment" not in content


@pytest.mark.unit
def test_hybrid_project_detail_shows_open_tasks_and_application(client):
    """DSC-005: hybrid projects expose both direct tasks and controlled-workstream application."""
    project = make_public_project(contribution_mode=ContributionMode.HYBRID)
    task = ProjectTaskFactory(project=project, title="Improve search labels")

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert list(response.context["open_tasks"]) == [task]
    assert "Hybrid (open tasks and application workstreams)" in content
    assert "Improve search labels" in content
    assert "Sign in to apply" in content


@pytest.mark.unit
def test_direct_project_detail_announces_when_no_open_tasks_are_available(client):
    """DSC-005/NFR-A11Y-01: direct contributors receive an accessible no-open-task state."""
    project = make_public_project(contribution_mode=ContributionMode.OPEN_DIRECT)
    ProjectTaskFactory(project=project, status=TaskStatus.IN_PROGRESS)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert not response.context["open_tasks"]
    assert 'role="status"' in content
    assert "There are no open tasks right now." in content


@pytest.mark.unit
@override_settings(LANGUAGE_CODE="ne")
def test_public_project_templates_select_nepali_project_and_ministry_content(client):
    """NFR-I18N-01: Nepali responses render available Nepali public project and ministry content."""
    project = make_public_project(
        title_en="English service directory",
        title_ne="नेपाली सेवा निर्देशिका",
        summary_en="English public service summary.",
        summary_ne="नेपाली सार्वजनिक सेवा सारांश।",
        ministry__name_en="Ministry of English Services",
        ministry__name_ne="नेपाली सेवा मन्त्रालय",
    )

    list_response = client.get(reverse("projects:list"))
    detail_response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert "नेपाली सेवा निर्देशिका" in list_response.content.decode()
    assert "नेपाली सार्वजनिक सेवा सारांश।" in list_response.content.decode()
    assert "नेपाली सेवा मन्त्रालय" in list_response.content.decode()
    assert "नेपाली सेवा निर्देशिका" in detail_response.content.decode()
    assert "नेपाली सार्वजनिक सेवा सारांश।" in detail_response.content.decode()
    assert "नेपाली सेवा मन्त्रालय" in detail_response.content.decode()


@pytest.mark.unit
@override_settings(LANGUAGE_CODE="ne")
def test_public_project_templates_fall_back_to_english_content_when_nepali_is_missing(client):
    """NFR-I18N-01: Nepali responses fall back to English public project and ministry content."""
    project = make_public_project(
        title_en="English service directory",
        title_ne="",
        summary_en="English public service summary.",
        summary_ne="",
        ministry__name_en="Ministry of English Services",
        ministry__name_ne="",
    )

    list_response = client.get(reverse("projects:list"))
    detail_response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert "English service directory" in list_response.content.decode()
    assert "English public service summary." in list_response.content.decode()
    assert "Ministry of English Services" in list_response.content.decode()
    assert "English service directory" in detail_response.content.decode()
    assert "English public service summary." in detail_response.content.decode()
    assert "Ministry of English Services" in detail_response.content.decode()


@pytest.mark.unit
def test_bookmark_toggle_requires_authentication_and_persists_member_preference(client):
    """DSC-004: members can bookmark public projects and opt into change notifications."""
    project = make_public_project()
    url = reverse("projects:bookmark", kwargs={"slug": project.slug})

    anonymous_response = client.post(url)
    assert anonymous_response.status_code == 302

    member = UserFactory()
    client.force_login(member)
    created_response = client.post(url, {"notify_on_change": ""})

    assert created_response.status_code == 302
    bookmark = ProjectBookmark.objects.get(user=member, project=project)
    assert bookmark.notify_on_change is False

    removed_response = client.post(url)

    assert removed_response.status_code == 302
    assert not ProjectBookmark.objects.filter(user=member, project=project).exists()
