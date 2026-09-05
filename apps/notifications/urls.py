from django.urls import path

from apps.notifications import views

app_name = "notifications"

urlpatterns = [
    path("notifications/", views.notification_list, name="list"),
    path("notifications/email-preferences/", views.email_preferences, name="email_preferences"),
    path("notifications/read-all/", views.notification_read_all, name="read_all"),
    path("notifications/<int:pk>/read/", views.notification_read, name="read"),
]
