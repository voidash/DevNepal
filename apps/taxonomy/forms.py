from django import forms
from django.utils.translation import gettext_lazy as _

from apps.taxonomy.enums import LicenseUse
from apps.taxonomy.models import Skill, SkillSuggestion


class SkillSuggestionForm(forms.ModelForm):
    class Meta:
        model = SkillSuggestion
        fields = ("term_name", "note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note"].widget = forms.Textarea(attrs={"rows": 4})

    def clean_term_name(self):
        term_name = self.cleaned_data["term_name"]
        if SkillSuggestion.objects.filter(term_name__iexact=term_name).exists():
            raise forms.ValidationError(_("This term is already awaiting review."))
        if Skill.objects.filter(name__iexact=term_name).exists():
            raise forms.ValidationError(_("This skill is already in the taxonomy."))
        return term_name


class SuggestionReviewForm(forms.Form):
    APPROVE = "approve"
    REJECT = "reject"

    decision = forms.ChoiceField(
        choices=((APPROVE, _("Approve")), (REJECT, _("Reject"))),
        widget=forms.HiddenInput,
    )


class SkillForm(forms.Form):
    """ADM-001/D5.5: both languages are required before a term can go live."""

    name = forms.CharField(label=_("Skill · English"), max_length=100)
    name_ne = forms.CharField(
        label=_("Skill · नेपाली"),
        max_length=100,
        required=False,
        help_text=_("A term stays hidden from pickers until both languages are present."),
    )
    description = forms.CharField(
        label=_("Description"), widget=forms.Textarea(attrs={"rows": 2}), required=False
    )


class SkillMergeForm(forms.Form):
    """ADM-001/D5.5: fold a duplicate into the term it should have been."""

    target = forms.CharField(label=_("Merge into skill slug"), max_length=120)


class LicenseForm(forms.Form):
    """ADM-001/D5.6: register an SPDX licence, pending until legal approval."""

    spdx_id = forms.CharField(label=_("SPDX identifier"), max_length=64)
    name = forms.CharField(label=_("Name"), max_length=200)
    use = forms.ChoiceField(label=_("Use"), choices=LicenseUse.choices)
    reference_url = forms.URLField(label=_("Legal reference URL"), required=False)
    legal_reference = forms.CharField(
        label=_("Legal approval reference"),
        max_length=60,
        required=False,
        help_text=_("For example PMO-L-2026-01. Leave blank while approval is pending."),
    )


class LicenseApprovalForm(forms.Form):
    legal_reference = forms.CharField(label=_("Legal approval reference"), max_length=60)


class LicenseWithdrawalForm(forms.Form):
    reason = forms.CharField(
        label=_("Reason for withdrawing"), widget=forms.Textarea(attrs={"rows": 2}), max_length=500
    )
