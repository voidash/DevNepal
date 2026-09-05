from django.urls import include, path

urlpatterns = [
    path("", include("apps.projects.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.contributions.urls")),
    path("", include("apps.recognition.urls")),
    path("", include("apps.moderation.urls")),
]
