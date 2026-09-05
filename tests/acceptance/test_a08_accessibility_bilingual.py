import unicodedata

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import translation

from apps.blogs.enums import BlogStatus
from apps.blogs.tests.factories import BlogPostFactory
from apps.projects.enums import ContributionMode, ProjectStatus
from apps.projects.models import Application
from apps.projects.tests.factories import ProjectScreeningQuestionFactory, make_publishable

pytestmark = [pytest.mark.django_db, pytest.mark.acceptance]


def _open_application_project():
    project = make_publishable(
        title_en="Accessible public-service search",
        title_ne="पहुँचयोग्य सार्वजनिक सेवा खोज",
        contribution_mode=ContributionMode.APPLICATION,
    )
    project.status = ProjectStatus.OPEN_FOR_CONTRIBUTION
    project.save(update_fields=["status"])
    question = ProjectScreeningQuestionFactory(project=project, question="Availability?")
    return project, question


def test_a08_keyboard_and_bilingual_core_route_contract(client):
    """A8/NFR-A11Y-01/NFR-I18N-01: core public and member routes remain operable in Nepali.

    This executable check covers registration, a labelled search, an application,
    public blog reading, and account settings. Screen-reader, zoom/reflow, and
    low-bandwidth checks remain recorded manual evidence because Django's test
    client cannot operate an assistive technology stack.
    """
    project, question = _open_application_project()
    post = BlogPostFactory(
        author=project.owner,
        status=BlogStatus.PUBLISHED,
        title="Public-interest release notes",
    )

    registration = client.post(
        reverse("accounts:signup"),
        {
            "username": "a08-member",
            "email": "a08.member@example.com",
            "password1": "a08-strong-password-2026",
            "password2": "a08-strong-password-2026",
        },
    )
    sign_in = client.post(
        reverse("accounts:login"),
        {"username": "a08-member", "password": "a08-strong-password-2026"},
    )

    assert registration.status_code == 302
    assert sign_in.status_code == 302
    assert get_user_model().objects.filter(username="a08-member").exists()

    with translation.override("ne"):
        home_url = reverse("projects:home")
        catalog_url = reverse("projects:list")
        application_url = reverse("projects:apply", kwargs={"slug": project.slug})
        blogs_list_url = reverse("blogs:list")
        blog_url = reverse("blogs:detail", kwargs={"post_id": post.pk})
        settings_url = reverse("accounts:profile_edit")
        sessions_url = reverse("accounts:session_list")

    language_response = client.post(
        reverse("set_language"),
        {"language": "ne", "next": home_url},
    )
    home = client.get(home_url)
    catalog = client.get(catalog_url, {"q": unicodedata.normalize("NFD", project.title_ne)})
    blog = client.get(blog_url)
    settings = client.get(settings_url)
    sessions = client.get(sessions_url)
    application = client.post(
        application_url,
        {"motivation": "म पहुँचयोग्य सामग्रीमा योगदान गर्न चाहन्छु।", f"answer_{question.pk}": "10"},
    )

    assert language_response.status_code == 302
    assert language_response.url == home_url
    for response in (home, catalog, blog, settings, sessions):
        assert response.status_code == 200
        content = response.content.decode()
        assert '<html lang="ne"' in content
        assert 'class="btn dn-skip-link" href="#main-content"' in content
        assert 'id="main-content" tabindex="-1"' in content
        assert "onclick=" not in content.lower()
    assert project.title_ne in home.content.decode()
    assert project.title_ne in catalog.content.decode()
    assert f'href="{blogs_list_url}">प्रविधि ब्लगहरू</a>' in blog.content.decode()
    assert "प्रोफाइल सम्पादन गर्नुहोस्" in settings.content.decode()
    assert "साइन इन भएका उपकरणहरू" in sessions.content.decode()
    assert application.status_code == 302
    assert Application.objects.filter(project=project, applicant__username="a08-member").exists()
