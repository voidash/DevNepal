from django import forms
from django.utils.translation import gettext_lazy as _

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
