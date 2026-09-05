# ADR 0004: Append-only audit trail

Date: 2026-09-03
Status: Accepted

## Context

SEC-008 (Must) requires tamper-evident audit records for privileged actions, security
changes, approval decisions, data exports, and failed authorization. ADM-008 (Must)
requires that no privileged user can erase the audit record of their own action through
the application interface. GOV-005 requires every review action to record actor,
timestamp, decision, reason, and before/after version; BR-008 forbids project
deletion/unpublishing from erasing audit or contribution evidence; §4.2 makes every
publish/approve/verify/suspend/material-edit attributable to a named person. NFR-OBS-01
requires a correlation ID on every request and background job — audit rows are where that
ID becomes durable evidence.

A Django model with a normal admin and default delete permissions would violate ADM-008
by accident: bulk `QuerySet.delete()`/`update()` bypass `Model.delete()`, and the admin's
delete-selected action is exactly the "application interface" ADM-008 closes.

## Decision

- `apps.audit.models.AuditEvent` is append-only: UUID primary key (public, immutable
  identity), actor, action, target (content_type/object_id), before/after JSON, source,
  result, correlation_id, created_at.
- Rows are written exclusively through `apps.audit.services.record_audit(...)`, called by
  every privileged/state-changing service action (publish, approve, verify, suspend,
  moderate, export, provisioning) within the same transaction as the action.
- Application-level guards on the model: `save()` raises if the row already exists;
  `delete()` always raises. Bulk operations (`bulk_update`, `bulk_delete`,
  `QuerySet.update/delete`) are prohibited on `AuditEvent` anywhere in the codebase; the
  audit app exposes no manager methods that mutate. Django admin is read-only for audit
  rows and grants no delete permission.
- Audit rows are never rewritten to "correct" data — corrections are new events with a
  reference to the earlier event (BR-012 spirit: changes are versioned, history kept).

## Consequences

Positive: ADM-008 holds at the application boundary; A1/A5 acceptance scenarios have a
durable evidence trail; retention/archival (§9.3) becomes an operational (DB-level export)
concern, not an application feature.

Negative/risk: an application-level guard is not cryptographic tamper-evidence — a
database superuser bypasses it. Hardening path (explicitly deferred): DB-level REVOKE of
UPDATE/DELETE, a BEFORE UPDATE/DELETE trigger, and/or chained hashing or log shipping to
WORM storage; a penetration test (SEC-011) should probe this. Reading audit data is
access-controlled and itself audited (ADM-005, SEC-008).

Relevant SRS: §4.2, §9.3, ADM-008, SEC-008, GOV-005, ADM-005, BR-008, BR-012, NFR-OBS-01,
A1, A5.
