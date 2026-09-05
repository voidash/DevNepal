import factory
from django.contrib.contenttypes.models import ContentType

from apps.ministries.tests.factories import SuperAdminFactory, UserFactory
from apps.moderation.enums import CaseEventType, CaseStatus, ReportReason
from apps.moderation.models import ModerationCase, ModerationEvent, Report
from apps.projects.tests.factories import ProjectFactory


class ReportFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Report
        exclude = ("target",)

    target = factory.SubFactory(ProjectFactory)
    reporter = factory.SubFactory(UserFactory)
    content_type = factory.LazyAttribute(lambda o: ContentType.objects.get_for_model(o.target))
    object_id = factory.LazyAttribute(lambda o: str(o.target.pk))
    reason = ReportReason.SPAM
    details = ""
    evidence_url = ""


class ModerationCaseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ModerationCase

    report = factory.SubFactory(ReportFactory)
    assigned_to = None
    status = CaseStatus.NEW


class ModerationEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ModerationEvent

    case = factory.SubFactory(ModerationCaseFactory)
    actor = factory.SubFactory(SuperAdminFactory)
    event = CaseEventType.CREATED
    comment = ""
