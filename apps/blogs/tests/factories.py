import typing

from django.contrib.auth import get_user_model
from factory import Sequence, SubFactory
from factory.django import DjangoModelFactory

from apps.blogs.enums import BlogStatus
from apps.blogs.models import BlogPost, BlogVersion
from apps.taxonomy.enums import ContentLanguage, TermVocabulary
from apps.taxonomy.models import TaxonomyTerm


class UserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = Sequence(lambda n: f"member{n}")
    is_active = True


class TagFactory(DjangoModelFactory):
    class Meta:
        model = TaxonomyTerm

    vocabulary = TermVocabulary.TAG
    label = Sequence(lambda n: f"Django {n}")
    slug = Sequence(lambda n: f"django-{n}")


class BlogPostFactory(DjangoModelFactory):
    class Meta:
        model = BlogPost

    author = SubFactory(UserFactory)
    title = Sequence(lambda n: f"Shipping Nepali NLP pipelines {n}")
    excerpt = "Notes from routing Devanagari text through an open pipeline."
    canonical_url = Sequence(lambda n: f"https://medium.com/@writer{n}/nepali-nlp-pipelines")
    language = ContentLanguage.ENGLISH
    reading_time_minutes = 5
    status = BlogStatus.DRAFT


class BlogVersionFactory(DjangoModelFactory):
    class Meta:
        model = BlogVersion

    post = SubFactory(BlogPostFactory)
    version_number = 1
    snapshot: typing.ClassVar[dict] = {
        "title": "Shipping Nepali NLP pipelines",
        "excerpt": "Notes from routing Devanagari text through an open pipeline.",
        "canonical_url": "https://medium.com/@writer/nepali-nlp-pipelines",
        "language": ContentLanguage.ENGLISH,
        "reading_time_minutes": 5,
        "tags": [],
    }
    created_by = SubFactory(UserFactory)
