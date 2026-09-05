from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from apps.moderation.enums import AppealStatus, ModerationAction, ReportReason
from apps.moderation.services import EXPORT_MIN_PURPOSE_LENGTH


class ReportForm(forms.Form):
    content_type = forms.ModelChoiceField(
        queryset=ContentType.objects.none(), label=_("Target type")
    )
    object_id = forms.IntegerField(min_value=1, label=_("Target ID"))
    reason = forms.ChoiceField(choices=ReportReason.choices, label=_("Reason"))
    details = forms.CharField(required=False, widget=forms.Textarea, label=_("Details"))
    evidence_url = forms.URLField(required=False, label=_("Evidence URL"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["content_type"].queryset = ContentType.objects.filter(
            app_label__in=("accounts", "blogs", "contributions", "projects"),
            model__in=("user", "blogpost", "contributionrecord", "project", "projectlink"),
        )

    def clean(self):
        cleaned_data = super().clean()
        content_type = cleaned_data.get("content_type")
        object_id = cleaned_data.get("object_id")
        if content_type and object_id:
            try:
                cleaned_data["target"] = content_type.get_object_for_this_type(pk=object_id)
            except content_type.model_class().DoesNotExist:
                self.add_error("object_id", _("The report target does not exist."))
        return cleaned_data


class CaseDecisionForm(forms.Form):
    action = forms.ChoiceField(choices=ModerationAction.choices, label=_("Action"))
    reason = forms.ChoiceField(choices=ReportReason.choices, label=_("Reason"))
    comment = forms.CharField(required=False, widget=forms.Textarea, label=_("Comment"))


class CaseExportForm(forms.Form):
    purpose = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("Export purpose"),
        help_text=_(
            "Explain why this confidential record must be exported "
            "(minimum %(min_length)s characters)."
        )
        % {"min_length": EXPORT_MIN_PURPOSE_LENGTH},
    )


class AppealForm(forms.Form):
    grounds = forms.CharField(widget=forms.Textarea, label=_("Appeal grounds"))


class AppealResolutionForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=(
            (AppealStatus.UPHELD, AppealStatus.UPHELD.label),
            (AppealStatus.OVERTURNED, AppealStatus.OVERTURNED.label),
        ),
        label=_("Outcome"),
    )
    reason = forms.CharField(widget=forms.Textarea, label=_("Resolution reason"))
