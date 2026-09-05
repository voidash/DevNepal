from functools import partial

import factory
from django_otp.middleware import is_verified
from django_otp.plugins.otp_totp.models import TOTPDevice
from factory.django import DjangoModelFactory

from apps.accounts.enums import LinkType
from apps.accounts.models import (
    MemberEducation,
    MemberLink,
    MemberProfile,
    MemberSkill,
    User,
    UserSession,
)
from apps.taxonomy.tests.factories import SkillFactory


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"member{n}")
    email = factory.Sequence(lambda n: f"member{n}@example.com")


class OTPVerifiedUserFactory(UserFactory):
    @factory.post_generation
    def otp_verified(obj, create, extracted, **kwargs):
        if not create:
            return
        attach_otp_verification(obj)


def attach_otp_verification(user):
    device, _ = TOTPDevice.objects.get_or_create(user=user, name="devnepal")
    user.otp_device = device
    user.is_verified = partial(is_verified, user)
    return user


class MemberProfileFactory(DjangoModelFactory):
    class Meta:
        model = MemberProfile

    user = factory.SubFactory(UserFactory)


class MemberEducationFactory(DjangoModelFactory):
    class Meta:
        model = MemberEducation

    user = factory.SubFactory(UserFactory)
    institution = factory.Sequence(lambda n: f"Institute of Technology {n}")


class MemberLinkFactory(DjangoModelFactory):
    class Meta:
        model = MemberLink

    user = factory.SubFactory(UserFactory)
    link_type = LinkType.GITHUB
    url = factory.Sequence(lambda n: f"https://github.com/member{n}")


class MemberSkillFactory(DjangoModelFactory):
    class Meta:
        model = MemberSkill

    user = factory.SubFactory(UserFactory)
    skill = factory.SubFactory(SkillFactory)
    self_rating = ""


class UserSessionFactory(DjangoModelFactory):
    class Meta:
        model = UserSession

    user = factory.SubFactory(UserFactory)
    session_key = factory.Sequence(lambda n: f"{n:040d}")
    device_label = "Firefox on Linux"
