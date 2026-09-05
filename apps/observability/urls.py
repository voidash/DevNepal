from django.urls import path

from apps.observability import views

app_name = "observability"

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("readyz", views.readyz, name="readyz"),
    path("metrics", views.metrics, name="metrics"),
]
