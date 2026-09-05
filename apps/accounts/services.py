import hashlib
import logging
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import models, transaction
from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.enums import Visibility
from apps.accounts.github import GitHubConnectError, GitHubProfileError
from apps.audit.services import record_audit
from apps.github_sync.models import GithubConnection
from apps.projects.enums import ApplicationStatus, ProjectStatus
from apps.taxonomy.fields import normalize_nfc

logger = logging.getLogger(__name__)

VISIBILITY_CONTROLLED_FIELDS = frozenset({"location", "province", "education", "links", "skills"})
SENSITIVE_OPTIONAL_FIELDS = frozenset({"location", "province", "education"})
GITHUB_USERNAME_FALLBACK = "github-member"
_DISALLOWED_USERNAME_CHARS = re.compile(r"[^\w.@+-]")
COMPLETENESS_FIELDS = (
    "headline",
    "bio",
    "interests",
    "contribution_preferences",
    "experience_band",
    "availability",
    "location",
    "province",
)


class AccountsServiceError(Exception):
    """Base class for accounts service failures."""


class PrivilegedMFARequiredError(AccountsServiceError):
    """A privileged service action was attempted without a verified MFA session."""


class AccountDeletionExternalEffectError(AccountsServiceError):
    """Post-commit account deletion cleanup could not complete."""


class GitHubUnverifiedEmailError(GitHubConnectError):
    """GitHub sign-up was refused because no verified email was consented (GIT-002)."""


class GitHubEmailInUseError(GitHubConnectError):
    """GitHub sign-up was refused because the verified email already has an account."""


class GitHubConnectionConflictError(GitHubConnectError):
    """The GitHub identity is already connected to a different member account."""


class GitHubAccountInactiveError(GitHubConnectError):
    """A suspended account may not re-enter through provider sign-in (AUTH-009)."""


def mfa_verified(actor) -> bool:
    if getattr(settings, "PRIVILEGED_MFA_BYPASS", False):
        return True
    verified = getattr(actor, "is_verified", None)
    return bool(verified and verified())


def require_privileged_mfa(
    actor, *, action: str, obj=None, error_type: type[Exception] = PrivilegedMFARequiredError
) -> None:
    if (
        actor is not None
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and mfa_verified(actor)
    ):
        return
    record_audit(actor=actor, action=f"{action}.denied", obj=obj, result="failure")
    raise error_type(f"{action} requires an OTP-verified privileged session")


def create_member_account(*, username: str, email: str, password: str | None = None):
    """AUTH-001: provision a member identity and profile with an audit trail."""
    from apps.accounts.models import MemberProfile, User

    with transaction.atomic():
        user = User.objects.create_user(
            username=normalize_nfc(username),
            email=normalize_nfc(email),
            password=password,
        )
        MemberProfile.objects.create(user=user)
        record_audit(actor=user, action="account.created", obj=user)
    return user


def derive_github_username(login: str) -> str:
    """GIT-002: derive a valid, collision-safe username from a GitHub login."""
    from apps.accounts.models import User

    base = _DISALLOWED_USERNAME_CHARS.sub("", normalize_nfc(str(login)) or "")
    base = base[:100] or GITHUB_USERNAME_FALLBACK
    candidate = base
    suffix = 0
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def complete_github_connect(*, user, github_profile: dict, emails: list[dict], scopes: list[str]):
    """AUTH-002/GIT-002: connect a GitHub identity without ever storing token material.

    Authenticated members are linked through an upsert. Anonymous visitors either
    sign in through an existing active connection or receive a new account
    provisioned from their verified GitHub email. Failures are audited and typed.
    """
    github_user_id = github_profile.get("id")
    login_name = normalize_nfc(str(github_profile.get("login") or ""))
    if not isinstance(github_user_id, int) or not login_name:
        raise GitHubProfileError("GitHub identity is missing id or login")
    now = timezone.now()
    if getattr(user, "is_authenticated", False):
        return _connect_authenticated_user(user, github_user_id, login_name, scopes, now)
    matched = (
        GithubConnection.objects.select_related("user")
        .filter(github_user_id=github_user_id, revoked_at__isnull=True)
        .first()
    )
    if matched is not None:
        return _sign_in_existing_connection(matched, login_name, scopes, now)
    return _create_member_from_github(github_user_id, login_name, emails, scopes, now)


def _connect_authenticated_user(user, github_user_id, login_name, scopes, now):
    conflict = (
        GithubConnection.objects.filter(github_user_id=github_user_id).exclude(user=user).first()
    )
    if conflict is not None:
        record_audit(
            actor=user,
            action="github_connection.conflict",
            obj=conflict,
            after={"github_user_id": github_user_id},
            result="failure",
        )
        raise GitHubConnectionConflictError("GitHub identity belongs to another member")
    connection = GithubConnection.objects.filter(user=user).first()
    if connection is None:
        connection = GithubConnection(user=user, github_user_id=github_user_id)
    connection.login = login_name
    connection.scopes = list(scopes)
    connection.consent_scopes = list(scopes)
    connection.consent_recorded_at = now
    connection.revoked_at = None
    connection.save()
    record_audit(
        actor=user,
        action="github_connection.connect",
        obj=connection,
        after={"login": login_name, "github_user_id": github_user_id, "scopes": list(scopes)},
    )
    return user


def _sign_in_existing_connection(connection, login_name, scopes, now):
    user = connection.user
    if not user.is_active:
        record_audit(
            actor=None,
            action="github_connection.login_refused",
            obj=connection,
            after={"reason": "account_inactive"},
            result="failure",
        )
        raise GitHubAccountInactiveError("This account cannot sign in")
    connection.login = login_name
    connection.scopes = list(scopes)
    connection.consent_scopes = list(scopes)
    connection.consent_recorded_at = now
    connection.save(update_fields=["login", "scopes", "consent_scopes", "consent_recorded_at"])
    record_audit(
        actor=user,
        action="github_connection.connect",
        obj=connection,
        after={"login": login_name, "scopes": list(scopes)},
    )
    return user


def _create_member_from_github(github_user_id, login_name, emails, scopes, now):
    from apps.accounts.models import User

    verified = [row for row in emails if row.get("verified") and row.get("email")]
    primary = next((row["email"] for row in verified if row.get("primary")), None)
    email = normalize_nfc(str(primary or (verified[0]["email"] if verified else "")))
    if not email:
        record_audit(
            actor=None,
            action="github_connection.unverified_email",
            after={"github_user_id": github_user_id},
            result="failure",
        )
        raise GitHubUnverifiedEmailError("No verified GitHub email was consented")
    if User.objects.filter(email__iexact=email, is_active=True).exists():
        record_audit(
            actor=None,
            action="github_connection.email_in_use",
            after={"github_user_id": github_user_id},
            result="failure",
        )
        raise GitHubEmailInUseError("This email already belongs to a member account")
    user = create_member_account(username=derive_github_username(login_name), email=email)
    connection = GithubConnection.objects.create(
        user=user,
        github_user_id=github_user_id,
        login=login_name,
        scopes=list(scopes),
        consent_scopes=list(scopes),
        consent_recorded_at=now,
    )
    record_audit(
        actor=user,
        action="github_connection.connect",
        obj=connection,
        after={"login": login_name, "github_user_id": github_user_id, "scopes": list(scopes)},
    )
    return user


def normalize_public_url(value):
    """Normalize a member-supplied URL: NFC input, lowercase scheme/host, IDN to punycode,
    trailing slash for an empty path (MEM-007). Validation of the scheme happens at clean time.
    """
    if not isinstance(value, str) or not value:
        return value
    url = normalize_nfc(value.strip())
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return url
    try:
        port = parts.port
    except ValueError:
        return url
    host = parts.hostname.lower()
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            host = normalize_nfc(host)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, parts.fragment))


def visibility_of(profile, field):
    """Effective Visibility for a profile field; absent configuration is private (MEM-003)."""
    if field not in VISIBILITY_CONTROLLED_FIELDS:
        raise ValueError(f"'{field}' is not a visibility-controlled profile field")
    return Visibility(profile.field_visibility.get(field, Visibility.PRIVATE))


def discoverable_member_profiles(*, query: str = "", skill_slug: str = ""):
    """MEM-003: return the fail-closed projection backing public member discovery."""
    from apps.accounts.models import MemberProfile, MemberSkill

    query = normalize_nfc(query) or ""
    skill_slug = normalize_nfc(skill_slug) or ""
    profiles = (
        MemberProfile.objects.filter(directory_discoverable=True, user__is_active=True)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__skills",
                queryset=MemberSkill.objects.filter(skill__is_active=True)
                .select_related("skill")
                .order_by("skill__name"),
                to_attr="directory_skills",
            )
        )
    )
    if query:
        profiles = profiles.filter(
            Q(user__username__icontains=query)
            | Q(headline__icontains=query)
            | Q(interests__icontains=query)
            | (
                Q(field_visibility__skills=Visibility.PUBLIC)
                & Q(user__skills__skill__is_active=True)
                & Q(user__skills__skill__name__icontains=query)
            )
        )
    if skill_slug:
        profiles = profiles.filter(
            field_visibility__skills=Visibility.PUBLIC,
            user__skills__skill__is_active=True,
            user__skills__skill__slug=skill_slug,
        )
    return profiles.distinct(), query, skill_slug


PORTFOLIO_PROJECT_STATUSES = (
    ProjectStatus.OPEN_FOR_CONTRIBUTION,
    ProjectStatus.PAUSED,
    ProjectStatus.COMPLETED,
    ProjectStatus.CANCELLED,
    ProjectStatus.ARCHIVED,
)


def sync_member_skills(user, skills) -> None:
    """MEM-004: reconcile the member's taxonomy skills with the submitted selection."""
    from apps.accounts.models import MemberSkill

    desired_ids = {skill.pk for skill in skills}
    current_ids = set(user.skills.values_list("skill_id", flat=True))
    if desired_ids == current_ids:
        return
    with transaction.atomic():
        MemberSkill.objects.filter(user=user, skill_id__in=current_ids - desired_ids).delete()
        MemberSkill.objects.bulk_create(
            MemberSkill(user=user, skill_id=skill_id) for skill_id in desired_ids - current_ids
        )


def public_portfolio(profile):
    """MEM-005: public portfolio sections — open/past projects the member owns or was an
    accepted contributor on, published blog listings, verified contribution counts by type,
    and active badges. Only records that are already public outside the profile appear."""
    from apps.blogs.enums import BlogModerationState, BlogPostType, BlogStatus
    from apps.blogs.models import BlogPost
    from apps.contributions.enums import VerificationStatus
    from apps.contributions.models import ContributionRecord
    from apps.projects.models import Project
    from apps.recognition.enums import AwardStatus
    from apps.recognition.models import BadgeAward

    user = profile.user
    projects = Project.objects.filter(
        models.Q(owner=user)
        | models.Q(applications__applicant=user, applications__status=ApplicationStatus.ACCEPTED),
        status__in=PORTFOLIO_PROJECT_STATUSES,
    ).distinct()
    blogs = BlogPost.objects.filter(
        author=user,
        status=BlogStatus.PUBLISHED,
    ).exclude(moderation_state=BlogModerationState.RESTRICTED)
    contributions = (
        ContributionRecord.objects.filter(contributor=user, status=VerificationStatus.ACCEPTED)
        .values("contribution_type__label")
        .annotate(count=models.Count("pk"))
        .order_by("contribution_type__label")
    )
    badges = BadgeAward.objects.filter(recipient=user, status=AwardStatus.ACTIVE).select_related(
        "badge"
    )
    return {
        "projects": [
            {
                "title": project.localized_title,
                "slug": project.slug,
                "status": project.get_status_display(),
                "official": project.is_official,
            }
            for project in projects
        ],
        "blogs": [
            {
                "title": post.title,
                "url": (
                    post.canonical_url
                    if post.post_type == BlogPostType.EXTERNAL
                    else reverse("blogs:detail", kwargs={"post_id": post.pk})
                ),
                "published_at": post.published_at,
                "external": post.post_type == BlogPostType.EXTERNAL,
            }
            for post in blogs
        ],
        "contributions": [
            {"label": row["contribution_type__label"], "count": row["count"]}
            for row in contributions
        ],
        "badges": [
            {"name": award.badge.name, "description": award.badge.description} for award in badges
        ],
    }


def public_profile_payload(profile):
    """Serialize the public view of a member profile (MEM-003). Email, authentication provider,
    and private contact information are never included, regardless of configuration. Education
    records are never published (§12.2 minimisation).
    """
    payload = {
        "username": profile.user.username,
        "headline": profile.headline,
        "bio": profile.bio,
    }
    for field in ("location", "province"):
        if visibility_of(profile, field) is Visibility.PUBLIC:
            payload[field] = getattr(profile, field)
    payload["links"] = _public_links(profile)
    payload["skills"] = _public_skills(profile)
    payload.update(public_portfolio(profile))
    return payload


def _public_links(profile):
    if visibility_of(profile, "links") is not Visibility.PUBLIC:
        return []
    return [
        {"link_type": link.link_type, "url": link.url, "label": link.label}
        for link in profile.user.links.filter(is_public=True)
    ]


def _public_skills(profile):
    if visibility_of(profile, "skills") is not Visibility.PUBLIC:
        return []
    return [
        {"name": member_skill.skill.name, "self_rating": member_skill.self_rating}
        for member_skill in profile.user.skills.select_related("skill")
    ]


def preview_public_profile(profile):
    """Render the public profile as it would appear if the given (possibly unsaved) state were
    published, without persisting anything (MEM-008).
    """
    return public_profile_payload(profile)


def profile_completeness(profile):
    """Compute completeness guidance over optional profile fields (MEM-009). Nothing is mandatory;
    sensitive optional fields are flagged and never required.
    """
    items = [
        {
            "field": field,
            "filled": bool(getattr(profile, field)),
            "sensitive": field in SENSITIVE_OPTIONAL_FIELDS,
            "required": False,
        }
        for field in COMPLETENESS_FIELDS
    ]
    user = profile.user
    for section in ("links", "education", "skills"):
        manager = getattr(user, section)
        items.append(
            {
                "field": section,
                "filled": manager.exists(),
                "sensitive": section in SENSITIVE_OPTIONAL_FIELDS,
                "required": False,
            }
        )
    filled_count = sum(item["filled"] for item in items)
    percent = round(100 * filled_count / len(items))
    return {"percent": percent, "items": items}


def export_profile_data(user):
    """Export the member's own account and contribution data (AUTH-010)."""
    from apps.contributions.models import ContributionRecord

    profile = getattr(user, "profile", None)
    data = {
        "account": {
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "date_joined": user.date_joined.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None,
        },
        "profile": None,
        "education": [
            {
                "institution": row.institution,
                "credential": row.credential,
                "field_of_study": row.field_of_study,
                "start_year": row.start_year,
                "end_year": row.end_year,
                "created_at": row.created_at.isoformat(),
            }
            for row in user.education.all()
        ],
        "links": [
            {
                "link_type": row.link_type,
                "url": row.url,
                "label": row.label,
                "is_public": row.is_public,
                "created_at": row.created_at.isoformat(),
            }
            for row in user.links.all()
        ],
    }
    if profile is not None:
        data["profile"] = {
            "headline": profile.headline,
            "bio": profile.bio,
            "location": profile.location,
            "province": profile.province,
            "preferred_language": profile.preferred_language,
            "experience_band": profile.experience_band,
            "availability": profile.availability,
            "interests": profile.interests,
            "contribution_preferences": profile.contribution_preferences,
            "field_visibility": dict(profile.field_visibility),
            "directory_discoverable": profile.directory_discoverable,
            "leaderboard_opt_out": profile.leaderboard_opt_out,
            "avatar": profile.avatar.name if profile.avatar else None,
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat(),
        }
    data["skills"] = [
        {
            "name": member_skill.skill.name,
            "self_rating": member_skill.self_rating,
        }
        for member_skill in user.skills.select_related("skill")
    ]
    contributions = ContributionRecord.objects.filter(contributor=user).order_by("pk")
    data["contributions"] = [
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
        for contribution in contributions
    ]
    record_audit(
        actor=user,
        action="account.data_export",
        obj=user,
        after={"contribution_count": len(data["contributions"])},
        correlation_id=uuid.uuid4().hex,
    )
    return data


def request_account_deletion(user):
    """AUTH-010: anonymize an account while retaining legal audit and contribution evidence."""
    from apps.accounts.models import MemberProfile, UserSession
    from apps.contributions.models import ContributionRecord
    from apps.github_sync.models import GithubConnection

    correlation_id = uuid.uuid4().hex
    connection = GithubConnection.objects.filter(user=user, revoked_at__isnull=True).first()

    try:
        with transaction.atomic():
            record_audit(
                actor=user,
                action="account.deletion_requested",
                obj=user,
                correlation_id=correlation_id,
            )
            profile = MemberProfile.objects.filter(user=user).first()
            avatar = profile.avatar if profile is not None and profile.avatar else None

            session_keys = list(
                UserSession.objects.filter(user=user).values_list("session_key", flat=True)
            )
            Session.objects.filter(session_key__in=session_keys).delete()
            UserSession.objects.filter(user=user).delete()
            TOTPDevice.objects.filter(user=user).delete()
            MemberProfile.objects.filter(user=user).delete()
            user.education.all().delete()
            user.links.all().delete()
            user.skills.all().delete()
            ContributionRecord.objects.filter(contributor=user).update(contributor=None)
            user.set_unusable_password()
            user.username = f"deleted-{user.pk}"
            user.email = ""
            user.first_name = ""
            user.last_name = ""
            user.is_active = False
            user.save(
                update_fields=[
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "is_active",
                    "password",
                ]
            )
            record_audit(
                actor=user,
                action="account.anonymized",
                obj=user,
                after={"contribution_attribution_removed": True},
                correlation_id=correlation_id,
            )
            if connection is not None or avatar is not None:
                transaction.on_commit(
                    lambda: _finalize_account_deletion_external_effects(
                        user=user,
                        disconnect_github=connection is not None,
                        avatar=avatar,
                    )
                )
    except AccountDeletionExternalEffectError:
        raise
    except Exception:
        logger.exception("account deletion failed (user_id=%s)", user.pk)
        raise


def _finalize_account_deletion_external_effects(*, user, disconnect_github, avatar) -> None:
    from apps.github_sync.services import disconnect

    try:
        if disconnect_github:
            disconnect(user)
        if avatar is not None:
            avatar.delete(save=False)
    except Exception as exc:
        logger.exception("post-commit account deletion cleanup failed (user_id=%s)", user.pk)
        raise AccountDeletionExternalEffectError(
            "post-commit account deletion cleanup failed"
        ) from exc


def record_session(request, user):
    from apps.accounts.models import UserSession

    session_key = request.session.session_key
    if not session_key:
        request.session.save()
        session_key = request.session.session_key
    ip_address = request.META.get("REMOTE_ADDR", "")
    ip_hash = hashlib.sha256(f"{settings.SECRET_KEY}:{ip_address}".encode()).hexdigest()
    session, _ = UserSession.objects.update_or_create(
        session_key=session_key,
        defaults={
            "user": user,
            "last_activity": timezone.now(),
            "ip_hash": ip_hash,
        },
    )
    return session


def revoke_session(session_key: str) -> None:
    from apps.accounts.models import UserSession

    UserSession.objects.filter(session_key=session_key, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
