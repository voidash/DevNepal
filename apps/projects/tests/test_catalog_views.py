import re
import unicodedata
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone, translation

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
    assert "featured_community_projects" not in response.context
    assert "platform_metrics" not in response.context
    assert community.title_en.encode() not in response.content
    assert paused.title_en.encode() not in response.content


@pytest.mark.unit
def test_home_featured_projects_lead_with_the_work_not_repeated_status(client):
    """DSC-001/GOV-011: featured official cards name the ministry and the work."""
    featured = make_public_project(title_en="Featured civic service", published_at=timezone.now())

    response = client.get(reverse("projects:home"))
    section = (
        response.content.split(b'aria-labelledby="opportunities-heading"', 1)[1]
        .split(b'aria-labelledby="safeguards-heading"', 1)[0]
        .decode()
    )

    assert featured.title_en in section
    assert "Official" in section
    assert "See all government projects" in section
    assert "Open for contribution" not in section
    assert "dn-featured-card__facts" in section


@pytest.mark.unit
def test_home_does_not_promote_community_projects_on_the_visitor_entry(client):
    """DSC-001/GOV-011: first-time visitors see government work, not secondary catalogs."""
    make_public_project(
        project_type=ProjectType.PERSONAL,
        ministry=None,
        title_en="Community work that is not official",
        published_at=timezone.now(),
    )

    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Community projects" not in content
    assert "Browse community projects" not in content
    assert "Community work that is not official" not in content
    assert reverse("projects:community") not in content

    community_catalogue = client.get(reverse("projects:community"))
    community_content = community_catalogue.content.decode()
    assert community_catalogue.status_code == 200
    assert "Community projects" in community_content
    assert "do not carry government endorsement" in community_content
    assert "Community work that is not official" in community_content


@pytest.mark.unit
def test_home_does_not_leak_community_owner_data_into_the_government_entry(client):
    """DSC-001/GOV-011: hidden secondary listings do not leak owner identity on home."""
    community = make_public_project(
        project_type=ProjectType.PERSONAL,
        ministry=None,
        title_en="Valley bus timetable",
        published_at=timezone.now(),
    )

    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    assert community.title_en not in content
    assert f"@{community.owner.username}" not in content
    assert reverse("projects:detail", args=[community.slug]) not in content

    catalogue = client.get(reverse("projects:community"))
    catalogue_section = (
        catalogue.content.decode().split('class="dn-catalog-results', 1)[1].split("</main>", 1)[0]
    )
    assert community.title_en in catalogue_section
    assert "Community project" in catalogue_section
    assert "Official" not in catalogue_section
    assert reverse("projects:detail", args=[community.slug]) in catalogue_section


@pytest.mark.unit
def test_home_keeps_legacy_member_directory_off_the_visitor_entry(client):
    """MEM-003/REC-001: member records remain stored without expanding the demo home."""
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
    # Opting out of the leaderboard must not remove someone from the directory.
    still_listed = MemberProfileFactory(
        headline="Leaderboard opted out",
        directory_discoverable=True,
        leaderboard_opt_out=True,
    )

    response = client.get(reverse("projects:home"))
    content = response.content.decode()
    assert visible.user.username not in content
    assert visible.headline not in content
    assert hidden.user.username not in content
    assert still_listed.headline not in content
    assert reverse("accounts:member_directory") not in content

    directory = client.get(reverse("accounts:member_directory"))
    directory_content = directory.content.decode()
    assert visible.user.username in directory_content
    assert visible.headline in directory_content
    assert reverse("accounts:public_profile", args=[visible.user.username]) in directory_content
    assert hidden.user.username not in directory_content
    assert still_listed.user.username in directory_content
    assert "points" not in directory_content.lower()


@pytest.mark.unit
def test_home_keeps_technical_writing_off_the_minimal_visitor_entry(client):
    """BLG-005/DSC-001: blog records remain available without competing with open work."""
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
    content = response.content.decode()
    assert published.title not in content
    assert published.excerpt not in content
    assert reverse("blogs:detail", args=[published.pk]) not in content
    assert reverse("blogs:list") not in content

    blog_index = client.get(reverse("blogs:list"))
    blog_content = blog_index.content.decode()
    assert published.title in blog_content
    assert reverse("blogs:detail", args=[published.pk]) in blog_content
    assert "Draft that must stay private" not in blog_content
    assert "Restricted post" not in blog_content


@pytest.mark.unit
def test_home_states_listing_boundaries_and_links_to_full_guidance(client):
    """DSC-001/GOV-007: the compact home states its boundary and links to details."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert "What DevNepal verifies" in content
    assert 'aria-labelledby="safeguards-heading"' in content
    assert reverse("projects:about") in content
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
    assert b"Built in public." in response.content
    assert b"public repository on GitHub" in response.content
    assert b"anyone can contribute" in response.content
    assert b"Browse government projects" in response.content
    assert b"Government of Nepal" in response.content
    assert b"Collaborate on Nepal's digital future" not in response.content


@pytest.mark.unit
def test_home_exposes_compact_live_metrics_and_the_github_contribution_path(client):
    """DSC-001/GOV-011: home keeps Madan's metric and journey design without extra products."""
    response = client.get(reverse("projects:home"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "On DevNepal today" not in content
    assert "From public project to GitHub contribution" in content
    assert "A named officer publishes" in content
    assert "You pick an issue" in content
    assert "You contribute on GitHub" in content
    assert "Nine ways to contribute" in content
    assert "Community projects" not in content
    assert "People in the directory" not in content
    assert "Technical writing" not in content
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
    assert b'href="/en/issues/"' in english.content
    assert reverse("projects:community").encode() not in english.content
    assert reverse("accounts:member_directory").encode() not in english.content
    assert b'aria-labelledby="about-heading"' in english.content
    assert b'class="dn-container dn-doc-layout dn-doc-layout--wide"' in english.content
    assert b'class="dn-doc-main"' in english.content
    assert nepali.status_code == 200
    assert "कसरी योगदान गर्ने" in nepali.content.decode()


@pytest.mark.unit
def test_about_page_keeps_the_numbered_process_and_the_policy_sheet(client):
    """A1.2/DSC-001/GOV-007: public guidance makes process and reporting scannable."""
    response = client.get(reverse("projects:about"))

    content = response.content.decode()
    assert response.status_code == 200
    safety = content.split('id="safety"', 1)[1].split("</section>", 1)[0]

    assert "blueprint dn-sheet" in safety
    assert "01 · The process" in content
    assert "A ministry lists a project" in content
    assert "You contribute" in content
    assert "Work is verified and recognised" in content
    assert "What DevNepal is — and is not" in content
    assert "Security and reporting" in content
    assert "Report content confidentially" in content


@pytest.mark.unit
def test_about_page_walks_three_numbered_steps_without_the_pmo_gate(client):
    """A1.2/DSC-001: the published contribution path is an ordered list of three steps."""
    english = client.get(reverse("projects:about"))
    nepali = client.get("/ne/about/")

    content = english.content.decode()
    process = content.split('<ol class="dn-journey">', 1)[1].split("</ol>", 1)[0]

    assert english.status_code == 200
    assert nepali.status_code == 200
    assert process.count('class="dn-journey-step"') == 3
    assert re.findall(r'<span class="Counter">(\d+)</span>', process) == ["1", "2", "3"]
    assert "PMO approves" not in content
    assert "PMO approves" not in nepali.content.decode()
    assert "{% trans" not in content


@pytest.mark.unit
def test_about_page_routes_and_labels_point_at_destinations_that_exist(client):
    """A1.2/NFR-A11Y-01: route cards and section labels reference real targets."""
    response = client.get(reverse("projects:about"))
    content = response.content.decode()
    article = content.split("dn-doc-layout--wide", 1)[1].split("</main>", 1)[0]
    routes = re.findall(r'<a class="dn-route" href="([^"]+)"', article)
    headings = [int(level) for level in re.findall(r"<h([1-6])[ >]", article)]
    identifiers = re.findall(r'\sid="([^"]+)"', content)

    assert response.status_code == 200
    assert routes == [
        reverse("projects:government"),
        reverse("projects:issue_index"),
    ]
    for route in routes:
        assert client.get(route).status_code == 200, route
    assert f'href="{reverse("moderation:report_create")}"' in article
    assert len(identifiers) == len(set(identifiers))
    referenced = {
        idref
        for attribute in re.findall(r'aria-labelledby="([^"]+)"', content)
        for idref in attribute.split()
    }
    assert referenced <= set(identifiers)
    assert headings[0] == 1
    assert all(later - earlier <= 1 for earlier, later in pairwise(headings))


@pytest.mark.unit
def test_about_page_serves_the_redesigned_guidance_in_nepali(client):
    """NFR-I18N-01: the rebuilt about sections reach Nepali readers translated."""
    response = client.get("/ne/about/")

    content = response.content.decode()

    assert response.status_code == 200
    assert '<html lang="ne"' in content
    assert "तीन चरण, प्रत्येकका लागि एक नामित पक्ष उत्तरदायी हुन्छ।" in content
    assert "देवनेपाल के हो — र के होइन" in content
    assert "०५ · कहाँबाट सुरु गर्ने" in content
    assert "Three steps, each with a named party" not in content
    assert "Where to start" not in content


@pytest.mark.unit
def test_about_page_strings_are_all_present_in_the_compiled_nepali_catalog():
    """NFR-I18N-01: the shipped django.mo covers every string the about page renders.

    A .po edited without recompiling leaves the Nepali page silently English, and a
    msgid that drifts from the template by one character does the same.
    """
    template = (Path(settings.BASE_DIR) / "apps/projects/templates/projects/about.html").read_text()
    strings = [
        double or single
        for double, single in re.findall(
            r"{%\s*(?:trans|translate)\s+(?:\"(.*?)\"|'(.*?)')", template
        )
    ]

    assert strings
    with translation.override("ne"):
        untranslated = [source for source in strings if translation.gettext(source) == source]
    assert untranslated == []


@pytest.mark.unit
def test_journey_track_follows_its_step_count_instead_of_a_fixed_four_columns():
    """DSC-001: the shared journey component fits three steps and four alike."""
    css = (Path(settings.BASE_DIR) / "static/src/devnepal.css").read_text()
    home = (Path(settings.BASE_DIR) / "apps/projects/templates/projects/home.html").read_text()
    about = (Path(settings.BASE_DIR) / "apps/projects/templates/projects/about.html").read_text()
    track = css.split("\n.dn-journey { ", 1)[1].split("}", 1)[0]

    assert "grid-auto-flow: column;" in track
    assert "grid-auto-columns: minmax(0, 1fr);" in track
    assert "grid-template-columns: none;" in track
    assert "repeat(4," not in track
    assert css.count(".dn-journey { grid-auto-flow: row;") == 2
    assert home.count('class="dn-journey-step"') == 4
    assert about.count('class="dn-journey-step"') == 3


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
    assert "fetch(" in script
    assert "DOMParser" in script
    assert "history.pushState" in script
    assert "popstate" in script
    assert "event.preventDefault()" in script
    assert "AbortController" in script
    assert "incoming?.abort()" in script
    assert "window.location.assign(url)" in script
    assert 'closest(".dn-catalog-results")' in script
    # Back must swap, not reload: loadCatalog coerces whatever it is handed
    # into a URL, because a bare string has no .searchParams and used to
    # throw straight into the full-navigation fallback.
    assert "loadCatalog(window.location.href, { push: false })" in script
    assert "target instanceof URL ? target : new URL(String(target)" in script
    assert 'credentials: "same-origin"' in script
    assert 'headers: { Accept: "text/html" }' in script
    assert "catalog.replaceWith(next)" in script
    assert "enhance(next)" in script
    assert "new FormData(form)" in script
    assert "url.origin === window.location.origin" in script
    assert "url.pathname === window.location.pathname" in script
    assert "event.button !== 0" in script
    assert "event.metaKey || event.ctrlKey || event.shiftKey || event.altKey" in script
    assert 'history.pushState({}, "", url)' in script
    assert 'element.getAttribute("href") === focusHref' in script
    assert 'next.querySelector("#projects-heading")' in script
    catalog = (
        Path(settings.BASE_DIR) / "apps/projects/templates/projects/project_list.html"
    ).read_text()
    results_open = catalog.index(
        '<div class="dn-catalog-results dn-catalog-results--{{ layout }}">'
    )
    endfor = catalog.index("{% endfor %}", results_open)
    results_close = catalog.index("</div>", endfor)
    pagination = catalog.index('class="pagination dn-catalog-pagination"', results_close)
    assert "{% url 'projects:detail' project.slug %}" in catalog[results_open:results_close]
    assert pagination > results_close


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
def test_application_project_with_a_public_repository_starts_only_on_github(client):
    """DSC-001/DSC-005: a public repository remains usable without member application UI."""
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
    assert "Sign in to apply" not in content
    assert "Open tasks" not in content
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
def test_application_project_detail_hides_the_retired_member_application_flow(client):
    """DSC-005/DSC-006: application records do not expose a contributor account flow."""
    project = make_public_project(contribution_mode=ContributionMode.APPLICATION)
    ProjectTaskFactory(project=project, title="Task reserved for assignment")

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert "Sign in to apply" not in content
    assert "Open tasks" not in content
    assert "Task reserved for assignment" not in content


@pytest.mark.unit
def test_hybrid_project_detail_shows_open_tasks_without_member_application(client):
    """DSC-005: hybrid records expose GitHub work without a contributor account flow."""
    project = make_public_project(contribution_mode=ContributionMode.HYBRID)
    task = ProjectTaskFactory(project=project, title="Improve search labels")

    response = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    content = response.content.decode()
    assert response.status_code == 200
    assert list(response.context["open_tasks"]) == [task]
    assert "Hybrid (open tasks and application workstreams)" in content
    assert "Improve search labels" in content
    assert "Choose a task" in content
    assert "Sign in to apply" not in content


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
    assert "Sign in to apply" not in content
