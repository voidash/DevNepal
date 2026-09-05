import unicodedata

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.contributions.enums import ContributionSource, ImpactTier, VerificationStatus
from apps.contributions.models import ContributionRecord
from apps.contributions.tests.factories import ContributionRecordFactory

pytestmark = [pytest.mark.django_db]


@pytest.mark.unit
def test_enums_match_the_normative_data_model():
    """BR-006: ContributionSource, VerificationStatus, and ImpactTier values are literal."""
    assert dict(ContributionSource.choices) == {
        "provider_event": "Authoritative provider event",
        "maintainer_attestation": "Maintainer attestation",
        "member_submission": "Member-submitted evidence",
    }
    assert dict(VerificationStatus.choices) == {
        "candidate": "Candidate",
        "pending_info": "Clarification requested",
        "accepted": "Accepted",
        "rejected": "Rejected",
        "revoked": "Revoked",
    }
    assert dict(ImpactTier.choices) == {
        "minor": "Minor",
        "standard": "Standard",
        "major": "Major",
    }


@pytest.mark.unit
def test_user_text_is_nfc_normalized_on_save():
    """DSC-003: titles and descriptions are stored NFC-normalized for search and display."""
    nfc_title = "योगदान ऱेकर्ड"
    nfd_title = unicodedata.normalize("NFD", nfc_title)
    assert nfd_title != nfc_title
    record = ContributionRecordFactory(title=nfd_title, description=nfd_title)
    stored = ContributionRecord.objects.get(pk=record.pk)
    assert stored.title == nfc_title
    assert stored.description == nfc_title


@pytest.mark.unit
def test_project_deletion_is_protected_so_evidence_survives():
    """BR-008: deleting/unpublishing a project must not erase contribution evidence."""
    record = ContributionRecordFactory()
    with pytest.raises(ProtectedError):
        record.project.delete()
    assert ContributionRecord.objects.filter(pk=record.pk).exists()


@pytest.mark.unit
def test_contributor_anonymisation_retains_the_record():
    """AUTH-010/§9.3: account deletion keeps the record with attribution cleared."""
    record = ContributionRecordFactory()
    contributor = record.contributor
    contributor.delete()
    record.refresh_from_db()
    assert record.contributor is None
    assert ContributionRecord.objects.filter(pk=record.pk).exists()


@pytest.mark.unit
def test_one_record_per_provider_event_structurally():
    """A5/GIT-005: provider event provenance is unique, so no duplicate credit rows."""
    first = ContributionRecordFactory(provider_event=True, provider_event_ref="github:1")
    assert first.provider_event_ref == "github:1"
    with pytest.raises(IntegrityError), transaction.atomic():
        ContributionRecordFactory(provider_event_ref="github:1")
    ContributionRecordFactory()
    assert ContributionRecord.objects.count() == 2
