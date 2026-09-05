import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.blogs.tests.factories import BlogPostFactory
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.ministries.tests.factories import SuperAdminFactory
from apps.moderation.tests.factories import ModerationCaseFactory
from apps.notifications.tests.factories import NotificationFactory

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_sec005_member_cannot_edit_foreign_blog_post(client):
    """SEC-005-U1: foreign blog edit yields 404 without field leakage."""
    author = UserFactory(username="author-a")
    post = BlogPostFactory(author=author)
    intruder = client
    intruder.force_login(UserFactory(username="member-b"))

    response = intruder.get(reverse("blogs:edit", kwargs={"post_id": post.pk}))

    assert response.status_code == 404
    assert post.title.encode() not in response.content


@pytest.mark.integration
def test_sec005_member_cannot_mark_foreign_notification_read(client):
    """SEC-005-U1: foreign notification read yields 404 without field leakage."""
    notification = NotificationFactory()
    intruder = client
    intruder.force_login(UserFactory(username="member-c"))

    response = intruder.post(reverse("notifications:read", kwargs={"pk": notification.pk}))

    assert response.status_code == 404
    assert notification.title.encode() not in response.content


@pytest.mark.integration
def test_sec005_member_cannot_view_foreign_report_case(client):
    """SEC-005-U1: report confirmation is reporter-scoped; strangers get 404."""
    case = ModerationCaseFactory()
    intruder = client
    intruder.force_login(UserFactory(username="member-d"))

    response = intruder.get(reverse("moderation:report_confirmation", kwargs={"pk": case.pk}))

    assert response.status_code == 404


@pytest.mark.integration
def test_sec005_member_cannot_open_moderation_case_queue_views(client):
    """SEC-005-U1: function-level moderation views deny plain members."""
    ModerationCaseFactory()
    intruder = client
    intruder.force_login(UserFactory(username="member-e"))

    response = intruder.get(reverse("moderation:case_detail", kwargs={"pk": 1}))

    assert response.status_code == 403


@pytest.mark.integration
def test_sec005_member_cannot_create_recognition_policy(client):
    """SEC-005-U1: function-level recognition administration denies plain members."""
    intruder = client
    intruder.force_login(UserFactory(username="member-f"))

    response = intruder.get(reverse("recognition:policy_create"))

    assert response.status_code == 403


@pytest.mark.integration
def test_sec005_member_cannot_view_foreign_contribution(client):
    """SEC-005-U1: contribution detail is participant-scoped; strangers get 404."""
    record = ContributionRecordFactory()
    intruder = client
    intruder.force_login(UserFactory(username="member-g"))

    response = intruder.get(reverse("contributions:detail", kwargs={"contribution_id": record.pk}))

    assert response.status_code == 404
    assert record.title.encode() not in response.content


@pytest.mark.integration
def test_srs309_super_admin_without_verified_mfa_is_gated_at_function_level(client):
    """SRS:309/SEC-005: privileged views redirect MFA-less super admins to enrollment."""
    super_admin = SuperAdminFactory()
    case = ModerationCaseFactory()
    intruder = client
    intruder.force_login(super_admin)

    response = intruder.get(reverse("moderation:case_detail", kwargs={"pk": case.pk}))

    assert response.status_code == 302
    assert reverse("accounts:mfa_setup") in response.url
