from django.urls import path

from apps.administration import views

app_name = "administration"

urlpatterns = [
    path("admin-console/", views.console, name="console"),
    path("admin-console/feature-flags/", views.feature_flags, name="feature_flags"),
    path(
        "admin-console/feature-flags/<slug:key>/change/",
        views.feature_flag_change,
        name="feature_flag_change",
    ),
    path(
        "admin-console/feature-flags/changes/<int:change_id>/approve/",
        views.feature_flag_approve,
        name="feature_flag_approve",
    ),
    path("admin-console/privileged-access/", views.privileged_access, name="privileged_access"),
    path(
        "admin-console/privileged-access/grants/<int:grant_id>/confirm/",
        views.super_admin_grant_confirm,
        name="super_admin_grant_confirm",
    ),
    path(
        "admin-console/privileged-access/<str:username>/revoke/",
        views.super_admin_revoke,
        name="super_admin_revoke",
    ),
]
