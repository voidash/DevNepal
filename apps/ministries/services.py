import hashlib
import logging
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.accounts.services import require_privileged_mfa
from apps.audit.services import record_audit
from apps.ministries.enums import (
    ContactChallengeStatus,
    ContactVerificationStatus,
    OnboardingRequestStatus,
    OrgStatus,
    PublisherStatus,
)
from apps.ministries.models import (
    MinistryOnboardingRequest,
    MinistryOrganization,
    MinistryPublisher,
    OfficialContactChallenge,
)
from apps.taxonomy.fields import normalize_nfc

logger = logging.getLogger(__name__)

DEFAULT_CONTACT_VERIFICATION_TTL = timedelta(hours=24)


class MinistryProvisioningError(Exception):
    """Organization provisioning, activation, suspension, or revocation failed."""


class MinistryOnboardingRequestError(MinistryProvisioningError):
    """A D1.1 onboarding request cannot be logged or transitioned."""


class PublisherAssignmentError(Exception):
    """Named officer assignment could not be granted."""


class OfficialContactVerificationError(PublisherAssignmentError):
    """Official contact could not complete the AUTH-005, D3 verification lifecycle."""


class OfficialContactNotificationError(OfficialContactVerificationError):
    """The official-contact verification notification could not be delivered."""


class PublisherLifecycleError(Exception):
    """Publisher suspension or revocation requested an invalid state transition."""


def _require_super_admin(actor, *, action: str, obj=None) -> None:
    allowed = (
        actor is not None
        and getattr(actor, "is_authenticated", False)
        and actor.is_active
        and actor.is_superuser
    )
    if not allowed:
        record_audit(
            actor=actor,
            action=f"{action}.denied",
            obj=obj,
            result="failure",
        )
        raise MinistryProvisioningError(f"{action} requires an active Super Admin")
    require_privileged_mfa(actor, action=action, obj=obj, error_type=MinistryProvisioningError)


def _require_reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise PublisherLifecycleError("a non-empty reason is required")
    return cleaned


def _official_domain(ministry: MinistryOrganization) -> str:
    if not ministry.website_url:
        raise OfficialContactVerificationError(
            "ministry has no official website to verify the contact domain against"
        )
    host = (urlsplit(ministry.website_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        raise OfficialContactVerificationError(
            "ministry website URL has no usable host to verify the contact domain against"
        )
    return host


def _email_domain(email: str) -> str:
    return (email.rsplit("@", 1)[-1] or "").lower()


def _website_domain(website_url: str) -> str:
    host = (urlsplit(website_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _verify_onboarding_request(
    *,
    website_url: str,
    official_email: str,
    nominated_officer_name: str,
    signatory_name: str,
    signatory_verified: bool,
) -> tuple[bool, bool]:
    domain = _website_domain(website_url)
    if not domain.endswith(".gov.np"):
        raise MinistryOnboardingRequestError(
            _("the official website must use a registered .gov.np domain")
        )
    if _email_domain(official_email) != domain:
        raise MinistryOnboardingRequestError(
            _("the nominated officer email must match the official website domain")
        )
    local_part = official_email.partition("@")[0].lower()
    if local_part in {"admin", "contact", "info", "it", "office", "support"}:
        raise MinistryOnboardingRequestError(
            _("the nominated officer must use a named, non-shared mailbox")
        )
    if len((nominated_officer_name or "").strip()) < 3:
        raise MinistryOnboardingRequestError(_("the nominated officer must be a named person"))
    if not (signatory_name or "").strip() or not signatory_verified:
        raise MinistryOnboardingRequestError(
            _("the letter signatory must be verified with the ministry focal contact")
        )
    return True, True


def _onboarding_reference(request: MinistryOnboardingRequest) -> str:
    return f"REQ-{timezone.localdate().year}-{request.pk:03d}"


def log_onboarding_request(
    super_admin,
    *,
    name_en: str,
    name_ne: str = "",
    abbreviation: str = "",
    website_url: str,
    official_email: str,
    nominated_officer_name: str,
    nominated_officer_title: str,
    purpose: str,
    focal_contact: str,
    nomination_reference: str,
    signatory_name: str,
    signatory_verified: bool,
) -> MinistryOnboardingRequest:
    """AUTH-004/D1.1: log a verified ministry request before organization provisioning."""
    _require_super_admin(super_admin, action="ministry.onboarding_request.log")
    domain_verified, named_person_verified = _verify_onboarding_request(
        website_url=website_url,
        official_email=official_email,
        nominated_officer_name=nominated_officer_name,
        signatory_name=signatory_name,
        signatory_verified=signatory_verified,
    )
    with transaction.atomic():
        request = MinistryOnboardingRequest.objects.create(
            reference=f"pending-{secrets.token_hex(12)}",
            name_en=name_en,
            name_ne=name_ne,
            abbreviation=abbreviation,
            website_url=website_url,
            official_email=official_email,
            nominated_officer_name=nominated_officer_name,
            nominated_officer_title=nominated_officer_title,
            purpose=purpose,
            focal_contact=focal_contact,
            nomination_reference=nomination_reference,
            signatory_name=signatory_name,
            domain_verified=domain_verified,
            named_person_verified=named_person_verified,
            signatory_verified=signatory_verified,
            logged_by=super_admin,
        )
        request.reference = _onboarding_reference(request)
        request.save(update_fields=["reference", "updated_at"])
        record_audit(
            actor=super_admin,
            action="ministry.onboarding_request.logged",
            obj=request,
            after={
                "reference": request.reference,
                "name_en": request.name_en,
                "official_domain": _website_domain(request.website_url),
                "domain_verified": request.domain_verified,
                "named_person_verified": request.named_person_verified,
                "signatory_verified": request.signatory_verified,
            },
        )
    return request


def provision_onboarding_request(
    super_admin, request: MinistryOnboardingRequest
) -> MinistryOrganization:
    """AUTH-004/D1.1/D1.2: provision one validated request into the existing ministry lifecycle."""
    _require_super_admin(
        super_admin,
        action="ministry.onboarding_request.provision",
        obj=request,
    )
    with transaction.atomic():
        request = MinistryOnboardingRequest.objects.select_for_update().get(pk=request.pk)
        if request.status != OnboardingRequestStatus.NEW:
            raise MinistryOnboardingRequestError(
                _("only a new onboarding request can be provisioned")
            )
        if request.duplicate_organization is not None:
            raise MinistryOnboardingRequestError(_("this organization already exists on DevNepal"))
        try:
            organization = provision_ministry(
                super_admin,
                name_en=request.name_en,
                name_ne=request.name_ne,
                abbreviation=request.abbreviation,
                description=request.purpose,
                contact_email=request.official_email,
                website_url=request.website_url,
            )
        except MinistryProvisioningError as exc:
            raise MinistryOnboardingRequestError(
                _("the organization could not be provisioned")
            ) from exc
        request.status = OnboardingRequestStatus.PROVISIONED
        request.provisioned_organization = organization
        request.provisioned_at = timezone.now()
        request.save(
            update_fields=[
                "status",
                "provisioned_organization",
                "provisioned_at",
                "updated_at",
            ]
        )
        record_audit(
            actor=super_admin,
            action="ministry.onboarding_request.provisioned",
            obj=request,
            after={
                "reference": request.reference,
                "organization_id": organization.pk,
                "organization_slug": organization.slug,
            },
        )
    return organization


def decline_onboarding_request(
    super_admin, request: MinistryOnboardingRequest, *, reason: str
) -> MinistryOnboardingRequest:
    """AUTH-004/SEC-008: retain an accountable refusal for a new onboarding request."""
    _require_super_admin(
        super_admin,
        action="ministry.onboarding_request.decline",
        obj=request,
    )
    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise MinistryOnboardingRequestError(_("a non-empty reason is required"))
    with transaction.atomic():
        request = MinistryOnboardingRequest.objects.select_for_update().get(pk=request.pk)
        if request.status != OnboardingRequestStatus.NEW:
            raise MinistryOnboardingRequestError(_("only a new onboarding request can be declined"))
        request.status = OnboardingRequestStatus.DECLINED
        request.decline_reason = cleaned_reason
        request.declined_at = timezone.now()
        request.save(update_fields=["status", "decline_reason", "declined_at", "updated_at"])
        record_audit(
            actor=super_admin,
            action="ministry.onboarding_request.declined",
            obj=request,
            after={"reference": request.reference, "reason": request.decline_reason},
        )
    return request


def _discard_contact_verification_notification(*, publisher: MinistryPublisher, token: str) -> None:
    return None


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_contact_challenge(
    actor,
    publisher: MinistryPublisher,
    *,
    notification_sender,
    verification_ttl: timedelta,
) -> OfficialContactChallenge:
    if verification_ttl <= timedelta():
        raise OfficialContactVerificationError("contact verification expiry must be in the future")
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        pending_challenges = OfficialContactChallenge.objects.select_for_update().filter(
            publisher=publisher, status=ContactChallengeStatus.PENDING
        )
        superseded_count = pending_challenges.update(
            status=ContactChallengeStatus.SUPERSEDED,
            superseded_at=now,
        )
        challenge = OfficialContactChallenge.objects.create(
            publisher=publisher,
            token_digest=_token_digest(token),
            expires_at=now + verification_ttl,
        )
        record_audit(
            actor=actor,
            action="publisher.contact_challenge_issued",
            obj=publisher,
            after={
                "challenge_id": challenge.pk,
                "expires_at": challenge.expires_at.isoformat(),
                "superseded_challenge_count": superseded_count,
            },
        )
    try:
        notification_sender(publisher=publisher, token=token)
    except Exception as exc:
        logger.exception(
            "Official contact challenge delivery failed for publisher=%s", publisher.pk
        )
        record_audit(
            actor=actor,
            action="publisher.contact_challenge_delivery_failed",
            obj=publisher,
            after={"challenge_id": challenge.pk},
            result="failure",
        )
        raise OfficialContactNotificationError(
            "official contact verification delivery failed"
        ) from exc
    challenge.delivered_at = timezone.now()
    challenge.save(update_fields=["delivered_at"])
    return challenge


def reissue_official_contact_challenge(
    actor,
    publisher: MinistryPublisher,
    *,
    notification_sender=None,
    verification_ttl: timedelta = DEFAULT_CONTACT_VERIFICATION_TTL,
) -> OfficialContactChallenge:
    """AUTH-005, D3: replace an unconsumed official-contact challenge without exposing its token."""
    is_assignee = (
        actor is not None
        and getattr(actor, "is_authenticated", False)
        and actor.is_active
        and actor.pk == publisher.user_id
    )
    if not is_assignee:
        _require_super_admin(actor, action="publisher.contact_challenge.reissue", obj=publisher)
    else:
        require_privileged_mfa(
            actor,
            action="publisher.contact_challenge.reissue",
            obj=publisher,
            error_type=OfficialContactVerificationError,
        )
    publisher.refresh_from_db()
    if publisher.status != PublisherStatus.ACTIVE:
        raise OfficialContactVerificationError(
            "only active publisher assignments can verify contact"
        )
    if publisher.contact_verification_status == ContactVerificationStatus.VERIFIED:
        raise OfficialContactVerificationError("official contact is already verified")
    return _issue_contact_challenge(
        actor,
        publisher,
        notification_sender=notification_sender or _discard_contact_verification_notification,
        verification_ttl=verification_ttl,
    )


def provision_ministry(
    super_admin,
    *,
    name_en: str,
    name_ne: str = "",
    slug: str | None = None,
    abbreviation: str = "",
    description: str = "",
    contact_email: str = "",
    website_url: str = "",
) -> MinistryOrganization:
    """AUTH-004: Super Admin creates a PENDING ministry organization, attributed and audited."""
    _require_super_admin(super_admin, action="ministry.create")

    slug_value = normalize_nfc(slug or slugify(name_en, allow_unicode=True))
    if not slug_value:
        raise MinistryProvisioningError("a non-empty slug is required")
    if len(slug_value) > MinistryOrganization._meta.get_field("slug").max_length:
        raise MinistryProvisioningError("slug exceeds the maximum length")
    if MinistryOrganization.objects.filter(slug=slug_value).exists():
        raise MinistryProvisioningError(f"slug '{slug_value}' is already taken")

    try:
        # Keep the integrity boundary in its own savepoint. Callers such as the
        # onboarding workflow already run in an outer transaction and must be
        # able to translate a concurrent uniqueness collision without leaving
        # that transaction rollback-only.
        with transaction.atomic():
            org = MinistryOrganization.objects.create(
                name_en=name_en,
                name_ne=name_ne,
                slug=slug_value,
                abbreviation=abbreviation,
                description=description,
                contact_email=contact_email,
                website_url=website_url,
                provisioned_by=super_admin,
                provisioned_at=timezone.now(),
            )
    except IntegrityError as exc:
        raise MinistryProvisioningError("ministry organization could not be created") from exc

    record_audit(
        actor=super_admin,
        action="ministry.created",
        obj=org,
        before=None,
        after={
            "name_en": org.name_en,
            "slug": org.slug,
            "status": org.status,
            "website_url": org.website_url,
        },
    )
    return org


def activate_organization(super_admin, ministry: MinistryOrganization) -> MinistryOrganization:
    """AUTH-004: a Super Admin activates a provisioned organization; revocation is terminal."""
    _require_super_admin(super_admin, action="ministry.activate", obj=ministry)

    if ministry.status == OrgStatus.REVOKED:
        raise MinistryProvisioningError("a revoked organization cannot be reactivated")
    if ministry.status == OrgStatus.ACTIVE:
        raise MinistryProvisioningError("organization is already active")

    before = {"status": ministry.status}
    ministry.status = OrgStatus.ACTIVE
    ministry.suspended_at = None
    ministry.suspension_reason = ""
    ministry.save()

    record_audit(
        actor=super_admin,
        action="ministry.activated",
        obj=ministry,
        before=before,
        after={"status": ministry.status},
    )
    return ministry


def suspend_organization(
    super_admin,
    ministry: MinistryOrganization,
    *,
    reason: str,
) -> MinistryOrganization:
    """AUTH-004: suspending an organization blocks all its publisher actions."""
    _require_super_admin(super_admin, action="ministry.suspend", obj=ministry)
    reason = _require_reason(reason)

    if ministry.status != OrgStatus.ACTIVE:
        raise MinistryProvisioningError("only an active organization can be suspended")

    before = {"status": ministry.status}
    ministry.status = OrgStatus.SUSPENDED
    ministry.suspended_at = timezone.now()
    ministry.suspension_reason = reason
    ministry.save()

    record_audit(
        actor=super_admin,
        action="ministry.suspended",
        obj=ministry,
        before=before,
        after={"status": ministry.status, "reason": reason},
    )
    return ministry


def revoke_organization(
    super_admin,
    ministry: MinistryOrganization,
    *,
    reason: str,
) -> MinistryOrganization:
    """AUTH-004: revoking an organization is terminal and blocks all its publisher actions."""
    _require_super_admin(super_admin, action="ministry.revoke", obj=ministry)
    reason = _require_reason(reason)

    if ministry.status == OrgStatus.REVOKED:
        raise MinistryProvisioningError("organization is already revoked")

    before = {"status": ministry.status}
    ministry.status = OrgStatus.REVOKED
    ministry.revoked_at = timezone.now()
    ministry.revocation_reason = reason
    ministry.save()

    record_audit(
        actor=super_admin,
        action="ministry.revoked",
        obj=ministry,
        before=before,
        after={"status": ministry.status, "reason": reason},
    )
    return ministry


def create_publisher(
    super_admin,
    *,
    ministry: MinistryOrganization,
    user,
    title: str,
    official_email: str,
    notification_sender=None,
    verification_ttl: timedelta = DEFAULT_CONTACT_VERIFICATION_TTL,
) -> MinistryPublisher:
    """AUTH-004, AUTH-005, D3: grant an eligible assignment and issue its contact challenge."""
    _require_super_admin(super_admin, action="publisher.grant", obj=ministry)

    if ministry.status not in (OrgStatus.PENDING, OrgStatus.ACTIVE):
        raise PublisherAssignmentError(
            f"publishers cannot be granted against a {ministry.status} organization"
        )

    official_domain = _official_domain(ministry)
    if _email_domain(official_email) != official_domain:
        raise OfficialContactVerificationError(
            f"official email domain must match the ministry domain '{official_domain}'"
        )

    if MinistryPublisher.objects.filter(
        user=user,
        ministry=ministry,
        status=PublisherStatus.ACTIVE,
    ).exists():
        raise PublisherAssignmentError(
            "user already holds a publisher assignment for this ministry"
        )

    try:
        publisher = MinistryPublisher.objects.create(
            user=user,
            ministry=ministry,
            title=title,
            official_email=official_email,
            assigned_by=super_admin,
        )
    except IntegrityError as exc:
        raise PublisherAssignmentError(
            "user already holds a publisher assignment for this ministry"
        ) from exc

    record_audit(
        actor=super_admin,
        action="publisher.granted",
        obj=publisher,
        before=None,
        after={
            "ministry": ministry.slug,
            "user": user.username,
            "status": publisher.status,
            "official_email": publisher.official_email,
            "official_domain": official_domain,
            "official_domain_eligible": True,
            "official_domain_attested_by": super_admin.username,
            "contact_verification_status": publisher.contact_verification_status,
        },
    )
    _issue_contact_challenge(
        super_admin,
        publisher,
        notification_sender=notification_sender or _discard_contact_verification_notification,
        verification_ttl=verification_ttl,
    )
    return publisher


def verify_official_contact(
    publisher: MinistryPublisher,
    token: str,
    *,
    now=None,
) -> MinistryPublisher:
    """AUTH-005, D3: consume a current one-time official-contact challenge."""
    moment = now or timezone.now()
    digest = _token_digest(token)
    error_message = ""
    with transaction.atomic():
        publisher = MinistryPublisher.objects.select_for_update().get(pk=publisher.pk)
        challenge = (
            OfficialContactChallenge.objects.select_for_update()
            .filter(publisher=publisher, status=ContactChallengeStatus.PENDING)
            .order_by("-issued_at", "-id")
            .first()
        )
        if challenge is None or not constant_time_compare(challenge.token_digest, digest):
            record_audit(
                actor=publisher.user,
                action="publisher.contact_verification.denied",
                obj=publisher,
                result="failure",
            )
            error_message = "official contact token is invalid or already used"
        elif challenge.expires_at <= moment:
            challenge.status = ContactChallengeStatus.EXPIRED
            challenge.expired_at = moment
            challenge.save(update_fields=["status", "expired_at"])
            record_audit(
                actor=publisher.user,
                action="publisher.contact_challenge_expired",
                obj=publisher,
                after={"challenge_id": challenge.pk},
                result="failure",
            )
            error_message = "official contact token has expired"
        else:
            challenge.status = ContactChallengeStatus.COMPLETED
            challenge.consumed_at = moment
            challenge.save(update_fields=["status", "consumed_at"])
            publisher.contact_verification_status = ContactVerificationStatus.VERIFIED
            publisher.contact_verified_at = moment
            publisher.save(update_fields=["contact_verification_status", "contact_verified_at"])
            record_audit(
                actor=publisher.user,
                action="publisher.contact_verified",
                obj=publisher,
                before={"contact_verification_status": ContactVerificationStatus.PENDING},
                after={
                    "contact_verification_status": publisher.contact_verification_status,
                    "challenge_id": challenge.pk,
                },
            )
    if error_message:
        raise OfficialContactVerificationError(error_message)
    return publisher


def suspend_publisher(
    super_admin,
    publisher: MinistryPublisher,
    *,
    reason: str,
) -> MinistryPublisher:
    """AUTH-009: suspension deactivates the account immediately, with reason and audit."""
    _require_super_admin(super_admin, action="publisher.suspend", obj=publisher)
    reason = _require_reason(reason)

    if publisher.status != PublisherStatus.ACTIVE:
        raise PublisherLifecycleError("only an active publisher assignment can be suspended")

    user = publisher.user
    was_active = user.is_active
    if was_active:
        user.is_active = False
        user.save(update_fields=["is_active"])

    record_audit(
        actor=super_admin,
        action="publisher.suspended",
        obj=publisher,
        before={"status": publisher.status, "user_is_active": was_active},
        after={
            "status": publisher.status,
            "user_is_active": user.is_active,
            "reason": reason,
        },
    )
    return publisher


def revoke_publisher(
    super_admin,
    publisher: MinistryPublisher,
    *,
    reason: str,
) -> MinistryPublisher:
    """AUTH-004, A1: revoke one named officer; other publishers are unaffected."""
    _require_super_admin(super_admin, action="publisher.revoke", obj=publisher)
    reason = _require_reason(reason)

    if publisher.status == PublisherStatus.REVOKED:
        raise PublisherLifecycleError("publisher assignment is already revoked")

    before = {"status": publisher.status}
    publisher.status = PublisherStatus.REVOKED
    publisher.revoked_by = super_admin
    publisher.revoked_at = timezone.now()
    publisher.revocation_reason = reason
    publisher.save()

    record_audit(
        actor=super_admin,
        action="publisher.revoked",
        obj=publisher,
        before=before,
        after={"status": publisher.status, "reason": reason},
    )
    return publisher


def is_publisher_active(user, ministry: MinistryOrganization) -> bool:
    """AUTH-005, AUTH-006, GOV-001: verified active assignment + active organization/account."""
    if user is None or ministry is None or not user.is_active:
        return False
    if ministry.status != OrgStatus.ACTIVE:
        return False
    return MinistryPublisher.objects.filter(
        user=user,
        ministry=ministry,
        status=PublisherStatus.ACTIVE,
        contact_verification_status=ContactVerificationStatus.VERIFIED,
    ).exists()
