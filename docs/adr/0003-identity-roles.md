# ADR 0003: Custom User, SRS roles as data, named ministry officers, MFA for privileged roles

Date: 2026-09-03
Status: Accepted

## Context

The SRS fixes exactly three authorization roles (§1, §4.2): Super Admin, Ministry
Publisher, Member; public visitors are an unauthenticated state, not a role. AUTH-004
requires that only a Super Admin creates/suspends/revokes a ministry organization and its
*named publisher accounts* — the SRS explicitly rejects shared ministry credentials
(§4.2 control requirement; §17 "Shared ministry credentials" risk) and requires every
publish/approve/verify action to be attributable to a named person. AUTH-005 requires MFA
and verified official contact details for Super Admin and Ministry Publisher. AUTH-006
requires server-side, object-level enforcement including ministry boundaries (GOV-001: a
publisher acts only for their assigned ministry). AUTH-003 requires auditable Super Admin
grants with the first admin provisioned through a controlled deployment process.

Django's Group/Permission tables alone do not model any of this: they are runtime-editable
metadata with no ministry scoping, no attribution semantics, and no SRS mapping.

## Decision

- Custom user model `apps.accounts.User` (AbstractUser), set as `AUTH_USER_MODEL` before
  the first migration; it carries authentication state only.
- Roles are **data on explicit models, checked in the service layer** — not groups-only:
  a `TextChoices` role discriminator for the three SRS roles, plus ministry membership as
  a separate assignment record linking a named User to a Ministry organization
  (`apps/ministries`). Every protected action performs an explicit, testable check of
  role + object ownership + ministry boundary (AUTH-006, GOV-001).
- Super Admin provisioning of ministries and named publishers is a service function that
  records audit events (AUTH-004, A1); it is not delegated to Django admin editing.
- Django's built-in groups/permissions are used only where Django itself needs them
  (admin access); application authorization never consults them.
- MFA is a required path for Super Admin and Ministry Publisher (AUTH-005): sign-in and
  high-risk actions for privileged roles enforce a second factor (TOTP device, verify
  official contact as a secondary channel), enforced at the accounts service boundary.
  The first Super Admin is bootstrapped via a controlled deployment step (AUTH-003).
- Member federated sign-in (Google/GitHub/Facebook, AUTH-001) attaches provider identities
  to the same User; public visitor remains simply an unauthenticated request.

## Consequences

Positive: role checks are greppable, cite SRS IDs in tests (A1), and audit cleanly; adding
a second publisher to a ministry — or revoking one without affecting the other (A1) — is
a row operation with audit; no hidden authorization state.

Negative/risk: Django admin cannot be used to manage roles safely (by design); the MFA
dependency (e.g., a TOTP library) lands with AUTH-005 implementation, not at scaffold
time — until then the enforcement point exists and fails closed for privileged grant
flows. `apps/accounts/models.py` is locked to the accounts domain (AGENTS.md).

Relevant SRS: §4.2, AUTH-001, AUTH-003, AUTH-004, AUTH-005, AUTH-006, AUTH-007, GOV-001,
ADM-001, A1.
