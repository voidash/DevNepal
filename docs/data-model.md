# DevNepal Data Model — Authoritative Django Model Specification

Status: **Normative.** Implementation agents follow this document literally. Source of truth for
requirements: `docs/srs-v0.9.txt` (SRS v0.9). Requirement IDs in brackets map each model and field
to the SRS.

Target: Django 6.1, `AUTH_USER_MODEL = "accounts.User"` (already set in `config/settings/base.py`).
`USE_TZ = True` — all datetimes UTC aware; render in `Asia/Kathmandu`. Production DB PostgreSQL;
tests SQLite. `models.JSONField` is Django's native field and works on both backends (SQLite ≥ 3.9
with JSON1, enabled by default on supported builds). Never use `django-jsonfield` or
backend-specific JSON column types.

Apps (fixed): `accounts`, `ministries`, `taxonomy`, `projects`, `contributions`, `github_sync`,
`blogs`, `recognition`, `notifications`, `moderation`, `audit`.

---

## 1. Global conventions (apply to every model below)

### 1.1 Primary keys

- Default `BigAutoField` pk (Django default). Do not declare it explicitly.
- UUID pk (`models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`) ONLY where
  the row is an immutable ledger entry: `projects.ProjectVersion`, `github_sync.ProviderEvent`.
  Everything else is BigAuto; public addressing goes through unique slugs or usernames.

### 1.2 Timestamps

`created_at = models.DateTimeField(auto_now_add=True)` and, where the row is mutable,
`updated_at = models.DateTimeField(auto_now=True)`.

### 1.3 Unicode normalization [DSC-003; AGENTS.md rule 6]

All user-authored text that is searchable, displayed, or slug-relevant MUST be NFC-normalized on
save. One shared implementation in `apps/taxonomy/fields.py` (taxonomy has no model dependencies,
so every app can import it without cycles):

```python
import unicodedata

from django.db import models


def normalize_nfc(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return value


class NFCCharField(models.CharField):
    def get_prep_value(self, value):
        return normalize_nfc(super().get_prep_value(value))


class NFCTextField(models.TextField):
    def get_prep_value(self, value):
        return normalize_nfc(super().get_prep_value(value))


class NFCSlugField(models.SlugField):
    def get_prep_value(self, value):
        return normalize_nfc(super().get_prep_value(value))
```

Import contract: `from apps.taxonomy.fields import NFCCharField, NFCTextField, NFCSlugField`.
Use `NFCCharField`/`NFCTextField` for every user-entered Char/Text field and `NFCSlugField` for
slugs (`allow_unicode=True` where Devanagari slugs are allowed — DSC-003). Each app's tests assert
NFC normalization on save (cite DSC-003).

### 1.4 Shared enums (`apps/taxonomy/enums.py`)

Other apps import these rather than redefining:

```python
from django.db import models


class ContentLanguage(models.TextChoices):
    ENGLISH = "en", "English"
    NEPALI = "ne", "Nepali"


class DataClassification(models.TextChoices):
    PUBLIC = "public", "Public"
    INTERNAL = "internal", "Internal"
    CONFIDENTIAL = "confidential", "Confidential"
```

`DataClassification` values follow SRS §9.2. `SECRET` and `PROHIBITED` classes are never stored as
model data — the platform must not collect them (§9.2 "Prohibited for DevNepal"). Government
projects listed publicly must be `PUBLIC` (service-enforced via §5.3 suitability).

### 1.5 Relationships

- FKs to users use the string `"accounts.User"` (resolves via `AUTH_USER_MODEL`).
- `on_delete` policy:
  - `CASCADE` — child rows meaningless without parent (profiles, solely-owned content, throughs).
  - `PROTECT` — rows with retention/audit obligations [BR-008]: contributions → projects,
    badges/policies from recognition, taxonomy terms referenced by live records, versions/reviews.
  - `SET_NULL` (`null=True`) — attribution on ledger rows (actors, verifiers, reviewers) so
    history survives account deletion/anonymisation [AUTH-010, §9.3].
- Every FK/M2M declares `related_name`. Every model defines `__str__`.
- Generic relations (`Report`/`ModerationCase` targets) use `contenttypes.ContentType` +
  `GenericForeignKey` (contenttypes already installed).

### 1.6 Meta conventions

- `Meta.constraints` and `Meta.indexes` carry explicit `name=` (≤ 60 chars).
- `Meta.verbose_name` in English; Nepali comes from `locale/ne/LC_MESSAGES/django.po`
  [NFR-I18N-01].
- `Meta.ordering` ends with `-created_at`/`-id`/`pk` for deterministic paging.

### 1.7 Files and JSON

- File fields: `models.FileField` with a private object-storage backend and an `upload_to`
  callable (§10 object storage; SEC-007). Attachment rows record `original_filename`,
  content-verified `content_type`, `size_bytes`, and a scan status. Nothing under media roots is
  served without an access check; uploads are never executable.
- `JSONField` defaults are callables: `default=dict` or `default=list`, never mutable literals.

### 1.8 Audit obligations [AGENTS.md rule 7]

Every privileged/state-changing action calls `apps.audit.services.record_audit(...)` with
before/after payloads. Model layer duty: keep before/after serializable and immutable once
written. Actions: ministry create/suspend/revoke; publisher grant/revoke; project
submit/approve/request-changes/reject/publish/revoke-approval/pause/resume/complete/cancel/
archive/restore and material-edit resubmission [GOV-004, GOV-006]; application decisions
[DSC-007]; contribution verify/reject/revoke [BR-006, REC-005]; badge award/revoke; scoring policy
activation; moderation actions and appeals [ADM-004, BR-010]; account suspension [AUTH-009];
privileged exports [ADM-005].

### 1.9 App dependency / migration order

```
taxonomy      (no deps; hosts shared fields + enums)
accounts      (taxonomy: fields/enums only)
ministries    (accounts)
projects      (accounts, ministries, taxonomy)
github_sync   (accounts, projects)
contributions (accounts, projects, taxonomy, github_sync)
blogs         (accounts, taxonomy)
recognition   (accounts, contributions)
notifications (accounts)
moderation    (accounts)
audit         (exists; no new models)
```

Cross-app references in `models.py` are string FKs only; no cross-app model imports at module
level (avoid import cycles and app-loading order issues).

---

## 2. Given models — DO NOT redesign

### 2.1 `accounts.User` (exists; `apps/accounts/models.py` is coordinator-locked)

Custom `AbstractUser`, BigAuto pk, no extra fields. Roles, ministry assignment, and officer status
live OUTSIDE `User` (§4.3 below). `username` is the unique public username [MEM-001]; the pk is the
immutable internal identifier [MEM-001]. Suspension = `is_active=False`, losing authenticated
access immediately [AUTH-009]. Deletion requests lead to deactivation + anonymisation, not row
deletion, where retention applies [AUTH-010, §9.3].

### 2.2 `audit.AuditEvent` (exists; coordinator-locked)

UUID pk, append-only; update/delete raise `PermissionError` [ADM-008, SEC-008]. Fields as
implemented: `actor` FK (SET_NULL), `action`, `content_type` FK, `object_id`, `before`/`after`
JSON, `source`, `result`, `correlation_id`, `created_at`. Serves §9.1 "Audit event". No additional
audit models; never bulk-update/delete these rows.

> **COORDINATOR ACTION REQUIRED:** §9.1 requires member-profile entities in the accounts domain,
> but `apps/accounts/models.py` is in the permanently-locked list (AGENTS.md). Either unlock the
> file for the accounts agent or have the coordinator apply Section 3 verbatim. All other
> accounts-app files (admin/views/tests/factories) already belong to the accounts agent.

---

## 3. `apps.accounts` — member identity surface

Serves §9.1 "Member profile": public/private fields, skills, education, interests, links,
preferences, visibility. `User` stays generic (given); all profile data lives here.

### 3.1 Enums (`apps/accounts/enums.py`)

```python
from django.db import models


class Province(models.TextChoices):
    KOSHI = "koshi", "Koshi"
    MADHESH = "madhesh", "Madhesh"
    BAGMATI = "bagmati", "Bagmati"
    GANDAKI = "gandaki", "Gandaki"
    LUMBINI = "lumbini", "Lumbini"
    KARNALI = "karnali", "Karnali"
    SUDURPASCHIM = "sudurpaschim", "Sudurpashchim"
    OUTSIDE_NEPAL = "outside_nepal", "Outside Nepal"


class Availability(models.TextChoices):
    AVAILABLE_NOW = "available_now", "Available now"
    LIMITED = "limited", "Limited (a few hours per week)"
    UNAVAILABLE = "unavailable", "Not available"


class LinkType(models.TextChoices):
    GITHUB = "github", "GitHub"
    MEDIUM = "medium", "Medium"
    WEBSITE = "website", "Personal website"
    PORTFOLIO = "portfolio", "Portfolio"
    LINKEDIN = "linkedin", "LinkedIn"
    OTHER = "other", "Other"
```

`Province` exists for privacy-safe inclusion reporting only (§3.2 Inclusion metric; reported at
aggregation levels with ANL-003 suppression).

### 3.2 `MemberProfile` [MEM-001…MEM-003, MEM-008, MEM-009; REC-004; §18.3 directory opt-in]

| Field | Type | null/blank | default |
|---|---|---|---|
| user | OneToOneField("accounts.User", on_delete=CASCADE, related_name="profile") | no | — |
| headline | NFCCharField(200) | blank | "" |
| bio | NFCTextField(blank=True) | blank | "" |
| location | NFCCharField(120, blank=True) | blank | "" |
| province | CharField(20, choices=Province.choices, blank=True) | blank | "" |
| preferred_language | CharField(2, choices=ContentLanguage.choices) | no | "en" |
| experience_band | CharField(30, blank=True) | blank | "" |
| availability | CharField(20, choices=Availability.choices, blank=True) | blank | "" |
| interests | NFCTextField(blank=True) | blank | "" |
| contribution_preferences | NFCTextField(blank=True) | blank | "" |
| avatar | FileField(upload_to=<private callable>, null=True, blank=True) | yes | None |
| field_visibility | JSONField(default=dict) | no | {} |
| directory_discoverable | BooleanField(default=False) | no | False |
| leaderboard_opt_out | BooleanField(default=False) | no | False |
| created_at / updated_at | auto_now_add / auto_now | — | — |

Notes:
- `experience_band` stores the slug of a taxonomy `EXPERIENCE_BAND` term. It is a plain CharField
  (not an FK) so accounts depends on taxonomy only for fields/enums; the service layer validates
  it against taxonomy [MEM-002, MEM-004].
- `field_visibility` keys: `location`, `province`, `education`, `links`, `skills`; values
  `public` / `members` / `private`. Email, authentication provider, and private contact info are
  non-public regardless of this map [MEM-003].
- `directory_discoverable` gates the public member directory (§18.3 "Public member directory:
  opt-in discoverability").
- `leaderboard_opt_out` hides public leaderboard display while retaining private history
  [REC-004]; recognition renders must respect it.
- Profile preview (MEM-008) and completeness guidance (MEM-009) are service/view features over
  this row; no extra columns.

Meta: `ordering = ["-updated_at"]`; `verbose_name = "member profile"`;
`UniqueConstraint(fields=["user"], name="uniq_member_profile_user")` (OneToOne already enforces;
keep the field-level unique, no duplicate constraint). Index:
`Index(fields=["directory_discoverable"], name="idx_profile_discoverable")`.
`__str__` → `f"Profile of {self.user.username}"`.

### 3.3 `MemberSkill` [MEM-002, MEM-004; BR-004]

| Field | Type |
|---|---|
| user | FK("accounts.User", on_delete=CASCADE, related_name="skills") |
| skill | FK("taxonomy.Skill", on_delete=PROTECT, related_name="members") |
| self_rating | CharField(20, blank=True, default="") |
| created_at | DateTimeField(auto_now_add=True) |

`self_rating` is self-declared and is never a government-verified credential [BR-004].
Meta: `ordering = ["skill__name"]`;
`UniqueConstraint(fields=["user", "skill"], name="uniq_member_skill")`;
`Index(fields=["user"], name="idx_memberskill_user")`.
`__str__` → `f"{self.user.username}: {self.skill.name}"`.

### 3.4 `MemberEducation` [MEM-002, MEM-003; §12.2 minimisation]

Fields: user FK CASCADE related_name="education"; institution `NFCCharField(200)`;
credential `NFCCharField(200, blank=True)`; field_of_study `NFCCharField(120, blank=True)`;
start_year / end_year `PositiveIntegerField(null=True, blank=True)`; created_at.
Education records are NEVER published — no public-visibility flag exists by design [MEM-003,
§12.2 "avoid publishing … education documents"].
Meta: `ordering = ["-start_year"]`; `Index(fields=["user"], name="idx_memberedu_user")`.
`__str__` → `f"{self.user.username} — {self.institution}"`.

### 3.5 `MemberLink` [MEM-005, MEM-006, MEM-007]

Fields: user FK CASCADE related_name="links"; link_type
`CharField(15, choices=LinkType.choices)`; url `URLField()` (clean-time validation: http/https
only, normalised, unsafe schemes rejected — MEM-007); label `NFCCharField(120, blank=True)`;
is_public `BooleanField(default=False)` [MEM-003]; created_at.
Meta: `ordering = ["link_type", "id"]`;
`UniqueConstraint(fields=["user", "url"], name="uniq_member_link_url")`.
`__str__` → `f"{self.user.username} → {self.url}"`.

### 3.6 `UserSession` [AUTH-007]

Device/session listing for privileged users (Super Admin, Ministry Publisher).
Fields: session_key `CharField(40, unique=True)`; user FK CASCADE related_name="sessions";
device_label `NFCCharField(200, blank=True)` (user-agent family); created_at; last_activity
`DateTimeField(null=True, blank=True)`; revoked_at `DateTimeField(null=True, blank=True)`;
ip_hash `CharField(64, blank=True, default="")` (salted hash only — raw IPs are not stored
[§9.2 minimisation, ANL-001]).
Meta: `ordering = ["-last_activity"]`; `Index(fields=["user", "last_activity"],
name="idx_usersession_user_activity")`.
`__str__` → `f"{self.user.username} on {self.device_label or 'device'}"`.

---

## 4. `apps.ministries` — ministry organizations and named officers

Serves §9.1 "Ministry organization" and the §4.2 control requirement: one organization, multiple
named publisher accounts, never shared credentials. `accounts.User` stays generic; the officer
relationship and its status live here [AUTH-004].

### 4.1 Enums (`apps/ministries/enums.py`)

```python
from django.db import models


class OrgStatus(models.TextChoices):
    PENDING = "pending", "Pending activation"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    REVOKED = "revoked", "Revoked"


class PublisherStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"
```

[§4.2: create/activate/suspend/revoke organizations; create/revoke named officers.]

### 4.2 `MinistryOrganization` [AUTH-004; GOV-001; BR-001; A1]

| Field | Type | null/blank | default |
|---|---|---|---|
| name_en | NFCCharField(200) | no | — |
| name_ne | NFCTextField(blank=True) | blank | "" |
| slug | NFCSlugField(max_length=220, allow_unicode=True, unique=True) | no | — |
| abbreviation | NFCCharField(20, blank=True) | blank | "" |
| description | NFCTextField(blank=True) | blank | "" |
| contact_email | EmailField(blank=True) | blank | "" |
| website_url | URLField(blank=True) | blank | "" |
| status | CharField(12, choices=OrgStatus.choices) | no | OrgStatus.PENDING |
| provisioned_by | FK("accounts.User", null=True, on_delete=SET_NULL, related_name="provisioned_ministries") | yes | None |
| provisioned_at | DateTimeField(null=True, blank=True) | yes | None |
| suspended_at | DateTimeField(null=True, blank=True) | yes | None |
| suspension_reason | NFCTextField(blank=True) | blank | "" |
| revoked_at | DateTimeField(null=True, blank=True) | yes | None |
| revocation_reason | NFCTextField(blank=True) | blank | "" |
| created_at / updated_at | auto | — | — |

Notes: `name_ne` bilingual ministry name [NFR-I18N-01]. `contact_email` is Confidential class
[§9.2] — never rendered publicly. Suspended/revoked organizations block all publisher actions
(service; AUTH-004). `slug` unique for stable public URLs [DSC-003].

Meta: `ordering = ["name_en"]`; `verbose_name = "ministry organization"`;
`Index(fields=["status"], name="idx_ministry_status")`.
`__str__` → `self.name_en`.

### 4.3 `MinistryPublisher` [AUTH-004, AUTH-005; GOV-001; A1; §4.2 control requirement]

Named officer assignment; credentials are per-person, revocable independently (A1: revoking one
publisher must not affect another). MFA is enforced by the auth stack for any user holding an
ACTIVE assignment [AUTH-005] — policy, not a column; tests assert behavior.

| Field | Type |
|---|---|
| user | FK("accounts.User", on_delete=CASCADE, related_name="publisher_assignments") |
| ministry | FK(MinistryOrganization, on_delete=CASCADE, related_name="publishers") |
| title | NFCCharField(120) |
| official_email | EmailField() |
| status | CharField(10, choices=PublisherStatus.choices, default=PublisherStatus.ACTIVE) |
| assigned_by | FK("accounts.User", null=True, on_delete=SET_NULL, related_name="granted_publisher_roles") |
| assigned_at | DateTimeField(auto_now_add=True) |
| revoked_by | FK("accounts.User", null=True, on_delete=SET_NULL, related_name="revoked_publisher_roles") |
| revoked_at | DateTimeField(null=True, blank=True) |
| revocation_reason | NFCTextField(blank=True, default="") |

Meta: `ordering = ["ministry__name_en", "user__username"]`;
`UniqueConstraint(fields=["user", "ministry"], name="uniq_publisher_user_ministry")`;
`Index(fields=["user", "status"], name="idx_publisher_user_status")`;
`Index(fields=["ministry", "status"], name="idx_publisher_ministry_status")`.
`__str__` → `f"{self.user.username} @ {self.ministry.name_en}"`.

Authorization derivation [AUTH-006, GOV-001]: a user may create/edit government drafts only for
ministries where they hold `status=ACTIVE` and the ministry itself is ACTIVE. All publish,
approve, verification, suspension, and material-edit actions by these users are attributable to
the named person via audit [§4.2 control requirement].

---

## 5. `apps.taxonomy` — admin-managed vocabularies

Serves [MEM-004, ADM-001, GOV-008, DSC-002, BR-012, §12.4 license allowlist]. Also hosts the
shared NFC fields (§1.3) and shared enums (§1.4). Referenced via PROTECT from other apps so
taxonomy edits never silently rewrite historical meaning [BR-012].

### 5.1 Enums (`apps/taxonomy/enums.py`)

```python
class TermVocabulary(models.TextChoices):
    PROJECT_CATEGORY = "project_category", "Project category"
    CONTRIBUTION_TYPE = "contribution_type", "Contribution type"
    TECHNOLOGY = "technology", "Technology"
    EXPERIENCE_BAND = "experience_band", "Experience band"
    TAG = "tag", "Tag"


class SuggestionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DISMISSED = "dismissed", "Dismissed"
```

Seed `CONTRIBUTION_TYPE` with the GOV-008 list — engineering, UI/UX, QA, security, data,
documentation, localization, research, community support — via data migration; Nepali labels come
from po files, not the DB.

### 5.2 `Skill` [MEM-002, MEM-004, DSC-002]

Fields: name `NFCCharField(100)`; slug `NFCSlugField(120, allow_unicode=True, unique=True)`;
description `NFCTextField(blank=True)`; is_active `BooleanField(default=True)`; created_at /
updated_at.
Meta: `ordering = ["name"]`; `UniqueConstraint(fields=["name"], name="uniq_skill_name")`;
`Index(fields=["is_active"], name="idx_skill_active")`.
`__str__` → `self.name`.

### 5.3 `TaxonomyTerm` [ADM-001; GOV-008; DSC-002; BR-012]

Fields: vocabulary `CharField(30, choices=TermVocabulary.choices, db_index=True)`; label
`NFCCharField(150)`; slug `NFCSlugField(170, allow_unicode=True)`; description
`NFCTextField(blank=True)`; parent `FK("self", null=True, blank=True, on_delete=PROTECT,
related_name="children")`; sort_order `IntegerField(default=0)`; is_active
`BooleanField(default=True)`; created_at / updated_at.
Meta: `ordering = ["vocabulary", "sort_order", "label"]`;
`UniqueConstraint(fields=["vocabulary", "slug"], name="uniq_term_vocab_slug")`;
`UniqueConstraint(fields=["vocabulary", "label"], name="uniq_term_vocab_label")`;
`Index(fields=["vocabulary", "is_active"], name="idx_term_vocab_active")`.
`__str__` → `f"{self.get_vocabulary_display()}: {self.label}"`.
Terms are deactivated, never hard-deleted while referenced (PROTECT + admin guard) [BR-012].

### 5.4 `ApprovedLicense` [§12.4; GOV-002 Rights; BR-003; §18.3 "no free-text licenses"]

Fields: spdx_id `CharField(80, unique=True,
validators=[RegexValidator(r"^[A-Za-z0-9.+-]+$")])`; name `NFCCharField(200)`; reference_url
`URLField(blank=True)`; is_approved `BooleanField(default=False)`; is_default
`BooleanField(default=False)`.
Meta: `ordering = ["spdx_id"]`; `verbose_name = "approved license"`. At most one default
(service/admin enforced — documented, not a DB constraint).
`__str__` → `f"{self.spdx_id} ({self.name})"`.

### 5.5 `SkillSuggestion` [MEM-004]

Fields: suggested_by FK("accounts.User", null=True, on_delete=SET_NULL,
related_name="skill_suggestions"); term_name `NFCCharField(100)`; note `NFCTextField(blank=True)`;
status `CharField(10, choices=SuggestionStatus.choices, default=SuggestionStatus.PENDING)`;
resolved_by FK("accounts.User", null=True, on_delete=SET_NULL,
related_name="resolved_suggestions"); resolved_at `DateTimeField(null=True, blank=True)`;
created_at.
Meta: `ordering = ["-created_at"]`;
`UniqueConstraint(fields=["term_name"], name="uniq_suggestion_term")` — one open suggestion per
name; accepted suggestion creates a Skill and marks this ACCEPTED.
`__str__` → `f"Suggestion: {self.term_name}"`.

---

## 6. `apps.projects` — projects, lifecycle, review, applications

Serves §9.1 "Project", "Project version / review", "Application / participation"; §6.1 lifecycle;
§6.2–6.3 workflows; Appendix A field groups; Tables 7C, 7D, 7E. The state machine lives in
`apps/projects/services.py` (AGENTS.md); the models below are its data contract.

### 6.1 Enums (`apps/projects/enums.py`)

```python
from django.db import models


class ProjectType(models.TextChoices):
    GOVERNMENT = "government", "Government"
    PERSONAL = "personal", "Personal (community)"


class ProjectStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    IN_REVIEW = "in_review", "In review"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    APPROVED = "approved", "Approved / scheduled"
    OPEN_FOR_CONTRIBUTION = "open_for_contribution", "Open for contribution"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    ARCHIVED = "archived", "Archived"


class DifficultyLevel(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"


class EffortBand(models.TextChoices):
    SMALL = "small", "Small (about 1 week)"
    MEDIUM = "medium", "Medium (1-4 weeks)"
    LARGE = "large", "Large (over 4 weeks)"


class ContributionMode(models.TextChoices):
    OPEN_DIRECT = "open_direct", "Open direct contribution"
    APPLICATION = "application", "Application required"
    HYBRID = "hybrid", "Hybrid (open tasks and application workstreams)"


class ResponseSla(models.TextChoices):
    WITHIN_24_HOURS = "24h", "Within 24 hours"
    WITHIN_3_DAYS = "3d", "Within 3 days"
    WITHIN_1_WEEK = "1w", "Within 1 week"


class GovernanceModel(models.TextChoices):
    MAINTAINER_CONSENSUS = "maintainer_consensus", "Maintainer consensus"
    LEAD_MAINTAINER = "lead_maintainer", "Lead maintainer decides"
    MINISTRY_APPROVAL = "ministry_approval", "Ministry approval required"


class SignoffModel(models.TextChoices):
    DCO = "dco", "DCO-style sign-off"
    CLA = "cla", "CLA required"
    NONE_REQUIRED = "none", "None required (non-code)"


class MaintainerRole(models.TextChoices):
    LEAD = "lead", "Lead maintainer"
    MAINTAINER = "maintainer", "Maintainer"
    REVIEWER = "reviewer", "Reviewer"


class AttachmentKind(models.TextChoices):
    PROPOSAL = "proposal", "Proposal"
    REQUIREMENTS = "requirements", "Requirements"
    ARCHITECTURE = "architecture", "Architecture"
    DESIGN = "design", "Design"
    API_DOC = "api_doc", "API documentation"
    RESEARCH = "research", "Research"
    TERMS = "terms", "Terms"
    IMAGE = "image", "Image"
    OTHER = "other", "Other"


class ScanStatus(models.TextChoices):
    PENDING = "pending", "Pending scan"
    CLEAN = "clean", "Clean"
    QUARANTINED = "quarantined", "Quarantined"
    FAILED = "failed", "Scan failed"


class ReviewDecision(models.TextChoices):
    APPROVED = "approved", "Approved"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    REJECTED = "rejected", "Rejected"
    PUBLISHED = "published", "Published"
    REVOKED = "revoked", "Approval revoked"
    RESTORED = "restored", "Restored from archive"


class ParticipationKind(models.TextChoices):
    INTEREST = "interest", "Expressed interest"
    APPLICATION = "application", "Application"
    ASSIGNMENT = "assignment", "Assigned work"


class ApplicationStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    INFO_REQUESTED = "info_requested", "Information requested"
    WAITLISTED = "waitlisted", "Waitlisted"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    WITHDRAWN = "withdrawn", "Withdrawn"


class ApplicationEventType(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    STATUS_CHANGED = "status_changed", "Status changed"
    INFO_REQUESTED = "info_requested", "Information requested"
    INFO_PROVIDED = "info_provided", "Information provided"
    COMMENTED = "commented", "Comment"
    ASSIGNED = "assigned", "Work assigned"
    WITHDRAWN = "withdrawn", "Withdrawn"


class TaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In progress"
    DONE = "done", "Done"
    CANCELLED = "cancelled", "Cancelled"


class MilestoneStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    IN_PROGRESS = "in_progress", "In progress"
    ACHIEVED = "achieved", "Achieved"
    DROPPED = "dropped", "Dropped"


class UpdateKind(models.TextChoices):
    PROGRESS = "progress", "Progress"
    MILESTONE = "milestone", "Milestone"
    RELEASE = "release", "Release/result"
    COMPLETION = "completion", "Completion summary"


class ProjectLinkKind(models.TextChoices):
    REPOSITORY = "repository", "Repository"
    DEMO = "demo", "Demo"
    WEBSITE = "website", "Website"
    DOCUMENTATION = "documentation", "Documentation"
    ARTICLE = "article", "Article"
    OTHER = "other", "Other"


class OwnershipVerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    VERIFIED_GITHUB = "verified_github", "Verified via GitHub"
    VERIFIED_DOMAIN = "verified_domain", "Verified via domain"
    VERIFIED_MANUAL = "verified_manual", "Verified manually by Super Admin"
```

`ProjectStatus` is exactly the nine §6.1 lifecycle rows; `APPROVED` carries the "scheduled"
meaning together with `Project.scheduled_publication_at`.

### 6.2 `Project` — common record; `project_type` discriminates government vs personal [§9.1; §6.1; GOV-002; PPR-002; DSC-001–DSC-003; BR-001, BR-002, BR-011]

Fields grouped per Appendix A. All user text uses NFC field types (§1.3).

**Identity [GOV-002 Identity; GOV-011; PPR-003]**

| Field | Type | null/blank | Notes |
|---|---|---|---|
| project_type | CharField(12, choices=ProjectType.choices, db_index=True) | no | personal projects are labelled community projects and never imply GoN endorsement [PPR-003, BR-009] |
| title_en | NFCCharField(200) | no | |
| title_ne | NFCCharField(200, blank=True) | blank | required for government at submit [§14.3] |
| slug | NFCSlugField(220, allow_unicode=True, unique=True) | no | stable, human-readable, Devanagari-capable [DSC-003] |
| ministry | FK("ministries.MinistryOrganization", null=True, blank=True, on_delete=PROTECT, related_name="projects") | yes | set iff government [GOV-001]; PROTECT: published projects must not vanish with an org row [BR-008] |
| owner | FK("accounts.User", on_delete=PROTECT, related_name="owned_projects") | no | the publisher (gov) or member (personal); attribution retained [BR-008] |
| maintainers | M2M("accounts.User", through="ProjectMaintainer", related_name="maintained_projects") | — | named maintainers [GOV-002; Appendix A Governance; BR-002] |

**Public value [GOV-002]**

problem_statement `NFCTextField(blank=True)`; target_users `NFCTextField(blank=True)`;
expected_outcome `NFCTextField(blank=True)`; success_indicators `NFCTextField(blank=True)`.

**Description [GOV-002]**

summary_en `NFCTextField(blank=True)`; summary_ne `NFCTextField(blank=True)` (both required for
government at submit [§14.3]); description_md `NFCTextField(blank=True)`; background
`NFCTextField(blank=True)`; current_state `NFCTextField(blank=True)`; limitations
`NFCTextField(blank=True)`; related_initiatives `NFCTextField(blank=True)`.

**Contribution need [GOV-002; GOV-007; GOV-008; DSC-002]**

contribution_types `M2M("taxonomy.TaxonomyTerm", blank=True, related_name="projects")`
(vocabulary CONTRIBUTION_TYPE — enforced in service/forms); skills
`M2M("taxonomy.Skill", blank=True, related_name="projects")`; technologies
`M2M("taxonomy.TaxonomyTerm", blank=True, related_name="technology_projects")` (vocabulary
TECHNOLOGY); difficulty `CharField(15, choices=DifficultyLevel.choices, blank=True)`;
experience_band `CharField(30, blank=True)` (taxonomy EXPERIENCE_BAND slug); estimated_effort
`CharField(10, choices=EffortBand.choices, blank=True)`; contributor_capacity
`PositiveIntegerField(null=True, blank=True)`; is_remote `BooleanField(default=True)`; location
`NFCCharField(120, blank=True)`; deadline `DateField(null=True, blank=True)` (expiry never
silently closes the project — GOV-010; owner must extend/pause/complete/cancel/archive).

**How to contribute [GOV-007; DSC-005; DSC-006; BR-002]**

contribution_mode `CharField(15, choices=ContributionMode.choices, blank=True)`;
prerequisites `NFCTextField(blank=True)`; communication_channel `URLField(blank=True)`
(public channel — §2.3 "visible contact channels"); response_sla `CharField(2,
choices=ResponseSla.choices, blank=True)`; code_of_conduct_url `URLField(blank=True)`;
screening questions are `ProjectScreeningQuestion` rows.

**Technical [GOV-002; BR-003]**

repository_url `URLField(blank=True)`; default_branch `NFCCharField(100, blank=True)`;
issue_tracker_url `URLField(blank=True)`; documentation_url `URLField(blank=True)`;
architecture_url `URLField(blank=True)`; environments_url `URLField(blank=True)`;
test_build_instructions `NFCTextField(blank=True)`; ci_status_url `URLField(blank=True)`.

**Governance [GOV-002; BR-003]**

governance_model `CharField(25, choices=GovernanceModel.choices, blank=True)`;
outcome_ownership `NFCTextField(blank=True)`; escalation_path `NFCTextField(blank=True)`;
completion_criteria `NFCTextField(blank=True)`. Review/merge authority lives on
`ProjectMaintainer.role` / `can_review_merge`.

**Rights [GOV-002; §12.4; BR-003]**

license `FK("taxonomy.ApprovedLicense", null=True, blank=True, on_delete=PROTECT,
related_name="projects")` (required for government before ready — no free-text licenses);
signoff_model `CharField(15, choices=SignoffModel.choices, blank=True)`;
third_party_rights_confirmed `BooleanField(default=False)`; content_license
`NFCCharField(200, blank=True)`.

**Security and data [GOV-002; §5.3; §9.2]**

data_classification `CharField(12, choices=DataClassification.choices,
default=DataClassification.PUBLIC)`; security_contact `EmailField(blank=True)`;
vulnerability_disclosure_url `URLField(blank=True)`; prohibited_data_statement
`NFCTextField(blank=True)`; suitability is the OneToOne `ProjectSuitability`.

**Planning [GOV-004; GOV-010; §6.1]**

status `CharField(25, choices=ProjectStatus.choices, default=ProjectStatus.DRAFT, db_index=True)`;
status_changed_at `DateTimeField(null=True, blank=True)`; scheduled_publication_at
`DateTimeField(null=True, blank=True)` (APPROVED + future date — §6.1 "optionally with a future
publication date"); published_at `DateTimeField(null=True, blank=True)`; current_version
`FK("projects.ProjectVersion", null=True, blank=True, on_delete=SET_NULL, related_name="+")` —
pointer to the approved live version so publication serves exactly the approved version [A2];
dependencies `NFCTextField(blank=True)`; risks `NFCTextField(blank=True)`;
last_maintainer_activity_at `DateTimeField(null=True, blank=True)` (input for DSC-009 activity
indicators and GOV-012 SLA flags); created_at / updated_at.

**Personal-project-only [PPR-002; PPR-004]**

role `NFCCharField(120, blank=True)`; ownership_verification `CharField(20,
choices=OwnershipVerificationStatus.choices, default=OwnershipVerificationStatus.UNVERIFIED)`.
Images are `ProjectAttachment(kind=IMAGE)` rows [PPR-002].

**Closure [GOV-002 Closure; GOV-009; BR-011]**

outcome_summary `NFCTextField(blank=True)`; deliverables `JSONField(default=list, blank=True)`
(list of `{label, url}`); impact_summary `NFCTextField(blank=True)`; lessons_learned
`NFCTextField(blank=True)`; archive_reason `NFCTextField(blank=True)`; archived_at
`DateTimeField(null=True, blank=True)`. Credited contributors derive from accepted
ContributionRecords (acknowledgements text supplements — GOV-009).

Meta:
- `ordering = ["-status_changed_at", "-id"]`.
- Constraints: `CheckConstraint(condition=Q(project_type=ProjectType.GOVERNMENT,
  ministry__isnull=False) | Q(project_type=ProjectType.PERSONAL, ministry__isnull=True),
  name="chk_project_type_ministry")`.
- Indexes: `Index(fields=["project_type", "status"], name="idx_project_type_status")`;
  `Index(fields=["ministry", "status"], name="idx_project_ministry_status")`;
  `Index(fields=["status", "-published_at"], name="idx_project_status_published")`;
  `Index(fields=["deadline"], name="idx_project_deadline")` (GOV-010 sweeps).
- PostgreSQL search: a separate vendor-guarded migration may add
  `django.contrib.postgres.indexes.GinIndex` on title/summary; SQLite tests use icontains.

`__str__` → `self.title_en`.

Property `is_official`: `project_type == GOVERNMENT and current_version_id is not None and
status in {APPROVED, OPEN_FOR_CONTRIBUTION, PAUSED, COMPLETED}` — computed, never stored
[GOV-011; BR-001]. The official badge renders from this property only.

### 6.3 Lifecycle transition table (enforced in `apps/projects/services.py`) [§6.1; GOV-004]

| From | To (actor) |
|---|---|
| DRAFT | IN_REVIEW (publisher submits) |
| IN_REVIEW | CHANGES_REQUESTED (Super Admin) · APPROVED (Super Admin) · DRAFT (Super Admin rejects submission; decision recorded) |
| CHANGES_REQUESTED | IN_REVIEW (publisher edits and resubmits) |
| APPROVED | OPEN_FOR_CONTRIBUTION (Super Admin publishes — immediately or at `scheduled_publication_at`) · CHANGES_REQUESTED (Super Admin revokes approval, with reason) |
| OPEN_FOR_CONTRIBUTION | PAUSED · COMPLETED · CANCELLED · ARCHIVED (owner/Super Admin per §4.2) |
| PAUSED | OPEN_FOR_CONTRIBUTION (resume) · COMPLETED · CANCELLED · ARCHIVED |
| COMPLETED | ARCHIVED (after retention period) · OPEN_FOR_CONTRIBUTION (reopen by approval) |
| CANCELLED | ARCHIVED · OPEN_FOR_CONTRIBUTION (reopen by approval) |
| ARCHIVED | prior state via Super Admin RESTORED decision only |

Interpretation notes (SRS names no target state for "reject" and "revoke approval"): reject returns
the project to DRAFT with the decision recorded in ProjectReview; revoking approval returns to
CHANGES_REQUESTED. Tests citing GOV-004 must cover both interpretations explicitly.

Personal projects use the subset DRAFT → OPEN_FOR_CONTRIBUTION ↔ PAUSED (PAUSED is the
"unpublish" equivalent: status stays publicly visible, applications disabled — PPR-001, BR-011) →
COMPLETED / CANCELLED / ARCHIVED. Personal projects never enter IN_REVIEW, CHANGES_REQUESTED, or
APPROVED (service check + test citing PPR-001).

Material edit [GOV-006]: changing license, repository_url, data_classification, scope
(description_md / problem_statement), signoff_model, security_contact, or communication_channel on
a project whose status is OPEN_FOR_CONTRIBUTION forces a new ProjectVersion and re-entry to
IN_REVIEW (or direct Super Admin approval). Service-level; tests cite GOV-006.

### 6.4 `ProjectMaintainer` (M2M through) [GOV-002 Identity/Governance; GOV-012]

Fields: project `FK(Project, on_delete=CASCADE, related_name="maintainer_assignments")`; user
`FK("accounts.User", on_delete=CASCADE, related_name="maintainer_assignments")`; role
`CharField(12, choices=MaintainerRole.choices, default=MaintainerRole.MAINTAINER)`;
can_review_merge `BooleanField(default=False)`; created_at.
Meta: `ordering = ["role", "user__username"]`;
`UniqueConstraint(fields=["project", "user"], name="uniq_project_maintainer")`.
`__str__` → `f"{self.user.username} as {self.get_role_display()} on {self.project}"`.

### 6.5 `ProjectVersion` — immutable submission snapshot [GOV-005; A2; BR-012]

UUID pk (§1.1 — immutability). Fields: project `FK(Project, on_delete=PROTECT,
related_name="versions")` [BR-008: deleting a project must not erase version history];
version_number `PositiveIntegerField()`; snapshot `JSONField(default=dict)` — full serialization
of every Appendix A field at submit time (keys = field names in §6.2); submitted_by
`FK("accounts.User", null=True, on_delete=SET_NULL, related_name="submitted_versions")`;
submitted_at `DateTimeField(auto_now_add=True)`; published_at `DateTimeField(null=True,
blank=True)`; published_by `FK("accounts.User", null=True, on_delete=SET_NULL,
related_name="published_versions")`.
Meta: `ordering = ["project", "-version_number"]`; `verbose_name = "project version"`;
`UniqueConstraint(fields=["project", "version_number"], name="uniq_project_version_number")`;
`Index(fields=["project", "-submitted_at"], name="idx_version_project_submitted")`.
`__str__` → `f"{self.project} v{self.version_number}"`.
Rows are immutable after creation except `published_at`/`published_by` (service-guarded; tested).

### 6.6 `ProjectReview` [GOV-004; GOV-005; §6.1]

Fields: project `FK(Project, on_delete=PROTECT, related_name="reviews")`; version
`FK(ProjectVersion, on_delete=PROTECT, related_name="reviews")`; reviewer
`FK("accounts.User", null=True, on_delete=SET_NULL, related_name="project_reviews")`; decision
`CharField(20, choices=ReviewDecision.choices, db_index=True)`; comment `NFCTextField(blank=True)`
(actor, timestamp, decision, reason/comment — GOV-005); from_status / to_status
`CharField(25, blank=True, default="")` (lifecycle before/after; pause/complete/cancel/archive/
restore/publish transitions are also recorded here, giving GOV-005 provenance for every action);
created_at `DateTimeField(auto_now_add=True, db_index=True)`.
Meta: `ordering = ["-created_at"]`;
`Index(fields=["project", "-created_at"], name="idx_review_project_created")`.
`__str__` → `f"{self.get_decision_display()} on {self.project} by {self.reviewer}"`.

### 6.7 `ProjectSuitability` [§5.3; BR-002]

Fields: project `OneToOneField(Project, on_delete=CASCADE, related_name="suitability")`;
checklist `JSONField(default=dict)` with required keys — each `{checked: bool, note: str}` —
covering the ten §5.3 areas: `legal_authority`, `source_code_rights`, `data_classification`,
`security_exposure`, `procurement_restrictions`, `third_party_licenses`, `repository_readiness`,
`maintainer_capacity`, `contribution_agreement`, `public_communications`; completed_by
`FK("accounts.User", null=True, on_delete=SET_NULL, related_name="suitability_completed")`;
completed_at `DateTimeField(null=True, blank=True)`; confirmed_by `FK("accounts.User", null=True,
on_delete=SET_NULL, related_name="suitability_confirmed")` (Super Admin confirmation — §5.3);
confirmed_at `DateTimeField(null=True, blank=True)`; notes `NFCTextField(blank=True)`.
`__str__` → `f"Suitability for {self.project}"`.
BR-002: publishing requires `confirmed_at is not None` plus named ministry owner, public
maintainer/contact path, approved contribution mode, and response expectation (service check +
test citing BR-002).

### 6.8 `ProjectScreeningQuestion` [DSC-006]

Fields: project `FK(Project, on_delete=CASCADE, related_name="screening_questions")`; question
`NFCCharField(300)`; help_text `NFCTextField(blank=True)`; is_required `BooleanField(default=True)`;
sort_order `IntegerField(default=0)`; is_active `BooleanField(default=True)`; created_at.
Meta: `ordering = ["sort_order", "id"]`;
`Index(fields=["project"], name="idx_screening_project")`.
`__str__` → `self.question`. Only these configured questions may be asked — forms capture nothing
else [DSC-006].

### 6.9 `ProjectTask` [GOV-007; BR-002; Appendix B starter issues]

Fields: project `FK(Project, on_delete=CASCADE, related_name="tasks")`; title `NFCCharField(200)`;
description `NFCTextField(blank=True)`; is_starter `BooleanField(default=False)`; issue_url
`URLField(blank=True)`; skills `M2M("taxonomy.Skill", blank=True, related_name="tasks")`;
assigned_to `FK("accounts.User", null=True, blank=True, on_delete=SET_NULL,
related_name="assigned_tasks")`; status `CharField(12, choices=TaskStatus.choices,
default=TaskStatus.OPEN)`; created_at / updated_at.
Meta: `ordering = ["status", "id"]`;
`Index(fields=["project", "status"], name="idx_task_project_status")`.
`__str__` → `self.title`. BR-002/GOV-007: an open project needs at least one actionable task or
workstream (service check).

### 6.10 `ProjectMilestone` [GOV-002 Planning; GOV-009]

Fields: project `FK(Project, on_delete=CASCADE, related_name="milestones")`; title
`NFCCharField(200)`; description `NFCTextField(blank=True)`; due_date `DateField(null=True,
blank=True)`; status `CharField(12, choices=MilestoneStatus.choices,
default=MilestoneStatus.PLANNED)`; completed_at `DateTimeField(null=True, blank=True)`;
sort_order `IntegerField(default=0)`; created_at.
Meta: `ordering = ["sort_order", "id"]`;
`Index(fields=["project", "status"], name="idx_milestone_project_status")`.
`__str__` → `self.title`.

### 6.11 `ProjectUpdate` [GOV-009]

Fields: project `FK(Project, on_delete=CASCADE, related_name="updates")`; title
`NFCCharField(200)`; body `NFCTextField()`; kind `CharField(12, choices=UpdateKind.choices,
default=UpdateKind.PROGRESS)`; link `URLField(blank=True)` (release/result links); created_by
`FK("accounts.User", null=True, on_delete=SET_NULL, related_name="project_updates")`; created_at.
Meta: `ordering = ["-created_at"]`;
`Index(fields=["project", "-created_at"], name="idx_update_project_created")`.
`__str__` → `self.title`.

### 6.12 `ProjectAttachment` [GOV-003; SEC-007; A7; Appendix A Attachments]

Fields: project `FK(Project, on_delete=CASCADE, related_name="attachments")`; kind `CharField(12,
choices=AttachmentKind.choices)`; file `FileField(upload_to=<private callable>)`;
original_filename `NFCCharField(255)`; content_type `CharField(100, blank=True, default="")`
(verified by content, not extension — SEC-007); size_bytes `PositiveBigIntegerField(default=0)`;
version `PositiveIntegerField(default=1)`; language `CharField(2,
choices=ContentLanguage.choices, default="en")`; classification `CharField(12,
choices=DataClassification.choices, default=DataClassification.PUBLIC)`; scan `CharField(12,
choices=ScanStatus.choices, default=ScanStatus.PENDING, db_index=True)`; accessibility_note
`NFCTextField(blank=True)`; uploaded_by `FK("accounts.User", null=True, on_delete=SET_NULL,
related_name="uploaded_attachments")`; created_at.
Meta: `ordering = ["kind", "-version"]`;
`Index(fields=["project", "kind"], name="idx_attachment_project_kind")`.
`__str__` → `f"{self.get_kind_display()}: {self.original_filename}"`.
Quarantined/failed files are never served and are deleted by the scan job (SEC-007; service +
test citing A7).

### 6.13 `ProjectLink` [PPR-002; PPR-005; MEM-007-style URL validation]

Fields: project `FK(Project, on_delete=CASCADE, related_name="links")`; kind `CharField(15,
choices=ProjectLinkKind.choices)`; url `URLField()` (validated/normalised; scheme allowlist);
label `NFCCharField(150, blank=True)`; created_at.
Meta: `ordering = ["kind", "id"]`;
`UniqueConstraint(fields=["project", "url"], name="uniq_project_link_url")`.
`__str__` → `f"{self.get_kind_display()}: {self.url}"`.

### 6.14 `Application` — application / participation [§9.1; DSC-005–DSC-008; BR-011]

Fields: project `FK(Project, on_delete=PROTECT, related_name="applications")` — applications are
Confidential-class records retained per §9.3; applicant `FK("accounts.User", on_delete=PROTECT,
related_name="applications")` — anonymisation, not cascade [AUTH-010]; kind `CharField(12,
choices=ParticipationKind.choices, default=ParticipationKind.APPLICATION)` [DSC-005: express
interest, apply, or assigned work]; status `CharField(15, choices=ApplicationStatus.choices,
default=ApplicationStatus.SUBMITTED, db_index=True)` [DSC-007: accept, waitlist, decline, request
information + member withdraw]; motivation `NFCTextField(blank=True)`; screening_answers
`JSONField(default=list, blank=True)` — list of `{question_id, question, answer}` with question
text snapshotted at submission [DSC-006]; decided_by `FK("accounts.User", null=True,
on_delete=SET_NULL, related_name="decided_applications")`; decided_at `DateTimeField(null=True,
blank=True)`; decision_note `NFCTextField(blank=True)` (reusable response templates resolved in
service — DSC-007); submitted_at `DateTimeField(auto_now_add=True)`; updated_at.
Meta: `ordering = ["-submitted_at"]`; `verbose_name = "application"`;
`UniqueConstraint(fields=["project", "applicant", "kind"],
name="uniq_application_project_applicant_kind")`;
`Index(fields=["applicant", "status"], name="idx_application_applicant_status")`;
`Index(fields=["project", "status"], name="idx_application_project_status")`.
`__str__` → `f"{self.applicant} → {self.project} ({self.get_status_display()})"`.
BR-011: creation blocked when project status is PAUSED/COMPLETED/CANCELLED/ARCHIVED (service +
test citing BR-011).

### 6.15 `ApplicationEvent` — member/ministry-visible timeline [DSC-008; A4]

Fields: application `FK(Application, on_delete=CASCADE, related_name="events")`; actor
`FK("accounts.User", null=True, on_delete=SET_NULL, related_name="application_events")`; event
`CharField(20, choices=ApplicationEventType.choices)`; comment `NFCTextField(blank=True)`;
from_status / to_status `CharField(15, blank=True, default="")`; created_at
`DateTimeField(auto_now_add=True, db_index=True)`.
Meta: `ordering = ["created_at", "id"]`;
`Index(fields=["application", "created_at"], name="idx_appevent_app_created")`.
`__str__` → `f"{self.get_event_display()} on {self.application}"`.
Visibility: the member and authorized ministry users only (Internal/Confidential classes).

### 6.16 `ProjectBookmark` [DSC-004]

Fields: user `FK("accounts.User", on_delete=CASCADE, related_name="bookmarks")`; project
`FK(Project, on_delete=CASCADE, related_name="bookmarks")`; notify_on_change
`BooleanField(default=True)` (opt-in change notifications feed NTF BOOKMARK_CHANGE); created_at.
Meta: `ordering = ["-created_at"]`;
`UniqueConstraint(fields=["user", "project"], name="uniq_bookmark_user_project")`.
`__str__` → `f"{self.user.username} bookmarked {self.project}"`.

---

## 7. `apps.contributions` — verified contribution records

Serves §9.1 "Contribution record"; §6.2 end-to-end workflow; BR-006, BR-007, BR-008; REC-001,
REC-006, REC-008; GIT-007, GIT-008; A5, A6.

### 7.1 Enums (`apps/contributions/enums.py`)

```python
from django.db import models


class ContributionSource(models.TextChoices):
    PROVIDER_EVENT = "provider_event", "Authoritative provider event"
    MAINTAINER_ATTESTATION = "maintainer_attestation", "Maintainer attestation"
    MEMBER_SUBMISSION = "member_submission", "Member-submitted evidence"


class VerificationStatus(models.TextChoices):
    CANDIDATE = "candidate", "Candidate"
    PENDING_INFO = "pending_info", "Clarification requested"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    REVOKED = "revoked", "Revoked"


class ImpactTier(models.TextChoices):
    MINOR = "minor", "Minor"
    STANDARD = "standard", "Standard"
    MAJOR = "major", "Major"
```

[BR-006: self-submission alone is evidence, not verification. §6.2: maintainer accepts, rejects,
or requests clarification with a reason.]

### 7.2 `ContributionRecord`

| Field | Type | Notes |
|---|---|---|
| project | FK("projects.Project", on_delete=PROTECT, related_name="contributions") | PROTECT — contribution evidence survives project deletion/unpublishing [BR-008] |
| contributor | FK("accounts.User", null=True, blank=True, on_delete=SET_NULL, related_name="contributions") | SET_NULL + display "removed member" after anonymisation [AUTH-010, §9.3] |
| contribution_type | FK("taxonomy.TaxonomyTerm", on_delete=PROTECT, related_name="contributions") | vocabulary CONTRIBUTION_TYPE; PROTECT per BR-012; correct type credited without a Git commit [A6, REC-008] |
| title | NFCCharField(200) | |
| description | NFCTextField(blank=True) | |
| evidence_url | URLField(blank=True) | evidence, not verification [BR-006] |
| evidence_file | FileField(upload_to=<private callable>, null=True, blank=True) | approved non-code evidence [A6; SEC-007 scanning] |
| source | CharField(25, choices=ContributionSource.choices, default=ContributionSource.MEMBER_SUBMISSION) | [BR-006] |
| provider_event | OneToOneField("github_sync.ProviderEvent", null=True, blank=True, on_delete=SET_NULL, related_name="contribution") | authoritative provenance [GIT-007, GIT-012]; OneToOne structurally guarantees one record per event [A5] |
| status | CharField(15, choices=VerificationStatus.choices, default=VerificationStatus.CANDIDATE, db_index=True) | |
| impact_tier | CharField(10, choices=ImpactTier.choices, default=ImpactTier.STANDARD) | §9.1 "impact tier"; REC-006 anti-gaming reads it |
| verified_by | FK("accounts.User", null=True, blank=True, on_delete=SET_NULL, related_name="verified_contributions") | authorized maintainer, or Super Admin override with audit [§4.2] |
| verified_at | DateTimeField(null=True, blank=True) | |
| verification_note | NFCTextField(blank=True) | accept/reject/clarification reason [§6.2] |
| secondary_approval_by | FK("accounts.User", null=True, blank=True, on_delete=SET_NULL, related_name="secondary_approvals") | BR-007: a ministry maintainer awarding credit to themselves requires secondary approval or an authoritative event; service refuses ACCEPTED otherwise |
| revocation_reason | NFCTextField(blank=True) | REC-005 reversal reason |
| revoked_by | FK("accounts.User", null=True, blank=True, on_delete=SET_NULL, related_name="revoked_contributions") | |
| revoked_at | DateTimeField(null=True, blank=True) | |
| created_at / updated_at | auto | |

Meta: `ordering = ["-verified_at", "-created_at"]`;
`Index(fields=["project", "status"], name="idx_contrib_project_status")`;
`Index(fields=["contributor", "status"], name="idx_contrib_contributor_status")`;
`Index(fields=["status", "-verified_at"], name="idx_contrib_status_verified")`;
`Index(fields=["contribution_type", "-verified_at"], name="idx_contrib_type_verified")`
(leaderboard queries — REC-003).
`__str__` → `f"{self.title} by {self.contributor}"`.

Verified portfolio and all recognition derive from `status=ACCEPTED` rows only [REC-001; §1 key
recommendation]. Raw commits, merge commits, automated/bot events, and duplicates are filtered in
the `github_sync` service and never create records [GIT-008] — deliberately not a model-layer
constraint.

---

## 8. `apps.github_sync` — GitHub App, connections, webhooks

Serves §9.1 "Repository connection", "Provider event"; Table 7F; A5, A9; NFR-OBS-01.

**Secrets rule:** OAuth/installation tokens and webhook secrets are NEVER stored in these models
(§9.2 Secret class; AUTH-008). They live in configured secret storage; models store only
non-secret references, scopes, and state. On revocation/uninstall, synchronization stops and
tokens are deleted [GIT-011; §9.3].

### 8.1 Enums (`apps/github_sync/enums.py`)

```python
from django.db import models


class Provider(models.TextChoices):
    GITHUB = "github", "GitHub"


class SyncState(models.TextChoices):
    IDLE = "idle", "Idle"
    SYNCING = "syncing", "Syncing"
    DEGRADED = "degraded", "Degraded"
    STOPPED = "stopped", "Stopped"
    ERROR = "error", "Error"


class DeliverySource(models.TextChoices):
    WEBHOOK = "webhook", "Webhook"
    RECONCILIATION = "reconciliation", "Reconciliation"


class ProcessingState(models.TextChoices):
    RECEIVED = "received", "Received"
    QUEUED = "queued", "Queued"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    DUPLICATE = "duplicate", "Duplicate"
    IGNORED = "ignored", "Ignored"
```

`Provider` is a single-value enum now (GitHub is the initial provider) but exists so Phase 3
cross-provider work does not rewrite schema [§18.1 provider-neutral assumption].

### 8.2 `GithubConnection` — user-level connection [AUTH-002, AUTH-008; GIT-002, GIT-009, GIT-011; A3]

Fields: user `OneToOneField("accounts.User", on_delete=CASCADE, related_name="github_connection")`;
provider `CharField(10, choices=Provider.choices, default=Provider.GITHUB)`; github_user_id
`BigIntegerField(unique=True)`; login `NFCCharField(100)`; scopes `JSONField(default=list)`
(granted scope); connected_at `DateTimeField(auto_now_add=True)`; consent_scopes
`JSONField(default=list)`; consent_recorded_at `DateTimeField(default=timezone.now)` [AUTH-008:
consent, scopes, connection time]; last_synced_at `DateTimeField(null=True, blank=True)`
[AUTH-008: last synchronization]; revoked_at `DateTimeField(null=True, blank=True)` [AUTH-008:
revocation status; GIT-011]; show_annual_calendar `BooleanField(default=False)`; 
calendar_fetched_at `DateTimeField(null=True, blank=True)` [GIT-009 consent + freshness label].
Meta: `ordering = ["-connected_at"]`. Property `is_active` → `revoked_at is None`.
`__str__` → `f"{self.user.username} GitHub:{self.login}"`.

### 8.3 `RepositoryConnection` [GIT-001, GIT-003, GIT-006, GIT-011; §9.1]

Fields: provider `CharField(10, choices=Provider.choices, default=Provider.GITHUB)`;
installation_id `BigIntegerField()` (GitHub App installation); repository_id `BigIntegerField()`;
full_name `NFCCharField(250)`; project `FK("projects.Project", null=True, blank=True,
on_delete=SET_NULL, related_name="repository_connections")` — the listed project this repo feeds;
granted_scopes `JSONField(default=list)`; sync_state `CharField(10, choices=SyncState.choices,
default=SyncState.IDLE, db_index=True)`; last_synced_at `DateTimeField(null=True, blank=True)`;
sync_cursor `CharField(255, blank=True, default="")` (reconciliation cursor — GIT-006);
health_note `NFCTextField(blank=True)`; activated_by `FK("accounts.User", null=True,
on_delete=SET_NULL, related_name="activated_repositories")`; deactivated_at
`DateTimeField(null=True, blank=True)`; created_at / updated_at.
Meta: `ordering = ["full_name"]`;
`UniqueConstraint(fields=["provider", "repository_id"], name="uniq_repo_connection")`;
`Index(fields=["sync_state"], name="idx_repoconn_sync_state")`;
`Index(fields=["project"], name="idx_repoconn_project")`.
`__str__` → `self.full_name`.
Repository selection is owner-consented [GIT-003]; reconciliation respects rate limits [GIT-006].

### 8.4 `ProviderEvent` — immutable delivery ledger [GIT-004, GIT-005, GIT-012; A5, A9; §9.1]

UUID pk (§1.1). Fields: provider `CharField(10, choices=Provider.choices, default=Provider.GITHUB)`;
event_type `CharField(100, db_index=True)` (e.g. `pull_request.closed`); provider_event_id
`CharField(200)` (provider event/delivery id); repository `FK(RepositoryConnection, null=True,
on_delete=SET_NULL, related_name="provider_events")`; actor `FK("accounts.User", null=True,
blank=True, on_delete=SET_NULL, related_name="provider_events")` (mapped member, if resolvable);
source `CharField(15, choices=DeliverySource.choices, default=DeliverySource.WEBHOOK)`;
signature_valid `BooleanField(default=False)`; signature_note `CharField(50, blank=True,
default="")` (`valid` / `invalid` / `missing` — GIT-004 high-entropy-secret validation result);
received_at `DateTimeField(auto_now_add=True, db_index=True)`; payload `JSONField(null=True,
blank=True)` — minimal fields needed for processing; no private repository content [GIT-010];
payload_digest `CharField(64, blank=True, default="")` (replay/duplicate detection — GIT-005);
processing_state `CharField(12, choices=ProcessingState.choices, default=ProcessingState.RECEIVED,
db_index=True)`; processing_attempts `PositiveSmallIntegerField(default=0)`; last_error
`TextField(blank=True, default="")`; processed_at `DateTimeField(null=True, blank=True)`;
correlation_id `CharField(100, blank=True, default="", db_index=True)` [NFR-OBS-01].

Meta: `ordering = ["-received_at"]`;
`UniqueConstraint(fields=["provider", "provider_event_id"], name="uniq_provider_event")` —
structural idempotency: a duplicate delivery resolves to DUPLICATE and never creates a second
ContributionRecord [GIT-005; A5];
`Index(fields=["processing_state", "received_at"], name="idx_provevent_state_received")`;
`Index(fields=["repository", "received_at"], name="idx_provevent_repo_received")`.
`__str__` → `f"{self.provider}:{self.event_type} {self.provider_event_id}"`.
Mutability: only `processing_state`, `processing_attempts`, `last_error`, `processed_at` may
update after insert (service-guarded; tested — GIT-005 "idempotent, queued, retryable,
timestamped").

---

## 9. `apps.blogs` — technical writing

Serves §9.1 "Blog post"; Table 7G; A7.

### 9.1 Enums (`apps/blogs/enums.py`)

```python
from django.db import models


class BlogStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    UNPUBLISHED = "unpublished", "Unpublished"
    ARCHIVED = "archived", "Archived"


class BlogModerationState(models.TextChoices):
    NOT_REVIEWED = "not_reviewed", "Not reviewed"
    UNDER_REVIEW = "under_review", "Under review"
    RESTRICTED = "restricted", "Restricted"
    REINSTATED = "reinstated", "Reinstated"
```

### 9.2 `BlogPost` [BLG-001–BLG-007]

Fields: author `FK("accounts.User", on_delete=PROTECT, related_name="blog_posts")` — PROTECT:
moderation version history survives account changes [BLG-006, BR-008]; title `NFCCharField(200)`;
slug `NFCSlugField(220, allow_unicode=True, unique=True)` [DSC-003]; excerpt
`NFCTextField(blank=True)`; content_markdown `NFCTextField(blank=True)`; content_rendered
`TextField(blank=True, default="")` — sanitized safe HTML produced by the renderer; scripts and
iframes prohibited by default; stored-XSS guard [BLG-002, BLG-003; A7 — sanitization in service,
rendered form cached here]; cover_image `FileField(upload_to=<private callable>, null=True,
blank=True)`; tags `M2M("taxonomy.TaxonomyTerm", blank=True, related_name="blog_posts")`
(vocabulary TAG); language `CharField(2, choices=ContentLanguage.choices, default="en")`
[BLG-004]; reading_time_minutes `PositiveIntegerField(default=0)` [BLG-004]; canonical_url
`URLField(blank=True)` [BLG-004; BLG-005 — external Medium/article links are posts with
canonical_url and no copied text]; status `CharField(12, choices=BlogStatus.choices,
default=BlogStatus.DRAFT, db_index=True)` [BLG-001]; moderation_state `CharField(15,
choices=BlogModerationState.choices, default=BlogModerationState.NOT_REVIEWED)` [BLG-006];
is_official `BooleanField(default=False)`; official_published_by `FK("accounts.User", null=True,
blank=True, on_delete=SET_NULL, related_name="official_blog_posts")` — explicit official
publishing permission + distinct visual label [BLG-007]; published_at `DateTimeField(null=True,
blank=True)`; created_at / updated_at.

Meta: `ordering = ["-published_at", "-id"]`;
`Index(fields=["status", "-published_at"], name="idx_blog_status_published")`;
`Index(fields=["author", "-published_at"], name="idx_blog_author_published")`;
`Index(fields=["language", "status"], name="idx_blog_language_status")`.
`__str__` → `self.title`.

### 9.3 `BlogVersion` [BLG-001; BLG-006]

Fields: post `FK(BlogPost, on_delete=CASCADE, related_name="versions")`; version_number
`PositiveIntegerField()`; snapshot `JSONField(default=dict)` (title, excerpt, content_markdown);
created_by `FK("accounts.User", null=True, on_delete=SET_NULL, related_name="blog_versions")`;
created_at.
Meta: `ordering = ["post", "-version_number"]`;
`UniqueConstraint(fields=["post", "version_number"], name="uniq_blog_version_number")`.
`__str__` → `f"{self.post} v{self.version_number}"`.
A version row is written on every create/publish/edit/unpublish — moderator-visible history
[BLG-006].

---

## 10. `apps.recognition` — badges, scoring, leaderboard

Serves §9.1 "Recognition / badge"; Table 7H; BR-005. The leaderboard is derived from
`contributions.ContributionRecord(status=ACCEPTED)` joined to `ContributionScore` — never raw
commit counts [REC-001; BR-005; §1 key recommendation].

### 10.1 Enums (`apps/recognition/enums.py`)

```python
from django.db import models


class BadgeKind(models.TextChoices):
    CONTRIBUTION = "contribution", "Contribution"
    MILESTONE = "milestone", "Milestone"
    COMMUNITY = "community", "Community"
    SPECIAL = "special", "Special"


class AwardStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"
```

### 10.2 `Badge` [REC-007; ADM-001; BR-012]

Fields: name `NFCCharField(100, unique=True)`; slug `NFCSlugField(120, allow_unicode=True,
unique=True)`; description `NFCTextField(blank=True)`; criteria_md `NFCTextField(blank=True)` —
documented criteria [REC-007]; criteria_version `PositiveIntegerField(default=1)` — criteria
changes bump the version and never silently rewrite meaning [BR-012]; kind `CharField(12,
choices=BadgeKind.choices, default=BadgeKind.CONTRIBUTION)`; icon `FileField(upload_to=<private
callable>, null=True, blank=True)`; is_active `BooleanField(default=True)`; created_at /
updated_at.
Meta: `ordering = ["name"]`. `__str__` → `self.name`.

### 10.3 `BadgeAward` [REC-004; REC-005; REC-007]

Fields: badge `FK(Badge, on_delete=PROTECT, related_name="awards")`; recipient
`FK("accounts.User", on_delete=PROTECT, related_name="badge_awards")`; contribution
`FK("contributions.ContributionRecord", null=True, blank=True, on_delete=SET_NULL,
related_name="badge_awards")` — evidence link [REC-007]; issuer `FK("accounts.User", null=True,
on_delete=SET_NULL, related_name="issued_badge_awards")`; issued_at
`DateTimeField(auto_now_add=True)`; status `CharField(8, choices=AwardStatus.choices,
default=AwardStatus.ACTIVE, db_index=True)`; revocation_reason `NFCTextField(blank=True)`;
revoked_by `FK("accounts.User", null=True, blank=True, on_delete=SET_NULL,
related_name="revoked_badge_awards")`; revoked_at `DateTimeField(null=True, blank=True)`.
Meta: `ordering = ["-issued_at"]`;
`UniqueConstraint(fields=["badge", "recipient"], condition=Q(status=AwardStatus.ACTIVE),
name="uniq_active_award_badge_recipient")` — at most one ACTIVE award of a badge per member;
re-award after revocation inserts a new row;
`Index(fields=["recipient", "status"], name="idx_award_recipient_status")`.
`__str__` → `f"{self.badge.name} → {self.recipient.username}"`.
Public display additionally gated by `recipient.profile.leaderboard_opt_out` [REC-004].

### 10.4 `ScoringPolicy` [REC-002; BR-012]

Fields: version `PositiveIntegerField(unique=True)`; rules `JSONField(default=dict)` — documented,
versioned weights per contribution type and impact tier; document_url `URLField(blank=True)`
(publicly documented policy); approved_by `FK("accounts.User", null=True, on_delete=SET_NULL,
related_name="approved_scoring_policies")` — product-owner approval before activation [REC-002];
activated_at `DateTimeField(null=True, blank=True)`; is_active `BooleanField(default=False)`.
Meta: `ordering = ["-version"]`; `verbose_name = "scoring policy"`;
`UniqueConstraint(fields=["is_active"], condition=Q(is_active=True),
name="uniq_active_scoring_policy")` — exactly one active policy.
`__str__` → `f"Scoring policy v{self.version}"`.

### 10.5 `ContributionScore` [REC-001; REC-003; REC-005]

Fields: contribution `OneToOneField("contributions.ContributionRecord", on_delete=CASCADE,
related_name="score")`; policy `FK(ScoringPolicy, on_delete=PROTECT, related_name="scores")`;
points `PositiveIntegerField()`; scored_at `DateTimeField(auto_now_add=True)`; reversed_at
`DateTimeField(null=True, blank=True)`; reversal_reason `NFCTextField(blank=True)`.
Meta: `ordering = ["-scored_at"]`;
`Index(fields=["policy", "-points"], name="idx_score_policy_points")`.
`__str__` → `f"{self.points} pts for {self.contribution}"`.
Revoking a ContributionRecord reverses its score with reason and audit record [REC-005; A5].
Leaderboard views (rolling-period, annual, ministry, project, contribution-type, lifetime) are
queries over scores; opt-out filtering applied at render; rate caps, bot exclusion, duplicate
detection, and anomaly review operate on accepted records in service [REC-003, REC-004, REC-006].

---

## 11. `apps.notifications` — in-app and email

Serves §9.1 "Notification"; Table 7I.

### 11.1 Enums (`apps/notifications/enums.py`)

```python
from django.db import models


class NotificationType(models.TextChoices):
    APPLICATION_STATUS = "application_status", "Application status"
    REVIEW_DECISION = "review_decision", "Review decision"
    REVIEW_COMMENT = "review_comment", "Review comment"
    ASSIGNMENT = "assignment", "Work assignment"
    CONTRIBUTION_VERIFIED = "contribution_verified", "Contribution verified"
    CONTRIBUTION_REVOKED = "contribution_revoked", "Contribution revoked"
    BADGE_AWARDED = "badge_awarded", "Badge awarded"
    PROJECT_UPDATE = "project_update", "Project update"
    PROJECT_STATUS = "project_status", "Project status change"
    BOOKMARK_CHANGE = "bookmark_change", "Bookmarked project changed"
    MODERATION = "moderation", "Moderation"
    SECURITY = "security", "Security"
    ACCOUNT = "account", "Account"


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed"


class DigestFrequency(models.TextChoices):
    NONE = "none", "No digest"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
```

`NotificationType` covers the NTF-001 enumeration (approvals, review comments, applications,
assignments, contribution verification, moderation, security events).

### 11.2 `Notification` [NTF-001; NTF-003; NTF-004]

Fields: recipient `FK("accounts.User", on_delete=CASCADE, related_name="notifications")`; type
`CharField(25, choices=NotificationType.choices, db_index=True)`; channel `CharField(8,
choices=Channel.choices, default=Channel.IN_APP)`; title `NFCCharField(200)`; body
`NFCTextField(blank=True)` — no sensitive content in body or email subject lines; detail sits
behind an authenticated link [NTF-003]; context_url `CharField(500, blank=True, default="")`
(platform-relative URL of the detail view); read_at `DateTimeField(null=True, blank=True,
db_index=True)`; delivery_status `CharField(10, choices=DeliveryStatus.choices,
default=DeliveryStatus.PENDING, db_index=True)`; template_version `CharField(20, blank=True,
default="")` (§9.1 "template version"); delivery_attempts `PositiveSmallIntegerField(default=0)`;
last_attempt_at `DateTimeField(null=True, blank=True)`; created_at
`DateTimeField(auto_now_add=True, db_index=True)`.
Meta: `ordering = ["-created_at"]`;
`Index(fields=["recipient", "read_at"], name="idx_notif_recipient_read")`;
`Index(fields=["delivery_status"], name="idx_notif_delivery_status")`.
`__str__` → `f"{self.get_type_display()} to {self.recipient.username}"`.
Delivery failures are logged and retried without duplicate user-visible notifications
(service-level queue; `delivery_attempts` is the data contract) [NTF-004].

### 11.3 `NotificationPreference` [NTF-002]

Fields: user `OneToOneField("accounts.User", on_delete=CASCADE,
related_name="notification_preferences")`; email_applications `BooleanField(default=True)`;
email_reviews `BooleanField(default=True)`; email_contributions `BooleanField(default=True)`;
email_community `BooleanField(default=False)`; digest_frequency `CharField(8,
choices=DigestFrequency.choices, default=DigestFrequency.NONE)`; updated_at.
Meta: `ordering = ["user_id"]`; `verbose_name = "notification preference"`.
`__str__` → `f"Preferences for {self.user.username}"`.
Mandatory security/administrative notices bypass these switches (service-enforced; test citing
NTF-002 "cannot be disabled").

---

## 12. `apps.moderation` — reports and moderation cases

Serves §9.1 "Report / moderation case"; Table 7J (ADM-003, ADM-004, ADM-007); BR-010; §13.2
principles; A7.

### 12.1 Enums (`apps/moderation/enums.py`)

```python
from django.db import models


class ReportReason(models.TextChoices):
    IMPERSONATION = "impersonation", "Impersonation"
    GOV_BRANDING_MISUSE = "gov_branding_misuse", "Misleading government branding"
    UNSAFE_LINK = "unsafe_link", "Unsafe link"
    MALWARE = "malware", "Malicious file"
    COPYRIGHT = "copyright", "Copyright or intellectual property"
    HARASSMENT = "harassment", "Harassment or code-of-conduct violation"
    SPAM = "spam", "Spam"
    UNLAWFUL_CONTENT = "unlawful_content", "Unlawful content"
    SECURITY_CONCERN = "security_concern", "Security concern"
    OTHER = "other", "Other"


class CaseStatus(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under review"
    ACTION_TAKEN = "action_taken", "Action taken"
    CLOSED_NO_ACTION = "closed_no_action", "Closed - no action"
    APPEALED = "appealed", "Appealed"
    ESCALATED = "escalated", "Escalated"


class ModerationAction(models.TextChoices):
    NO_ACTION = "no_action", "No action"
    WARNING = "warning", "Warning"
    CONTENT_RESTRICTION = "content_restriction", "Content restriction"
    UNPUBLISH = "unpublish", "Unpublish"
    ACCOUNT_SUSPENSION = "account_suspension", "Account suspension"
    ESCALATION = "escalation", "Escalation"


class AppealStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPHELD = "upheld", "Upheld"
    OVERTURNED = "overturned", "Overturned"


class CaseEventType(models.TextChoices):
    CREATED = "created", "Created"
    ASSIGNED = "assigned", "Assigned"
    COMMENTED = "commented", "Comment"
    ACTION_TAKEN = "action_taken", "Action taken"
    APPEALED = "appealed", "Appealed"
    ESCALATED = "escalated", "Escalated"
    DECIDED = "decided", "Decided"
    REINSTATED = "reinstated", "Reinstated"
```

`ReportReason` covers the ADM-003 target set (profile, project, blog, link, comment/evidence
record, security concern) plus MEM-010 (impersonation / disputed identity or ownership) and
BR-009 (official-seal misuse). `ModerationAction` is the ADM-004 action set verbatim.

### 12.2 `Report` [ADM-003; MEM-010; BR-009; A7]

Fields: reporter `FK("accounts.User", null=True, on_delete=SET_NULL, related_name="filed_reports")`
(null = system/automated reports; reporter identity is never exposed publicly — §13.2 protect
reporters); content_type `FK("contenttypes.ContentType", on_delete=PROTECT)`; object_id
`CharField(255)`; target `GenericForeignKey(ct_field="content_type", fk_field="object_id")`;
reason `CharField(25, choices=ReportReason.choices, db_index=True)`; details `NFCTextField(blank=True)`;
evidence_url `URLField(blank=True)`; created_at / updated_at.
Meta: `ordering = ["-created_at"]`;
`Index(fields=["content_type", "object_id"], name="idx_report_target")`;
`Index(fields=["reason", "created_at"], name="idx_report_reason_created")`.
`__str__` → `f"{self.get_reason_display()} on {target}"`.
Evidence is Confidential class [§9.2]; public moderation summaries must not expose reporter or
evidence [§13.2; A7].

### 12.3 `ModerationCase` [ADM-004; ADM-007; BR-010; §9.1]

Fields: report `OneToOneField(Report, on_delete=CASCADE, related_name="case")`; assigned_to
`FK("accounts.User", null=True, blank=True, on_delete=SET_NULL, related_name="assigned_cases")`
[ADM-002 assignment]; status `CharField(15, choices=CaseStatus.choices, default=CaseStatus.NEW,
db_index=True)`; action `CharField(25, blank=True, default="")` — ADM-004 action when decided;
action_reason `CharField(25, blank=True, default="")` (structured reason — ReportReason values);
decision_comment `NFCTextField(blank=True)`; decided_by `FK("accounts.User", null=True,
blank=True, on_delete=SET_NULL, related_name="decided_cases")`; decided_at `DateTimeField(null=True,
blank=True)`; appeal_text `NFCTextField(blank=True, default="")`; appealed_at `DateTimeField(null=True,
blank=True)`; appeal_status `CharField(10, blank=True, default="")` (AppealStatus values; blank
until appealed); appeal_decided_by `FK("accounts.User", null=True, blank=True, on_delete=SET_NULL,
related_name="appeal_decisions")`; appeal_decided_at `DateTimeField(null=True, blank=True)`;
created_at / updated_at.
Meta: `ordering = ["-created_at"]`; `verbose_name = "moderation case"`;
`Index(fields=["status", "-created_at"], name="idx_case_status_created")`;
`Index(fields=["assigned_to", "status"], name="idx_case_assignee_status")`.
`__str__` → `f"Case on {self.report} ({self.get_status_display()})"`.
Every action/decision/appeal writes an AuditEvent and a ModerationEvent [ADM-004; BR-010 —
defined reasons and appeal path, except urgent security containment].

### 12.4 `ModerationEvent` — case timeline [ADM-002; ADM-004]

Fields: case `FK(ModerationCase, on_delete=PROTECT, related_name="events")` (PROTECT — case
history is retained evidence [BR-008]); actor `FK("accounts.User", null=True, on_delete=SET_NULL,
related_name="moderation_events")`; event `CharField(15, choices=CaseEventType.choices)`;
comment `NFCTextField(blank=True)`; created_at `DateTimeField(auto_now_add=True, db_index=True)`.
Meta: `ordering = ["created_at", "id"]`;
`Index(fields=["case", "created_at"], name="idx_caseevent_case_created")`.
`__str__` → `f"{self.get_event_display()} on {self.case}"`.

---

## 13. Cross-cutting notes

### 13.1 Data classification mapping [§9.2]

| Model(s) | Class |
|---|---|
| Published projects, public profiles fields, published blogs, accepted contribution acknowledgements | Public |
| Project drafts, ProjectReview comments, ProjectVersion snapshots, application timelines, ministry-scoped dashboards | Internal |
| MemberProfile private fields, Application + answers, Report evidence, ModerationCase details, GithubConnection, UserSession, attachments pre-publication | Confidential |
| OAuth tokens, webhook secrets, signing keys, session secrets | Secret — never in models (§8 header) |

### 13.2 Retention hooks [§9.3]

Records schedule is policy, not schema. The model layer supports it: append-only AuditEvent and
ProviderEvent; PROTECT FKs on evidence-bearing rows; `revoked_at`-style soft states instead of
deletes; anonymisation via SET_NULL attribution columns.

### 13.3 Entities/requirements intentionally NOT modeled

| SRS item | Disposition |
|---|---|
| Feature flags [ADM-001] | Settings-level configuration, not a DB model (no runtime flag store in MVP). |
| Analytics event store [ANL-001–ANL-004] | Dashboards are aggregation queries over the models above + AuditEvent, with suppression thresholds applied in query/render layers. No separate event table in MVP. |
| Public read-only API [ANL-005] | "Could" priority; Phase 3; reads the models above; no schema impact now. |
| Recommendations [DSC-010] | Explainable views computed from profile skills/interests/language and project needs — no model; document matching inputs in service docstrings/tests. |
| Email digests / bounce handling [NTF-004; §10 email service] | Service-layer queue and templates; Notification rows are the durable record. |
| Malware scanning itself [SEC-007] | External scanner integration; models store `scan` status only. |
| OAuth sessions/providers beyond GitHub [AUTH-001] | Federated sign-in (Google/Facebook) is handled by the auth stack (allauth-style); no provider-identity table is specified here. If a durable social-account table is needed, it belongs in `apps/accounts` and requires the same coordinator unlock as §3. |

### 13.4 Factory and test obligations

Every model above gets a factory-boy `DjangoModelFactory` in `apps/<app>/tests/factories.py` and
unit tests citing the SRS IDs bracketed in its section (AGENTS.md rules 1–2). Lifecycle,
material-edit, self-award, dedup, opt-out, and moderation-appeal behaviors named in this document
each need at least one acceptance test in `tests/acceptance/` (A1–A10 mapping: A1 → ministries,
A2 → projects review/versions, A3 → github_sync, A4 → projects applications, A5/A6 →
contributions + recognition, A7 → blogs + moderation, A8 → templates/i18n, A9 → github_sync
reconciliation, A10 → ops, no models).

## 14. Model count summary

| App | Models |
|---|---|
| accounts | User (given) + MemberProfile, MemberSkill, MemberEducation, MemberLink, UserSession |
| ministries | MinistryOrganization, MinistryPublisher |
| taxonomy | Skill, TaxonomyTerm, ApprovedLicense, SkillSuggestion |
| projects | Project, ProjectMaintainer, ProjectVersion, ProjectReview, ProjectSuitability, ProjectScreeningQuestion, ProjectTask, ProjectMilestone, ProjectUpdate, ProjectAttachment, ProjectLink, Application, ApplicationEvent, ProjectBookmark |
| contributions | ContributionRecord |
| github_sync | GithubConnection, RepositoryConnection, ProviderEvent |
| blogs | BlogPost, BlogVersion |
| recognition | Badge, BadgeAward, ScoringPolicy, ContributionScore |
| notifications | Notification, NotificationPreference |
| moderation | Report, ModerationCase, ModerationEvent |
| audit | AuditEvent (given; no additions) |

39 new models + 2 given = 41 total.
