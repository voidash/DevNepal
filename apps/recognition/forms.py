from typing import ClassVar

from django import forms
from django.utils.translation import gettext_lazy as _

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
