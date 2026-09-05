import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent
from apps.notifications.enums import DigestFrequency
from apps.notifications.models import NotificationPreference
from apps.notifications.tests.factories import NotificationPreferenceFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

NOTIFICATION_URLCONF = override_settings(ROOT_URLCONF="apps.notifications.tests.urls")


def preferences_url():
    return reverse("notifications:email_preferences")


@NOTIFICATION_URLCONF
def test_ntf002_preferences_page_requires_login(client):
    """NTF-002: the email-preferences page is member-only."""
    response = client.get(preferences_url())

    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('accounts:login')}?next=")


@NOTIFICATION_URLCONF
def test_ntf002_preferences_page_lists_categories_and_digest(client):
    """NTF-002: members see toggles for every non-essential email category plus digest frequency."""
    member = UserFactory()
    NotificationPreferenceFactory(user=member, email_community=True)
    client.force_login(member)

    response = client.get(preferences_url())

    assert response.status_code == 200
    html = response.content.decode()
    assert "Application and assignment emails" in html
    assert "Review emails" in html
    assert "Contribution emails" in html
    assert "Community and project update emails" in html
    assert "Digest frequency" in html
    assert DigestFrequency.WEEKLY in html


@NOTIFICATION_URLCONF
def test_ntf002_mandatory_notices_are_shown_as_locked(client):
    """NTF-002: the page states security/administrative notices cannot be disabled."""
    member = UserFactory()
    client.force_login(member)

    response = client.get(preferences_url())

    html = response.content.decode()
    assert "cannot be disabled" in html


@NOTIFICATION_URLCONF
def test_ntf002_preferences_never_change_on_get(client):
    """NTF-002: rendering the preferences page never mutates stored preferences."""
    member = UserFactory()
    NotificationPreferenceFactory(user=member, email_applications=False)
    client.force_login(member)

    client.get(preferences_url())

    preference = NotificationPreference.objects.get(user=member)
    assert preference.email_applications is False


@NOTIFICATION_URLCONF
def test_ntf002_save_is_csrf_protected():
    """NTF-002: saving preferences without a CSRF token is rejected."""
    member = UserFactory()
    NotificationPreferenceFactory(user=member)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(member)

    response = csrf_client.post(preferences_url(), {"email_applications": "on"})

    assert response.status_code == 403
    preference = NotificationPreference.objects.get(user=member)
    assert preference.email_applications is True


@NOTIFICATION_URLCONF
def test_ntf002_save_persists_toggles_and_audits(client):
    """NTF-002: a CSRF-valid POST persists each category toggle and records an audit event."""
    member = UserFactory()
    NotificationPreferenceFactory(
        user=member,
        email_applications=True,
        email_reviews=True,
        email_contributions=True,
        email_community=False,
    )
    client.force_login(member)

    response = client.post(
        preferences_url(),
        {
            "email_applications": "on",
            "email_reviews": "on",
            "email_contributions": "on",
            "email_community": "on",
            "digest_frequency": DigestFrequency.WEEKLY,
        },
    )

    preference = NotificationPreference.objects.get(user=member)
    assert response.status_code == 302
    assert response.url == preferences_url()
    assert preference.email_community is True
    assert preference.digest_frequency == DigestFrequency.WEEKLY
    event = AuditEvent.objects.get(
        action="notification.preferences_update",
        object_id=str(preference.pk),
        actor=member,
    )
    assert event.before["email_community"] is False
    assert event.after["email_community"] is True
    assert event.after["digest_frequency"] == DigestFrequency.WEEKLY


@NOTIFICATION_URLCONF
def test_ntf002_unchecked_category_is_saved_as_off(client):
    """NTF-002: a category left untoggled in the form is stored as opted out."""
    member = UserFactory()
    NotificationPreferenceFactory(user=member, email_reviews=True)
    client.force_login(member)

    client.post(
        preferences_url(),
        {
            "email_applications": "on",
            "digest_frequency": DigestFrequency.NONE,
        },
    )

    preference = NotificationPreference.objects.get(user=member)
    assert preference.email_reviews is False
    assert preference.email_applications is True


@NOTIFICATION_URLCONF
def test_ntf002_notification_list_links_to_preferences(client):
    """NTF-002: the in-app notification list header links to the email preferences page."""
    member = UserFactory()
    client.force_login(member)

    list_response = client.get(reverse("notifications:list"))
    preferences_response = client.get(preferences_url())

    assert list_response.status_code == 200
    assert preferences_response.status_code == 200
    assert f'href="{preferences_url()}"' in list_response.content.decode()
