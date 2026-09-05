import typing
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import get_valid_filename

from apps.accounts.enums import Availability, LinkType, Province
from apps.accounts.fields import NormalizedURLField
from apps.taxonomy.enums import ContentLanguage
from apps.taxonomy.fields import NFCCharField, NFCTextField


class User(AbstractUser):
    """Platform identity. Roles and ministry assignment are modelled separately."""


def member_avatar_path(instance, filename):
    return f"avatars/{instance.user_id}/{uuid.uuid4().hex}/{get_valid_filename(filename)}"


class MemberProfile(models.Model):
    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="profile")
    headline = NFCCharField(max_length=200, blank=True, default="")
    bio = NFCTextField(blank=True, default="")
    location = NFCCharField(max_length=120, blank=True, default="")
    province = models.CharField(max_length=20, choices=Province.choices, blank=True, default="")
    preferred_language = models.CharField(
        max_length=2, choices=ContentLanguage.choices, default=ContentLanguage.ENGLISH
    )
    experience_band = models.CharField(max_length=30, blank=True, default="")
    availability = models.CharField(
        max_length=20, choices=Availability.choices, blank=True, default=""
    )
    interests = NFCTextField(blank=True, default="")
    contribution_preferences = NFCTextField(blank=True, default="")
    avatar = models.FileField(upload_to=member_avatar_path, null=True, blank=True, max_length=255)
    field_visibility = models.JSONField(default=dict, blank=True)
    directory_discoverable = models.BooleanField(default=False)
    leaderboard_opt_out = models.BooleanField(default=False)
    onboarding_completed = models.BooleanField(default=False)
    github_onboarding_skipped = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-updated_at"]
        verbose_name = "member profile"
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["directory_discoverable"], name="idx_profile_discoverable"),
        ]

    def __str__(self):
        return f"Profile of {self.user.username}"


class MemberEducation(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="education")
    institution = NFCCharField(max_length=200)
    credential = NFCCharField(max_length=200, blank=True, default="")
    field_of_study = NFCCharField(max_length=120, blank=True, default="")
    start_year = models.PositiveIntegerField(null=True, blank=True)
    end_year = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-start_year"]
        indexes: typing.ClassVar[list] = [models.Index(fields=["user"], name="idx_memberedu_user")]

    def __str__(self):
        return f"{self.user.username} — {self.institution}"


class MemberLink(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="links")
    link_type = models.CharField(max_length=15, choices=LinkType.choices)
    url = NormalizedURLField()
    label = NFCCharField(max_length=120, blank=True, default="")
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["link_type", "id"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["user", "url"], name="uniq_member_link_url"),
        ]

    def __str__(self):
        return f"{self.user.username} → {self.url}"


class UserSession(models.Model):
    session_key = models.CharField(max_length=40, unique=True)
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="sessions")
    device_label = NFCCharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["-last_activity"]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["user", "last_activity"], name="idx_usersession_user_activity"),
        ]

    def __str__(self):
        return f"{self.user.username} on {self.device_label or 'device'}"


class MemberSkill(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="skills")
    skill = models.ForeignKey("taxonomy.Skill", on_delete=models.PROTECT, related_name="members")
    self_rating = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: typing.ClassVar[list[str]] = ["skill__name"]
        constraints: typing.ClassVar[list] = [
            models.UniqueConstraint(fields=["user", "skill"], name="uniq_member_skill"),
        ]
        indexes: typing.ClassVar[list] = [
            models.Index(fields=["user"], name="idx_memberskill_user")
        ]

    def __str__(self):
        return f"{self.user.username}: {self.skill.name}"
