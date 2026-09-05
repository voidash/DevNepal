from django.contrib.admin.apps import AdminConfig


class DevNepalAdminConfig(AdminConfig):
    """SRS:309: serve django.contrib.admin through the MFA-gated Super Admin site.

    This lives outside ``apps.py`` on purpose: Django treats every ``AppConfig``
    subclass found in an app's ``apps`` module as a candidate default, and a
    second one there makes the app's default ambiguous.
    """

    default_site = "apps.administration.admin_site.DevNepalAdminSite"
