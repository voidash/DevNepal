import typing

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.administration.models import FeatureFlag


class FeatureFlagForm(forms.ModelForm):
    class Meta:
        model = FeatureFlag
        fields = ("key", "label", "description", "scope", "owner", "reason", "affects_members")
        labels: typing.ClassVar[dict] = {
            "key": _("Key"),
            "label": _("Switch"),
            "description": _("What this switch controls"),
            "scope": _("Scope"),
            "owner": _("Owner"),
            "reason": _("Reason"),
            "affects_members": _("Changes what members see"),
        }
        help_texts: typing.ClassVar[dict] = {
            "key": _("Lowercase identifier used by the code that reads this switch."),
            "scope": _("Who the switch applies to, for example Everyone or Pilot ministries."),
            "owner": _("The role accountable for this decision, for example Product owner."),
            "affects_members": _(
                "A switch that changes what members see needs a second Super Admin to confirm "
                "every change to it."
            ),
        }


class FeatureFlagChangeForm(forms.Form):
    """D5.7: a switch change always carries the reason it was made."""

    reason = forms.CharField(
        label=_("Reason for this change"),
        widget=forms.Textarea(attrs={"rows": 2}),
        max_length=1000,
    )


class SuperAdminGrantForm(forms.Form):
    """AUTH-003/D5.8: propose a Super Admin grant, naming the person and the reason."""

    username = forms.CharField(label=_("Username to grant Super Admin"), max_length=150)
    reason = forms.CharField(
        label=_("Reason for this grant"),
        widget=forms.Textarea(attrs={"rows": 2}),
        max_length=1000,
    )


class SuperAdminRevokeForm(forms.Form):
    """AUTH-003/D5.8: revocation takes effect at once and still records why."""

    reason = forms.CharField(
        label=_("Reason for revoking"),
        widget=forms.Textarea(attrs={"rows": 2}),
        max_length=1000,
    )
