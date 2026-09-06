from django.urls import path

from apps.contributions import views

app_name = "contributions"

urlpatterns = [
    path("contributions/verification-queue/", views.verification_queue, name="verification_queue"),
    path("contributions/submit/<int:project_id>/", views.submit, name="submit"),
    path("contributions/<int:contribution_id>/", views.detail, name="detail"),
    path("contributions/<int:contribution_id>/history/", views.history, name="history"),
    path("contributions/<int:contribution_id>/verify/", views.verify_contribution, name="verify"),
    path("contributions/<int:contribution_id>/hold/", views.hold_contribution, name="hold"),
    path(
        "contributions/<int:contribution_id>/release-hold/",
        views.release_contribution_hold,
        name="release_hold",
    ),
    path(
        "contributions/<int:contribution_id>/hold-response/",
        views.respond_to_contribution_hold,
        name="hold_response",
    ),
    path("contributions/<int:contribution_id>/revoke/", views.revoke_contribution, name="revoke"),
]
