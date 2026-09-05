from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.ministries.models import MinistryOrganization


class MinistryOrganizationForm(forms.ModelForm):
    class Meta:
        model = MinistryOrganization
        fields = (
            "name_en",
            "name_ne",
            "slug",
            "abbreviation",
            "description",
            "contact_email",
            "website_url",
        )


class PublisherCreateForm(forms.Form):
    user = forms.ModelChoiceField(queryset=get_user_model().objects.none(), label=_("User"))
    title = forms.CharField(max_length=120, label=_("Official title"))
    official_email = forms.EmailField(label=_("Official email"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            get_user_model().objects.filter(is_active=True).order_by("username")
        )


class MinistryActionForm(forms.Form):
    ACTIVATE = "activate"
    SUSPEND = "suspend"
    REVOKE = "revoke"

    action = forms.ChoiceField(
        choices=(
            (ACTIVATE, _("Activate")),
            (SUSPEND, _("Suspend")),
            (REVOKE, _("Revoke")),
        ),
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(required=False, widget=forms.Textarea, label=_("Reason"))


class PublisherActionForm(forms.Form):
    SUSPEND = "suspend"
    REVOKE = "revoke"

    action = forms.ChoiceField(
        choices=((SUSPEND, _("Suspend")), (REVOKE, _("Revoke"))),
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(widget=forms.Textarea, label=_("Reason"))


class ContactConfirmationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput)
