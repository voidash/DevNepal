from apps.accounts.permissions import is_super_admin
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryPublisher

ANONYMOUS_ROLES = {
    "viewer_is_super_admin": False,
    "viewer_is_ministry_publisher": False,
    "viewer_ministry_id": None,
}


def roles(request):
    """AUTH-006: expose the viewer's authorization role so shared navigation can branch."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return dict(ANONYMOUS_ROLES)
    if is_super_admin(user):
        return {
            "viewer_is_super_admin": True,
            "viewer_is_ministry_publisher": False,
            "viewer_ministry_id": None,
        }
    publisher = (
        MinistryPublisher.objects.filter(
            user=user,
            status=PublisherStatus.ACTIVE,
            ministry__status=OrgStatus.ACTIVE,
        )
        .values_list("ministry_id", flat=True)
        .first()
    )
    return {
        "viewer_is_super_admin": False,
        "viewer_is_ministry_publisher": publisher is not None,
        "viewer_ministry_id": publisher,
    }
