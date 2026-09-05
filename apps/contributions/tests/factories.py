import factory

from apps.contributions.enums import ContributionSource, VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.projects.tests.factories import ProjectFactory, UserFactory
from apps.taxonomy.enums import TermVocabulary
from apps.taxonomy.models import TaxonomyTerm


def contribution_type(slug: str) -> TaxonomyTerm:
    """Return a seeded active CONTRIBUTION_TYPE term (GOV-008 vocabulary)."""
    term = TaxonomyTerm.objects.filter(
        vocabulary=TermVocabulary.CONTRIBUTION_TYPE, slug=slug, is_active=True
    ).first()
    if term is None:
        raise AssertionError(f"seeded contribution type '{slug}' is missing")
    return term


class ContributionRecordFactory(factory.django.DjangoModelFactory):
    """CANDIDATE member-submitted record by default (BR-006 evidence state)."""

    class Meta:
        model = ContributionRecord

    class Params:
        provider_event = factory.Trait(
            source=ContributionSource.PROVIDER_EVENT,
            provider_event_ref=factory.Sequence(lambda n: f"github:{100000 + n}"),
        )

    project = factory.SubFactory(ProjectFactory)
    contributor = factory.SubFactory(UserFactory)
    contribution_type = factory.LazyFunction(lambda: contribution_type("engineering"))
    title = factory.Sequence(lambda n: f"Contribution {n}")
    description = ""
    evidence_url = ""
    source = ContributionSource.MEMBER_SUBMISSION
    provider_event_ref = ""
    status = VerificationStatus.CANDIDATE
    impact_tier = "standard"
