import typing

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.notifications.models import NotificationPreference


class EmailPreferencesForm(forms.ModelForm):
    """NTF-002: member-controlled non-essential email categories and digest frequency."""

    class Meta:
        model = NotificationPreference
        fields: typing.ClassVar[list[str]] = [
            "email_applications",
            "email_reviews",
            "email_contributions",
            "email_community",
            "digest_frequency",
        ]
        labels: typing.ClassVar[dict[str, str]] = {
            "email_applications": _("Application and assignment emails"),
            "email_reviews": _("Review emails"),
            "email_contributions": _("Contribution emails"),
            "email_community": _("Community and project update emails"),
            "digest_frequency": _("Digest frequency"),
        }
