from django.urls import path

from apps.moderation import views

app_name = "moderation"

urlpatterns = [
    path("reports/new/", views.report_create, name="report_create"),
    path("reports/<int:pk>/", views.report_confirmation, name="report_confirmation"),
    path("cases/", views.case_queue, name="case_queue"),
    path("community-health/", views.community_health, name="community_health"),
    path("cases/<int:pk>/", views.case_detail, name="case_detail"),
    path("cases/<int:pk>/assign/", views.case_assign, name="case_assign"),
    path("cases/<int:pk>/decide/", views.case_decide, name="case_decide"),
    path("cases/<int:pk>/export/", views.case_export, name="case_export"),
    path("cases/<int:pk>/appeal/", views.appeal_case, name="appeal"),
    path("cases/<int:pk>/appeal/resolve/", views.appeal_resolve, name="appeal_resolve"),
]
