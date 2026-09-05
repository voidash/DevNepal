import factory

from apps.analytics.enums import EventName
from apps.analytics.models import AnalyticsEventRecord
from apps.projects.tests.factories import ProjectFactory


class AnalyticsEventRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnalyticsEventRecord

    event_name = EventName.PROJECT_VIEWED
    ministry = factory.SelfAttribute("project.ministry")
    project = factory.SubFactory(ProjectFactory)
