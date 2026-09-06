from django.contrib.admin import AdminSite
from django.utils.translation import gettext_lazy as _

from apps.accounts.permissions import is_super_admin
from apps.accounts.services import mfa_verified


class DevNepalAdminSite(AdminSite):
    """SRS:309/SEC-008: restrict model administration to MFA-verified Super Admins.

    Django's default rule admits any ``is_staff`` account. The SRS requires every
    privileged surface to be Super Admin only and behind multi-factor
    authentication, so both conditions are checked before the site renders.
    """

    site_title = _("DevNepal administration")
    site_header = _("DevNepal administration")
    index_title = _("Reference data and records")

    def has_permission(self, request):
        return is_super_admin(request.user) and mfa_verified(request.user)
