import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditEvent
from apps.taxonomy.enums import SuggestionStatus
from apps.taxonomy.models import Skill, SkillSuggestion
from apps.taxonomy.tests.factories import SkillSuggestionFactory

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.taxonomy.tests.urls"),
]


def verify_privileged_session(client, user):
    device = TOTPDevice.objects.create(user=user, name="devnepal")
    client.force_login(user)
    token = totp(
        device.bin_key,
        step=device.step,
        t0=device.t0,
        digits=device.digits,
        drift=device.drift,
    )
    client.post(reverse("accounts:mfa_setup"), {"token": token})


@pytest.mark.unit
def test_member_submits_missing_skill_suggestion_and_submission_is_audited(client):
    """MEM-004/D4: authenticated members submit missing terms to the audited review queue."""
    member = UserFactory()
    client.force_login(member)

    response = client.post(
        reverse("taxonomy:skill_suggestion_create"),
        {"term_name": "Kubernetes", "note": "Useful for cloud projects."},
    )

    suggestion = SkillSuggestion.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("taxonomy:skill_suggestion_create")
    assert suggestion.suggested_by == member
    assert suggestion.status == SuggestionStatus.PENDING
    assert AuditEvent.objects.filter(
        actor=member,
        action="taxonomy.skill_suggestion.submitted",
        object_id=str(suggestion.pk),
    ).exists()


@pytest.mark.unit
def test_anonymous_member_cannot_submit_a_skill_suggestion(client):
    """MEM-004/AUTH-006: submitting a missing term requires authentication."""
    response = client.post(reverse("taxonomy:skill_suggestion_create"), {"term_name": "Kubernetes"})

    assert response.status_code == 302
    assert response.url.startswith(f"{reverse('accounts:login')}?next=")
    assert not SkillSuggestion.objects.exists()


@pytest.mark.unit
def test_duplicate_suggestion_returns_an_actionable_error(client):
    """MEM-004: duplicate missing-term submissions are rejected without another queue record."""
    member = UserFactory()
    SkillSuggestionFactory(term_name="Kubernetes")
    client.force_login(member)

    response = client.post(reverse("taxonomy:skill_suggestion_create"), {"term_name": "kubernetes"})

    assert response.status_code == 400
    assert b"already awaiting review" in response.content
    assert SkillSuggestion.objects.count() == 1


@pytest.mark.unit
def test_only_a_super_admin_can_review_suggestions(client):
    """D4/ADM-001/AUTH-006: members cannot approve or reject the taxonomy queue."""
    suggestion = SkillSuggestionFactory()
    client.force_login(UserFactory())

    response = client.post(
        reverse("taxonomy:skill_suggestion_review", kwargs={"pk": suggestion.pk}),
        {"decision": "approve"},
    )

    suggestion.refresh_from_db()
    assert response.status_code == 403
    assert suggestion.status == SuggestionStatus.PENDING


@pytest.mark.unit
def test_super_admin_approves_a_suggestion_and_the_queue_excludes_resolved_items(client):
    """D4/ADM-001: a verified Super Admin approves a term into the admin-managed skill taxonomy."""
    pending = SkillSuggestionFactory(term_name="Kubernetes")
    resolved = SkillSuggestionFactory(status=SuggestionStatus.DISMISSED)
    super_admin = UserFactory(is_superuser=True)
    verify_privileged_session(client, super_admin)

    page = client.get(reverse("taxonomy:skill_suggestion_review_list"))
    response = client.post(
        reverse("taxonomy:skill_suggestion_review", kwargs={"pk": pending.pk}),
        {"decision": "approve"},
    )

    pending.refresh_from_db()
    assert page.status_code == 200
    assert pending.term_name.encode() in page.content
    assert resolved.term_name.encode() not in page.content
    assert response.status_code == 302
    assert pending.status == SuggestionStatus.ACCEPTED
    assert pending.resolved_by == super_admin
    assert Skill.objects.filter(name=pending.term_name).exists()
    assert AuditEvent.objects.filter(
        actor=super_admin,
        action="taxonomy.skill_suggestion.approved",
        object_id=str(pending.pk),
    ).exists()


@pytest.mark.unit
def test_super_admin_rejects_a_suggestion_without_creating_a_skill(client):
    """D4/ADM-001: a verified Super Admin can reject a missing term with an audit trail."""
    suggestion = SkillSuggestionFactory(term_name="Obsolete tool")
    super_admin = UserFactory(is_superuser=True)
    verify_privileged_session(client, super_admin)

    response = client.post(
        reverse("taxonomy:skill_suggestion_review", kwargs={"pk": suggestion.pk}),
        {"decision": "reject"},
    )

    suggestion.refresh_from_db()
    assert response.status_code == 302
    assert suggestion.status == SuggestionStatus.DISMISSED
    assert suggestion.resolved_by == super_admin
    assert not Skill.objects.filter(name=suggestion.term_name).exists()
    assert AuditEvent.objects.filter(
        actor=super_admin,
        action="taxonomy.skill_suggestion.dismissed",
        object_id=str(suggestion.pk),
    ).exists()
