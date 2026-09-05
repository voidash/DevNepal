import typing

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _

from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization
from apps.projects.enums import AttachmentKind, UpdateKind
from apps.projects.models import (
    SUITABILITY_AREAS,
    Project,
    ProjectMaintainer,
    ProjectMilestone,
    ProjectScreeningQuestion,
    ProjectTask,
)
from apps.taxonomy.enums import ContentLanguage, DataClassification

SUITABILITY_LABELS = {
    "legal_authority": _("Legal authority"),
    "source_code_rights": _("Source-code rights"),
    "data_classification": _("Data classification"),
    "security_exposure": _("Security exposure"),
    "procurement_restrictions": _("Procurement restrictions"),
    "third_party_licenses": _("Third-party licenses"),
    "repository_readiness": _("Repository readiness"),
    "maintainer_capacity": _("Maintainer capacity"),
    "contribution_agreement": _("Contribution agreement"),
    "public_communications": _("Public communications"),
}


class ProjectAuthoringForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = (
            "title_en",
            "title_ne",
            "summary_en",
            "summary_ne",
            "description_md",
            "problem_statement",
            "target_users",
            "expected_outcome",
            "success_indicators",
            "contribution_types",
            "skills",
            "technologies",
            "difficulty",
            "estimated_effort",
            "deadline",
            "contribution_mode",
            "prerequisites",
            "communication_channel",
            "response_sla",
            "repository_url",
            "default_branch",
            "issue_tracker_url",
            "documentation_url",
            "code_of_conduct_url",
            "license",
            "signoff_model",
            "data_classification",
            "security_contact",
            "vulnerability_disclosure_url",
        )
        labels: typing.ClassVar = {
            "title_en": _("English title"),
            "title_ne": _("Nepali title"),
            "summary_en": _("English summary"),
            "summary_ne": _("Nepali summary"),
            "description_md": _("Description"),
            "problem_statement": _("Problem statement"),
            "target_users": _("Target users"),
            "expected_outcome": _("Expected outcome"),
            "success_indicators": _("Success indicators"),
            "contribution_types": _("Contribution types"),
            "skills": _("Skills"),
            "technologies": _("Technologies"),
            "difficulty": _("Difficulty"),
            "estimated_effort": _("Estimated effort"),
            "deadline": _("Deadline"),
            "contribution_mode": _("Contribution mode"),
            "prerequisites": _("Contribution instructions and prerequisites"),
            "communication_channel": _("Public communication channel"),
            "response_sla": _("Expected first response"),
            "repository_url": _("Repository URL"),
            "default_branch": _("Default branch"),
            "issue_tracker_url": _("Issue or task entry URL"),
            "documentation_url": _("README or documentation URL"),
            "code_of_conduct_url": _("Code of conduct URL"),
            "license": _("Approved license"),
            "signoff_model": _("Contribution agreement"),
            "data_classification": _("Data classification"),
            "security_contact": _("Security contact"),
            "vulnerability_disclosure_url": _("Vulnerability disclosure URL"),
        }
        widgets: typing.ClassVar = {
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "description_md": forms.Textarea(attrs={"rows": 8}),
            "problem_statement": forms.Textarea(attrs={"rows": 4}),
            "target_users": forms.Textarea(attrs={"rows": 3}),
            "expected_outcome": forms.Textarea(attrs={"rows": 3}),
            "success_indicators": forms.Textarea(attrs={"rows": 3}),
            "prerequisites": forms.Textarea(attrs={"rows": 4}),
        }


class GovernmentDraftCreateForm(ProjectAuthoringForm):
    ministry = forms.ModelChoiceField(
        queryset=MinistryOrganization.objects.none(), label=_("Ministry")
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        ministries = MinistryOrganization.objects.filter(status=OrgStatus.ACTIVE)
        if not actor.is_superuser:
            ministries = ministries.filter(
                publishers__user=actor,
                publishers__status=PublisherStatus.ACTIVE,
                publishers__contact_verification_status=ContactVerificationStatus.VERIFIED,
            )
        self.fields["ministry"].queryset = ministries.order_by("name_en").distinct()


class PersonalProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = (
            "title_en",
            "title_ne",
            "summary_en",
            "summary_ne",
            "description_md",
            "role",
            "technologies",
            "skills",
            "deadline",
            "repository_url",
            "documentation_url",
            "issue_tracker_url",
        )
        labels: typing.ClassVar = {
            "title_en": _("English title"),
            "title_ne": _("Nepali title"),
            "summary_en": _("English summary"),
            "summary_ne": _("Nepali summary"),
            "description_md": _("Description"),
            "role": _("Your role"),
            "technologies": _("Technologies"),
            "skills": _("Skills"),
            "deadline": _("Project date"),
            "repository_url": _("Repository URL"),
            "documentation_url": _("Documentation URL"),
            "issue_tracker_url": _("Issue tracker URL"),
        }
        widgets: typing.ClassVar = {
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "description_md": forms.Textarea(attrs={"rows": 8}),
        }


class PersonalProjectWorkflowForm(forms.Form):
    action = forms.ChoiceField(
        choices=(
            ("publish", _("Publish")),
            ("unpublish", _("Unpublish")),
            ("archive", _("Archive")),
        )
    )
    reason = forms.CharField(required=False, widget=forms.Textarea, label=_("Archive reason"))

    def __init__(self, *args, allowed_actions=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_actions is not None:
            self.fields["action"].choices = [
                choice for choice in self.fields["action"].choices if choice[0] in allowed_actions
            ]


class DeliverablesField(forms.CharField):
    widget = forms.Textarea(attrs={"rows": 5})

    def prepare_value(self, value):
        if isinstance(value, list):
            return "\n".join(
                f"{item.get('label', '')} | {item.get('url', '')}".rstrip(" |")
                for item in value
                if isinstance(item, dict)
            )
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return []
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if len(lines) > 50:
            raise ValidationError(_("Add no more than 50 deliverables."))
        url_validator = URLValidator(schemes=("http", "https"))
        deliverables = []
        for line_number, line in enumerate(lines, start=1):
            label, separator, url = line.partition("|")
            label = label.strip()
            url = url.strip() if separator else ""
            if not label:
                raise ValidationError(
                    _("Deliverable %(line)s needs a label."), params={"line": line_number}
                )
            if len(label) > 200:
                raise ValidationError(
                    _("Deliverable %(line)s label must be 200 characters or fewer."),
                    params={"line": line_number},
                )
            if url:
                try:
                    url_validator(url)
                except ValidationError as error:
                    raise ValidationError(
                        _("Use an HTTP or HTTPS URL on deliverable line %(line)s."),
                        params={"line": line_number},
                    ) from error
            deliverables.append({"label": label, "url": url})
        return deliverables


class ProjectCompletionForm(forms.ModelForm):
    outcome_summary = forms.CharField(
        label=_("Outcome summary"), widget=forms.Textarea(attrs={"rows": 5})
    )
    deliverables = DeliverablesField(
        label=_("Deliverables and releases"),
        help_text=_("Add one per line as: Deliverable name | https://optional-link.example"),
    )
    impact_summary = forms.CharField(
        label=_("Impact summary"), widget=forms.Textarea(attrs={"rows": 4})
    )
    lessons_learned = forms.CharField(
        label=_("Lessons learned"), widget=forms.Textarea(attrs={"rows": 4})
    )

    class Meta:
        model = Project
        fields = ("outcome_summary", "deliverables", "impact_summary", "lessons_learned")


class ProjectWorkflowForm(forms.Form):
    action = forms.ChoiceField(
        choices=(
            ("submit", _("Submit for review")),
            ("resubmit", _("Resubmit for review")),
            ("request_changes", _("Request changes")),
            ("approve", _("Approve")),
            ("publish", _("Publish")),
            ("pause", _("Pause")),
            ("resume", _("Resume")),
            ("complete", _("Complete")),
            ("archive", _("Archive")),
            ("restore", _("Restore from archive")),
        )
    )
    reason = forms.CharField(required=False, widget=forms.Textarea, label=_("Reason"))

    def __init__(self, *args, allowed_actions=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_actions is not None:
            self.fields["action"].choices = [
                choice for choice in self.fields["action"].choices if choice[0] in allowed_actions
            ]

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("action") == "request_changes"
            and not cleaned_data.get("reason", "").strip()
        ):
            self.add_error("reason", _("A reason is required when requesting changes."))
        return cleaned_data


def editable_project_fields(form: ProjectAuthoringForm) -> dict:
    many_to_many_names = {field.name for field in form._meta.model._meta.many_to_many}
    return {
        field: form.cleaned_data[field]
        for field in form.changed_data
        if field in form.fields and field not in many_to_many_names
    }


class ProjectMaintainerForm(forms.ModelForm):
    class Meta:
        model = ProjectMaintainer
        fields = ("user", "role", "can_review_merge")
        labels: typing.ClassVar = {
            "user": _("Maintainer"),
            "role": _("Role"),
            "can_review_merge": _("Can review and merge"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            self.fields["user"].queryset.filter(is_active=True).order_by("username")
        )


class ProjectTaskForm(forms.ModelForm):
    class Meta:
        model = ProjectTask
        fields = ("title", "description", "is_starter", "issue_url", "skills", "status")
        labels: typing.ClassVar = {
            "title": _("Task title"),
            "description": _("Task description"),
            "is_starter": _("Suitable for first-time contributors"),
            "issue_url": _("Issue URL"),
            "skills": _("Skills"),
            "status": _("Task status"),
        }


class ProjectMilestoneForm(forms.ModelForm):
    class Meta:
        model = ProjectMilestone
        fields = ("title", "description", "due_date", "status", "sort_order")
        labels: typing.ClassVar = {
            "title": _("Milestone title"),
            "description": _("Milestone description"),
            "due_date": _("Due date"),
            "status": _("Milestone status"),
            "sort_order": _("Display order"),
        }
        widgets: typing.ClassVar = {"due_date": forms.DateInput(attrs={"type": "date"})}


class SuitabilityChecklistForm(forms.Form):
    notes = forms.CharField(required=False, widget=forms.Textarea, label=_("Suitability notes"))

    def __init__(self, *args, checklist=None, **kwargs):
        super().__init__(*args, **kwargs)
        checklist = checklist or {}
        for area in SUITABILITY_AREAS:
            self.fields[area] = forms.BooleanField(
                required=False,
                initial=checklist.get(area, {}).get("checked", False),
                label=SUITABILITY_LABELS[area],
            )


class ProjectAttachmentForm(forms.Form):
    kind = forms.ChoiceField(choices=AttachmentKind.choices, label=_("Attachment kind"))
    file = forms.FileField(label=_("File"))
    language = forms.ChoiceField(choices=ContentLanguage.choices, label=_("Language"))
    classification = forms.ChoiceField(
        choices=DataClassification.choices, label=_("Data classification")
    )
    accessibility_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label=_("Accessibility note"),
        help_text=_("Describe how the document can be used with assistive technology."),
    )


class ProjectUpdateForm(forms.Form):
    kind = forms.ChoiceField(choices=UpdateKind.choices, label=_("Update kind"))
    title = forms.CharField(max_length=200, label=_("Update title"))
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), label=_("Update body"))
    link = forms.URLField(required=False, label=_("Related release or result link"))


class ProjectScreeningQuestionForm(forms.ModelForm):
    class Meta:
        model = ProjectScreeningQuestion
        fields = ("question", "help_text", "is_required", "sort_order")
        labels: typing.ClassVar = {
            "question": _("Screening question"),
            "help_text": _("Help text"),
            "is_required": _("Answer required"),
            "sort_order": _("Display order"),
        }
