import unicodedata
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import MemberProfileFactory
from apps.blogs.enums import BlogModerationState, BlogStatus
from apps.blogs.tests.factories import BlogPostFactory
from apps.github_sync.models import GithubStarterTask
from apps.github_sync.tests.factories import RepositoryConnectionFactory
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
    ProjectSuitabilityFactory,
    ProjectTaskFactory,
    ProjectVersionFactory,
    UserFactory,
)
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.tests.factories import SkillFactory, TaxonomyTermFactory

pytestmark = pytest.mark.django_db


def make_public_project(**kwargs):
    kwargs.setdefault("status", ProjectStatus.OPEN_FOR_CONTRIBUTION)
    project = ProjectFactory(**kwargs)
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
    assert community not in response.context["featured_projects"]
    assert community in response.context["featured_community_projects"]
    assert paused.title_en.encode() not in response.content


@pytest.mark.unit
def test_home_featured_projects_lead_with_the_work_not_repeated_status(client):
    """DSC-001/GOV-011: featured official cards name the ministry and the work."""
    featured = make_public_project(title_en="Featured civic service", published_at=timezone.now())

    response = client.get(reverse("projects:home"))
    section = (
        response.content.split(b'aria-labelledby="opportunities-heading"', 1)[1]
        .split(b'aria-labelledby="community-heading"', 1)[0]
        .decode()
    )

    assert featured.title_en in section
    assert "Official" in section
    assert "See all government projects" in section
    assert "Open for contribution" not in section
    assert "dn-featured-card__facts" in section


@pytest.mark.unit
def test_home_community_sheet_puts_the_catalog_exit_in_the_header(client):
    """DSC-001/GOV-011: community listings keep one catalog exit and no endorsement chrome."""
    make_public_project(
        project_type=ProjectType.PERSONAL,
        ministry=None,
        title_en="Community work that is not official",
        published_at=timezone.now(),
    )

    response = client.get(reverse("projects:home"))
    section = (
        response.content.split(b'aria-labelledby="community-heading"', 1)[1]
        .split(b'aria-labelledby="ministry-cta-heading"', 1)[0]
        .decode()
    )

    assert "Community projects" in section
    assert "Browse community projects" in section
    assert section.count("Browse community projects") == 1
    assert "never imply government endorsement" in section
    assert "not reviewed by PMO" not in section
    assert "Community work that is not official" in section


@pytest.mark.unit
def test_home_community_sheet_names_the_owner_not_a_ministry(client):
    """DSC-001/GOV-011: community rows identify the member owner and keep endorsement off."""
    community = make_public_project(
        project_type=ProjectType.PERSONAL,
        ministry=None,
        title_en="Valley bus timetable",
        published_at=timezone.now(),
    )

    response = client.get(reverse("projects:home"))
    section = (
        response.content.split(b'aria-labelledby="community-heading"', 1)[1]
        .split(b'aria-labelledby="ministry-cta-heading"', 1)[0]
        .decode()
    )

    assert community.title_en in section
    assert f"@{community.owner.username}" in section
    assert "Official" not in section
    assert reverse("projects:detail", args=[community.slug]) in section
    assert ">Owner<" in section
    assert ">Project<" in section


@pytest.mark.unit
def test_home_people_sheet_lists_discoverable_members_without_scores(client):
    """MEM-003/REC-001: home shows opted-in members and never publishes a score there."""
    visible = MemberProfileFactory(
        headline="Civic accessibility reviewer",
        directory_discoverable=True,
        leaderboard_opt_out=False,
    )
    hidden = MemberProfileFactory(
        headline="Private operator",
        directory_discoverable=False,
        leaderboard_opt_out=False,
    )
    opted_out = MemberProfileFactory(
        headline="Leaderboard opted out",
        directory_discoverable=True,
        leaderboard_opt_out=True,
    )

    response = client.get(reverse("projects:home"))
    section = (
        response.content.split(b'aria-labelledby="people-heading"', 1)[1]
        .split(b'aria-labelledby="safeguards-heading"', 1)[0]
        .decode()
    )

    assert visible.user.username in section
    assert visible.headline in section
    assert reverse("accounts:public_profile", args=[visible.user.username]) in section
    assert hidden.user.username not in section
    assert opted_out.headline not in section
    assert "points" not in section.lower()
    assert "leaderboard" not in section.lower()


@pytest.mark.unit
def test_home_writing_sheet_lists_published_posts_only(client):
    """BLG-005/DSC-001: home writing is published public learning, never drafts."""
    published = BlogPostFactory(
        title="Shipping Nepali issue templates",
        excerpt="A maintainer note on bilingual contribution guidance.",
        status=BlogStatus.PUBLISHED,
        published_at=timezone.now(),
    )
    BlogPostFactory(title="Draft that must stay private", status=BlogStatus.DRAFT)
    BlogPostFactory(
        title="Restricted post",
        status=BlogStatus.PUBLISHED,
        published_at=timezone.now(),
        moderation_state=BlogModerationState.RESTRICTED,
    )

    response = client.get(reverse("projects:home"))
    section = (
        response.content.split(b'aria-labelledby="writing-heading"', 1)[1]
        .split(b'aria-labelledby="safeguards-heading"', 1)[0]
        .decode()
    )

    assert published.title in section
    assert published.excerpt in section
    assert reverse("blogs:detail", args=[published.pk]) in section
    assert "Draft that must stay private" not in section
    assert "Restricted post" not in section


@pytest.mark.unit
def test_home_states_publication_safeguards_before_the_ministry_cta(client):
    """DSC-001/GOV-007: an empty catalogue still explains what listing does and does not mean."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert "What DevNepal verifies" in content
    assert "What DevNepal does not promise" in content
    assert "A listing is not an employment offer" in content
    assert "How are contributions verified?" in content
    assert 'aria-labelledby="safeguards-heading"' in content
    assert 'aria-labelledby="ministry-cta-heading"' in content


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
    assert b"public repository on GitHub" in response.content
    assert b"anyone can contribute" in response.content
    assert b"Browse government projects" in response.content
    assert b"Government of Nepal" in response.content
    assert b"Collaborate on Nepal's digital future" not in response.content


@pytest.mark.unit
def test_home_exposes_the_prototype_trust_sheet_and_contribution_model(client):
    """DSC-001/GOV-011/REC-001: home reproduces the approved trust and work model."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "On DevNepal today" in content
    assert "ministries publishing, each through a named officer" in content
    assert "projects open for contribution" in content
    assert "contributions accepted by a named maintainer" in content
    assert "Public member profiles" not in content
    assert "Nine ways to contribute" in content
    assert "Writing code is one of them" in content
    assert "Community projects" in content
    assert "Browse community projects" in content
    assert "A named maintainer verifies accepted work" in content
    assert 'class="blueprint' in content


@pytest.mark.unit
def test_home_never_asks_a_visitor_for_an_account(client):
    """DSC-001/AUTH-001: contributing needs no account, so home offers none."""
    response = client.get(reverse("projects:home"))
    main = response.content.split(b"<main", 1)[1].split(b"</main>", 1)[0].decode()

    assert response.status_code == 200
    assert "no DevNepal account is needed" in main
    assert reverse("accounts:signup") not in main
    assert "Create an account" not in main
    assert "Join with GitHub" not in main
    assert reverse("accounts:login") in main
    assert "Ministry sign-in" in main


@pytest.mark.unit
def test_home_empty_state_explains_the_publication_safeguard_without_filler(client):
    """DSC-001/NFR-A11Y-01: an empty catalogue states its reason and offers the exit."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Government opportunities are being prepared." in content
    assert "a named owner, contribution guidance, and suitability review" in content
    assert 'class="dn-public-work-illustration"' not in content
    assert f'href="{reverse("projects:government")}"' in content


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
    assert "blueprint dn-sheet" in content
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
    assert 'class="dn-catalog-form catalog-filter"' in content
    assert "dn-sheet__header" not in content
    assert "Advanced filters" in content
    assert 'class="card blueprint"' in content
    assert government.title_en in content
    assert community.title_en in content
    assert "Official" in content
    assert "Community" in content
    assert ">Mode<" in content
    assert "First response" in content


@pytest.mark.unit
def test_catalog_matches_a2_1_status_sort_layout_and_active_filter_controls(client):
    """A2.1/DSC-002: real counts, sorting, layout, and reset state follow the catalog sheet."""
    older = make_public_project(
        title_en="Alpha service",
        difficulty=DifficultyLevel.BEGINNER,
        updated_at=timezone.now() - timedelta(days=2),
    )
    newer = make_public_project(
        title_en="Zulu service",
        difficulty=DifficultyLevel.INTERMEDIATE,
        updated_at=timezone.now(),
    )
    ProjectFactory(status=ProjectStatus.PAUSED)
    ProjectFactory(status=ProjectStatus.COMPLETED)

    response = client.get(
        reverse("projects:government"),
        {"sort": "title", "layout": "list", "difficulty": DifficultyLevel.BEGINNER},
    )

    assert response.status_code == 200
    assert list(response.context["projects"]) == [older]
    assert response.context["status_counts"] == {
        ProjectStatus.OPEN_FOR_CONTRIBUTION: 2,
        ProjectStatus.PAUSED: 1,
        ProjectStatus.COMPLETED: 1,
    }
    assert response.context["sort"] == "title"
    assert response.context["layout"] == "list"
    assert "difficulty=beginner" in response.context["query_string"]
    assert "sort=title" in response.context["query_string"]
    assert "layout=list" in response.context["query_string"]
    content = response.content.decode()
    assert 'class="dn-catalog-results dn-catalog-results--list"' in content
    assert "Recently updated" in content
    assert "Active filters" in content
    assert "Difficulty: Beginner" in content
    assert "Clear all" in content
    assert newer.title_en not in content

    sorted_response = client.get(
        reverse("projects:government"),
        {"q": "service", "sort": "title"},
    )
    sorted_projects = list(sorted_response.context["projects"])
    assert sorted_projects[0] == older
    assert sorted_projects[-1] == newer


@pytest.mark.unit
def test_catalog_selection_controls_apply_without_a_distant_submit_button(client):
    """A2.1/DSC-002/NFR-A11Y-01: catalog choices apply immediately with a no-JS fallback."""
    response = client.get(reverse("projects:community"))

    content = response.content.decode()
    assert response.status_code == 200
    for field_name in (
        "sort",
        "contribution_type",
        "technology",
        "skill",
        "difficulty",
        "effort",
        "status",
        "language",
    ):
        assert f'name="{field_name}" data-auto-submit' in content
    assert 'src="/static/src/catalog-controls.js?v=' in content
    assert "onchange=" not in content
    assert '<button class="btn btn--secondary" type="submit">Apply filters</button>' in content
    script = (Path(settings.BASE_DIR) / "static/src/catalog-controls.js").read_text()
    assert 'querySelectorAll("[data-auto-submit]")' in script
    assert 'addEventListener("change"' in script
    assert "form.requestSubmit()" in script


@pytest.mark.unit
def test_catalog_keeps_search_simple_and_the_filter_rail_in_view(client):
    """DSC-001/DSC-002: search stays a single field while the filters stay visible beside it."""
    response = client.get(reverse("projects:government"))
    content = response.content.decode()

    toolbar = content.split('<div class="dn-catalog-toolbar">', 1)[1].split("</div>", 1)[0]
    rail = content.split('<details class="dn-catalog-filters" open>', 1)[1]
    filters = rail.split("</details>", 1)[0]

    assert 'name="q"' in toolbar
    assert 'name="sort"' not in toolbar
    assert 'name="layout"' not in toolbar
    assert 'name="technology"' in filters
    assert 'name="deadline_from"' in filters
    assert 'name="difficulty"' in filters


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
    assert "View open issues" in content
    assert "View on GitHub" in content
    assert "Contributing needs no DevNepal account." in content
    assert "Sign in to apply" not in content
    assert content.index("View open issues") < content.index("Project sheet")
    assert content.index("Open tasks") < content.index("Project sheet")
    assert "Suitability checklist not started" not in content


@pytest.mark.unit
def test_direct_project_detail_without_a_repository_still_offers_a_task_without_signin(
    client,
):
    """DSC-001/DSC-005: direct work can start from published tasks with no DevNepal account."""
    project = make_public_project(contribution_mode=ContributionMode.OPEN_DIRECT)
    ProjectTaskFactory(project=project, title="Document the first API call")

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Choose a task" in content
    assert 'href="#open-tasks"' in content
    assert "Sign in to apply" not in content
    assert content.index("Choose a task") < content.index("Project sheet")


@pytest.mark.unit
def test_published_project_sheet_omits_unpublished_suitability_process(client):
    """DSC-009: public pages do not expose unpublished suitability checklist chrome."""
    project = make_public_project(contribution_mode=ContributionMode.OPEN_DIRECT)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Suitability checklist not started" not in content
    assert "Repository visibility and issue data are checked before publication." not in content


@pytest.mark.unit
def test_published_project_sheet_names_confirmed_suitability(client):
    """DSC-009/BR-002: confirmed suitability is the only suitability state shown publicly."""
    project = make_public_project(contribution_mode=ContributionMode.OPEN_DIRECT)
    ProjectSuitabilityFactory(project=project, confirmed=True)

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Suitability confirmed" in content
    assert "Suitability checklist not started" not in content


@pytest.mark.unit
def test_application_project_with_a_public_repository_still_starts_on_github(client):
    """DSC-001/DSC-005: a controlled workstream does not block GitHub contribution."""
    project = make_public_project(
        contribution_mode=ContributionMode.APPLICATION,
        repository_url="https://github.com/moit/controlled-workstream",
        issue_tracker_url="https://github.com/moit/controlled-workstream/issues",
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "View open issues" in content
    assert "View on GitHub" in content
    assert "Contributing needs no DevNepal account." in content
    assert "Application required" in content
    assert "Sign in to apply" in content
    assert "Open tasks" not in content
    assert content.index("View open issues") < content.index("Sign in to apply")
    assert content.index("View open issues") < content.index("Project sheet")


@pytest.mark.unit
def test_completed_project_detail_leads_with_the_public_record(client):
    """GOV-011: completed listings are a public record, not an open call to apply."""
    project = make_public_project(
        status=ProjectStatus.COMPLETED,
        contribution_mode=ContributionMode.APPLICATION,
        repository_url="https://github.com/doit-np/sewa-portal",
        issue_tracker_url="https://github.com/doit-np/sewa-portal/issues",
        outcome_summary="Keyboard and bilingual recovery now meet WCAG 2.2 AA.",
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "View on GitHub" in content
    assert "Completion summary" in content
    assert "View open issues" not in content
    assert "Choose an issue" not in content
    assert "Sign in to apply" not in content
    assert "Apply to contribute" not in content
    assert content.index("Completion summary") < content.index("Project sheet")


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
    assert "blueprint dn-sheet" in content
    assert "Project sheet" in content
    assert "Maintainers" in content
    assert first.user.username in content
    assert second.user.username in content
    assert "How to join" in content
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
    assert "Choose a task" in content
    assert "Sign in to apply" in content
    assert content.index("Choose a task") < content.index("Sign in to apply")


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


@pytest.mark.unit
def test_public_project_displays_only_persisted_github_starter_task_snapshot(client):
    """DSC-009/GIT-010: public task hand-off is DB-only, labelled, and freshness-labelled."""
    project = make_public_project(contribution_mode=ContributionMode.APPLICATION)
    repository = RepositoryConnectionFactory(
        project=project,
        full_name="doit-np/sewa-portal",
        is_public=True,
        task_snapshot_at=timezone.now(),
    )
    GithubStarterTask.objects.create(
        repository=repository,
        github_issue_id=131,
        number=131,
        title='Add lang="ne" to error strings',
        url="https://github.com/doit-np/sewa-portal/issues/131",
        labels=["good first issue"],
    )

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Starter tasks from GitHub" in content
    assert "doit-np/sewa-portal #131 · Add lang=&quot;ne&quot; to error strings" in content
    assert "good first issue" in content
    assert "Issue snapshot" in content
    assert "Choose an issue" in content
    assert "Contributing needs no DevNepal account." in content
    assert "Sign in to apply" in content
    assert content.index("Choose an issue") < content.index("Sign in to apply")
