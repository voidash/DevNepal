import factory
from django.contrib.auth import get_user_model

from apps.audit.models import AuditEvent


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.Sequence(lambda n: f"user-{n}@devnepal.gov.np")


class AuditEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditEvent

    actor = factory.SubFactory(UserFactory)
    action = factory.Sequence(lambda n: f"test.action.{n}")
    source = "web"
    result = "success"
    correlation_id = factory.Sequence(lambda n: f"corr-{n}")
