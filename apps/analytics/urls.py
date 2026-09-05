from django.urls import path

from apps.analytics import views

app_name = "analytics"

urlpatterns = [
    path("reports/monthly/", views.public_monthly_report, name="public_monthly_report"),
    path(
        "reports/monthly/export.json",
        views.public_monthly_report_export,
        name="public_monthly_report_export",
    ),
    path(
        "analytics/ministries/<int:ministry_id>/",
        views.ministry_dashboard,
        name="ministry_dashboard",
    ),
]
