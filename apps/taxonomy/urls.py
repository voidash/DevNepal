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
]
