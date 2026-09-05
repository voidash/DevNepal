from django.urls import path

from apps.recognition import views

app_name = "recognition"

urlpatterns = [
    path("recognition/me/", views.my_profile, name="my_profile"),
    path("recognition/me/leaderboard-opt-out/", views.leaderboard_opt_out, name="opt_out"),
    path("recognition/badges/", views.public_badges, name="public_badges"),
    path("recognition/badges/<str:slug>/", views.public_badge_detail, name="public_badge_detail"),
    path("recognition/policy/", views.public_policy, name="public_policy"),
    path("leaderboard/", views.public_leaderboard, name="leaderboard"),
    path("admin/recognition/policies/", views.policy_create, name="policy_create"),
    path("admin/recognition/badges/", views.badge_list, name="badge_list"),
    path("admin/recognition/badges/new/", views.badge_create, name="badge_create"),
    path("admin/recognition/badges/<slug:slug>/", views.badge_edit, name="badge_edit"),
    path("admin/recognition/badges/<slug:slug>/award/", views.badge_award, name="badge_award"),
    path("admin/recognition/awards/<int:pk>/revoke/", views.award_revoke, name="award_revoke"),
    path("admin/recognition/anomalies/", views.anomaly_review, name="anomaly_review"),
]
