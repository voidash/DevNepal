from factory import Sequence
from factory.django import DjangoModelFactory

from apps.administration.models import FeatureFlag


class FeatureFlagFactory(DjangoModelFactory):
    class Meta:
        model = FeatureFlag

    key = Sequence(lambda n: f"capability-{n}")
    label = Sequence(lambda n: f"Capability {n}")
    description = "Prototype capability switch."
    scope = "Everyone"
    owner = "Product owner"
    reason = "Initial configuration."
    affects_members = False
    is_enabled = False


class MemberFacingFlagFactory(FeatureFlagFactory):
    """D5.7: a switch that changes what members see, so it needs four eyes."""

    key = Sequence(lambda n: f"member-capability-{n}")
    affects_members = True
