import unicodedata

import pytest

from apps.ministries.enums import OrgStatus, PublisherStatus
from apps.ministries.models import MinistryOrganization, MinistryPublisher
from apps.ministries.tests.factories import (
    MinistryOrganizationFactory,
    MinistryPublisherFactory,
    UserFactory,
)

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def test_ministry_and_publisher_repr_and_defaults():
    """AUTH-004, BR-001: organizations default PENDING; officer assignments default ACTIVE."""
    assert MinistryOrganization().status == OrgStatus.PENDING
    org = MinistryOrganizationFactory()
    assert str(org) == org.name_en

    publisher = MinistryPublisherFactory(ministry=org)
    assert publisher.status == PublisherStatus.ACTIVE
    assert str(publisher) == f"{publisher.user.username} @ {org.name_en}"


def test_user_text_stored_nfc_normalized():
    """DSC-003: user-entered ministry text is NFC-normalized on save."""
    nfd_input = "Ministry of Communication" + "é" + " सूचना तथा सञ्चार प्रविधि"
    assert unicodedata.normalize("NFD", nfd_input) != unicodedata.normalize("NFC", nfd_input)

    org = MinistryOrganizationFactory(
        name_en=nfd_input,
        description=nfd_input,
        slug=unicodedata.normalize("NFD", "moit-sanchaar"),
    )
    org.refresh_from_db()
    assert org.name_en == unicodedata.normalize("NFC", nfd_input)
    assert org.description == unicodedata.normalize("NFC", nfd_input)
    assert org.slug == "moit-sanchaar"


def test_only_one_active_publisher_per_user_per_ministry():
    """AUTH-004, D14: historical revoked assignments do not prevent a new active assignment."""
    from django.db import IntegrityError, transaction

    org = MinistryOrganizationFactory()
    user = UserFactory()
    MinistryPublisherFactory(user=user, ministry=org)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MinistryPublisherFactory(user=user, ministry=org)

    MinistryPublisher.objects.filter(user=user, ministry=org).update(status=PublisherStatus.REVOKED)
    active_assignment = MinistryPublisherFactory(user=user, ministry=org)
    assert active_assignment.status == PublisherStatus.ACTIVE
    assert MinistryPublisher.objects.filter(user=user, ministry=org).count() == 2

    other_org = MinistryOrganizationFactory()
    assignment = MinistryPublisherFactory(user=user, ministry=other_org)
    assert assignment.ministry == other_org
    assert user.publisher_assignments.count() == 3
