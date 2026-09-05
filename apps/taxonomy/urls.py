from django.urls import path

from apps.taxonomy import views

app_name = "taxonomy"

urlpatterns = [
    path("skills/suggest/", views.skill_suggestion_create, name="skill_suggestion_create"),
    path(
        "admin/taxonomy/skill-suggestions/",
        views.skill_suggestion_review_list,
        name="skill_suggestion_review_list",
    ),
    path(
        "admin/taxonomy/skill-suggestions/<int:pk>/review/",
        views.skill_suggestion_review,
        name="skill_suggestion_review",
    ),
    path("admin/taxonomy/skills/", views.skill_management, name="skill_management"),
    path("admin/taxonomy/skills/<slug:slug>/state/", views.skill_state, name="skill_state"),
    path("admin/taxonomy/skills/<slug:slug>/merge/", views.skill_merge, name="skill_merge"),
    path("admin/taxonomy/licences/", views.license_management, name="license_management"),
    path(
        "admin/taxonomy/licences/<int:pk>/decision/",
        views.license_decision,
        name="license_decision",
    ),
]
