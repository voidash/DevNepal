import typing
import uuid

from django.db import models
from django.utils.text import get_valid_filename, slugify
from django.utils.translation import get_language

from apps.accounts.fields import NormalizedURLField
from apps.projects.enums import (
    ApplicationEventType,
    ApplicationStatus,
    AttachmentKind,
    ContributionMode,
    DifficultyLevel,
    EffortBand,
    GovernanceModel,
    MaintainerRole,
    MilestoneStatus,
    OwnershipVerificationStatus,
    ParticipationKind,
    ProjectLinkKind,
    ProjectStatus,
    ProjectType,
    ResponseSla,
    ReviewDecision,
    ScanStatus,
    SignoffModel,
    TaskStatus,
    UpdateKind,
)
from apps.taxonomy.enums import ContentLanguage, DataClassification
from apps.taxonomy.fields import NFCCharField, NFCSlugField, NFCTextField


def attachment_upload_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f"project-attachments/{instance.project_id}/{uuid.uuid4().hex}/{safe_name}"


class Project(models.Model):
    """Common project record; project_type discriminates government vs personal."""

    project_type = models.CharField(max_length=12, choices=ProjectType.choices, db_index=True)
    title_en = NFCCharField(max_length=200)
    title_ne = NFCCharField(max_length=200, blank=True, default="")
    slug = NFCSlugField(max_length=220, allow_unicode=True, unique=True)
    ministry = models.ForeignKey(
        "ministries.MinistryOrganization",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    owner = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="owned_projects"
    )
    maintainers = models.ManyToManyField(
        "accounts.User", through="ProjectMaintainer", related_name="maintained_projects"
    )

    problem_statement = NFCTextField(blank=True, default="")
    target_users = NFCTextField(blank=True, default="")
    expected_outcome = NFCTextField(blank=True, default="")
    success_indicators = NFCTextField(blank=True, default="")

    summary_en = NFCTextField(blank=True, default="")
    summary_ne = NFCTextField(blank=True, default="")
    description_md = NFCTextField(blank=True, default="")
    background = NFCTextField(blank=True, default="")
    current_state = NFCTextField(blank=True, default="")
    limitations = NFCTextField(blank=True, default="")
    related_initiatives = NFCTextField(blank=True, default="")

    contribution_types = models.ManyToManyField(
        "taxonomy.TaxonomyTerm", blank=True, related_name="projects"
    )
    skills = models.ManyToManyField("taxonomy.Skill", blank=True, related_name="projects")
    technologies = models.ManyToManyField(
        "taxonomy.TaxonomyTerm", blank=True, related_name="technology_projects"
    )
    difficulty = models.CharField(
        max_length=15, choices=DifficultyLevel.choices, blank=True, default=""
    )
    experience_band = models.CharField(max_length=30, blank=True, default="")
    estimated_effort = models.CharField(
        max_length=10, choices=EffortBand.choices, blank=True, default=""
    )
    contributor_capacity = models.PositiveIntegerField(null=True, blank=True)
    is_remote = models.BooleanField(default=True)
    location = NFCCharField(max_length=120, blank=True, default="")
    deadline = models.DateField(null=True, blank=True)

    contribution_mode = models.CharField(
        max_length=15, choices=ContributionMode.choices, blank=True, default=""
    )
    prerequisites = NFCTextField(blank=True, default="")
    communication_channel = models.URLField(blank=True, default="")
    response_sla = models.CharField(
        max_length=3,
        choices=ResponseSla.choices,
        blank=True,
        default=ResponseSla.WITHIN_1_WEEK,
    )
    code_of_conduct_url = models.URLField(blank=True, default="")

    repository_url = models.URLField(blank=True, default="")
    default_branch = NFCCharField(max_length=100, blank=True, default="")
    issue_tracker_url = models.URLField(blank=True, default="")
    documentation_url = models.URLField(blank=True, default="")
    architecture_url = models.URLField(blank=True, default="")
    environments_url = models.URLField(blank=True, default="")
    test_build_instructions = NFCTextField(blank=True, default="")
    ci_status_url = models.URLField(blank=True, default="")

    governance_model = models.CharField(
        max_length=25, choices=GovernanceModel.choices, blank=True, default=""
    )
    outcome_ownership = NFCTextField(blank=True, default="")
    escalation_path = NFCTextField(blank=True, default="")
    completion_criteria = NFCTextField(blank=True, default="")

    license = models.ForeignKey(
        "taxonomy.ApprovedLicense",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    signoff_model = models.CharField(
        max_length=15, choices=SignoffModel.choices, blank=True, default=""
    )
    third_party_rights_confirmed = models.BooleanField(default=False)
    content_license = NFCCharField(max_length=200, blank=True, default="")

    data_classification = models.CharField(
        max_length=12,
        choices=DataClassification.choices,
        default=DataClassification.PUBLIC,
    )
    security_contact = models.EmailField(blank=True, default="")
    vulnerability_disclosure_url = models.URLField(blank=True, default="")
    prohibited_data_statement = NFCTextField(blank=True, default="")

    status = models.CharField(
        max_length=25,
        choices=ProjectStatus.choices,
        default=ProjectStatus.DRAFT,
        db_index=True,
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    scheduled_publication_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    current_version = models.ForeignKey(
        "projects.ProjectVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    dependencies = NFCTextField(blank=True, default="")
    risks = NFCTextField(blank=True, default="")
    last_maintainer_activity_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    role = NFCCharField(max_length=120, blank=True, default="")
    ownership_verification = models.CharField(
        max_length=20,
        choices=OwnershipVerificationStatus.choices,
        default=OwnershipVerificationStatus.UNVERIFIED,
    )

    outcome_summary = NFCTextField(blank=True, default="")
    deliverables = models.JSONField(default=list, blank=True)
    impact_summary = NFCTextField(blank=True, default="")
    lessons_learned = NFCTextField(blank=True, default="")
    archive_reason = NFCTextField(blank=True, default="")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-status_changed_at", "-id"]
        constraints: typing.ClassVar[list] = [
            models.CheckConstraint(
                condition=models.Q(project_type=ProjectType.GOVERNMENT, ministry__isnull=False)
                | models.Q(project_type=ProjectType.PERSONAL, ministry__isnull=True),
                name="chk_project_type_ministry",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project_type", "status"], name="idx_project_type_status"),
            models.Index(fields=["ministry", "status"], name="idx_project_ministry_status"),
            models.Index(fields=["status", "-published_at"], name="idx_project_status_published"),
            models.Index(fields=["deadline"], name="idx_project_deadline"),
        ]

    def __str__(self) -> str:
        return self.title_en

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title_en or "project", allow_unicode=True) or "project"
            candidate = base
            suffix = 2
            while Project.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate = f"{base}-{suffix}"
                suffix += 1
            self.slug = candidate
        return super().save(*args, **kwargs)

    @property
    def localized_title(self) -> str:
        if get_language() == "ne" and self.title_ne:
            return self.title_ne
        return self.title_en

    @property
    def localized_summary(self) -> str:
        if get_language() == "ne" and self.summary_ne:
            return self.summary_ne
        return self.summary_en

    @property
    def is_official(self) -> bool:
        return (
            self.project_type == ProjectType.GOVERNMENT
            and self.current_version_id is not None
            and self.status
            in {
                ProjectStatus.APPROVED,
                ProjectStatus.OPEN_FOR_CONTRIBUTION,
                ProjectStatus.PAUSED,
                ProjectStatus.COMPLETED,
            }
        )


class ProjectMaintainer(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="maintainer_assignments"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="maintainer_assignments"
    )
    role = models.CharField(
        max_length=12, choices=MaintainerRole.choices, default=MaintainerRole.MAINTAINER
    )
    can_review_merge = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["role", "user__username"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["project", "user"], name="uniq_project_maintainer"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} as {self.get_role_display()} on {self.project}"


class ProjectVersion(models.Model):
    """Immutable submission snapshot (GOV-005, A2). Only publication stamps may change."""

    MUTABLE_ON_PUBLISH: typing.ClassVar[set[str]] = {"published_at", "published_by"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    submitted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="submitted_versions",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="published_versions",
    )

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["project", "-version_number"]
        verbose_name = "project version"
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["project", "version_number"], name="uniq_project_version_number"
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "-submitted_at"], name="idx_version_project_submitted"),
        ]

    def __str__(self) -> str:
        return f"{self.project} v{self.version_number}"

    def save(self, *args, **kwargs):
        if self.pk and ProjectVersion.objects.filter(pk=self.pk).exists():
            stored = ProjectVersion.objects.get(pk=self.pk)
            for field in self._meta.concrete_fields:
                if field.name in self.MUTABLE_ON_PUBLISH:
                    continue
                if getattr(self, field.attname) != getattr(stored, field.attname):
                    raise PermissionError("ProjectVersion rows are immutable (GOV-005)")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("ProjectVersion rows are immutable (GOV-005)")


class ProjectReview(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="reviews")
    version = models.ForeignKey(ProjectVersion, on_delete=models.PROTECT, related_name="reviews")
    reviewer = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL, related_name="project_reviews"
    )
    decision = models.CharField(max_length=20, choices=ReviewDecision.choices, db_index=True)
    comment = NFCTextField(blank=True, default="")
    from_status = models.CharField(max_length=25, blank=True, default="")
    to_status = models.CharField(max_length=25, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "-created_at"], name="idx_review_project_created"),
        ]

    def __str__(self) -> str:
        return f"{self.get_decision_display()} on {self.project} by {self.reviewer}"


class ProjectReviewAssignment(models.Model):
    """Current PMO review ownership and working notes for one immutable version."""

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="review_assignment"
    )
    version = models.ForeignKey(
        ProjectVersion, on_delete=models.PROTECT, related_name="review_assignments"
    )
    reviewer = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="assigned_project_reviews"
    )
    assigned_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="review_assignments_made",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(db_index=True)
    reviewer_note = NFCTextField(blank=True, default="")
    checklist = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["due_at", "project"]

    def __str__(self) -> str:
        return f"Review of {self.project} v{self.version.version_number} by {self.reviewer}"


SUITABILITY_AREAS: typing.Final = (
    "legal_authority",
    "source_code_rights",
    "data_classification",
    "security_exposure",
    "procurement_restrictions",
    "third_party_licenses",
    "repository_readiness",
    "maintainer_capacity",
    "contribution_agreement",
    "public_communications",
)


class ProjectSuitability(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="suitability")
    checklist = models.JSONField(default=dict)
    completed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="suitability_completed",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="suitability_confirmed",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    notes = NFCTextField(blank=True, default="")

    def __str__(self) -> str:
        return f"Suitability for {self.project}"


class ProjectScreeningQuestion(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="screening_questions"
    )
    question = NFCCharField(max_length=300)
    help_text = NFCTextField(blank=True, default="")
    is_required = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["sort_order", "id"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project"], name="idx_screening_project"),
        ]

    def __str__(self) -> str:
        return self.question


class ProjectTask(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = NFCCharField(max_length=200)
    description = NFCTextField(blank=True, default="")
    is_starter = models.BooleanField(default=False)
    issue_url = models.URLField(blank=True, default="")
    skills = models.ManyToManyField("taxonomy.Skill", blank=True, related_name="tasks")
    assigned_to = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
    )
    status = models.CharField(max_length=12, choices=TaskStatus.choices, default=TaskStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["status", "id"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "status"], name="idx_task_project_status"),
        ]

    def __str__(self) -> str:
        return self.title


class ProjectMilestone(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = NFCCharField(max_length=200)
    description = NFCTextField(blank=True, default="")
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=MilestoneStatus.choices, default=MilestoneStatus.PLANNED
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["sort_order", "id"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "status"], name="idx_milestone_project_status"),
        ]

    def __str__(self) -> str:
        return self.title


class ProjectUpdate(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    title = NFCCharField(max_length=200)
    body = NFCTextField()
    kind = models.CharField(max_length=12, choices=UpdateKind.choices, default=UpdateKind.PROGRESS)
    link = models.URLField(blank=True, default="")
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="project_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "-created_at"], name="idx_update_project_created"),
        ]

    def __str__(self) -> str:
        return self.title


class ProjectAttachment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="attachments")
    kind = models.CharField(max_length=12, choices=AttachmentKind.choices)
    file = models.FileField(upload_to=attachment_upload_path, max_length=255)
    original_filename = NFCCharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    language = models.CharField(
        max_length=2, choices=ContentLanguage.choices, default=ContentLanguage.ENGLISH
    )
    classification = models.CharField(
        max_length=12, choices=DataClassification.choices, default=DataClassification.PUBLIC
    )
    scan = models.CharField(
        max_length=12, choices=ScanStatus.choices, default=ScanStatus.PENDING, db_index=True
    )
    accessibility_note = NFCTextField(blank=True, default="")
    uploaded_by = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["kind", "-version"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["project", "kind"], name="idx_attachment_project_kind"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.original_filename}"


class ProjectLink(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="links")
    kind = models.CharField(max_length=15, choices=ProjectLinkKind.choices)
    url = NormalizedURLField()
    label = NFCCharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["kind", "id"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["project", "url"], name="uniq_project_link_url"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.url}"


class Application(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="applications")
    applicant = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="applications"
    )
    kind = models.CharField(
        max_length=12,
        choices=ParticipationKind.choices,
        default=ParticipationKind.APPLICATION,
    )
    status = models.CharField(
        max_length=15,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.SUBMITTED,
        db_index=True,
    )
    motivation = NFCTextField(blank=True, default="")
    screening_answers = models.JSONField(default=list, blank=True)
    decided_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_applications",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = NFCTextField(blank=True, default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-submitted_at"]
        verbose_name = "application"
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(
                fields=["project", "applicant", "kind"],
                name="uniq_application_project_applicant_kind",
            ),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["applicant", "status"], name="idx_app_applicant_status"),
            models.Index(fields=["project", "status"], name="idx_application_project_status"),
        ]

    def __str__(self) -> str:
        return f"{self.applicant} → {self.project} ({self.get_status_display()})"


class ApplicationEvent(models.Model):
    """Append-only application timeline entry (DSC-008)."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="application_events",
    )
    event = models.CharField(max_length=20, choices=ApplicationEventType.choices)
    comment = NFCTextField(blank=True, default="")
    from_status = models.CharField(max_length=15, blank=True, default="")
    to_status = models.CharField(max_length=15, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["created_at", "id"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["application", "created_at"], name="idx_appevent_app_created"),
        ]

    def __str__(self) -> str:
        return f"{self.get_event_display()} on {self.application}"

    def save(self, *args, **kwargs):
        if self.pk and ApplicationEvent.objects.filter(pk=self.pk).exists():
            raise PermissionError("ApplicationEvent rows are append-only (DSC-008)")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("ApplicationEvent rows are append-only (DSC-008)")


class ProjectBookmark(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="bookmarks")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="bookmarks")
    notify_on_change = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-created_at"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["user", "project"], name="uniq_bookmark_user_project"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} bookmarked {self.project}"


class CommunityTermsAcceptance(models.Model):
    """PPR-006: a member's acceptance receipt for one version of the community terms."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="community_terms_acceptances",
    )
    version = NFCCharField(max_length=30)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-accepted_at"]
        verbose_name = "community terms acceptance"
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["user", "version"], name="uniq_terms_user_version"),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["user", "version"], name="idx_terms_user_version"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} accepted community terms {self.version}"
