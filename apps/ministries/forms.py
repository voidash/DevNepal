import typing

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.ministries.models import MinistryOnboardingRequest, MinistryOrganization


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


class MinistryOnboardingRequestForm(forms.ModelForm):
    signatory_verified = forms.BooleanField(
        label=_("I verified the letter signatory with the ministry focal contact"),
        required=True,
    )

    class Meta:
        model = MinistryOnboardingRequest
        fields = (
            "name_en",
            "name_ne",
            "abbreviation",
            "website_url",
            "official_email",
            "nominated_officer_name",
            "nominated_officer_title",
            "purpose",
            "focal_contact",
            "nomination_reference",
            "signatory_name",
            "signatory_verified",
        )
        labels: typing.ClassVar = {
            "name_en": _("Organization name (English)"),
            "name_ne": _("Organization name (Nepali)"),
            "abbreviation": _("Organization code"),
            "website_url": _("Official website"),
            "official_email": _("Nominated officer's official email"),
            "nominated_officer_name": _("Nominated officer"),
            "nominated_officer_title": _("Designation"),
            "purpose": _("Purpose"),
            "focal_contact": _("Focal contact who verified the signatory"),
            "nomination_reference": _("Nomination letter reference"),
            "signatory_name": _("Letter signatory"),
        }


class OnboardingRequestDeclineForm(forms.Form):
    reason = forms.CharField(
        label=_("Reason for declining"),
        widget=forms.Textarea,
        max_length=2000,
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
