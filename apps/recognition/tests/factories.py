import factory

from apps.contributions.tests.factories import ContributionRecordFactory
from apps.recognition.enums import AwardStatus, BadgeKind
from apps.recognition.models import Badge, BadgeAward, ContributionScore, ScoringPolicy


class BadgeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Badge

    name = factory.Sequence(lambda n: f"Verified contributor {n}")
    slug = factory.Sequence(lambda n: f"verified-contributor-{n}")
    criteria_md = "Accepted contribution to a DevNepal-listed project."
    kind = BadgeKind.CONTRIBUTION


class ScoringPolicyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScoringPolicy

    version = factory.Sequence(lambda n: n + 1)
    rules = factory.LazyFunction(lambda: {"minor": 1, "standard": 3, "major": 5})
    is_active = False


class ContributionScoreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContributionScore

    contribution = factory.SubFactory(ContributionRecordFactory)
    policy = factory.SubFactory(ScoringPolicyFactory)
    points = 3


class BadgeAwardFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BadgeAward

    badge = factory.SubFactory(BadgeFactory)
    recipient = factory.LazyAttribute(lambda obj: ContributionRecordFactory().contributor)
    issuer = None
    status = AwardStatus.ACTIVE
