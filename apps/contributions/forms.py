from django import forms
from django.utils.translation import gettext_lazy as _

from apps.contributions.services import InvalidEvidenceFileError, validate_evidence_file
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.models import TaxonomyTerm


class EvidenceForm(forms.Form):
    title = forms.CharField(max_length=200, label=_("Title"))
    contribution_type = forms.ModelChoiceField(
        queryset=TaxonomyTerm.objects.none(), label=_("Contribution type")
    )
    description = forms.CharField(required=False, widget=forms.Textarea, label=_("Description"))
    evidence_url = forms.URLField(required=False, label=_("Evidence link"))
    evidence_file = forms.FileField(required=False, label=_("Evidence file"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contribution_type"].queryset = TaxonomyTerm.objects.filter(
            vocabulary=TermVocabulary.CONTRIBUTION_TYPE,
            is_active=True,
        ).order_by("label")

    def clean(self):
        cleaned_data = super().clean()
        if not (
            cleaned_data.get("description")
            or cleaned_data.get("evidence_url")
            or cleaned_data.get("evidence_file")
        ):
            raise forms.ValidationError(
                _("Provide a description, an evidence link, or an evidence file.")
            )
        return cleaned_data

    def clean_evidence_file(self):
        evidence_file = self.cleaned_data.get("evidence_file")
        if evidence_file is None:
            return None
        try:
            validate_evidence_file(evidence_file)
        except InvalidEvidenceFileError as error:
            raise forms.ValidationError(str(error), code="invalid_evidence_file") from error
        return evidence_file
