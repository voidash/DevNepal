from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.administration.models import FeatureFlag
from apps.contributions.enums import VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.moderation.enums import CaseStatus
from apps.moderation.models import ModerationCase
from apps.projects.enums import ProjectStatus, ProjectType
from apps.projects.models import Project
from apps.recognition.models import Badge
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.models import ApprovedLicense, Skill, SkillSuggestion, TaxonomyTerm

BREACHED_REVIEW_DAYS = 5
BREACHED_CASE_DAYS = 5


def _queue(*, queue_id, title, description, url, count, breached=0):
    return {
        "id": queue_id,
        "title": title,
        "description": description,
        "url": url,
        "count": count,
        "breached": breached,
    }


def _project_review_queue():
    pending = Project.objects.filter(
        project_type=ProjectType.GOVERNMENT,
        status__in=(ProjectStatus.IN_REVIEW, ProjectStatus.CHANGES_REQUESTED),
    )
    threshold = timezone.now() - timedelta(days=BREACHED_REVIEW_DAYS)
    return _queue(
        queue_id="project_reviews",
        title=_("Project submissions awaiting review"),
        description=_("Government submissions in review or returned for changes."),
        url=reverse("projects:review_queue"),
        count=pending.count(),
        breached=pending.filter(status=ProjectStatus.IN_REVIEW, updated_at__lt=threshold).count(),
    )


def _moderation_queue():
    open_cases = ModerationCase.objects.filter(
        status__in=(CaseStatus.NEW, CaseStatus.UNDER_REVIEW, CaseStatus.ESCALATED)
    )
    threshold = timezone.now() - timedelta(days=BREACHED_CASE_DAYS)
    return _queue(
        queue_id="moderation_cases",
        title=_("Open moderation cases"),
        description=_("Reports awaiting triage, review, or escalation."),
        url=reverse("moderation:case_queue"),
        count=open_cases.count(),
        breached=open_cases.filter(created_at__lt=threshold).count(),
    )


def _appeal_queue():
    appealed = ModerationCase.objects.filter(status=CaseStatus.APPEALED)
    return _queue(
        queue_id="appeals",
        title=_("Appeals awaiting a decision"),
        description=_("Members have contested a moderation decision."),
        url=reverse("moderation:case_queue"),
        count=appealed.count(),
    )


def _verification_queue():
    pending = ContributionRecord.objects.filter(
        status__in=(VerificationStatus.CANDIDATE, VerificationStatus.PENDING_INFO)
    )
    return _queue(
        queue_id="contribution_verifications",
        title=_("Contributions awaiting verification"),
        description=_("Evidence submitted by members that maintainers have not ruled on."),
        url=reverse("contributions:verification_queue"),
        count=pending.count(),
        breached=ContributionRecord.objects.filter(hold_active=True).count(),
    )


def _skill_suggestion_queue():
    pending = SkillSuggestion.objects.filter(status=SuggestionStatus.PENDING)
    return _queue(
        queue_id="skill_suggestions",
        title=_("Suggested skills awaiting a ruling"),
        description=_("Member-proposed taxonomy terms that are not yet in the catalogue."),
        url=reverse("taxonomy:skill_suggestion_review_list"),
        count=pending.count(),
    )


def _ministry_provisioning_queue():
    pending_orgs = MinistryOrganization.objects.filter(status=OrgStatus.PENDING)
    unverified_publishers = MinistryPublisher.objects.filter(
        status=PublisherStatus.ACTIVE,
        contact_verification_status=ContactVerificationStatus.PENDING,
    )
    return _queue(
        queue_id="ministry_provisioning",
        title=_("Ministries and publishers to provision"),
        description=_("Organizations pending activation and officers with unverified contacts."),
        url=reverse("ministries:organization_list"),
        count=pending_orgs.count() + unverified_publishers.count(),
    )


def build_work_queues():
    """ADM-002/ADM-006: pending administrative work with service-level indicators."""
    return [
        _project_review_queue(),
        _moderation_queue(),
        _appeal_queue(),
        _verification_queue(),
        _skill_suggestion_queue(),
        _ministry_provisioning_queue(),
    ]


def build_catalogue_entries():
    """ADM-001: the reference data a Super Admin maintains, with live counts."""
    return [
        {
            "id": "skills",
            "title": _("Skills and tags"),
            "url": reverse("taxonomy:skill_management"),
            "count": Skill.objects.filter(is_active=True).count(),
            "total": Skill.objects.count(),
        },
        {
            "id": "categories",
            "title": _("Project categories and contribution types"),
            "url": reverse("admin:taxonomy_taxonomyterm_changelist"),
            "count": TaxonomyTerm.objects.filter(is_active=True).count(),
            "total": TaxonomyTerm.objects.count(),
        },
        {
            "id": "licenses",
            "title": _("Approved licenses"),
            "url": reverse("taxonomy:license_management"),
            "count": ApprovedLicense.objects.filter(is_approved=True).count(),
            "total": ApprovedLicense.objects.count(),
        },
        {
            "id": "badges",
            "title": _("Badges"),
            "url": reverse("recognition:badge_list"),
            "count": Badge.objects.filter(is_active=True).count(),
            "total": Badge.objects.count(),
        },
        {
            "id": "ministries",
            "title": _("Ministries and named publishers"),
            "url": reverse("ministries:organization_list"),
            "count": MinistryOrganization.objects.filter(status=OrgStatus.ACTIVE).count(),
            "total": MinistryOrganization.objects.count(),
        },
        {
            "id": "feature_flags",
            "title": _("Feature flags"),
            "url": reverse("administration:feature_flags"),
            "count": FeatureFlag.objects.filter(is_enabled=True).count(),
            "total": FeatureFlag.objects.count(),
        },
    ]


def build_oversight_entries():
    """ADM-005/ADM-006/ADM-008: read-only oversight surfaces reachable from the console."""
    return [
        {
            "id": "ops_dashboard",
            "title": _("Operations dashboard"),
            "description": _("Stale projects, sync health, delivery backlog, audit failures."),
            "url": reverse("audit:ops_dashboard"),
        },
        {
            "id": "privileged_access",
            "title": _("Privileged access"),
            "description": _("Who holds Super Admin, how it was granted, and their open sessions."),
            "url": reverse("administration:privileged_access"),
        },
        {
            "id": "audit_log",
            "title": _("Audit log"),
            "description": _("Append-only record of every privileged action."),
            "url": reverse("audit:audit_log"),
        },
        {
            "id": "recognition_anomalies",
            "title": _("Recognition anomalies"),
            "description": _("Velocity and duplicate-award review before recognition is trusted."),
            "url": reverse("recognition:anomaly_review"),
        },
        {
            "id": "django_admin",
            "title": _("Model administration"),
            "description": _("Direct record maintenance for reference data and accounts."),
            "url": reverse("admin:index"),
        },
    ]
