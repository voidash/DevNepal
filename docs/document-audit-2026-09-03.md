# Document Audit: 2026-09-03

This audit compares the SRS, design contract, data-model specification, test plan, ADRs, decision
log, operational runbooks, and current Django implementation. It is not launch approval.

## Verified Implementation Alignment

- The CI workflow runs formatting, linting, and coverage-enabled pytest.
- The local password login, TOTP enrollment, public project catalog, project lifecycle, contribution
  verification, webhook ledger, accessibility regression tests, and operational runbooks exist.
- The current suite passed **640 pytest items** on 2026-09-04; the SRS-citation gate also passed.
- D11–D13 deliberately narrow MVP scope to Google/GitHub identity, no public leaderboard, and
  external-article blogs.

## Required Corrections Before Release Approval

| Severity | Document claim | Verified implementation state | Required disposition |
| --- | --- | --- | --- |
| Critical | `test-plan.md` previously treated its proposed 241-case inventory, 41 planned acceptance functions, and 100/102 automated Must target as current coverage. | The current suite has 640 items: 10 acceptance functions yielding 35 parametrized acceptance items. The exact-path audit finds 28 matrix paths present and 35 absent; A8 and A10 have no collected file. Passing tests and citations do not prove the proposed Must target. | The plan now labels the inventory as planned, records exact-path status, separates operational/external evidence, and requires a case-level trace before any Must-coverage percentage is claimed. |
| Critical | ADR 0006 describes an HTTP webhook receiver, out-of-band worker, retries/backoff, and provider reconciliation. | There is no webhook route, worker, or provider client; `reconcile()` is a no-op. | Change ADR status to proposed/partially implemented and retain these as launch gates. |
| Critical | `data-model.md` specifies full Markdown `BlogPost` content, versions, images, and safe rendering. | The implementation is external-link listings only, per D13. | Replace the model section with MVP schema or explicitly version the full-blog schema as Phase 2. |
| High | ADR 0003 says a role discriminator, federated providers, and MFA at sign-in/high-risk boundaries exist. | Roles derive from superuser/publisher assignment; login is local password only; MFA currently protects the dashboard path. | Mark OAuth, session controls, and high-risk MFA enforcement as unimplemented. |
| High | `data-model.md` promises active session listing, revocation, idle timeout, and re-authentication. | `UserSession` is not wired into Django session lifecycle. | Add the feature and tests, or defer it explicitly. |
| High | D3 requires official-domain email round-trip plus Super Admin attestation. | Provisioning checks domain equality but does not perform contact verification. | Implement verification state/challenge or revise D3 and the SRS release scope. |
| High | The contribution model requires a `ProviderEvent` relation and immutable provider-event provenance. | Contributions store a string reference; `ProviderEvent` has no write guard. | Reconcile the schema/implementation and add immutability tests. |
| High | D12/D13 defer Phase-1 SRS features without an explicit release-scope amendment. | Public leaderboard and full blogs remain SRS Must scope. | Obtain product-owner approval and version the SRS/release scope. |
| High | The design contract promises self-hosted Inter/Noto Sans Devanagari fonts and locale-aware presentation helpers. | Font files and date helper are absent. | Supply assets/helpers or correct the contract. |
| Medium | The backup runbook refers to `member-avatar` storage paths. | Avatar uploads use the `avatars/` prefix. | Correct the restore inventory prefix. |
| Medium | D14 requires a partial publisher-assignment uniqueness constraint retaining revoked history. | Current uniqueness prevents re-grant history. | Implement the migration or mark D14 pending. |

## External Launch Gates

The following remain evidence-based operational gates, not documentation-only work: production
OAuth credentials and callback registration; approved hosting, secrets, encryption, monitoring, and
object storage; malware quarantine; GitHub App/receiver/worker/reconciliation; independent security
testing; WCAG manual audit; backup/restore and incident drills; privacy/legal approval; and pilot
ministry readiness.
