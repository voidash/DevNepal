import factory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    SuperAdminFactory,
    UserFactory,
)
from apps.projects.enums import (
    ApplicationEventType,
    ApplicationStatus,
    AttachmentKind,
    ParticipationKind,
    ProjectLinkKind,
    ProjectStatus,
    ProjectType,
    ReviewDecision,
    UpdateKind,
)
from apps.projects.models import (
    SUITABILITY_AREAS,
    Application,
    ApplicationEvent,
    Project,
    ProjectAttachment,
    ProjectBookmark,
    ProjectLink,
    ProjectMaintainer,
    ProjectMilestone,
    ProjectReview,
    ProjectScreeningQuestion,
    ProjectSuitability,
    ProjectTask,
    ProjectUpdate,
    ProjectVersion,
)


class ProjectFactory(factory.django.DjangoModelFactory):
    """Government project draft with bilingual identity defaults (GOV-002, 14.3)."""

    class Meta:
        model = Project

    class Params:
        ready = factory.Trait(
            contribution_mode="application",
            prerequisites="Familiarity with Django",
            communication_channel="https://matrix.to/#/#devnepal:matrix.org",
            difficulty="intermediate",
            estimated_effort="medium",
            repository_url="https://github.com/moit/service-directory",
            default_branch="main",
            issue_tracker_url="https://github.com/moit/service-directory/issues",
            documentation_url="https://github.com/moit/service-directory#readme",
            code_of_conduct_url="https://example.com/conduct",
            security_contact="security@moit.gov.np",
        )

    project_type = ProjectType.GOVERNMENT
    title_en = factory.Sequence(lambda n: f"National Service Directory {n}")
    title_ne = factory.Sequence(lambda n: f"राष्ट्रिय सेवा निर्देशिका {n}")
    slug = factory.Sequence(lambda n: f"national-service-directory-{n}")
    summary_en = "A public directory of government digital services."
    summary_ne = "सरकारी डिजिटल सेवाहरूको सार्वजनिक निर्देशिका।"
    ministry = factory.SubFactory(MinistryOrganizationFactory)
    owner = factory.SubFactory(UserFactory)
    status = ProjectStatus.DRAFT


class PersonalProjectFactory(ProjectFactory):
    """Member-owned community listing (PPR-002)."""

    project_type = ProjectType.PERSONAL
    ministry = None
    slug = factory.Sequence(lambda n: f"community-project-{n}")
    title_en = factory.Sequence(lambda n: f"Community Weather Widget {n}")


class ProjectMaintainerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectMaintainer

    project = factory.SubFactory(ProjectFactory)
    user = factory.SubFactory(UserFactory)
    role = "maintainer"
    can_review_merge = False


class ProjectVersionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectVersion

    project = factory.SubFactory(ProjectFactory)
    version_number = factory.LazyAttribute(
        lambda o: (
            (
                o.project.versions.order_by("-version_number")
                .values_list("version_number", flat=True)
                .first()
                or 0
            )
            + 1
        )
    )
    snapshot = factory.LazyAttribute(
        lambda o: {"title_en": o.project.title_en, "summary_en": o.project.summary_en}
    )
    submitted_by = factory.SelfAttribute("project.owner")


class ProjectReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectReview

    project = factory.SubFactory(ProjectFactory, status=ProjectStatus.IN_REVIEW)
    version = factory.SubFactory(ProjectVersionFactory, project=factory.SelfAttribute("..project"))
    reviewer = factory.SubFactory(SuperAdminFactory)
    decision = ReviewDecision.APPROVED
    comment = ""
    from_status = ProjectStatus.IN_REVIEW
    to_status = ProjectStatus.APPROVED


def default_suitability_checklist():
    return {area: {"checked": True, "note": ""} for area in SUITABILITY_AREAS}


class ProjectSuitabilityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectSuitability

    project = factory.SubFactory(ProjectFactory)
    checklist = factory.LazyFunction(default_suitability_checklist)

    class Params:
        confirmed = factory.Trait(
            confirmed_by=factory.SubFactory(SuperAdminFactory),
            confirmed_at=factory.LazyFunction(timezone.now),
        )


class ProjectScreeningQuestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectScreeningQuestion

    project = factory.SubFactory(ProjectFactory)
    question = factory.Sequence(lambda n: f"Screening question {n}?")
    help_text = ""
    is_required = True
    sort_order = 0
    is_active = True


class ProjectTaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectTask

    project = factory.SubFactory(ProjectFactory)
    title = factory.Sequence(lambda n: f"Starter task {n}")
    description = ""
    is_starter = True
    issue_url = "https://github.com/moit/service-directory/issues/1"
    status = "open"


class ProjectMilestoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectMilestone

    project = factory.SubFactory(ProjectFactory)
    title = factory.Sequence(lambda n: f"Milestone {n}")
    description = ""
    sort_order = 0
    status = "planned"


class ProjectUpdateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectUpdate

    project = factory.SubFactory(ProjectFactory)
    title = factory.Sequence(lambda n: f"Progress update {n}")
    body = "Steady progress on the directory."
    kind = UpdateKind.PROGRESS
    created_by = factory.SubFactory(UserFactory)


class ProjectAttachmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectAttachment

    project = factory.SubFactory(ProjectFactory)
    kind = AttachmentKind.PROPOSAL
    file = SimpleUploadedFile("proposal.pdf", b"%PDF-1.4 sample", content_type="application/pdf")
    original_filename = "proposal.pdf"
    content_type = "application/pdf"
    size_bytes = 14
    uploaded_by = factory.SubFactory(UserFactory)


class ProjectLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectLink

    project = factory.SubFactory(ProjectFactory)
    kind = ProjectLinkKind.REPOSITORY
    url = factory.Sequence(lambda n: f"https://github.com/moit/repo-{n}")
    label = ""


class ApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Application

    project = factory.SubFactory(ProjectFactory, status=ProjectStatus.OPEN_FOR_CONTRIBUTION)
    applicant = factory.SubFactory(UserFactory)
    kind = ParticipationKind.APPLICATION
    status = ApplicationStatus.SUBMITTED
    motivation = "I want to contribute to this project."
    screening_answers = factory.LazyFunction(list)


class ApplicationEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ApplicationEvent

    application = factory.SubFactory(ApplicationFactory)
    actor = factory.LazyAttribute(lambda o: o.application.applicant)
    event = ApplicationEventType.SUBMITTED
    comment = ""
    from_status = ""
    to_status = ApplicationStatus.SUBMITTED


class ProjectBookmarkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProjectBookmark

    user = factory.SubFactory(UserFactory)
    project = factory.SubFactory(ProjectFactory)
    notify_on_change = True


def make_publishable(project: Project | None = None, **kwargs) -> Project:
    """Return a government project whose owner is an active publisher and that passes every gate."""
    from apps.taxonomy.tests.factories import ApprovedLicenseFactory

    if project is None:
        project = ProjectFactory(ready=True, **kwargs)
    MinistryPublisherFactory(user=project.owner, ministry=project.ministry)
    ProjectMaintainerFactory(project=project)
    ProjectTaskFactory(project=project)
    ProjectSuitabilityFactory(project=project, confirmed=True)
    # Publication readiness depends on a verified GitHub App enrollment, not
    # merely a user-entered URL. Import locally to avoid the test-factory cycle.
    from apps.github_sync.tests.factories import RepositoryConnectionFactory

    RepositoryConnectionFactory(
        project=project,
        full_name="/".join(project.repository_url.rstrip("/").split("/")[-2:]),
        activated_by=project.owner,
        is_public=True,
    )
    project.license = ApprovedLicenseFactory(is_approved=True)
    project.outcome_summary = "The project delivered its planned public outcome."
    project.deliverables = [{"label": "Public release", "url": project.repository_url}]
    project.impact_summary = "The completed release improved the target public service."
    project.lessons_learned = "Publish progress evidence throughout delivery."
    project.save(
        update_fields=[
            "license",
            "outcome_summary",
            "deliverables",
            "impact_summary",
            "lessons_learned",
        ]
    )
    return project
