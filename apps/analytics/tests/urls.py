from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.projects.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.blogs.urls")),
    path("", include("apps.contributions.urls")),
    path("", include("apps.ministries.urls")),
    path("", include("apps.moderation.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.recognition.urls")),
    path("", include("apps.taxonomy.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.github_sync.urls")),
    path("", include("apps.analytics.urls")),
]
