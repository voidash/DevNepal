import factory
from django.utils.text import slugify

from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.models import ApprovedLicense, Skill, SkillSuggestion, TaxonomyTerm


class SkillFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Skill

    name = factory.Sequence(lambda n: f"Skill {n}")
    slug = factory.LazyAttribute(lambda o: slugify(o.name, allow_unicode=True))
    description = factory.Sequence(lambda n: f"Description for skill {n}")
    is_active = True


class TaxonomyTermFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TaxonomyTerm

    vocabulary = TermVocabulary.CONTRIBUTION_TYPE
    label = factory.Sequence(lambda n: f"Term {n}")
    slug = factory.LazyAttribute(lambda o: slugify(o.label, allow_unicode=True))
    description = ""
    sort_order = 0
    is_active = True


class ApprovedLicenseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ApprovedLicense

    spdx_id = factory.Sequence(lambda n: f"License-{n}")
    name = factory.Sequence(lambda n: f"License {n} Full Name")
    reference_url = ""
    is_approved = True
    is_default = False


class SkillSuggestionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SkillSuggestion

    term_name = factory.Sequence(lambda n: f"Suggested skill {n}")
    note = ""
