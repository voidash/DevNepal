import pytest

from apps.projects.tests.factories import ProjectFactory
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.models import TaxonomyTerm

pytestmark = [pytest.mark.django_db]

GOV_008_CATEGORIES = [
    "Engineering",
    "UI/UX",
    "QA",
    "Security",
    "Data",
    "Documentation",
    "Localization",
    "Research",
    "Community support",
]


@pytest.mark.integration
def test_project_supports_code_and_noncode_contribution_categories():
    """GOV-008: a project carries the nine seeded contribution categories, code and non-code."""
    categories = TaxonomyTerm.objects.filter(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, is_active=True, label__in=GOV_008_CATEGORIES
    )
    assert categories.count() == 9

    project = ProjectFactory()
    project.contribution_types.set(categories)
    project.refresh_from_db()
    labels = set(project.contribution_types.values_list("label", flat=True))
    assert labels == set(GOV_008_CATEGORIES)


@pytest.mark.integration
def test_project_contribution_need_links_skills_and_technologies():
    """GOV-002/DSC-002: contribution need groups contribution types, skills, and technologies."""
    from apps.projects.tests.factories import ProjectTaskFactory
    from apps.taxonomy.tests.factories import SkillFactory, TaxonomyTermFactory

    project = ProjectFactory()
    skill = SkillFactory(name="Distributed Systems")
    technology = TaxonomyTermFactory(vocabulary=TermVocabulary.TECHNOLOGY, label="Python")
    project.skills.add(skill)
    project.technologies.add(technology)
    task = ProjectTaskFactory(project=project)
    task.skills.add(skill)

    assert list(project.skills.values_list("name", flat=True)) == ["Distributed Systems"]
    assert list(project.technologies.values_list("label", flat=True)) == ["Python"]
    assert list(task.skills.all()) == [skill]
