"""Language-prefixed public GitHub snapshot routes."""

from django.urls import path

from apps.github_sync import views

app_name = "github_sync_public"

urlpatterns = [
    path("github/people/<str:login>/", views.public_profile, name="public_profile"),
]
