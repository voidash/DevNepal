from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("code-of-conduct/", views.code_of_conduct, name="code_of_conduct"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("security/", views.security_policy, name="security_policy"),
    path("ministry-onboarding/", views.ministry_onboarding, name="ministry_onboarding"),
    path("authoring/", views.authoring_dashboard, name="authoring_dashboard"),
    path("authoring/reviews/", views.review_queue, name="review_queue"),
    path("community/", views.community_dashboard, name="community_dashboard"),
    path("community/create/", views.community_create, name="community_create"),
    path("community/terms/accept/", views.community_accept_terms, name="community_accept_terms"),
    path(
        "community/<str:slug>/verify-github/",
        views.community_verify_github,
        name="community_verify_github",
    ),
    path("community/<str:slug>/", views.community_detail, name="community_detail"),
    path("community/<str:slug>/edit/", views.community_edit, name="community_edit"),
    path(
        "community/<str:slug>/workflow/",
        views.community_workflow,
        name="community_workflow",
    ),
    path("authoring/create/", views.authoring_create, name="authoring_create"),
    path("authoring/<str:slug>/", views.authoring_detail, name="authoring_detail"),
    path(
        "authoring/<str:slug>/readiness/",
        views.authoring_detail,
        {"tab": "readiness"},
        name="authoring_readiness",
    ),
    path(
        "authoring/<str:slug>/attachments/",
        views.authoring_attachment,
        name="authoring_attachment",
    ),
    path(
        "authoring/<str:slug>/updates/",
        views.authoring_detail,
        {"tab": "updates"},
        name="authoring_updates",
    ),
    path(
        "authoring/<str:slug>/questions/",
        views.authoring_detail,
        {"tab": "questions"},
        name="authoring_questions",
    ),
    path("authoring/<str:slug>/edit/", views.authoring_edit, name="authoring_edit"),
    path(
        "authoring/<str:slug>/completion/",
        views.completion_summary,
        name="completion_summary",
    ),
    path("authoring/<str:slug>/manage/", views.authoring_manage, name="authoring_manage"),
    path(
        "authoring/<str:slug>/workflow/",
        views.authoring_workflow,
        name="authoring_workflow",
    ),
    path("projects/", views.project_list, name="list"),
    path(
        "projects/gov/",
        views.project_list,
        {"project_type": "government"},
        name="government",
    ),
    path(
        "projects/community/",
        views.project_list,
        {"project_type": "personal"},
        name="community",
    ),
    path("projects/<str:slug>/bookmark/", views.toggle_bookmark, name="bookmark"),
    path("projects/<str:slug>/updates/", views.project_updates, name="updates"),
    path(
        "projects/<str:slug>/issues/<int:number>/",
        views.github_issue_detail,
        name="github_issue",
    ),
    path("projects/<str:slug>/apply/", views.apply, name="apply"),
    path("applications/", views.application_list, name="application_list"),
    path(
        "applications/<int:application_id>/",
        views.application_detail,
        name="application_detail",
    ),
    path(
        "applications/<int:application_id>/timeline/",
        views.application_timeline,
        name="application_timeline",
    ),
    path(
        "applications/<int:application_id>/withdraw/",
        views.application_withdraw,
        name="application_withdraw",
    ),
    path(
        "applications/<int:application_id>/provide-info/",
        views.application_provide_info,
        name="application_provide_info",
    ),
    path(
        "applications/<int:application_id>/decide/",
        views.application_decide,
        name="application_decide",
    ),
    path("projects/<str:slug>/", views.project_detail, name="detail"),
]
