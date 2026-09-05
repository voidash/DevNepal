"""End-to-end user-flow verification through the production URLconf.

These tests intentionally use the deployed root URLconf with no overrides:
a flow that 404s here is broken in the shipped product even if app-local
tests pass. Coverage follows docs/user-stories and A1-A10.
"""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import MemberProfile, MemberSkill, UserSession
from apps.blogs.enums import BlogStatus
from apps.blogs.models import BlogPost
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.contributions.tests.factories import ContributionRecordFactory, contribution_type
from apps.github_sync.enums import ProcessingState
from apps.github_sync.models import ProviderEvent
from apps.github_sync.tests.factories import (
    WEBHOOK_SECRET,
    RepositoryConnectionFactory,
    pr_merged_body,
    sign_body,
)
from apps.ministries.enums import ContactVerificationStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.ministries.services import is_publisher_active
from apps.ministries.tests.factories import MinistryPublisherFactory
from apps.moderation.enums import AppealStatus, CaseStatus, ModerationAction, ReportReason
from apps.moderation.models import Report
from apps.notifications.enums import Channel, NotificationType
from apps.notifications.models import Notification
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.models import (
    SUITABILITY_AREAS,
    Application,
    Project,
    ProjectBookmark,
)
from apps.projects.tests.factories import (
    ProjectMaintainerFactory,
    ProjectScreeningQuestionFactory,
    SuperAdminFactory,
    UserFactory,
    make_publishable,
)
from apps.recognition.models import ContributionScore
from apps.recognition.services import activate_policy
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.models import Skill, SkillSuggestion
from apps.taxonomy.tests.factories import ApprovedLicenseFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def verify_mfa(client, user):
    client.force_login(user)
    setup_url = reverse("accounts:mfa_setup")
    assert client.get(setup_url).status_code == 200
    device = TOTPDevice.objects.get(user=user)
    device.last_t = -1
    device.save(update_fields=["last_t"])
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    response = client.post(setup_url, {"token": token})
    assert response.status_code == 302


def open_project(**kwargs):
    project = make_publishable(**kwargs)
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    return project


def login(client, username, password="demo-password-2026"):  # noqa: S107
    return client.post(reverse("accounts:login"), {"username": username, "password": password})


def make_member(username="flow-member"):
    user = UserFactory(username=username)
    user.set_password("demo-password-2026")
    user.save(update_fields=["password"])
    MemberProfile.objects.create(user=user)
    return user


def verify_mfa_with_enrollment(client, user):
    device = TOTPDevice.objects.filter(user=user).first()
    if device is None:
        TOTPDevice.objects.create(user=user, name="devnepal")
    verify_mfa(client, user)


# ---------------------------------------------------------------------------
# Visitor flows


def main_content(response):
    """Return only the page body, excluding the shared shell.

    The shell greets the signed-in viewer by name, which is self-identification
    rather than a ranking disclosure, so recognition privacy assertions look at
    the page content alone (REC-003).
    """
    body = response.content
    start = body.index(b'<main id="main-content"')
    return body[start : body.index(b"</main>", start)]


@pytest.mark.unit
def test_visitor_browses_catalog_and_drafts_stay_hidden(client):
    """V1/DSC-001: approved projects are publicly visible and drafts are not."""
    visible = open_project()
    make_publishable()

    home = client.get(reverse("projects:home"))
    catalog = client.get(reverse("projects:list"))
    gov = client.get(reverse("projects:government"))
    community = client.get(reverse("projects:community"))
    detail = client.get(reverse("projects:detail", kwargs={"slug": visible.slug}))

    assert home.status_code == 200
    assert catalog.status_code == 200
    assert visible.title_en.encode() in catalog.content
    assert b"Draft project that must stay hidden" not in catalog.content
    assert gov.status_code == 200
    assert community.status_code == 200
    assert detail.status_code == 200


@pytest.mark.unit
def test_visitor_searches_in_devanagari_and_gets_the_project(client):
    """V2/DSC-002/DSC-003: Devanagari search matches the Nepali title."""
    project = open_project(title_ne="डिजिटल सेवा निर्देशिका")

    response = client.get(reverse("projects:list"), {"q": "डिजिटल"})

    assert response.status_code == 200
    assert project.title_en.encode() in response.content


@pytest.mark.unit
def test_visitor_views_public_profile_without_private_data(client):
    """V3/MEM-005: legacy profile fields stay off the GitHub-only public page."""
    user = make_member("profiled-member")
    profile = MemberProfile.objects.get(user=user)
    profile.headline = "Civic technologist"
    profile.location = "Kathmandu"
    profile.field_visibility = {"location": "public"}
    profile.save()

    response = client.get(reverse("accounts:public_profile", kwargs={"username": user.username}))

    assert response.status_code == 200
    assert b"Civic technologist" not in response.content
    assert b"Kathmandu" not in response.content
    assert b"has not shared a GitHub profile" in response.content
    assert b"@example.com" not in response.content


@pytest.mark.unit
def test_visitor_discovers_an_opted_in_member_and_follows_public_work(client):
    """MEM-003/MEM-005/BLG-005: discovery and blogs remain separate from GitHub profiles."""
    user = make_member("directory-profile-member")
    user.email = "directory-private@example.com"
    user.save(update_fields=["email"])
    profile = MemberProfile.objects.get(user=user)
    profile.headline = "Open public-service contributor"
    profile.directory_discoverable = True
    profile.field_visibility = {"skills": "public"}
    profile.save()
    skill = Skill.objects.create(name="Public service design", slug="public-service-design")
    MemberSkill.objects.create(user=user, skill=skill)
    post = BlogPost.objects.create(
        author=user,
        title="Designing useful public services",
        canonical_url="https://example.com/public-service-design",
        status=BlogStatus.PUBLISHED,
        published_at=timezone.now(),
    )
    ContributionRecordFactory(contributor=user, status=VerificationStatus.ACCEPTED)

    directory = client.get(reverse("accounts:member_directory"), {"q": skill.name})
    public_profile = client.get(
        reverse("accounts:public_profile", kwargs={"username": user.username})
    )
    blog = client.get(reverse("blogs:detail", kwargs={"post_id": post.pk}))

    assert directory.status_code == 200
    assert user.username.encode() in directory.content
    assert skill.name.encode() in directory.content
    assert public_profile.status_code == 200
    assert post.canonical_url.encode() not in public_profile.content
    assert b"verified contribution" not in public_profile.content
    assert user.email.encode() not in public_profile.content
    assert (
        f"/en/reports/new/?content_type={ContentType.objects.get_for_model(user).pk}"
        f"&amp;object_id={user.pk}"
    ).encode() in public_profile.content
    assert blog.status_code == 200
    assert blog.context["post"] == post


@pytest.mark.unit
def test_login_page_is_reachable_and_localized(client):
    """V9/AUTH-001: the sign-in entry point resolves under the localized root."""
    response = client.get(reverse("accounts:login"))

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Member flows


@pytest.mark.unit
def test_member_signs_in_and_reaches_the_dashboard(client):
    """M1/AUTH-001: password sign-in lands on the member dashboard."""
    user = make_member("signing-member")

    response = login(client, user.username)
    dashboard = client.get(reverse("accounts:dashboard"))

    assert response.status_code == 302
    assert dashboard.status_code == 200


@pytest.mark.unit
def test_member_edits_previews_and_publishes_profile_changes(client):
    """M6/MEM-002/MEM-008: legacy profile edits do not leak into the GitHub-only page."""
    user = make_member("editing-member")
    login(client, user.username)
    payload = {
        "headline": "Open-source cartographer",
        "bio": "Maps for public services.",
        "visibility_location": "private",
    }

    preview = client.post(reverse("accounts:profile_preview"), payload)
    saved = client.post(reverse("accounts:profile_edit"), payload)
    public = client.get(reverse("accounts:public_profile", kwargs={"username": user.username}))

    profile = MemberProfile.objects.get(user=user)
    assert preview.status_code == 200
    assert b"Open-source cartographer" in preview.content
    assert saved.status_code == 302
    assert profile.headline == "Open-source cartographer"
    assert b"Open-source cartographer" not in public.content
    assert b"has not shared a GitHub profile" in public.content


@pytest.mark.unit
def test_member_lists_revokes_and_relists_sessions(client):
    """M4/AUTH-007: session ledger lists devices and revocation is owner-scoped."""
    user = make_member("sessioned-member")
    login(client, user.username)
    stale = UserSession.objects.create(user=user, session_key="stale-device-key")

    listing = client.get(reverse("accounts:session_list"))
    revoked = client.post(reverse("accounts:session_revoke", kwargs={"pk": stale.pk}))
    foreign = client.post(
        reverse(
            "accounts:session_revoke",
            kwargs={
                "pk": UserSession.objects.create(user=UserFactory(), session_key="other-key").pk
            },
        )
    )

    stale.refresh_from_db()
    assert listing.status_code == 200
    assert revoked.status_code == 302
    assert foreign.status_code == 404
    assert stale.revoked_at is not None


@pytest.mark.unit
def test_member_exports_their_data_as_json(client):
    """M5/AUTH-010: the privacy export returns the member's own data."""
    user = make_member("exporting-member")
    login(client, user.username)

    response = client.get(reverse("accounts:privacy_export"))

    payload = json.loads(response.content)
    assert response.status_code == 200
    assert payload["account"]["username"] == user.username


@pytest.mark.unit
def test_member_manages_a_personal_project_through_the_ui(client):
    """M11/PPR-001/PPR-002/PPR-006: create, accept terms, publish, unpublish an owned listing."""
    user = make_member("builder-member")
    login(client, user.username)

    created = client.post(
        reverse("projects:community_create"),
        {
            "title_en": "Transit Companion",
            "title_ne": "सार्वजनिक यातायात सहायक",
            "summary_en": "Neighbourhood transit companion.",
            "summary_ne": "स्थानीय यातायात सहायक।",
        },
    )
    project = Project.objects.get(title_en="Transit Companion")
    terms = client.post(reverse("projects:community_accept_terms"))
    published = client.post(
        reverse("projects:community_workflow", kwargs={"slug": project.slug}),
        {"action": "publish"},
    )
    hidden_check = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))
    unpublished = client.post(
        reverse("projects:community_workflow", kwargs={"slug": project.slug}),
        {"action": "unpublish"},
    )
    after_unpublish = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert created.status_code == 302
    assert terms.status_code == 302
    assert published.status_code == 302
    assert hidden_check.status_code == 200
    assert unpublished.status_code == 302
    assert after_unpublish.status_code == 404
    republished = client.post(
        reverse("projects:community_workflow", kwargs={"slug": project.slug}),
        {"action": "publish"},
    )
    assert republished.status_code == 302


@pytest.mark.unit
def test_member_bookmarks_an_open_project(client):
    """M14/DSC-004: bookmarking an open project succeeds and redirects back."""
    project = open_project(contribution_mode=ContributionMode.OPEN_DIRECT)
    user = make_member("bookmarker")
    login(client, user.username)

    response = client.post(
        reverse("projects:bookmark", kwargs={"slug": project.slug}),
        {"notify_on_change": "on"},
    )

    assert response.status_code == 302
    assert project.bookmarks.filter(user=user, notify_on_change=True).exists()


@pytest.mark.unit
def test_member_applies_tracks_and_withdraws_an_application(client):
    """M15-M18/DSC-005..DSC-008: apply, review status, timeline, then withdraw."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)
    question = ProjectScreeningQuestionFactory(project=project, question="Hours per week?")
    user = make_member("applicant")
    login(client, user.username)

    applied = client.post(
        reverse("projects:apply", kwargs={"slug": project.slug}),
        {
            "motivation": "I can help every weekend.",
            f"answer_{question.pk}": "Eight hours",
        },
    )
    application = Application.objects.get(project=project, applicant=user)
    listing = client.get(reverse("projects:application_list"))
    detail = client.get(
        reverse("projects:application_detail", kwargs={"application_id": application.pk})
    )
    timeline = client.get(
        reverse("projects:application_timeline", kwargs={"application_id": application.pk})
    )
    withdrawn = client.post(
        reverse("projects:application_withdraw", kwargs={"application_id": application.pk})
    )

    application.refresh_from_db()
    assert applied.status_code == 302
    assert listing.status_code == 200
    assert detail.status_code == 200
    assert timeline.status_code == 200
    assert withdrawn.status_code == 302
    assert application.status == "withdrawn"


@pytest.mark.unit
def test_member_supplies_requested_information(client):
    """M17/DSC-007: an info_requested application accepts member context."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)
    user = make_member("informable")
    login(client, user.username)
    client.post(
        reverse("projects:apply", kwargs={"slug": project.slug}),
        {"motivation": "Ready to start."},
    )
    application = Application.objects.get(project=project, applicant=user)
    publisher_assignment = MinistryPublisherFactory(ministry=project.ministry)
    reviewer = Client()
    reviewer.force_login(publisher_assignment.user)
    verify_mfa(reviewer, publisher_assignment.user)
    reviewer.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": "info_requested", "note": "Share a portfolio link."},
    )

    response = client.post(
        reverse("projects:application_provide_info", kwargs={"application_id": application.pk}),
        {"text": "https://example.com/portfolio"},
    )

    assert response.status_code == 302
    assert application.events.filter(event="info_provided", actor=user).exists()


# ---------------------------------------------------------------------------
# Publisher and Super Admin flows


@pytest.mark.unit
def test_publisher_drives_a_government_project_from_draft_to_public(client):
    """P1-P5/A2/BR-002/BR-003: draft, readiness evidence, approve, publish, visible."""
    assignment = MinistryPublisherFactory()
    super_admin = SuperAdminFactory()
    maintainer = make_member("named-maintainer")
    verify_mfa(client, assignment.user)

    created = client.post(
        reverse("projects:authoring_create"),
        {
            "ministry": assignment.ministry.pk,
            "title_en": "Civic Help Directory",
            "title_ne": "नागरिक सहायता निर्देशिका",
            "summary_en": "Find civic help programs.",
            "summary_ne": "सार्वजनिक सहायता कार्यक्रमहरू।",
            "data_classification": "public",
        },
    )
    project = Project.objects.get(title_en="Civic Help Directory")
    workflow = reverse("projects:authoring_workflow", kwargs={"slug": project.slug})
    manage = reverse("projects:authoring_manage", kwargs={"slug": project.slug})
    edit = reverse("projects:authoring_edit", kwargs={"slug": project.slug})

    readiness = client.post(
        edit,
        {
            "ministry": assignment.ministry.pk,
            "title_en": "Civic Help Directory",
            "title_ne": "नागरिक सहायता निर्देशिका",
            "summary_en": "Find civic help programs.",
            "summary_ne": "सार्वजनिक सहायता कार्यक्रमहरू।",
            "difficulty": "beginner",
            "estimated_effort": "small",
            "contribution_mode": "open_direct",
            "prerequisites": "Basic Python.",
            "communication_channel": "https://matrix.to/#/#civic-help",
            "response_sla": "3d",
            "repository_url": "https://github.com/ministry/civic-help",
            "default_branch": "main",
            "issue_tracker_url": "https://github.com/ministry/civic-help/issues",
            "documentation_url": "https://github.com/ministry/civic-help#readme",
            "code_of_conduct_url": "https://ministry.example/code-of-conduct",
            "license": ApprovedLicenseFactory(is_approved=True).pk,
            "signoff_model": "dco",
            "data_classification": "public",
            "security_contact": "security@ministry.example",
        },
    )
    RepositoryConnectionFactory(
        project=project,
        full_name="ministry/civic-help",
    )
    maintainer_added = client.post(
        manage,
        {"action": "maintainer", "user": maintainer.pk, "role": "lead"},
    )
    task_added = client.post(
        manage,
        {"action": "task", "title": "Add first help category", "status": "open"},
    )
    suitability = client.post(
        manage,
        {"action": "suitability", **{area: "on" for area in SUITABILITY_AREAS}},
    )
    submitted = client.post(workflow, {"action": "submit"})

    reviewer = Client()
    reviewer.force_login(super_admin)
    verify_mfa(reviewer, super_admin)
    confirmed = reviewer.post(manage, {"action": "confirm_suitability"})
    approved = reviewer.post(workflow, {"action": "approve"})
    published = reviewer.post(workflow, {"action": "publish"})
    public_view = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))
    gov_listing = client.get(reverse("projects:government"))

    assert created.status_code == 302
    assert readiness.status_code == 302
    assert maintainer_added.status_code == 302
    assert task_added.status_code == 302
    assert suitability.status_code == 302
    assert submitted.status_code == 302
    assert confirmed.status_code == 302
    assert approved.status_code == 302
    assert published.status_code == 302
    assert public_view.status_code == 200
    assert b"Civic Help Directory" in gov_listing.content


@pytest.mark.unit
def test_publisher_accepts_an_application_with_audited_decision(client):
    """P6/DSC-007: an MFA-verified owning publisher accepts an applicant."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)
    user = make_member("accepted-applicant")
    login(client, user.username)
    client.post(
        reverse("projects:apply", kwargs={"slug": project.slug}),
        {"motivation": "Contributing weekly."},
    )
    application = Application.objects.get(project=project, applicant=user)
    assignment = MinistryPublisherFactory(ministry=project.ministry)
    verify_mfa(client, assignment.user)

    response = client.post(
        reverse("projects:application_decide", kwargs={"application_id": application.pk}),
        {"decision": "accepted", "note": "Welcome aboard."},
    )

    application.refresh_from_db()
    assert response.status_code == 302
    assert application.status == "accepted"
    assert application.decided_by == assignment.user


@pytest.mark.unit
def test_publisher_sees_own_ministry_timeline_only(client):
    """P7/DSC-008: owning publisher can open the timeline; others cannot."""
    project = open_project(contribution_mode=ContributionMode.APPLICATION)
    applicant = make_member("timeline-applicant")
    login(client, applicant.username)
    client.post(
        reverse("projects:apply", kwargs={"slug": project.slug}),
        {"motivation": "Interested."},
    )
    application = Application.objects.get(project=project, applicant=applicant)
    owner_assignment = MinistryPublisherFactory(ministry=project.ministry)
    foreign_assignment = MinistryPublisherFactory()

    verify_mfa(client, owner_assignment.user)
    allowed = client.get(
        reverse("projects:application_timeline", kwargs={"application_id": application.pk})
    )
    verify_mfa(client, foreign_assignment.user)
    denied = client.get(
        reverse("projects:application_timeline", kwargs={"application_id": application.pk})
    )

    assert allowed.status_code == 200
    assert denied.status_code in {403, 404}


# ---------------------------------------------------------------------------
# Route protection


@pytest.mark.unit
def test_protected_member_routes_redirect_anonymous_visitors_to_localized_login(client):
    """AUTH-001/AUTH-007: anonymous access to member routes hits the localized login."""
    for url in (
        reverse("accounts:dashboard"),
        reverse("accounts:profile_edit"),
        reverse("accounts:session_list"),
        reverse("accounts:privacy_export"),
        reverse("projects:application_list"),
        reverse("projects:community_create"),
        reverse("projects:authoring_dashboard"),
    ):
        response = client.get(url)
        assert response.status_code == 302, url
        assert response.url.startswith(reverse("accounts:login")), url


@pytest.mark.unit
def test_plain_member_cannot_open_publisher_authoring(client):
    """AUTH-006: member-role users are kept out of ministry authoring."""
    user = make_member("plain-member")
    login(client, user.username)

    response = client.get(reverse("projects:authoring_create"))

    assert response.status_code in {302, 403, 404}


# ---------------------------------------------------------------------------
# Newly reachable documented flows


@pytest.mark.unit
def test_member_publishes_an_external_listing_that_visitors_can_browse(client):
    """BLG-001/BLG-005/D13: a member's external-link listing goes public for visitors."""
    author = make_member("listing-author")
    login(client, author.username)

    created = client.post(
        reverse("blogs:link_external"),
        {
            "title": "Public infrastructure notes",
            "excerpt": "A link to the full article.",
            "canonical_url": "https://medium.com/@author/infrastructure",
            "language": "en",
            "reading_time_minutes": 4,
            "rights_confirmed": "on",
            "action": "list",
        },
    )
    post = BlogPost.objects.get(title="Public infrastructure notes")
    published = client.post(reverse("blogs:publish", kwargs={"post_id": post.pk}))

    post.refresh_from_db()
    visitor = Client()
    listing = visitor.get(reverse("blogs:list"))
    detail = visitor.get(reverse("blogs:detail", kwargs={"post_id": post.pk}))

    assert created.status_code == 302
    assert published.status_code == 302
    assert post.status == BlogStatus.PUBLISHED
    assert listing.status_code == 200
    assert post.canonical_url in listing.content.decode()
    assert detail.status_code == 200
    assert detail.context["post"] == post


@pytest.mark.unit
def test_project_publication_notifies_a_bookmarker_who_marks_it_read(
    client, django_capture_on_commit_callbacks
):
    """GOV-004/DSC-004/NTF-001: publication notifies an opted-in bookmarker via /notifications/."""
    project = make_publishable()
    bookmarker = make_member("notified-bookmarker")
    ProjectBookmark.objects.create(user=bookmarker, project=project, notify_on_change=True)

    verify_mfa(client, project.owner)
    submitted = client.post(
        reverse("projects:authoring_workflow", kwargs={"slug": project.slug}),
        {"action": "submit"},
    )
    reviewer = SuperAdminFactory()
    verify_mfa(client, reviewer)
    approved = client.post(
        reverse("projects:authoring_workflow", kwargs={"slug": project.slug}),
        {"action": "approve"},
    )
    with django_capture_on_commit_callbacks(execute=True):
        published = client.post(
            reverse("projects:authoring_workflow", kwargs={"slug": project.slug}),
            {"action": "publish"},
        )

    client.logout()
    login(client, bookmarker.username)
    feed = client.get(reverse("notifications:list"))
    notification = Notification.objects.get(
        recipient=bookmarker, channel=Channel.IN_APP, type=NotificationType.PROJECT_STATUS
    )
    marked = client.post(reverse("notifications:read", kwargs={"pk": notification.pk}))

    notification.refresh_from_db()
    assert submitted.status_code == 302
    assert approved.status_code == 302
    assert published.status_code == 302
    assert feed.status_code == 200
    assert feed.context["notifications"].get() == notification
    assert notification.context_url == f"/projects/{project.slug}/"
    assert f"/projects/{project.slug}/" in feed.content.decode()
    assert marked.status_code == 302
    assert notification.read_at is not None


@pytest.mark.unit
def test_reported_project_is_unpublished_then_restored_after_an_overturned_appeal(client):
    """ADM-003/ADM-004/BR-010/ADM-007: report, unpublish, appeal, overturn, restore."""
    project = open_project()
    reporter = make_member("vigilant-reporter")
    login(client, reporter.username)

    reported = client.post(
        reverse("moderation:report_create"),
        {
            "content_type": ContentType.objects.get_for_model(project).pk,
            "object_id": project.pk,
            "reason": ReportReason.SPAM,
            "details": "Repeated commercial advertising",
        },
    )
    report = Report.objects.get()
    confirmation = client.get(
        reverse("moderation:report_confirmation", kwargs={"pk": report.case.pk})
    )

    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)
    queue = client.get(reverse("moderation:case_queue"))
    case = report.case
    assigned = client.post(reverse("moderation:case_assign", kwargs={"pk": case.pk}))
    decided = client.post(
        reverse("moderation:case_decide", kwargs={"pk": case.pk}),
        {
            "action": ModerationAction.UNPUBLISH,
            "reason": ReportReason.SPAM,
            "comment": "Confirmed spam listing",
        },
    )
    case.refresh_from_db()
    project.refresh_from_db()
    hidden = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert reported.status_code == 302
    assert reported.url == reverse("moderation:report_confirmation", kwargs={"pk": report.case.pk})
    assert confirmation.status_code == 200
    assert queue.status_code == 200
    assert case.pk in {queued.pk for queued in queue.context["cases"]}
    assert assigned.status_code == 302
    assert decided.status_code == 302
    assert case.assigned_to == super_admin
    assert case.status == CaseStatus.ACTION_TAKEN
    assert project.status == ProjectStatus.DRAFT
    assert hidden.status_code == 404

    client.logout()
    login(client, reporter.username)
    appealed = client.post(
        reverse("moderation:appeal", kwargs={"pk": case.pk}),
        {"grounds": "The listing is not commercial advertising."},
    )
    case.refresh_from_db()

    assert appealed.status_code == 302
    assert case.status == CaseStatus.APPEALED
    assert case.appeal_status == AppealStatus.PENDING

    verify_mfa(client, super_admin)
    resolved = client.post(
        reverse("moderation:appeal_resolve", kwargs={"pk": case.pk}),
        {"outcome": AppealStatus.OVERTURNED, "reason": "The report was unfounded."},
    )
    project.refresh_from_db()
    case.refresh_from_db()
    restored = client.get(reverse("projects:detail", kwargs={"slug": project.slug}))

    assert resolved.status_code == 302
    assert case.status == CaseStatus.CLOSED_NO_ACTION
    assert case.appeal_status == AppealStatus.OVERTURNED
    assert project.status == ProjectStatus.OPEN_FOR_CONTRIBUTION
    assert restored.status_code == 200


@pytest.mark.unit
def test_member_evidence_is_maintainer_verified_and_forged_verification_is_denied(client):
    """BR-006/A5/AUTH-006: maintainer verification accepts evidence; a stranger is denied."""
    project = open_project(contribution_mode=ContributionMode.OPEN_DIRECT)
    member = make_member("evidence-author")
    login(client, member.username)

    submitted = client.post(
        reverse("contributions:submit", kwargs={"project_id": project.pk}),
        {
            "title": "Accessibility audit",
            "contribution_type": contribution_type("qa").pk,
            "description": "Tested keyboard navigation.",
            "evidence_url": "https://example.com/audit",
        },
    )
    record = ContributionRecord.objects.get(project=project, contributor=member)

    forger = make_member("evidence-forger")
    login(client, forger.username)
    forged = client.post(
        reverse("contributions:verify", kwargs={"contribution_id": record.pk}),
        {"decision": VerificationStatus.ACCEPTED, "reason": "Forged approval"},
    )
    record.refresh_from_db()

    assert submitted.status_code == 302
    assert forged.status_code == 403
    assert record.status == VerificationStatus.CANDIDATE

    maintainer = ProjectMaintainerFactory(project=project).user
    reviewer = Client()
    reviewer.force_login(maintainer)
    verified = reviewer.post(
        reverse("contributions:verify", kwargs={"contribution_id": record.pk}),
        {"decision": VerificationStatus.ACCEPTED, "reason": "Reviewed and accepted"},
    )

    record.refresh_from_db()
    assert verified.status_code == 302
    assert record.status == VerificationStatus.ACCEPTED
    assert record.verified_by == maintainer


@pytest.mark.unit
def test_recognition_profile_shows_private_work_and_public_leaderboard_explains_its_gate(client):
    """REC-003/REC-004: private work remains private while a disabled public route is honest."""
    member = make_member("scored-member")
    policy = activate_policy(SuperAdminFactory(), {"standard": 3})
    contribution = ContributionRecordFactory(contributor=member, status=VerificationStatus.ACCEPTED)
    score = ContributionScore.objects.create(contribution=contribution, policy=policy, points=3)
    login(client, member.username)

    profile = client.get(reverse("recognition:my_profile"))
    disabled = client.get(reverse("recognition:leaderboard"))
    with override_settings(RECOGNITION_ENABLED=True):
        enabled = client.get(reverse("recognition:leaderboard"))

    assert profile.status_code == 200
    assert list(profile.context["scores"]) == [score]
    assert disabled.status_code == 200
    assert b"Public rankings are not enabled." in disabled.content
    assert member.username.encode() not in main_content(disabled)
    assert enabled.status_code == 200
    assert member.username.encode() in main_content(enabled)


@pytest.mark.unit
def test_member_suggests_a_missing_skill_and_super_admin_approves_it(client):
    """MEM-004/D4: a member suggestion reaches the queue and a verified Super Admin approves it."""
    member = make_member("suggesting-member")
    login(client, member.username)

    submitted = client.post(
        reverse("taxonomy:skill_suggestion_create"),
        {"term_name": "Kubernetes", "note": "Useful for cloud projects."},
    )
    suggestion = SkillSuggestion.objects.get(term_name="Kubernetes")

    assert submitted.status_code == 302
    assert suggestion.status == SuggestionStatus.PENDING
    assert suggestion.suggested_by == member

    super_admin = SuperAdminFactory()
    verify_mfa(client, super_admin)
    review_queue = client.get(reverse("taxonomy:skill_suggestion_review_list"))
    approved = client.post(
        reverse("taxonomy:skill_suggestion_review", kwargs={"pk": suggestion.pk}),
        {"decision": "approve"},
    )

    suggestion.refresh_from_db()
    assert review_queue.status_code == 200
    assert b"Kubernetes" in review_queue.content
    assert approved.status_code == 302
    assert suggestion.status == SuggestionStatus.ACCEPTED
    assert suggestion.resolved_by == super_admin
    assert Skill.objects.filter(name="Kubernetes").exists()


@pytest.mark.unit
def test_ministry_provisioning_and_official_contact_confirmation_round_trip(client, mailoutbox):
    """AUTH-004/AUTH-005/D3: provision, grant, and the officer confirms the emailed token."""
    super_admin = SuperAdminFactory()
    officer = UserFactory(username="flow-officer")
    officer.set_password("demo-password-2026")
    officer.save(update_fields=["password"])
    verify_mfa(client, super_admin)

    created = client.post(
        reverse("ministries:organization_create"),
        {
            "name_en": "Ministry of Flow Assurance",
            "name_ne": "प्रवाह सुनिश्चितता मन्त्रालय",
            "slug": "mofa",
            "contact_email": "info@mofa.gov.np",
            "website_url": "https://mofa.gov.np",
        },
    )
    ministry = MinistryOrganization.objects.get(slug="mofa")
    activated = client.post(
        reverse("ministries:organization_action", kwargs={"slug": ministry.slug}),
        {"action": "activate"},
    )
    granted = client.post(
        reverse("ministries:publisher_create", kwargs={"slug": ministry.slug}),
        {
            "user": officer.pk,
            "title": "Information Officer",
            "official_email": "officer@mofa.gov.np",
        },
    )
    publisher = MinistryPublisher.objects.get(ministry=ministry, user=officer)

    assert created.status_code == 302
    assert activated.status_code == 302
    assert granted.status_code == 302
    assert len(mailoutbox) == 1
    assert publisher.contact_verification_status == ContactVerificationStatus.PENDING

    confirmation_url = mailoutbox[0].body.rsplit(" ", 1)[-1]
    token = parse_qs(urlparse(confirmation_url).query)["token"][0]
    client.logout()
    login(client, officer.username)
    verify_mfa_with_enrollment(client, officer)
    confirmed = client.post(
        reverse("ministries:contact_confirmation", kwargs={"publisher_id": publisher.pk}),
        {"token": token},
    )

    publisher.refresh_from_db()
    ministry.refresh_from_db()
    assert confirmed.status_code == 302
    assert publisher.contact_verification_status == ContactVerificationStatus.VERIFIED
    assert is_publisher_active(officer, ministry)


@pytest.mark.unit
@pytest.mark.github_webhook
def test_signed_github_delivery_is_processed_and_forged_signature_is_unauthorized(client):
    """GIT-004/GIT-012: signed PR deliveries project immediately; bad HMAC is 401."""
    assert reverse("github_sync:webhook") == "/webhooks/github/"
    repository = RepositoryConnectionFactory(repository_node_id="R_kgDOFlowWebhook001")
    body = pr_merged_body(node_id=repository.repository_node_id)
    headers = {
        "HTTP_X_GITHUB_EVENT": "pull_request",
        "HTTP_X_GITHUB_DELIVERY": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
        "HTTP_X_HUB_SIGNATURE_256": sign_body(body),
        "HTTP_X_GITHUB_DELIVERY_TIMESTAMP": timezone.now().isoformat(),
    }

    with override_settings(GITHUB_WEBHOOK_SECRET=WEBHOOK_SECRET):
        accepted = client.post(
            "/webhooks/github/", body, content_type="application/json", **headers
        )
        forged_headers = dict(
            headers,
            HTTP_X_GITHUB_DELIVERY="f2cba355-cc78-11e3-81ab-4c9367dc0958",
            HTTP_X_HUB_SIGNATURE_256="sha256=" + "0" * 64,
        )
        rejected = client.post(
            "/webhooks/github/", body, content_type="application/json", **forged_headers
        )

    event = ProviderEvent.objects.get(delivery_id="72d3162e-cc78-11e3-81ab-4c9367dc0958")
    rejected_event = ProviderEvent.objects.get(delivery_id="f2cba355-cc78-11e3-81ab-4c9367dc0958")

    assert accepted.status_code == 202
    assert event.processing_state == ProcessingState.PROCESSED
    assert event.repository_id == repository.pk
    assert rejected.status_code == 401
    assert rejected_event.processing_state == ProcessingState.REJECTED
