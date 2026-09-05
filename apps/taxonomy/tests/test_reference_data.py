import pytest
from django.urls import reverse

from apps.accounts.models import MemberSkill
from apps.audit.models import AuditEvent
from apps.audit.tests.factories import UserFactory
from apps.ministries.tests.factories import SuperAdminFactory
from apps.projects.tests.factories import ProjectFactory
from apps.taxonomy.enums import LicenseUse, TaxonomyChangeAction
from apps.taxonomy.models import ApprovedLicense, Skill, TaxonomyVersion
from apps.taxonomy.services import (
    SkillMergeError,
    SkillNotPublishableError,
    TaxonomyAuthorizationError,
    approve_license,
    create_skill,
    merge_skills,
    record_license,
    set_skill_active,
    withdraw_license,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _privileged_mfa_bypass(settings):
    settings.PRIVILEGED_MFA_BYPASS = True


@pytest.mark.unit
def test_a_skill_without_a_nepali_name_stays_hidden_from_pickers():
    """ADM-001/DSC-001: a term goes live only when both languages are present."""
    skill = create_skill(SuperAdminFactory(), name="GTFS")

    assert skill.is_active is False
    assert skill.is_publishable is False


@pytest.mark.unit
def test_a_bilingual_skill_goes_live_immediately():
    """ADM-001/DSC-001: both languages present means the term is offered."""
    skill = create_skill(SuperAdminFactory(), name="Nepali localisation", name_ne="नेपाली स्थानीयकरण")

    assert skill.is_active is True
    assert skill.is_publishable is True


@pytest.mark.integration
def test_a_skill_cannot_be_reinstated_until_both_languages_exist():
    """ADM-001/DSC-001: reinstating an incomplete term is refused."""
    super_admin = SuperAdminFactory()
    skill = create_skill(super_admin, name="jQuery")

    with pytest.raises(SkillNotPublishableError):
        set_skill_active(super_admin, skill, is_active=True)

    skill.refresh_from_db()
    assert skill.is_active is False


@pytest.mark.integration
def test_every_change_creates_a_numbered_attributed_version():
    """ADM-001/ADM-008: the catalogue reads back as a history, not only a current state."""
    super_admin = SuperAdminFactory()
    skill = create_skill(super_admin, name="Accessibility", name_ne="पहुँचयोग्यता")

    set_skill_active(super_admin, skill, is_active=False)

    versions = list(TaxonomyVersion.objects.order_by("version"))
    assert [version.version for version in versions] == [1, 2]
    assert versions[0].action == TaxonomyChangeAction.ADDED
    assert versions[1].action == TaxonomyChangeAction.DEPRECATED
    assert versions[1].actor == super_admin
    assert versions[1].diff["before"]["is_active"] is True


@pytest.mark.integration
def test_deprecating_a_skill_keeps_existing_records_readable():
    """ADM-001/D5.5: a deprecated skill leaves the profiles that already hold it intact."""
    super_admin = SuperAdminFactory()
    skill = create_skill(super_admin, name="jQuery", name_ne="जेक्वेरी")
    member = UserFactory()
    MemberSkill.objects.create(user=member, skill=skill)

    set_skill_active(super_admin, skill, is_active=False)

    assert MemberSkill.objects.filter(user=member, skill=skill).exists()
    assert Skill.objects.filter(is_active=True, pk=skill.pk).exists() is False


@pytest.mark.integration
def test_merging_retags_the_members_and_projects_that_used_the_duplicate():
    """ADM-001/D5.5: a merge moves existing holders rather than stranding them."""
    super_admin = SuperAdminFactory()
    source = create_skill(super_admin, name="accesibility", name_ne="पहुँच")
    target = create_skill(super_admin, name="Accessibility", name_ne="पहुँचयोग्यता")
    member = UserFactory()
    MemberSkill.objects.create(user=member, skill=source)
    project = ProjectFactory()
    project.skills.add(source)

    merge_skills(super_admin, source, target)

    source.refresh_from_db()
    assert source.is_active is False
    assert MemberSkill.objects.filter(user=member, skill=target).exists()
    assert not MemberSkill.objects.filter(user=member, skill=source).exists()
    assert list(project.skills.all()) == [target]


@pytest.mark.integration
def test_merging_does_not_duplicate_a_skill_a_member_already_holds():
    """ADM-001/D5.5: a member holding both skills ends with one record, not two."""
    super_admin = SuperAdminFactory()
    source = create_skill(super_admin, name="accesibility", name_ne="पहुँच")
    target = create_skill(super_admin, name="Accessibility", name_ne="पहुँचयोग्यता")
    member = UserFactory()
    MemberSkill.objects.create(user=member, skill=source)
    MemberSkill.objects.create(user=member, skill=target)

    merge_skills(super_admin, source, target)

    assert MemberSkill.objects.filter(user=member, skill=target).count() == 1
    assert not MemberSkill.objects.filter(user=member, skill=source).exists()


@pytest.mark.integration
def test_a_skill_cannot_be_merged_into_itself():
    """ADM-001/D5.5: a merge needs two distinct terms."""
    super_admin = SuperAdminFactory()
    skill = create_skill(super_admin, name="GTFS", name_ne="जीटीएफएस")

    with pytest.raises(SkillMergeError):
        merge_skills(super_admin, skill, skill)


@pytest.mark.integration
def test_a_member_cannot_change_the_catalogue_and_the_attempt_is_audited():
    """ADM-001/SEC-005: catalogue maintenance is Super Admin only."""
    with pytest.raises(TaxonomyAuthorizationError):
        create_skill(UserFactory(), name="Unauthorised", name_ne="अनधिकृत")

    assert AuditEvent.objects.filter(action="taxonomy.skill_added", result="denied").exists()


@pytest.mark.integration
def test_a_new_licence_is_pending_until_its_legal_approval_is_recorded():
    """ADM-001/D5.6: a licence is not offered before legal approval."""
    licence = record_license(
        SuperAdminFactory(),
        spdx_id="MPL-2.0",
        name="Mozilla Public License 2.0",
        use=LicenseUse.CODE,
    )

    assert licence.is_approved is False
    assert licence.legal_approved_on is None


@pytest.mark.integration
def test_recording_legal_approval_dates_and_references_the_decision():
    """ADM-001/D5.6: approval carries its legal reference and the date it was given."""
    super_admin = SuperAdminFactory()
    licence = record_license(
        super_admin,
        spdx_id="EUPL-1.2",
        name="European Union Public Licence 1.2",
        use=LicenseUse.CODE,
    )

    approve_license(super_admin, licence, legal_reference="PMO-L-2026-01")

    licence.refresh_from_db()
    assert licence.is_approved is True
    assert licence.legal_reference == "PMO-L-2026-01"
    assert licence.legal_approved_on is not None


@pytest.mark.integration
def test_withdrawing_a_licence_never_touches_an_already_published_project():
    """ADM-001/D5.6: licence removals do not affect projects that already use them."""
    super_admin = SuperAdminFactory()
    licence = record_license(
        super_admin,
        spdx_id="Unlicense",
        name="The Unlicense",
        use=LicenseUse.CODE,
    )
    approve_license(super_admin, licence, legal_reference="PMO-L-2026-01")
    project = ProjectFactory(license=licence)

    withdraw_license(super_admin, licence, reason="Superseded by Apache-2.0.")

    project.refresh_from_db()
    licence.refresh_from_db()
    assert licence.is_approved is False
    assert ApprovedLicense.objects.filter(pk=licence.pk).exists()
    assert project.license == licence


@pytest.mark.integration
def test_a_member_is_denied_the_catalogue_screens(client):
    """ADM-001/SEC-005: catalogue screens are Super Admin only."""
    client.force_login(UserFactory())

    assert client.get(reverse("taxonomy:skill_management")).status_code == 403
    assert client.get(reverse("taxonomy:license_management")).status_code == 403


@pytest.mark.integration
def test_the_skills_screen_shows_both_languages_usage_and_state(client):
    """ADM-001/D5.5: the screen carries the columns the catalogue is managed by."""
    super_admin = SuperAdminFactory()
    skill = create_skill(super_admin, name="Nepali localisation", name_ne="नेपाली स्थानीयकरण")
    MemberSkill.objects.create(user=UserFactory(), skill=skill)
    client.force_login(super_admin)

    content = client.get(reverse("taxonomy:skill_management")).content.decode()

    assert "Nepali localisation" in content
    assert "नेपाली स्थानीयकरण" in content
    assert skill.slug in content


@pytest.mark.integration
def test_the_licence_screen_records_an_approval(client):
    """ADM-001/D5.6: a Super Admin records legal approval from the screen."""
    super_admin = SuperAdminFactory()
    licence = record_license(
        super_admin,
        spdx_id="ODbL-1.0",
        name="Open Database License 1.0",
        use=LicenseUse.CONTENT_DATA,
    )
    client.force_login(super_admin)

    response = client.post(
        reverse("taxonomy:license_decision", args=[licence.pk]),
        {"intent": "approve", "legal_reference": "PMO-L-2026-02"},
    )

    licence.refresh_from_db()
    assert response.status_code == 302
    assert licence.is_approved is True
