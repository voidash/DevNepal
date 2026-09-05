import pytest
from django.db import IntegrityError, transaction

from apps.projects.tests.factories import (
    PersonalProjectFactory,
    ProjectBookmarkFactory,
    ProjectFactory,
    UserFactory,
)

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_bookmark_unique_per_user_and_project():
    """DSC-004: a member bookmarks a project once."""
    bookmark = ProjectBookmarkFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectBookmarkFactory(user=bookmark.user, project=bookmark.project)
    other_user = ProjectBookmarkFactory(user=UserFactory(), project=bookmark.project)
    assert other_user.pk != bookmark.pk


@pytest.mark.unit
def test_bookmark_opt_in_change_notification_default():
    """DSC-004: change notification is opt-in through notify_on_change."""
    bookmark = ProjectBookmarkFactory()
    assert bookmark.notify_on_change is True
    quiet = ProjectBookmarkFactory(notify_on_change=False)
    assert quiet.notify_on_change is False


@pytest.mark.unit
def test_bookmark_works_across_project_types():
    """DSC-004: bookmarks apply to government and community projects alike."""
    government = ProjectBookmarkFactory(project=ProjectFactory())
    community = ProjectBookmarkFactory(project=PersonalProjectFactory())
    assert government.project.project_type == "government"
    assert community.project.project_type == "personal"
