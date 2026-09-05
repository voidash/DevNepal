import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_legacy_official_posts_without_project_provenance_are_repaired_and_audited():
    """BLG-007/ADM-008: the provenance constraint preserves legacy content without a false seal."""
    executor = MigrationExecutor(connection)
    executor.migrate([("blogs", "0004_blogpost_official_project")])
    old_apps = executor.loader.project_state([("blogs", "0004_blogpost_official_project")]).apps
    User = old_apps.get_model("accounts", "User")
    BlogPost = old_apps.get_model("blogs", "BlogPost")
    author = User.objects.create(username="legacy-official-author")
    legacy_post = BlogPost.objects.create(
        author_id=author.pk,
        title="Legacy ministry statement",
        canonical_url="https://example.gov.np/legacy-statement",
        is_official=True,
    )

    executor = MigrationExecutor(connection)
    executor.migrate([("blogs", "0005_blogpost_chk_official_blog_provenance")])
    new_apps = executor.loader.project_state(
        [("blogs", "0005_blogpost_chk_official_blog_provenance")]
    ).apps
    MigratedPost = new_apps.get_model("blogs", "BlogPost")
    AuditEvent = new_apps.get_model("audit", "AuditEvent")
    migrated_post = MigratedPost.objects.get(pk=legacy_post.pk)

    assert migrated_post.is_official is False
    assert migrated_post.official_published_by_id is None
    assert migrated_post.official_project_id is None
    assert AuditEvent.objects.filter(
        action="blog.official.legacy_provenance_cleared",
        object_id=str(legacy_post.pk),
        source="migration",
    ).exists()

    executor.migrate(executor.loader.graph.leaf_nodes())
