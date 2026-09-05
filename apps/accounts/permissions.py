from functools import wraps

from django.shortcuts import redirect

from apps.accounts.services import mfa_verified
from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryPublisher


def is_super_admin(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def is_ministry_publisher(user) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    return MinistryPublisher.objects.filter(
        user=user,
        status=PublisherStatus.ACTIVE,
        ministry__status=OrgStatus.ACTIVE,
    ).exists()


def requires_mfa(user) -> bool:
    return is_super_admin(user) or is_ministry_publisher(user)


def privileged_mfa_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if requires_mfa(request.user) and not mfa_verified(request.user):
            return redirect("accounts:mfa_setup")
        return view(request, *args, **kwargs)

    return wrapped
