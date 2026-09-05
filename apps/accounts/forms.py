import typing

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UsernameField
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy

from apps.accounts.enums import Visibility
from apps.accounts.models import MemberLink, MemberProfile, User
from apps.accounts.services import (
    VISIBILITY_CONTROLLED_FIELDS,
    normalize_public_url,
    sync_member_skills,
)
from apps.taxonomy.fields import normalize_nfc
from apps.taxonomy.models import Skill


class NFCUsernameField(UsernameField):
    def to_python(self, value):
        return normalize_nfc(super().to_python(value))


class LocalAuthenticationForm(AuthenticationForm):
    pass


class MemberSignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    username = NFCUsernameField(
        label=gettext_lazy("Username"),
        max_length=150,
    )
    email = forms.EmailField(label=gettext_lazy("Email"))

    def clean_email(self):
        email = normalize_nfc(self.cleaned_data["email"].lower())
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                gettext_lazy("An account with this email already exists."),
                code="email_in_use",
            )
        return email


class MemberProfileForm(forms.ModelForm):
    MAX_AVATAR_BYTES = 5 * 1024 * 1024
    AVATAR_SIGNATURES: typing.ClassVar[dict[str, tuple[bytes, ...]]] = {
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
    }

    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.filter(is_active=True),
        required=False,
        label=gettext_lazy("Skills"),
        help_text=gettext_lazy("Choose from the admin-managed skill taxonomy."),
    )

    class Meta:
        model = MemberProfile
        fields = (
            "headline",
            "bio",
            "location",
            "province",
            "preferred_language",
            "experience_band",
            "availability",
            "interests",
            "contribution_preferences",
            "avatar",
            "directory_discoverable",
            "leaderboard_opt_out",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_language"].required = False
        if self.instance.user_id:
            self.fields["skills"].initial = list(
                self.instance.user.skills.filter(skill__is_active=True).values_list(
                    "skill_id", flat=True
                )
            )
        for field in sorted(VISIBILITY_CONTROLLED_FIELDS):
            self.fields[f"visibility_{field}"] = forms.ChoiceField(
                choices=Visibility.choices,
                initial=self.instance.field_visibility.get(field, Visibility.PRIVATE),
                required=False,
            )

    def clean_preferred_language(self):
        if "preferred_language" not in self.data:
            return self.instance.preferred_language
        return self.cleaned_data["preferred_language"]

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar or not hasattr(avatar, "file") or not hasattr(avatar, "size"):
            return avatar
        if avatar.size > self.MAX_AVATAR_BYTES:
            raise forms.ValidationError(
                gettext_lazy("Profile photographs must be 5 MB or smaller.")
            )
        suffix = "." + avatar.name.rsplit(".", 1)[-1].lower() if "." in avatar.name else ""
        signatures = self.AVATAR_SIGNATURES.get(suffix)
        if signatures is None:
            raise forms.ValidationError(gettext_lazy("Use a JPG, PNG, or WebP profile photograph."))
        header = avatar.file.read(12)
        avatar.file.seek(0)
        if not any(header.startswith(signature) for signature in signatures):
            raise forms.ValidationError(
                gettext_lazy("The profile photograph does not match its file type.")
            )
        if suffix == ".webp" and header[8:12] != b"WEBP":
            raise forms.ValidationError(
                gettext_lazy("The profile photograph does not match its file type.")
            )
        return avatar

    def save(self, commit=True):
        profile = super().save(commit=False)
        visibility = dict(profile.field_visibility)
        for field in VISIBILITY_CONTROLLED_FIELDS:
            value = self.cleaned_data[f"visibility_{field}"]
            if value:
                visibility[field] = value
        profile.field_visibility = visibility
        if commit:
            profile.save()
            self.save_m2m()
            sync_member_skills(profile.user, self.cleaned_data["skills"])
        return profile


class OnboardingProfileForm(forms.ModelForm):
    """The optional B1 profile details, saved independently from visibility choices."""

    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.filter(is_active=True),
        required=False,
        label=gettext_lazy("Skills"),
    )

    class Meta:
        model = MemberProfile
        fields = (
            "skills",
            "experience_band",
            "availability",
            "location",
            "province",
            "headline",
            "contribution_preferences",
            "interests",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.user_id:
            self.fields["skills"].initial = list(
                self.instance.user.skills.filter(skill__is_active=True).values_list(
                    "skill_id", flat=True
                )
            )

    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.save()
            self.save_m2m()
            sync_member_skills(profile.user, self.cleaned_data["skills"])
        return profile


class OnboardingVisibilityForm(forms.Form):
    """B1.4 controls only the visibility boundaries the public projection enforces."""

    directory_discoverable = forms.BooleanField(
        required=False,
        label=gettext_lazy("List my profile in the public member directory"),
    )
    leaderboard_opt_out = forms.BooleanField(
        required=False,
        label=gettext_lazy("Do not list me on the public leaderboard"),
    )

    def __init__(self, *args, profile: MemberProfile, **kwargs):
        self.profile = profile
        super().__init__(*args, **kwargs)
        self.fields["directory_discoverable"].initial = profile.directory_discoverable
        self.fields["leaderboard_opt_out"].initial = profile.leaderboard_opt_out
        for field in sorted(VISIBILITY_CONTROLLED_FIELDS):
            self.fields[f"visibility_{field}"] = forms.ChoiceField(
                choices=Visibility.choices,
                initial=profile.field_visibility.get(field, Visibility.PRIVATE),
                label=gettext_lazy(field.replace("_", " ").capitalize()),
            )

    def save(self):
        visibility = dict(self.profile.field_visibility)
        for field in VISIBILITY_CONTROLLED_FIELDS:
            visibility[field] = self.cleaned_data[f"visibility_{field}"]
        self.profile.field_visibility = visibility
        self.profile.directory_discoverable = self.cleaned_data["directory_discoverable"]
        self.profile.leaderboard_opt_out = self.cleaned_data["leaderboard_opt_out"]
        self.profile.save(
            update_fields=[
                "field_visibility",
                "directory_discoverable",
                "leaderboard_opt_out",
                "updated_at",
            ]
        )
        return self.profile


class MemberLinkForm(forms.ModelForm):
    class Meta:
        model = MemberLink
        fields = ("link_type", "url", "label", "is_public")
        labels: typing.ClassVar[dict] = {
            "link_type": gettext_lazy("Link type"),
            "url": gettext_lazy("URL"),
            "label": gettext_lazy("Label"),
            "is_public": gettext_lazy("Show publicly"),
        }


class MemberLinkBaseFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen_urls = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            url = form.cleaned_data.get("url")
            if not url:
                continue
            normalized = normalize_public_url(str(url))
            if normalized in seen_urls:
                form.add_error("url", gettext_lazy("This URL is already linked on your profile."))
            seen_urls.add(normalized)


MemberLinkFormSet = inlineformset_factory(
    User,
    MemberLink,
    form=MemberLinkForm,
    formset=MemberLinkBaseFormSet,
    extra=1,
    can_delete=True,
    max_num=8,
)
