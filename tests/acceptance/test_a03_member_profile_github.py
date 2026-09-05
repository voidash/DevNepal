import pytest
from django.test import override_settings

from apps.accounts.tests.factories import MemberProfileFactory, UserFactory
from apps.github_sync.enums import SyncState
from apps.github_sync.services import disconnect
from apps.github_sync.tests.factories import GithubConnectionFactory, RepositoryConnectionFactory
from apps.projects.tests.factories import PersonalProjectFactory

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def test_a03_member_profile_personal_project_and_github_disconnect():
    """A3/AUTH-002/GIT-011/PPR-001: disconnect stops sync without losing the profile."""
    member = UserFactory()
    profile = MemberProfileFactory(
        user=member,
        field_visibility={"location": "public", "links": "public"},
    )
    personal_project = PersonalProjectFactory(owner=member, ministry=None)
    connection = GithubConnectionFactory(user=member, login="devnepal-member")
    repository = RepositoryConnectionFactory(activated_by=member, project=personal_project)

    with override_settings(GITHUB_TOKEN_PURGE=None):
        disconnected = disconnect(member)

    profile.refresh_from_db()
    repository.refresh_from_db()
    assert disconnected.revoked_at is not None
    assert repository.sync_state == SyncState.STOPPED
    assert profile.field_visibility["location"] == "public"
    assert personal_project.owner == member
    assert connection.login == "devnepal-member"
