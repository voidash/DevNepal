from django.urls import path

from apps.github_sync import views

app_name = "github_sync"

urlpatterns = [
    path("webhooks/github/", views.github_webhook, name="webhook"),
    path("github/connection/", views.connection_status, name="connection"),
    path(
        "github/connection/disconnect/",
        views.disconnect_connection,
        name="disconnect",
    ),
    path(
        "github/connect-repository/",
        views.connect_repository,
        name="connect_repository",
    ),
]
