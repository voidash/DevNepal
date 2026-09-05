from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("accounts/login/", views.LocalLoginView.as_view(), name="login"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/github/connect/", views.github_connect, name="github_connect"),
    path(
        "accounts/github/login/callback/",
        views.github_callback,
        name="github_callback",
    ),
    path(
        "accounts/logout/",
        views.LocalLogoutView.as_view(next_page="projects:home"),
        name="logout",
    ),
    path("members/", views.member_directory, name="member_directory"),
    path("members/<str:username>/", views.public_profile, name="public_profile"),
    path("settings/profile/", views.profile_edit, name="profile_edit"),
    path("settings/profile/preview/", views.profile_preview, name="profile_preview"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/mfa/", views.mfa_setup, name="mfa_setup"),
    path("settings/sessions/", views.session_list, name="session_list"),
    path("settings/sessions/<int:pk>/revoke/", views.session_revoke, name="session_revoke"),
    path("settings/privacy/export/", views.privacy_export, name="privacy_export"),
    path("settings/privacy/delete/", views.privacy_delete, name="privacy_delete"),
]
