from typing import ClassVar

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.recognition.enums import CorrectionKind, CorrectionReason, CorrectionStatus
from apps.recognition.models import Badge
from apps.taxonomy.fields import normalize_nfc


class ScoringPolicyForm(forms.Form):
    rules = forms.JSONField(label=_("Scoring rules"), widget=forms.Textarea)
    document_url = forms.URLField(required=False, label=_("Public policy document URL"))


class BadgeForm(forms.ModelForm):
    class Meta:
        model = Badge
        fields = (
            "name",
            "slug",
            "description",
            "criteria_md",
            "criteria_version",
            "kind",
            "icon",
            "is_active",
        )
        labels: ClassVar = {
            "name": _("Name"),
            "slug": _("Slug"),
            "description": _("Description"),
            "criteria_md": _("Documented criteria"),
            "criteria_version": _("Criteria version"),
            "kind": _("Badge kind"),
            "icon": _("Icon"),
            "is_active": _("Active"),
        }
        widgets: ClassVar = {"description": forms.Textarea, "criteria_md": forms.Textarea}


class BadgeAwardForm(forms.Form):
    username = forms.CharField(label=_("Member username"), max_length=150)
    reason = forms.CharField(label=_("Award reason"), widget=forms.Textarea)

    def clean_username(self):
        return normalize_nfc(self.cleaned_data["username"])

    def clean_reason(self):
        value = normalize_nfc(self.cleaned_data["reason"])
        if not value:
            raise forms.ValidationError(_("An award reason is required."))
        return value


class BadgeRevokeForm(forms.Form):
    reason = forms.CharField(label=_("Revocation reason"), widget=forms.Textarea)

    def clean_reason(self):
        value = normalize_nfc(self.cleaned_data["reason"])
        if not value:
            raise forms.ValidationError(_("A revocation reason is required."))
        return value


class RecognitionCorrectionForm(forms.Form):
    kind = forms.ChoiceField(choices=CorrectionKind.choices, label=_("Correction"))
    contribution_ids = forms.CharField(
        label=_("Contribution record IDs"),
        help_text=_("Enter one or more IDs, separated by commas."),
    )
    reason = forms.ChoiceField(choices=CorrectionReason.choices, label=_("Reason"))
    basis = forms.CharField(label=_("Basis"), widget=forms.Textarea)
    member_note = forms.CharField(label=_("Note to the member"), widget=forms.Textarea)
    adjusted_points = forms.IntegerField(
        required=False,
        min_value=0,
        label=_("Corrected score"),
        help_text=_("Required for consolidation and score adjustment."),
    )

    def clean_contribution_ids(self):
        raw = normalize_nfc(self.cleaned_data["contribution_ids"])
        values = [value.strip() for value in raw.split(",") if value.strip()]
        try:
            ids = [int(value) for value in values]
        except ValueError as error:
            raise forms.ValidationError(_("Use comma-separated numeric record IDs.")) from error
        if not ids or any(value < 1 for value in ids) or len(set(ids)) != len(ids):
            raise forms.ValidationError(_("Select one or more distinct contribution record IDs."))
        return ids

    def clean(self):
        cleaned = super().clean()
        for field in ("reason", "basis", "member_note"):
            value = normalize_nfc(str(cleaned.get(field) or "")).strip()
            if not value:
                self.add_error(field, _("This field is required."))
            cleaned[field] = value
        if cleaned.get("kind") in {CorrectionKind.CONSOLIDATE, CorrectionKind.ADJUST_SCORE} and (
            cleaned.get("adjusted_points") is None
        ):
            self.add_error(
                "adjusted_points", _("A corrected score is required for this correction.")
            )
        return cleaned


class CorrectionAppealForm(forms.Form):
    grounds = forms.CharField(label=_("Appeal grounds"), widget=forms.Textarea)

    def clean_grounds(self):
        value = normalize_nfc(self.cleaned_data["grounds"]).strip()
        if not value:
            raise forms.ValidationError(_("Appeal grounds are required."))
        return value


class CorrectionAppealResolutionForm(forms.Form):
    outcome = forms.ChoiceField(
        choices=[
            (CorrectionStatus.UPHELD, CorrectionStatus.UPHELD.label),
            (CorrectionStatus.OVERTURNED, CorrectionStatus.OVERTURNED.label),
        ],
        label=_("Appeal outcome"),
    )
    reason = forms.CharField(label=_("Decision reason"), widget=forms.Textarea)

    def clean_reason(self):
        value = normalize_nfc(self.cleaned_data["reason"]).strip()
        if not value:
            raise forms.ValidationError(_("A decision reason is required."))
        return value
