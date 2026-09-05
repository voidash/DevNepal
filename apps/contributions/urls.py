from django.urls import path

from apps.contributions import views

app_name = "contributions"

urlpatterns = [
    path("contributions/verification-queue/", views.verification_queue, name="verification_queue"),
    path("contributions/submit/<int:project_id>/", views.submit, name="submit"),
    path("contributions/<int:contribution_id>/", views.detail, name="detail"),
    path("contributions/<int:contribution_id>/history/", views.history, name="history"),
    path("contributions/<int:contribution_id>/verify/", views.verify_contribution, name="verify"),
    path("contributions/<int:contribution_id>/revoke/", views.revoke_contribution, name="revoke"),
]
