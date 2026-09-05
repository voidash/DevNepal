import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import UserFactory
from apps.notifications.enums import Channel, NotificationType
from apps.notifications.models import Notification, NotificationPreference


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = Notification

    recipient = factory.SubFactory(UserFactory)
    type = NotificationType.PROJECT_UPDATE
    channel = Channel.IN_APP
    title = factory.Sequence(lambda n: f"Notification {n}")


class NotificationPreferenceFactory(DjangoModelFactory):
    class Meta:
        model = NotificationPreference

    user = factory.SubFactory(UserFactory)
