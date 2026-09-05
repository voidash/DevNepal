from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.projects.urls")),
    path("", include("apps.moderation.urls")),
    path("", include("apps.github_sync.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.audit.urls")),
]
