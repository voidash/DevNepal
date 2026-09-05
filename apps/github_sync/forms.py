from django import forms
from django.utils.translation import gettext_lazy as _

from apps.taxonomy.fields import normalize_nfc


class ReconciliationRunForm(forms.Form):
    """D5.4/SEC-008: purpose required before a privileged reconciliation action."""

    purpose = forms.CharField(
        label=_("Purpose for this run"),
        max_length=1000,
        min_length=8,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 1000}),
        help_text=_(
            "State why this reconciliation is needed. This is kept in the immutable audit trail."
        ),
    )

    def clean_purpose(self):
        purpose = normalize_nfc(self.cleaned_data["purpose"]).strip()
        if len(purpose) < 8:
            raise forms.ValidationError(_("Provide at least 8 characters describing this run."))
        return purpose
