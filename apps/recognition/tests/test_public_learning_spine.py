import io

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.blogs.models import BlogPost

pytestmark = pytest.mark.django_db


@pytest.mark.integration
@override_settings(RECOGNITION_ENABLED=True)
def test_a3_public_learning_spine_renders_seeded_records_with_public_provenance(client):
    """A3.1/A3.3/A3.4/A3.6/A3.7; BLG-004/MEM-003/MEM-005/REC-002/REC-007:
    public learning pages use real published records and explain their boundaries."""
    call_command("seed_prototype_demo", stdout=io.StringIO())
    aarati_post = BlogPost.objects.get(
        title="Handling Bikram Sambat dates in PostgreSQL without losing your mind"
    )

    blog_list = client.get(reverse("blogs:list"))
    blog_detail = client.get(reverse("blogs:detail", kwargs={"post_id": aarati_post.pk}))
    directory = client.get(reverse("accounts:member_directory"))
    profile = client.get(reverse("accounts:public_profile", kwargs={"username": "aarati-shrestha"}))
    leaderboard = client.get(reverse("recognition:leaderboard"))
    badges = client.get(reverse("recognition:public_badges"))
    badge_detail = client.get(reverse("recognition:public_badge_detail", args=["code-shipper"]))
    policy = client.get(reverse("recognition:public_policy"))

    assert blog_list.status_code == 200
    assert "Featured technical writing" in blog_list.content.decode()
    assert blog_list.context["featured_post"] == aarati_post
    assert "Handling Bikram Sambat dates in PostgreSQL without losing your mind" in (
        blog_list.content.decode()
    )
    assert "External article" in blog_list.content.decode()
    assert "Read the external article" in blog_list.content.decode()

    assert blog_detail.status_code == 200
    assert "Publication details" in blog_detail.content.decode()
    assert "Safe Markdown" in blog_detail.content.decode()
    assert "View author profile" in blog_detail.content.decode()

    assert directory.status_code == 200
    assert "Public profiles appear only when a member chooses discovery" in (
        directory.content.decode()
    )
    assert "aarati-shrestha" in directory.content.decode()
    assert "nisha-maharjan" in directory.content.decode()

    assert profile.status_code == 200
    assert "Public profile" in profile.content.decode()
    assert "Private by default" in profile.content.decode()
    assert "aarati-shrestha" in profile.content.decode()
    assert "demo-pmo-admin@example.invalid" not in profile.content.decode()

    assert leaderboard.status_code == 200
    assert "How rankings work" in leaderboard.content.decode()
    assert "aarati-shrestha" in leaderboard.content.decode()
    assert "kritika-poudel" in leaderboard.content.decode()
    assert "Not total commits" in leaderboard.content.decode()

    assert badges.status_code == 200
    assert "Code Shipper" in badges.content.decode()
    assert "How to earn" in badges.content.decode()
    assert badge_detail.status_code == 200
    assert "Award record" in badge_detail.content.decode()
    assert "Criteria version" in badge_detail.content.decode()

    assert policy.status_code == 200
    assert "Scoring is versioned" in policy.content.decode()
    assert "No personal activity or private repository data is used" in policy.content.decode()
