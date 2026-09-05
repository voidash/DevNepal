from django.urls import path

from apps.ministries import views

app_name = "ministries"

urlpatterns = [
    path("admin/ministries/", views.organization_list, name="organization_list"),
    path(
        "admin/ministries/requests/new/",
        views.onboarding_request_create,
        name="onboarding_request_create",
    ),
    path(
        "admin/ministries/requests/<str:reference>/",
        views.onboarding_request_detail,
        name="onboarding_request_detail",
    ),
    path(
        "admin/ministries/requests/<str:reference>/provision/",
        views.onboarding_request_provision,
        name="onboarding_request_provision",
    ),
    path(
        "admin/ministries/requests/<str:reference>/decline/",
        views.onboarding_request_decline,
        name="onboarding_request_decline",
    ),
    path("admin/ministries/create/", views.organization_create, name="organization_create"),
    path("admin/ministries/<slug:slug>/", views.organization_detail, name="organization_detail"),
    path(
        "admin/ministries/<slug:slug>/action/",
        views.organization_action,
        name="organization_action",
    ),
    path(
        "admin/ministries/<slug:slug>/publishers/create/",
        views.publisher_create,
        name="publisher_create",
    ),
    path(
        "admin/publishers/<int:publisher_id>/action/",
        views.publisher_action,
        name="publisher_action",
    ),
    path(
        "publishers/<int:publisher_id>/contact-confirm/",
        views.contact_confirmation,
        name="contact_confirmation",
    ),
    path(
        "publishers/<int:publisher_id>/contact-reissue/",
        views.contact_reissue,
        name="contact_reissue",
    ),
]
