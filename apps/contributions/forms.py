from django import forms
from django.utils.translation import gettext_lazy as _

from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.models import TaxonomyTerm


class EvidenceForm(forms.Form):
    title = forms.CharField(max_length=200, label=_("Title"))
    contribution_type = forms.ModelChoiceField(
        queryset=TaxonomyTerm.objects.none(), label=_("Contribution type")
    )
    description = forms.CharField(required=False, widget=forms.Textarea, label=_("Description"))
    evidence_url = forms.URLField(required=False, label=_("Evidence link"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contribution_type"].queryset = TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.CONTRIBUTION_TYPE,
            is_active=True,
        ).order_by("label")

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("description") and not cleaned_data.get("evidence_url"):
            raise forms.ValidationError(_("Provide a description or an evidence link."))
        return cleaned_data
