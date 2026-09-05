from django.urls import path

from apps.audit import views

app_name = "audit"

urlpatterns = [
    path("audit/", views.audit_log, name="audit_log"),
    path("audit/ops/", views.ops_dashboard, name="ops_dashboard"),
]
