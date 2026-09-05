import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import override_settings
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts import services
from apps.accounts.enums import Availability, Province
from apps.accounts.services import (
    export_profile_data,
    request_account_deletion,
)
from apps.accounts.tests.factories import (
    MemberEducationFactory,
    MemberLinkFactory,
    MemberProfileFactory,
    UserFactory,
    UserSessionFactory,
)
from apps.audit.models import AuditEvent
from apps.contributions.tests.factories import ContributionRecordFactory
from apps.github_sync.tests.factories import GithubConnectionFactory
from apps.taxonomy.enums import ContentLanguage

pytestmark = pytest.mark.django_db


@pytest.mark.integration
def test_auth010_i1_export_returns_complete_profile_data():
    """AUTH-010-I1: export returns the member's complete profile, education, and links."""
    user = UserFactory(email="sita@example.com", first_name="Sita", last_name="Karki")
    MemberProfileFactory(
        user=user,
        headline="Civic-tech engineer",
        bio="Builds public services",
        location="Kathmandu",
        province=Province.BAGMATI,
        preferred_language=ContentLanguage.NEPALI,
        experience_band="senior",
        availability=Availability.AVAILABLE_NOW,
        interests="open data",
        contribution_preferences="documentation",
        field_visibility={"location": "public"},
        leaderboard_opt_out=True,
    )
    education = MemberEducationFactory(user=user, institution="Tribhuvan University")
    link = MemberLinkFactory(user=user, url="https://github.com/sita", is_public=True, label="Code")

    data = export_profile_data(user)

    assert data["account"]["username"] == user.username
    assert data["account"]["email"] == "sita@example.com"
    assert data["account"]["first_name"] == "Sita"
    assert data["account"]["date_joined"]
    exported_profile = data["profile"]
    assert exported_profile["headline"] == "Civic-tech engineer"
    assert exported_profile["location"] == "Kathmandu"
    assert exported_profile["province"] == Province.BAGMATI
    assert exported_profile["preferred_language"] == ContentLanguage.NEPALI
    assert exported_profile["availability"] == Availability.AVAILABLE_NOW
    assert exported_profile["interests"] == "open data"
    assert exported_profile["contribution_preferences"] == "documentation"
    assert exported_profile["field_visibility"] == {"location": "public"}
    assert exported_profile["leaderboard_opt_out"] is True
    assert exported_profile["created_at"]
    assert data["education"] == [
        {
            "institution": "Tribhuvan University",
            "credential": education.credential,
            "field_of_study": education.field_of_study,
            "start_year": education.start_year,
            "end_year": education.end_year,
            "created_at": education.created_at.isoformat(),
        }
    ]
    assert data["links"] == [
        {
            "link_type": link.link_type,
            "url": "https://github.com/sita",
            "label": "Code",
            "is_public": True,
            "created_at": link.created_at.isoformat(),
        }
    ]


@pytest.mark.integration
def test_auth010_i1_export_works_for_user_without_profile():
    """AUTH-010-I1: export degrades honestly when the member never created a profile."""
    user = UserFactory()
    data = export_profile_data(user)
    assert data["account"]["username"] == user.username
    assert data["profile"] is None
    assert data["education"] == []
    assert data["links"] == []
    assert data["skills"] == []


@pytest.mark.integration
def test_auth010_export_includes_contribution_records_and_audit_event():
    """AUTH-010: an owner export contains their contribution records and is auditable."""
    user = UserFactory()
    contribution = ContributionRecordFactory(contributor=user)

    data = export_profile_data(user)

    assert data["contributions"] == [
        {
            "id": contribution.pk,
            "project_id": contribution.project_id,
            "contribution_type_id": contribution.contribution_type_id,
            "title": contribution.title,
            "description": contribution.description,
            "evidence_url": contribution.evidence_url,
            "evidence_file": contribution.evidence_file.name
            if contribution.evidence_file
            else None,
            "source": contribution.source,
            "provider_event_ref": contribution.provider_event_ref,
            "status": contribution.status,
            "impact_tier": contribution.impact_tier,
            "verified_at": contribution.verified_at.isoformat()
            if contribution.verified_at
            else None,
            "verification_note": contribution.verification_note,
            "revocation_reason": contribution.revocation_reason,
            "revoked_at": contribution.revoked_at.isoformat() if contribution.revoked_at else None,
            "created_at": contribution.created_at.isoformat(),
            "updated_at": contribution.updated_at.isoformat(),
        }
    ]
    audit = AuditEvent.objects.get(action="account.data_export", actor=user)
    assert audit.after == {"contribution_count": 1}


@pytest.mark.integration
def test_auth010_deletion_anonymizes_account_and_retains_required_evidence(
    django_capture_on_commit_callbacks,
):
    """AUTH-010: deletion erases account data, revokes access, and retains evidence."""
    user = UserFactory(
        username="sita-karki",
        email="sita@example.com",
        first_name="Sita",
        last_name="Karki",
    )
    MemberProfileFactory(user=user, headline="Civic-tech engineer")
    MemberEducationFactory(user=user)
    MemberLinkFactory(user=user)
    session = UserSessionFactory(user=user)
    Session.objects.create(
        session_key=session.session_key,
        session_data="",
        expire_date=timezone.now(),
    )
    TOTPDevice.objects.create(user=user, name="devnepal")
    contribution = ContributionRecordFactory(contributor=user)
    connection = GithubConnectionFactory(user=user)

    with django_capture_on_commit_callbacks(execute=True):
        request_account_deletion(user)

    anonymized = get_user_model().objects.get(pk=user.pk)
    contribution.refresh_from_db()
    connection.refresh_from_db()
    assert anonymized.username == f"deleted-{user.pk}"
    assert anonymized.email == ""
    assert anonymized.first_name == ""
    assert anonymized.last_name == ""
    assert anonymized.is_active is False
    assert anonymized.has_usable_password() is False
    assert not hasattr(anonymized, "profile")
    assert not anonymized.education.exists()
    assert not anonymized.links.exists()
    assert not anonymized.skills.exists()
    assert not anonymized.sessions.exists()
    assert not Session.objects.filter(session_key=session.session_key).exists()
    assert not TOTPDevice.objects.filter(user=anonymized).exists()
    assert contribution.contributor is None
    assert connection.revoked_at is not None
    assert AuditEvent.objects.filter(action="account.deletion_requested", actor=anonymized).exists()
    assert AuditEvent.objects.filter(action="account.anonymized", actor=anonymized).exists()
    assert AuditEvent.objects.filter(
        action="github_connection.disconnect", actor=anonymized
    ).exists()


@pytest.mark.integration
def test_auth010_deletion_failure_does_not_disconnect_github_or_purge_tokens(monkeypatch):
    """AUTH-010/GIT-011: a failed deletion never performs irreversible GitHub cleanup."""
    connection = GithubConnectionFactory()
    user = connection.user
    purges = []

    def fail_anonymization(*args, **kwargs):
        raise RuntimeError("simulated user save failure")

    def purge_tokens(deleted_user):
        purges.append(deleted_user)
        return 1

    monkeypatch.setattr(type(user), "save", fail_anonymization)

    with override_settings(GITHUB_TOKEN_PURGE=purge_tokens):
        with pytest.raises(RuntimeError, match="simulated user save failure"):
            services.request_account_deletion(user)

    connection.refresh_from_db()
    user.refresh_from_db()
    assert connection.is_active is True
    assert purges == []
    assert user.is_active is True
    assert AuditEvent.objects.filter(action="github_connection.disconnect").exists() is False
