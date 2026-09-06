from django.urls import path

from apps.audit import views

app_name = "audit"

urlpatterns = [
    path("audit/", views.audit_log, name="audit_log"),
    path("audit/my-actions/", views.my_actions, name="my_actions"),
    path("audit/my-actions/export/", views.export_my_actions, name="export_my_actions"),
    path("audit/ops/", views.ops_dashboard, name="ops_dashboard"),
]
