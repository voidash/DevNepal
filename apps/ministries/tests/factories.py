from django.contrib.auth import get_user_model
from factory import Sequence, SubFactory, post_generation
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import attach_otp_verification
from apps.ministries.enums import ContactVerificationStatus, OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher


class UserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = Sequence(lambda n: f"member{n}")
    is_active = True


class PrivilegedUserFactory(UserFactory):
    @post_generation
    def otp_verified(obj, create, extracted, **kwargs):
        if create:
            attach_otp_verification(obj)


class SuperAdminFactory(PrivilegedUserFactory):
    is_superuser = True
    is_staff = True


class MinistryOrganizationFactory(DjangoModelFactory):
    class Meta:
        model = MinistryOrganization

    name_en = Sequence(lambda n: f"Ministry of Communication and Information Technology {n}")
    slug = Sequence(lambda n: f"moit-{n}")
    website_url = "https://www.moit.gov.np"
    status = OrgStatus.ACTIVE


class MinistryPublisherFactory(DjangoModelFactory):
    class Meta:
        model = MinistryPublisher

    user = SubFactory(PrivilegedUserFactory)
    ministry = SubFactory(MinistryOrganizationFactory)
    title = "Information Officer"
    official_email = Sequence(lambda n: f"officer{n}@moit.gov.np")
    status = PublisherStatus.ACTIVE
    contact_verification_status = ContactVerificationStatus.VERIFIED
    assigned_by = SubFactory(SuperAdminFactory)

    @post_generation
    def otp_verified(obj, create, extracted, **kwargs):
        if create:
            attach_otp_verification(obj.user)
