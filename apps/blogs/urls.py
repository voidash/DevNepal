from django.urls import path

from apps.blogs import views

app_name = "blogs"

urlpatterns = [
    path("blogs/", views.blog_list, name="list"),
    path("blogs/new/", views.blog_create, name="create"),
    path("blogs/mine/", views.my_blog_list, name="mine"),
    path("blogs/<int:post_id>/", views.blog_detail, name="detail"),
    path("blogs/<int:post_id>/edit/", views.blog_edit, name="edit"),
    path("blogs/<int:post_id>/publish/", views.blog_publish, name="publish"),
    path(
        "blogs/<int:post_id>/publish-official/",
        views.blog_publish_official,
        name="publish_official",
    ),
    path("blogs/<int:post_id>/unpublish/", views.blog_unpublish, name="unpublish"),
    path("blogs/<int:post_id>/archive/", views.blog_archive, name="archive"),
]
