"""URL configuration for the DevNepal platform."""

from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
    path("", include("apps.github_sync.urls")),
]

urlpatterns += i18n_patterns(
    path("", include("apps.projects.urls")),
    path("", include("apps.analytics.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.administration.urls")),
    path("", include("apps.blogs.urls")),
    path("", include("apps.contributions.urls")),
    path("", include("apps.ministries.urls")),
    path("", include("apps.moderation.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.recognition.urls")),
    path("", include("apps.taxonomy.urls")),
    path("", include("apps.audit.urls")),
)
