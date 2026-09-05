# DevNepal Master Test Plan — Test Inventory v1.0

Source of truth: `docs/srs-v0.9.txt` (SRS v0.9). Every test case below cites the SRS requirement
ID(s) it verifies. No requirement is invented here; where a case also enforces an AGENTS.md swarm
rule (NFC normalization, audit immutability, Kathmandu time rendering), the SRS anchor
(DSC-003, SEC-008, NFR-I18N-01) is cited alongside.

This document is the proposed SRS-traceable inventory. Tests are written FIRST (AGENTS.md hard
rule 2). The citation gate, not this proposed inventory, is authoritative for whether a collected
test function cites an SRS requirement. The bootstrap-only exception is documented in §7's
citation-gate scope.

---

## 1. Test ID scheme

| Layer | ID pattern | Lives in | Marker |
|---|---|---|---|
| Unit | `<REQID>-U<n>` | `apps/<app>/tests/test_*.py` | `@pytest.mark.unit` |
| Integration | `<REQID>-I<n>` | `apps/<app>/tests/test_*.py` | `@pytest.mark.integration` |
| Acceptance | `<REQID>-A<n>`, realized as named pytest functions `test_aNN_*` | `tests/acceptance/test_a01*.py` … `test_a10*.py` | `@pytest.mark.acceptance` |
| Manual / external | `<REQID>-M<n>` (manual) / `<REQID>-T<n>` (tooling) | §8 register — executed outside pytest | n/a |

- Multiple cases per layer are numbered `U1, U2…`, `I1, I2…`.
- Acceptance scenarios A1–A10 (SRS §16.1) are fixed to files `tests/acceptance/test_a01*.py` …
  `test_a10*.py` by AGENTS.md; function names are given in §5.
- Business rules BR-001…BR-012 carry no MoSCoW priority in the SRS; they are binding launch
  rules and are treated as Must-equivalent for coverage gates (marked `Must*`).
- Counting rule used in every total below: each test ID in §4 counts once; each acceptance
  function in §5 counts once (matrix rows show `A` in the layer column without duplicating a
  case count); manual/tooling items (§8) count separately.

### File conventions

Unit/integration tests live in `apps/<app>/tests/test_<topic>.py`; factories in
`apps/<app>/tests/factories.py` (factory-boy `DjangoModelFactory`, never JSON fixtures —
AGENTS.md conventions). Cross-app SRS scenarios live only in `tests/acceptance/`.

---

## 2. Planned inventory summary

The counts in this section are planning targets derived from the matrix below, not a count of
pytest items currently collected from source. The current source snapshot is recorded in §9.

| Domain | Unit | Integration | Acceptance functions (§5) | Manual items (§8) |
|---|---|---|---|---|
| AUTH (Table 7A) | 12 | 14 | shared (A1, A3) | 1 |
| MEM (Table 7B) | 10 | 8 | shared (A3) | 0 |
| GOV (Table 7C) | 13 | 11 | shared (A2) | 0 |
| PPR (Table 7D) | 3 | 4 | shared (A3) | 0 |
| DSC (Table 7E) | 8 | 7 | shared (A4) | 0 |
| GIT (Table 7F) | 14 | 6 | shared (A3, A5, A9) | 0 |
| BLG (Table 7G) | 8 | 4 | shared (A7) | 0 |
| REC (Table 7H) | 10 | 1 | shared (A5, A6) | 0 |
| NTF (Table 7I) | 5 | 1 | shared (A4) | 0 |
| ADM (Table 7J) | 10 | 5 | shared (A7) | 0 |
| ANL (Table 7K) | 4 | 0 | — | 0 |
| BR (SRS §8) | 13 | 0 | shared (A2, A5, A6) | 0 |
| SEC (Table 12A) | 17 | 0 | shared (A7, A10) | 6 |
| NFR (Table 11A) | 9 | 3 | shared (A8, A9, A10) | 9 |
| **Totals** | **136** | **64** | **41** | **16** |

**Planned automated inventory: 241 cases** (136 unit + 64 integration + 41 acceptance), plus 16
manual/external verification items (§8). This planning total excludes the SRS-citation meta-test
defined in §7 and must not be reported as the current pytest collection count.

---

## 3. Requirement counts and coverage baseline

| Category | Must | Should | Could |
|---|---|---|---|
| AUTH-001…010 | 9 | 1 | 0 |
| MEM-001…010 | 8 | 2 | 0 |
| GOV-001…012 | 10 | 2 | 0 |
| PPR-001…006 | 4 | 1 | 1 |
| DSC-001…010 | 6 | 4 | 0 |
| GIT-001…012 | 11 | 1 | 0 |
| BLG-001…007 | 6 | 1 | 0 |
| REC-001…008 | 6 | 2 | 0 |
| NTF-001…004 | 3 | 1 | 0 |
| ADM-001…008 | 6 | 2 | 0 |
| ANL-001…005 | 3 | 1 | 1 |
| SEC-001…014 | 12 | 1 | 1 |
| NFR (Table 11A) | 6 | 8 | 0 |
| BR-001…012 (binding, Must-equivalent) | 12 | 0 | 0 |
| **Total** | **102** | **27** | **3** |

No requirement-level coverage percentage is asserted for the current implementation. The proposed
100/102 automated target and the 102/102 target with external evidence were planning arithmetic,
not a demonstrated trace from collected tests to every requirement. The exact-path audit in §4.15
and the current baseline in §9 identify what remains to be reconciled.

---

## 4. Coverage matrix

Columns: Req ID | Priority | Layer(s) | Test file | Cases (ID — one-line description).
`A` in Layer(s) means the requirement is also exercised end-to-end by acceptance functions in §5.

### 4.1 Table 7A — Identity, authentication, authorization

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| AUTH-001 | Must | U, I, A | `apps/accounts/tests/test_auth_providers.py` | AUTH-001-U1 — provider registry reflects configuration; Facebook absent unless enabled. • AUTH-001-I1 — mocked OIDC (Google) sign-in creates and links a member account. • AUTH-001-I2 — disabled provider offers no sign-in option and its callback is rejected. |
| AUTH-002 | Must | U, I, A | `apps/accounts/tests/test_auth_providers.py` | AUTH-002-U1 — GitHub connect/disconnect never touches the sign-in identity mapping. • AUTH-002-I1 — member signed in via Google connects then disconnects GitHub; sign-in still works. |
| AUTH-003 | Must | U, I, M | `apps/audit/tests/test_audit_trail.py` | AUTH-003-U1 — Super Admin grant requires an existing Super Admin and writes an audit event. • AUTH-003-I1 — non-super-admin grant attempt denied and audited. • AUTH-003-M1 — first-super-admin bootstrap via controlled deployment procedure (§8). |
| AUTH-004 | Must | U, I, A | `apps/ministries/tests/test_provisioning.py` | AUTH-004-U1 — suspending a ministry organization deactivates its publisher accounts. • AUTH-004-I1 — Super Admin provisions org and publishers; publisher/member roles get 403 on provisioning routes. • AUTH-004-I2 — revoking one publisher account leaves the other intact; both audited. |
| AUTH-005 | Must | U, I, A | `apps/accounts/tests/test_mfa_sessions.py` | AUTH-005-U1 — privileged login without an MFA factor is challenged and denied. • AUTH-005-U2 — MFA enrollment forced at first privileged login. • AUTH-005-I1 — publisher with unverified official contact cannot publish until verified. |
| AUTH-006 | Must | U, I, A | `apps/accounts/tests/test_permissions.py` | AUTH-006-U1 — parametrized route×role matrix: every protected route enforces a server-side role check. • AUTH-006-I1 — publisher A gets 403/404 touching ministry B's project, no data leaked in body. • AUTH-006-I2 — member hitting a draft URL gets 404 and the failed authorization is audited. |
| AUTH-007 | Must | U, I | `apps/accounts/tests/test_mfa_sessions.py` | AUTH-007-U1 — revoked session token rejected on next request. • AUTH-007-U2 — inactivity timeout expires the session server-side. • AUTH-007-I1 — high-risk action (role grant) demands re-authentication. • AUTH-007-I2 — privileged user sees own device/session list. |
| AUTH-008 | Must | U, A | `apps/accounts/tests/test_provider_connections.py` | AUTH-008-U1 — connection record stores consent, scopes, connection time, last sync, revocation status. • AUTH-008-U2 — tokens never appear in API responses, serializers, or captured logs. |
| AUTH-009 | Must | U, I, A | `apps/accounts/tests/test_suspension_lifecycle.py` | AUTH-009-U1 — suspending an account invalidates all its sessions immediately. • AUTH-009-I1 — suspended member's public profile/blogs render per moderation and retention policy. |
| AUTH-010 | Should | I | `apps/accounts/tests/test_suspension_lifecycle.py` | AUTH-010-I1 — profile+contribution export returns complete JSON. • AUTH-010-I2 — deletion request anonymizes the member while audit and contribution evidence are retained (BR-008). |

### 4.2 Table 7B — Member profiles

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| MEM-001 | Must | U | `apps/accounts/tests/test_profile_models.py` | MEM-001-U1 — duplicate public username rejected. • MEM-001-U2 — internal identifier immutable; username change preserves it. |
| MEM-002 | Must | U, I, A | `apps/accounts/tests/test_profile_models.py` | MEM-002-U1 — all specified fields (name … contribution preferences) round-trip. • MEM-002-I1 — profile edit accepts Devanagari text stored NFC-normalized (DSC-003). |
| MEM-003 | Must | U, I, A | `apps/accounts/tests/test_profile_visibility.py`, `apps/accounts/tests/test_member_directory.py` | MEM-003-U1 — public serialization omits email, auth provider, private contacts by default. • MEM-003-I1 — toggling field visibility changes the public profile view accordingly. • MEM-003-I2 — opt-in directory search is NFC-safe, bilingual, privacy-projected, and N+1-free. |
| MEM-004 | Must | U, I | `apps/taxonomy/tests/test_taxonomy_admin.py` | MEM-004-U1 — skills restricted to taxonomy terms; free text rejected into a suggestion queue. • MEM-004-I1 — a missing-term suggestion becomes an admin-reviewable record. |
| MEM-005 | Must | U, I, A | `apps/accounts/tests/test_profile_models.py` | MEM-005-U1 — profile querysets separate government, personal, blogs, verified contributions, badges, links. • MEM-005-I1 — public profile renders each section with only owned/public items. |
| MEM-006 | Must | U | `apps/accounts/tests/test_profile_links.py` | MEM-006-U1 — link types restricted to the allowlist (GitHub, Medium, website, portfolio). |
| MEM-007 | Must | U, I, A | `apps/accounts/tests/test_profile_links.py` | MEM-007-U1 — `javascript:`/`data:` and other unsafe schemes rejected (SEC-004). • MEM-007-U2 — URLs normalized (host case, trailing slash, IDN) before save. • MEM-007-I1 — templates render external links with `rel="noopener"` and external labeling. |
| MEM-008 | Should | I | `apps/accounts/tests/test_profile_visibility.py` | MEM-008-I1 — preview renders the post-change public profile without publishing it. |
| MEM-009 | Should | U | `apps/accounts/tests/test_profile_visibility.py` | MEM-009-U1 — completeness guidance computed; sensitive optional fields never required. |
| MEM-010 | Must | I, A | `apps/accounts/tests/test_views.py`, `apps/moderation/tests/test_views.py`, `apps/accounts/tests/test_impersonation_reports.py` | MEM-010-I1 — public profile hands off to a prefilled report target. • MEM-010-I2 — impersonation report creates a structured moderation case and reaches the moderation queue (ADM-003). • MEM-010-I3 — identity/ownership dispute reaches the moderation queue (ADM-003). |

### 4.3 Table 7C — Government project publishing

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| GOV-001 | Must | U, I, A | `apps/projects/tests/test_gov_lifecycle.py` | GOV-001-U1 — draft querysets scoped to the publisher's ministry assignments. • GOV-001-I1 — publisher drafts under own ministry; other-ministry attempt denied. |
| GOV-002 | Must | U, I, A | `apps/projects/tests/test_gov_fields_readiness.py` | GOV-002-U1 — model captures Appendix A field groups; missing required groups block submission. • GOV-002-I1 — submission requires bilingual title and summary (§14.3). |
| GOV-003 | Must | U, I, A | `apps/projects/tests/test_attachments.py` | GOV-003-U1 — content-sniffed type/size validation rejects mismatched or oversized files (SEC-007). • GOV-003-U2 — attachment replacement increments version. • GOV-003-I1 — malware-scan failure quarantines the file and blocks publication. |
| GOV-004 | Must | U, I, A | `apps/projects/tests/test_gov_lifecycle.py` | GOV-004-U1 — parametrized: exactly the legal lifecycle transitions succeed. • GOV-004-U2 — illegal transition raises typed `ProjectLifecycleError`. • GOV-004-I1 — scheduled publication goes public at the future date. • GOV-004-I2 — restore from archive is Super Admin only. |
| GOV-005 | Must | U, I, A | `apps/projects/tests/test_review_workflow.py` | GOV-005-U1 — approve/request-changes/reject record actor, timestamp, decision, comment, before/after version. • GOV-005-I1 — review trail visible in admin and mirrored to audit (SEC-008). |
| GOV-006 | Must | U, I, A | `apps/projects/tests/test_review_workflow.py` | GOV-006-U1 — parametrized: license/repository/classification/scope/agreement/contact edits are material. • GOV-006-I1 — material edit moves published → in review; non-material edit stays published. |
| GOV-007 | Must | U, I, A | `apps/projects/tests/test_public_exposure.py` | GOV-007-U1 — publication blocked without instructions, channel, response SLA, difficulty, effort, prerequisites, and at least one task (BR-002). • GOV-007-I1 — open project page renders all required exposure elements. |
| GOV-008 | Must | U, A | `apps/projects/tests/test_contribution_categories.py` | GOV-008-U1 — category set covers engineering, UI/UX, QA, security, data, documentation, localization, research, community support. |
| GOV-009 | Should | I | `apps/projects/tests/test_updates_completion.py` | GOV-009-I1 — publisher posts progress/milestone updates and a completion summary crediting contributors. |
| GOV-010 | Must | U, I | `apps/projects/tests/test_updates_completion.py` | GOV-010-U1 — expired deadline never auto-closes the project; flag raised instead. • GOV-010-I1 — owner must explicitly extend, pause, complete, cancel, or archive. |
| GOV-011 | Must | U, I, A | `apps/projects/tests/test_public_exposure.py` | GOV-011-U1 — official badge condition = approved, published, government type (BR-001). • GOV-011-I1 — badge never renders on personal or unapproved projects. |
| GOV-012 | Should | U | `apps/projects/tests/test_updates_completion.py` | GOV-012-U1 — maintainer non-response past SLA creates a flag to ministry and Super Admin. |

### 4.4 Table 7D — Member-owned projects

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| PPR-001 | Must | I, A | `apps/projects/tests/test_personal_projects.py` | PPR-001-I1 — member runs create/edit/unpublish/archive on own listing. • PPR-001-I2 — another member cannot modify someone else's listing (AUTH-006). |
| PPR-002 | Must | U | `apps/projects/tests/test_personal_projects.py` | PPR-002-U1 — title/summary/description/role/status/technology/skills/dates/images/URLs round-trip with validation. |
| PPR-003 | Must | I, A | `apps/projects/tests/test_personal_projects.py` | PPR-003-I1 — listing and detail views carry the community label and no endorsement wording (BR-009). |
| PPR-004 | Should | U | `apps/projects/tests/test_personal_projects.py` | PPR-004-U1 — connected GitHub repository match marks ownership verified; mismatch records unverified. |
| PPR-005 | Must | U, I, A | `apps/projects/tests/test_personal_projects.py` | PPR-005-U1 — automated unsafe-link/file check routes the listing to moderation. • PPR-005-I1 — community report opens a moderation case on a personal project. |
| PPR-006 | Could | — | — | Deferred (post-MVP per SRS phasing); no test cases. |

### 4.5 Table 7E — Discovery, applications, participation

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| DSC-001 | Must | U, I, A | `apps/projects/tests/test_catalog_views.py`, `apps/projects/tests/test_discovery_search.py` | DSC-001-U1 — public how-to page lays out a bilingual, accessible contribution flow and is linked from shared navigation. • DSC-001-I1 — anonymous users list and open approved projects; drafts are hidden. |
| DSC-002 | Must | U, I, A | `apps/projects/tests/test_discovery_search.py` | DSC-002-U1 — parametrized filters: ministry, technology, skill, contribution type, status, difficulty, effort, deadline, language. • DSC-002-I1 — title/summary text search returns expected hits only. |
| DSC-003 | Must | U, A | `apps/projects/tests/test_discovery_search.py` | DSC-003-U1 — NFC and NFD Devanagari query variants match the same record. • DSC-003-U2 — slugs stable, unique, Unicode-safe, unchanged on re-save. |
| DSC-004 | Should | I | `apps/projects/tests/test_bookmarks_recommendations.py` | DSC-004-I1 — bookmark toggle works; opt-in subscriber notified on project change (NTF-002). |
| DSC-005 | Must | U, I, A | `apps/projects/tests/test_applications.py` | DSC-005-U1 — mode enforcement: direct mode hides application; application mode hides direct instructions. • DSC-005-I1 — interest/application accepted on open projects; rejected when paused/completed/cancelled/archived (BR-011). |
| DSC-006 | Must | U, I, A | `apps/projects/tests/test_applications.py` | DSC-006-U1 — form contains only base plus ministry-configured screening questions. • DSC-006-I1 — configured screening questions render and validate answers. |
| DSC-007 | Should | I, A | `apps/projects/tests/test_applications.py` | DSC-007-I1 — accept/waitlist/decline/request-info decisions use reusable templates and produce auditable status. |
| DSC-008 | Must | U, I, A | `apps/projects/tests/test_applications.py` | DSC-008-U1 — timeline entries are append-only. • DSC-008-I1 — member and authorized ministry users see the timeline; other members cannot. |
| DSC-009 | Should | U | `apps/projects/tests/test_bookmarks_recommendations.py` | DSC-009-U1 — staleness computed from last maintainer response; public view shows only the aggregate indicator. |
| DSC-010 | Should | U | `apps/projects/tests/test_bookmarks_recommendations.py` | DSC-010-U1 — recommendations cite profile skills/interests/language/effort as reasons; no opaque score. |

### 4.6 Table 7F — GitHub integration

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| GIT-001 | Must | U, A | `apps/github_sync/tests/test_app_installation.py` | GIT-001-U1 — requested GitHub App permissions equal the configured minimal set; extras rejected. |
| GIT-002 | Must | U, I, A | `apps/github_sync/tests/test_app_installation.py` | GIT-002-U1 — profile import restricted to the consented field allowlist. • GIT-002-I1 — narrower consent imports a narrower activity set. |
| GIT-003 | Must | I | `apps/github_sync/tests/test_app_installation.py` | GIT-003-I1 — events from repositories not selected by the installation are ignored. |
| GIT-004 | Must | U, I, A | `apps/github_sync/tests/test_webhooks.py` | GIT-004-U1 — invalid/missing signature → 401 with the delivery stored as rejected. • GIT-004-U2 — low-entropy webhook secret rejected at configuration validation. • GIT-004-I1 — replayed signature/timestamp rejected. |
| GIT-005 | Must | U, I, A | `apps/github_sync/tests/test_webhooks.py` | GIT-005-U1 — same delivery ID processed exactly once (idempotency key). • GIT-005-U2 — failing processing retries with backoff; processing state recorded. • GIT-005-I1 — out-of-order deliveries handled via timestamps without double effects. |
| GIT-006 | Must | U, A | `apps/github_sync/tests/test_reconciliation.py` | GIT-006-U1 — reconciliation recovers missed events without duplicating webhook-sourced records. • GIT-006-U2 — rate-limit backoff respected (frozen clock). |
| GIT-007 | Must | U, A | `apps/github_sync/tests/test_verified_events.py` | GIT-007-U1 — parametrized event map: PR-merged, issue-closed, approved review, release, qualifying default-branch commits create candidates; other types ignored. |
| GIT-008 | Must | U, A | `apps/github_sync/tests/test_verified_events.py` | GIT-008-U1 — parametrized: bot authors and merge commits generate no leaderboard credit. • GIT-008-U2 — duplicate events deduplicated before scoring. |
| GIT-009 | Should | U | `apps/github_sync/tests/test_contribution_calendar.py` | GIT-009-U1 — calendar shows source and freshness labels plus the "not an exact record" note (BR-005). |
| GIT-010 | Must | U, I, A | `apps/github_sync/tests/test_privacy.py` | GIT-010-U1 — private repository names/content omitted from serializers and logs. • GIT-010-I1 — private activity counts hidden unless explicitly authorized. |
| GIT-011 | Must | I, A | `apps/github_sync/tests/test_disconnect.py` | GIT-011-I1 — revocation/uninstall stops sync, deletes/invalidates tokens, shows disconnected state. |
| GIT-012 | Must | U, A | `apps/github_sync/tests/test_provider_events.py` | GIT-012-U1 — every imported event stores provider event ID, repository ID, actor mapping, received time, processing state, verification provenance. |

### 4.7 Table 7G — Technical blogs

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| BLG-001 | Must | U, I, A | `apps/blogs/tests/test_blog_lifecycle.py` | BLG-001-U1 — post lifecycle (create/preview/save/publish/edit/unpublish/archive) allows legal transitions only. • BLG-001-I1 — author edits own post; other member denied. |
| BLG-002 | Must | U, A | `apps/blogs/tests/test_markdown_safety.py` | BLG-002-U1 — Markdown renders the allowed feature set (headings, code blocks, images, links, tables). • BLG-002-U2 — image without alternative text fails validation. |
| BLG-003 | Must | U, I, A | `apps/blogs/tests/test_markdown_safety.py` | BLG-003-U1 — parametrized payloads: scripts, iframes, `on*` handlers stripped or rejected. • BLG-003-I1 — stored malicious payload renders inert (stored-XSS regression). |
| BLG-004 | Must | U | `apps/blogs/tests/test_blog_lifecycle.py` | BLG-004-U1 — metadata (title, excerpt, cover, tags, language, reading time, pub date, canonical URL) round-trips; reading time computed. |
| BLG-005 | Should | U | `apps/blogs/tests/test_external_articles.py` | BLG-005-U1 — external article listed as link only; import blocked until rights confirmation recorded. |
| BLG-006 | Must | U, I, A | `apps/blogs/tests/test_blog_moderation.py` | BLG-006-U1 — report moves post into moderation state; version history preserved. • BLG-006-I1 — moderator sees version/audit history of the reported post. |
| BLG-007 | Must | U, I | `apps/blogs/tests/test_blog_moderation.py` | BLG-007-U1 — official publishing requires the explicit permission; ordinary member denied. • BLG-007-I1 — official label visually distinct from personal writing (BR-001 adjacent). |

### 4.8 Table 7H — Recognition and leaderboard

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| REC-001 | Must | U, A | `apps/recognition/tests/test_scoring.py` | REC-001-U1 — score computed only from verified accepted contributions; self-reported activity and raw commits excluded. |
| REC-002 | Must | U, A | `apps/recognition/tests/test_scoring.py` | REC-002-U1 — scoring uses the active approved policy version; unapproved versions are inert. • REC-002-U2 — each computation pins the policy version used (BR-012). |
| REC-003 | Should | U | `apps/recognition/tests/test_leaderboard_views.py` | REC-003-U1 — rolling/annual/ministry/project/type/lifetime views compute correct aggregates without private data. |
| REC-004 | Must | U | `apps/recognition/tests/test_leaderboard_views.py` | REC-004-U1 — opted-out member absent from public leaderboard; private contribution history intact. |
| REC-005 | Must | U, I, A | `apps/recognition/tests/test_corrections.py` | REC-005-U1 — reversal requires a reason, writes audit, recalculates recognition. • REC-005-I1 — unauthorized user cannot reverse recognition. |
| REC-006 | Must | U, A | `apps/recognition/tests/test_antigaming.py` | REC-006-U1 — per-contributor rate caps enforced across projects within a period. • REC-006-U2 — anomalous volume flagged into the anomaly review queue. |
| REC-007 | Should | U | `apps/recognition/tests/test_badges.py` | REC-007-U1 — badge award records criteria version, evidence, issuer, issue date; revocation reflected on profile. |
| REC-008 | Must | U, A | `apps/recognition/tests/test_badges.py` | REC-008-U1 — accepted documentation/design/QA work scores per policy without requiring a Git commit (GOV-008). |

### 4.9 Table 7I — Notifications

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| NTF-001 | Must | U, I, A | `apps/notifications/tests/test_notifications.py` | NTF-001-U1 — parametrized event→notification map (approval, review comment, application, assignment, verification, moderation, security). • NTF-001-I1 — user sees only own notifications. |
| NTF-002 | Must | U | `apps/notifications/tests/test_notifications.py` | NTF-002-U1 — preference toggle suppresses non-essential email; security/administrative notices always sent. • NTF-002-U2 — digest frequency honored (frozen clock). |
| NTF-003 | Must | U | `apps/notifications/tests/test_notifications.py` | NTF-003-U1 — subject lines carry no sensitive content; body links to authenticated detail. |
| NTF-004 | Should | U | `apps/notifications/tests/test_notifications.py` | NTF-004-U1 — failed delivery logged and retried without creating a duplicate user-visible notification. |

### 4.10 Table 7J — Administration and moderation

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| ADM-001 | Must | U, I, A | `apps/taxonomy/tests/test_taxonomy_admin.py`, `apps/ministries/tests/test_provisioning.py` | ADM-001-U1 — Super-Admin-only CRUD on skills/tags/categories/licenses/contribution types/badges/moderation reasons. • ADM-001-U2 — license entries restricted to the SPDX allowlist; no free text (§18.3). • ADM-001-I1 — feature flag gates a feature route end-to-end. |
| ADM-002 | Must | U, I, A | `apps/moderation/tests/test_review_queues.py` | ADM-002-U1 — submission enters queue; assignment is exclusive (one assignee). • ADM-002-I1 — queue filters by type/status; SLA indicator computed. |
| ADM-003 | Must | U, I, A | `apps/moderation/tests/test_reports.py` | ADM-003-U1 — parametrized: profile/project/blog/link/comment-evidence/security-concern all reportable with structured reasons. • ADM-003-I1 — security concern routes to the security queue, invisible publicly. |
| ADM-004 | Must | U, I, A | `apps/moderation/tests/test_moderation_actions.py` | ADM-004-U1 — parametrized actions (no action, warning, restriction, unpublish, suspension, escalation) require a reason and write audit. • ADM-004-I1 — escalation lands in the security queue. |
| ADM-005 | Must | U | `apps/moderation/tests/test_privileged_search.py` | ADM-005-U1 — privileged search/export requires purpose, is logged, denied to non-privileged users. • ADM-005-U2 — bulk export rate-limited (SEC-006). |
| ADM-006 | Should | U | `apps/moderation/tests/test_dashboards.py` | ADM-006-U1 — dashboard aggregates active/stale projects, response SLA, sync failures, reports, security alerts, adoption metrics. |
| ADM-007 | Should | I | `apps/moderation/tests/test_appeals.py` | ADM-007-I1 — appeal → review → correction/reinstatement path with audit trail. |
| ADM-008 | Must | U | `apps/audit/tests/test_audit_trail.py` | ADM-008-U1 — no application or ORM-admin path deletes `AuditEvent` rows; bulk update/delete blocked. • ADM-008-U2 — Super Admin deletion attempt denied and itself audited. |

### 4.11 Table 7K — Analytics and reporting

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| ANL-001 | Must | U | `apps/projects/tests/test_analytics.py` | ANL-001-U1 — analytics events validated against the documented schema; secrets, private repository content, unnecessary personal data rejected. |
| ANL-002 | Must | U | `apps/projects/tests/test_analytics.py` | ANL-002-U1 — ministry dashboards expose own-ministry data only; cross-government aggregates require explicit authorization. |
| ANL-003 | Must | U | `apps/projects/tests/test_analytics.py` | ANL-003-U1 — parametrized k: public reports suppress cells below the small-group identification threshold. |
| ANL-004 | Should | U | `apps/projects/tests/test_analytics.py` | ANL-004-U1 — exports embed source, generation time, filters, field definitions, license/usage notice. |
| ANL-005 | Could | — | — | Deferred pending security/rate-limit/privacy/open-data review; no test cases. |

Note: if a dedicated `apps/analytics` app is created later, ANL test paths move there wholesale;
until then they live under `apps/projects/tests/` (ministry dashboards render project data).

### 4.15 Current exact-path audit (2026-09-05)

This audit checks every concrete application-test path named in §§4.1–4.14. `Implemented` means
only that the exact path currently exists and is collected; it does not establish that every case
described in this proposed matrix has been implemented. `Planned` means the exact named path is
absent. Existing tests in differently named files are not treated as substitutes without a
case-level SRS traceability review.

| Status | Exact matrix paths |
|---|---|
| Implemented (30) | `apps/accounts/tests/test_mfa_sessions.py`; `apps/accounts/tests/test_profile_models.py`; `apps/accounts/tests/test_profile_visibility.py`; `apps/accounts/tests/test_profile_links.py`; `apps/audit/tests/test_audit_trail.py`; `apps/ministries/tests/test_provisioning.py`; `apps/taxonomy/tests/test_taxonomy_admin.py`; `apps/projects/tests/test_gov_lifecycle.py`; `apps/projects/tests/test_gov_fields_readiness.py`; `apps/projects/tests/test_attachments.py`; `apps/projects/tests/test_review_workflow.py`; `apps/projects/tests/test_public_exposure.py`; `apps/projects/tests/test_contribution_categories.py`; `apps/projects/tests/test_updates_completion.py`; `apps/projects/tests/test_personal_projects.py`; `apps/projects/tests/test_applications.py`; `apps/github_sync/tests/test_webhooks.py`; `apps/github_sync/tests/test_reconciliation.py`; `apps/github_sync/tests/test_disconnect.py`; `apps/blogs/tests/test_blog_lifecycle.py`; `apps/blogs/tests/test_external_articles.py`; `apps/blogs/tests/test_blog_moderation.py`; `apps/contributions/tests/test_verification.py`; `apps/notifications/tests/test_notifications.py`; `apps/moderation/tests/test_reports.py`; `apps/moderation/tests/test_moderation_actions.py`; `apps/moderation/tests/test_privileged_search.py`; `apps/moderation/tests/test_appeals.py`; `tests/acceptance/test_a08_accessibility_bilingual.py`; `tests/acceptance/test_a10_backup_recovery_incident.py` |
| Planned (34) | `apps/accounts/tests/test_auth_providers.py`; `apps/accounts/tests/test_permissions.py`; `apps/accounts/tests/test_provider_connections.py`; `apps/accounts/tests/test_suspension_lifecycle.py`; `apps/accounts/tests/test_impersonation_reports.py`; `apps/accounts/tests/test_session_security.py`; `apps/accounts/tests/test_rate_limits.py`; `apps/accounts/tests/test_localization.py`; `apps/audit/tests/test_correlation.py`; `apps/projects/tests/test_discovery_search.py`; `apps/projects/tests/test_bookmarks_recommendations.py`; `apps/projects/tests/test_analytics.py`; `apps/projects/tests/test_seo_metadata.py`; `apps/github_sync/tests/test_app_installation.py`; `apps/github_sync/tests/test_verified_events.py`; `apps/github_sync/tests/test_contribution_calendar.py`; `apps/github_sync/tests/test_privacy.py`; `apps/github_sync/tests/test_provider_events.py`; `apps/github_sync/tests/test_outage_resilience.py`; `apps/blogs/tests/test_markdown_safety.py`; `apps/contributions/tests/test_evidence_retention.py`; `apps/recognition/tests/test_scoring.py`; `apps/recognition/tests/test_leaderboard_views.py`; `apps/recognition/tests/test_corrections.py`; `apps/recognition/tests/test_antigaming.py`; `apps/recognition/tests/test_badges.py`; `apps/moderation/tests/test_review_queues.py`; `apps/moderation/tests/test_dashboards.py`; `tests/acceptance/test_a01_ministry_provisioning_mfa.py`; `tests/acceptance/test_a02_project_review_publication.py`; `tests/acceptance/test_a03_member_github_lifecycle.py`; `tests/acceptance/test_a05_webhook_contribution_recognition.py`; `tests/acceptance/test_a07_moderation_sanitization.py`; `tests/acceptance/test_a09_github_outage_resilience.py` |

The planned acceptance filenames for A1, A2, A3, A5, A7, and A9 have differently named,
collected counterparts in `tests/acceptance/`; they are recorded in §9 as partial scenario
implementations, not as exact-path matches. A4, A6, A8, and A10 use the planned filenames.
The collected A8 route/DOM contract and A10 runbook/containment checks do not replace their
required assistive-technology and staging-restore evidence.

### 4.12 Business rules (SRS §8) — anti-gaming and integrity core

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| BR-001 | Must* | U, A | `apps/projects/tests/test_public_exposure.py` | BR-001-U1 — draft/unapproved government project exposes no ministry identity or endorsement marks publicly. |
| BR-002 | Must* | U, A | `apps/projects/tests/test_gov_fields_readiness.py` | BR-002-U1 — parametrized: publication blocked without named ministry owner, public maintainer/contact path, approved contribution mode, response expectation, suitability clearance. |
| BR-003 | Must* | U, A | `apps/projects/tests/test_gov_fields_readiness.py` | BR-003-U1 — repository readiness checklist (approved license, README, CONTRIBUTING, code of conduct, security path, issue entry point, branch/review controls) must be complete before "ready". |
| BR-004 | Must* | U | `apps/accounts/tests/test_profile_models.py` | BR-004-U1 — self-declared skills/education never serialized as government-verified credentials. |
| BR-005 | Must* | U | `apps/github_sync/tests/test_contribution_calendar.py` | BR-005-U1 — GitHub graph block and DevNepal verified-record block rendered with separate labels. |
| BR-006 | Must* | U, A | `apps/contributions/tests/test_verification.py` | BR-006-U1 — self-submitted evidence remains unverified evidence; no recognition until authoritative repository event or authorized maintainer acceptance. |
| BR-007 | Must* | U, A | `apps/contributions/tests/test_verification.py` | BR-007-U1 — maintainer self-verification blocked without secondary approval or an automated authoritative event. |
| BR-008 | Must* | U, A | `apps/contributions/tests/test_evidence_retention.py` | BR-008-U1 — unpublishing/deleting a project preserves audit, security, and contribution evidence required by policy. |
| BR-009 | Must* | U | `apps/projects/tests/test_personal_projects.py` | BR-009-U1 — official-seal/wording block on personal projects and personal blogs routes to moderation. |
| BR-010 | Must* | U, A | `apps/moderation/tests/test_moderation_actions.py` | BR-010-U1 — takedown/suspension/leaderboard correction without reason rejected; appeal path created; urgent-security exception logged. |
| BR-011 | Must* | U, A | `apps/projects/tests/test_gov_lifecycle.py` | BR-011-U1 — parametrized: paused/completed/cancelled/archived projects reject new applications; existing records stay visible per permissions. |
| BR-012 | Must* | U | `apps/taxonomy/tests/test_taxonomy_admin.py`, `apps/recognition/tests/test_scoring.py` | BR-012-U1 — taxonomy edits version terms; historical records keep their version reference. • BR-012-U2 — scoring-policy change does not silently rewrite historical published scores. |

### 4.13 Security requirements (SRS Table 12A)

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| SEC-001 | Must | U | `apps/accounts/tests/test_permissions.py` | SEC-001-U1 — deny-by-default: parametrized permission matrix asserts ungranted role×object×action combinations are refused across users, services, admin tools. |
| SEC-002 | Must | U, M | `apps/github_sync/tests/test_privacy.py` | SEC-002-U1 — OAuth tokens stored encrypted at rest (stored value ≠ plaintext). • SEC-002-M1 — TLS, key management, backup encryption verified in deployment review (§8). |
| SEC-003 | Must | U | `apps/accounts/tests/test_provider_connections.py` | SEC-003-U1 — OAuth state mismatch rejected; PKCE verifier enforced where applicable. • SEC-003-U2 — issuer/audience validation rejects wrong-provider tokens. |
| SEC-004 | Must | U, A | `apps/accounts/tests/test_session_security.py`, `apps/projects/tests/test_attachments.py` | SEC-004-U1 — session cookies HttpOnly + Secure + SameSite. • SEC-004-U2 — redirect targets (`next`) restricted to allowed hosts (open redirect). • SEC-004-U3 — attachment path traversal rejected. • SEC-004-U4 — CSRF enforced on all state-changing POST routes. (XSS: BLG-003-U1/I1; unsafe schemes: MEM-007-U1; injection: ORM-only access asserted in model tests.) |
| SEC-005 | Must | U, A | `apps/accounts/tests/test_permissions.py` | SEC-005-U1 — parametrized object-level probe across apps: foreign objects yield 403/404 with no field leakage, including ministry ownership and moderation actions. |
| SEC-006 | Must | U, A | `apps/accounts/tests/test_rate_limits.py`, `apps/github_sync/tests/test_webhooks.py` | SEC-006-U1 — authentication attempts throttled. • SEC-006-U2 — webhook/callback endpoints rate-limited against floods. (Reports/exports/uploads covered by ADM-005-U2, GOV-003-U1.) |
| SEC-007 | Must | U, A | `apps/projects/tests/test_attachments.py` | SEC-007-U1 — safe renamed storage; executable extension/content rejected; no direct execution path. • SEC-007-U2 — size/count limits and quarantine-on-scan-failure enforced. |
| SEC-008 | Must | U, A | `apps/audit/tests/test_audit_trail.py` | SEC-008-U1 — privileged actions record actor/action/object/before-after/correlation ID. • SEC-008-U2 — failed authorization attempts audited. |
| SEC-009 | Must | M (pipeline) | `.github` workflows (coordinator-owned) | SEC-009-M1 — CI runs unit, integration, authorization, SAST, dependency, secret, container, and DAST checks that block release at defined severity thresholds (§8). |
| SEC-010 | Should | M (build) | build pipeline | SEC-010-M1 — SPDX SBOM generated and retained per release (§8). |
| SEC-011 | Must | M (pentest) | external engagement | SEC-011-M1 — independent penetration test before public launch and after major identity/authorization/upload/integration changes (§8). |
| SEC-012 | Must | U, M, A | `apps/moderation/tests/test_reports.py` | SEC-012-U1 — security reports accepted only through the private channel; public project pages expose no sensitive-report intake. • SEC-012-M1 — published disclosure policy and security contact verified by content review (§8). |
| SEC-013 | Must | U, M, A | `apps/github_sync/tests/test_disconnect.py` | SEC-013-U1 — provider-token revocation executable as a programmatic containment step. • SEC-013-M1 — incident severity/on-call/containment/evidence/comms/recovery runbook exercised in drill (§8, A10). |
| SEC-014 | Could | — | — | Deferred (posture signals are informational only); no test cases. |

### 4.14 Non-functional requirements (SRS Table 11A) — automatable subset

| Req | Pri | Layer | File | Cases |
|---|---|---|---|---|
| NFR-AVL-02 | Must | U, I, A | `apps/github_sync/tests/test_outage_resilience.py` | NFR-AVL-02-U1 — health endpoint reports dependency status without secrets. • NFR-AVL-02-I1 — GitHub outage: public pages unaffected, events queued and retried to protect continuity (with A9). |
| NFR-A11Y-01 | Must | U, M, A | `tests/acceptance/test_a08_accessibility_bilingual.py` | NFR-A11Y-01-U1 — automated axe-core scan of key pages: zero critical WCAG 2.2 violations. • NFR-A11Y-01-M1 — manual keyboard-only, screen-reader, zoom/reflow, Nepali, low-bandwidth audit protocol (§8). |
| NFR-I18N-01 | Must | U, I, A | `apps/accounts/tests/test_localization.py` | NFR-I18N-01-U1 — locale switch persists; UI-string scan finds no hardcoded text outside translation calls. • NFR-I18N-01-U2 — dates rendered locale-aware in Asia/Kathmandu from UTC storage. • NFR-I18N-01-I1 — missing translation falls back without mixed or broken layout markers. |
| NFR-OBS-01 | Must | U | `apps/audit/tests/test_correlation.py` | NFR-OBS-01-U1 — correlation ID present on responses/logs and propagated into background jobs. • NFR-OBS-01-U2 — log scrubber removes token/secret patterns. |
| NFR-MNT-01 | Must | U, M | CI check + docs review | NFR-MNT-01-U1 — `makemigrations --check` clean (no model/migration drift) as an automated gate. • NFR-MNT-01-M1 — documented APIs, configuration, runbooks, dependency ownership review (§8). |
| NFR-PORT-01 | Must | U, M | `apps/accounts/tests/test_suspension_lifecycle.py` | NFR-PORT-01-U1 — data exports validate against the documented open schema (JSON/CSV). • NFR-PORT-01-M1 — migration-to-government-hosting exercise (§8). |
| NFR-PERF-03 | Should | I | `apps/github_sync/tests/test_webhooks.py` | NFR-PERF-03-I1 — webhook acknowledged immediately and processed asynchronously; verified activity appears after queue drain (frozen clock; p95 target monitored in ops). |
| NFR-SEO-01 | Should | U | `apps/projects/tests/test_seo_metadata.py` | NFR-SEO-01-U1 — canonical URLs, descriptive/social metadata, sitemap include approved public content only; drafts/private excluded; indexing controlled. |
| NFR-PERF-01 | Should | T (tooling) | Lighthouse CI | NFR-PERF-01-T1 — LCP ≤ 2.5 s p75 on the Nepal 4G/mobile profile after pilot baseline (§8). |
| NFR-PERF-02 | Should | T (tooling) | k6/locust suite | NFR-PERF-02-T1 — read p95 ≤ 500 ms and write p95 ≤ 1 s under approved launch load (§8). |
| NFR-AVL-01 | Should | M (ops) | monitoring SLO | NFR-AVL-01-M1 — 99.5 % monthly availability measured operationally (§8). |
| NFR-DR-01 | Should | M (ops), A | restore drill | NFR-DR-01-M1 — RPO ≤ 24 h / RTO ≤ 8 h restore exercise (§8, A10). |
| NFR-SCL-01 | Should | M (arch) | architecture review | NFR-SCL-01-M1 — independent scaling review per tier (public reads, search, sync, notifications, file processing) (§8). |
| NFR-COMP-01 | Should | M (lab) | compatibility matrix | NFR-COMP-01-M1 — latest-two-evergreen browser matrix verification (§8). |

---

## 5. Acceptance scenarios A1–A10 (SRS §16.1) — decomposition

The following is the planned A1–A10 decomposition. It is not a statement that every listed
function exists. The current acceptance baseline is in §9; all collected acceptance functions do
cite SRS IDs through the citation gate.

### A1 — Super Admin provisions a ministry and two named publishers; MFA enforced; one publisher revoked without affecting the other; all audited

File: `tests/acceptance/test_a01_ministry_provisioning_mfa.py`

1. `test_a01_super_admin_provisions_ministry_organization` — AUTH-004, ADM-001, SEC-008: Super Admin creates the ministry organization; record visible; audit event written.
2. `test_a01_super_admin_creates_two_named_publishers` — AUTH-004, §4.2 control requirement: two named publisher accounts attach to the org; individual named accounts only (shared credentials impossible by model).
3. `test_a01_publisher_mfa_enforced_on_login` — AUTH-005: publisher cannot reach the dashboard without completing MFA.
4. `test_a01_revoking_one_publisher_leaves_other_intact` — AUTH-004, AUTH-007, AUTH-009: revoke publisher 1 → sessions die immediately; publisher 2 unaffected and still functional.
5. `test_a01_all_provisioning_actions_audited` — AUTH-003, SEC-008, ADM-008: create/grant/revoke trail complete with actor, timestamp, correlation ID; no erasure path exists.

### A2 — Bilingual project through change-request and resubmission to approved publication

File: `tests/acceptance/test_a02_project_review_publication.py`

1. `test_a02_ministry_drafts_bilingual_project` — GOV-001, GOV-002, DSC-003, NFR-I18N-01: publisher creates a draft with English+Nepali title and summary; slug stable and Unicode-safe.
2. `test_a02_draft_captures_repository_license_guide_milestones_suitability` — GOV-002, BR-002, BR-003: repository, SPDX license, contribution guide, maintainer, milestones, and suitability fields captured and complete.
3. `test_a02_attachments_upload_with_controls` — GOV-003, SEC-007: proposal attachment accepted under version/type/size/malware controls.
4. `test_a02_super_admin_requests_changes` — GOV-004, GOV-005: decision with actionable comments returns the project to changes-requested; before/after snapshot recorded.
5. `test_a02_ministry_edits_and_resubmits` — GOV-004, GOV-006: ministry edits and resubmits; only legal transitions used.
6. `test_a02_approval_publishes_exactly_the_approved_version` — GOV-004, GOV-005, GOV-011, BR-001: publication exposes exactly the approved snapshot version with the official badge.

### A3 — Member sign-in, profile visibility, limited-scope GitHub connect, personal project, disconnect

File: `tests/acceptance/test_a03_member_github_lifecycle.py`

1. `test_a03_member_signs_in_via_federated_provider` — AUTH-001, AUTH-002: member signs in via an approved provider.
2. `test_a03_configures_public_profile_visibility` — MEM-002, MEM-003: visibility configured; private fields stay private in the public view.
3. `test_a03_connects_github_with_limited_scope` — AUTH-008, GIT-001, GIT-002, GIT-003: consent recorded; only consented fields/public activity imported; repository selection honored.
4. `test_a03_lists_personal_project` — PPR-001, PPR-002, PPR-003, PPR-005, BR-009: personal project listed with community labeling and automated checks passing.
5. `test_a03_disconnect_github_stops_sync_and_removes_tokens` — GIT-011, AUTH-008: disconnect stops synchronization, deletes/invalidates tokens, profile shows disconnected state.

### A4 — Discovery via Nepali and English search, application, updates, auditable timeline

File: `tests/acceptance/test_a04_discovery_application_timeline.py`

1. `test_a04_public_browse_without_sign_in` — DSC-001: anonymous browsing of approved projects.
2. `test_a04_finds_project_in_nepali_and_english_search` — DSC-002, DSC-003, NFR-I18N-01: same project found via Devanagari and Latin queries with filters.
3. `test_a04_applies_or_starts_open_task` — DSC-005, DSC-006: application submitted per project mode with screening questions.
4. `test_a04_receives_status_updates` — NTF-001, DSC-007: decision updates notify the member in-app.
5. `test_a04_sees_auditable_timeline` — DSC-008: application/activity timeline complete and visible to the member and authorized ministry users only.

### A5 — Signed merged-PR webhook → single candidate contribution → verification → recognition → reversible revocation

File: `tests/acceptance/test_a05_webhook_contribution_recognition.py`

1. `test_a05_signed_merged_pr_webhook_creates_single_candidate` — GIT-004, GIT-005, GIT-007, BR-006: valid signature accepted; exactly one candidate contribution record created.
2. `test_a05_duplicate_delivery_creates_no_duplicate` — GIT-005, GIT-008, GIT-012: redelivered webhook deduplicated via provider event provenance.
3. `test_a05_maintainer_verifies_the_result` — BR-006, DSC-008: authorized maintainer acceptance moves the record to verified.
4. `test_a05_recognition_updates` — REC-001, REC-002: verified record updates recognition under the active approved policy version.
5. `test_a05_revocation_reverses_with_audit_reason` — REC-005, SEC-008: moderator revokes with reason; recognition recalculated; audit row written.

### A6 — Non-code contribution evidence → maintainer acceptance → correct contribution-type credit without a Git commit

File: `tests/acceptance/test_a06_noncode_contribution.py`

1. `test_a06_member_submits_noncode_evidence` — GOV-008, BR-006: evidence submitted for an approved non-code category; it is evidence, not verification.
2. `test_a06_authorized_maintainer_accepts` — BR-006, BR-007: authorized maintainer accepts; self-award path would require secondary approval.
3. `test_a06_profile_credits_correct_type_without_commit` — REC-008, MEM-005: profile credits the correct contribution type with no Git commit required.

### A7 — Malicious blog payload and unsafe file/link rejected or sanitized; report reaches correct queue without public evidence exposure

File: `tests/acceptance/test_a07_moderation_sanitization.py`

1. `test_a07_malicious_blog_payload_sanitized` — BLG-002, BLG-003, SEC-004: stored script/iframe payload renders inert.
2. `test_a07_unsafe_file_rejected` — SEC-007, GOV-003: unsafe upload rejected or quarantined.
3. `test_a07_unsafe_link_report_routed_to_correct_queue` — ADM-002, ADM-003, MEM-007: structured report lands in the right moderation queue.
4. `test_a07_report_evidence_not_publicly_exposed` — ADM-003, ANL-001, §13.2: reporter identity and evidence hidden from public views.

### A8 — Keyboard and screen-reader user completes registration, search, application, blog reading, settings in Nepali and English with no critical WCAG failures

File: `tests/acceptance/test_a08_accessibility_bilingual.py`

1. `test_a08_keyboard_and_bilingual_core_route_contract` — NFR-A11Y-01, NFR-I18N-01, DSC-003: registration, a labelled Nepali search, application, public blog reading, and settings execute through the localized URLconf with semantic skip-target and no inline pointer-only handlers.
2. Manual protocol (executed per §8): screen-reader pass, zoom/reflow 400 %, reduced motion, low-bandwidth behavior (NFR-A11Y-01-M1).

### A9 — GitHub outage does not block public browsing; queued sync resumes without data loss or duplicate credit

File: `tests/acceptance/test_a09_github_outage_resilience.py`

1. `test_a09_public_browsing_unaffected_during_github_outage` — NFR-AVL-02: with the provider erroring, public pages serve normally.
2. `test_a09_queued_sync_resumes_without_data_loss` — GIT-005, GIT-006: events delivered during the outage are queued and processed after recovery; reconciliation recovers the rest.
3. `test_a09_no_duplicate_credit_after_recovery` — GIT-005, GIT-008, BR-006: replayed and reconciled events produce no duplicate verified contributions or credit.

### A10 — Backup restoration meets approved RPO/RTO in a documented exercise; security/ops contacts can execute the incident runbook

File: `tests/acceptance/test_a10_backup_recovery_incident.py`

1. `test_a10_checked_in_recovery_protocol_preserves_the_staging_evidence_boundary` — NFR-DR-01, SEC-002: recovery and incident runbooks name the isolated restore, integrity evidence, RPO/RTO gate, and non-completion boundary; it is not a restore exercise.
2. `test_a10_connection_containment_executes_token_purge_and_preserves_an_audit_record` — SEC-013, GIT-011: the user-scoped containment step invokes the configured token purge, stops synchronization, and records an audit event. Contact/escalation and timed restore execution remain manual drills (§8).

---

## 6. Anti-gaming and edge-case suite

Consolidated map of gaming-attack tests derived from BR-006, BR-007, GIT-008, and REC-006.
No new IDs are introduced here; this section binds each attack to the concrete cases above so
reviewers can verify the defenses in one place.

| Attack / edge case | SRS anchor | Covering test IDs |
|---|---|---|
| Self-submitted evidence claimed as verified work | BR-006 | BR-006-U1, REC-001-U1, test_a06 step 1 |
| Maintainer awards credit to themselves | BR-007 | BR-007-U1, test_a06 step 2 |
| Raw commits counted as impact | REC-001, GIT-008 | REC-001-U1, GIT-008-U1 |
| Merge commits counted as contributions | GIT-008 | GIT-008-U1 (parametrized: merge-commit authorship detected) |
| Bot/automated events (e.g. dependabot-style authors) credited | GIT-008 | GIT-008-U1 (parametrized bot-author fixtures) |
| Duplicate webhook delivery inflating counts | GIT-005, GIT-008, GIT-012 | GIT-005-U1, GIT-008-U2, test_a05 step 2 |
| Webhook replay attack | GIT-004, GIT-005 | GIT-004-I1, GIT-005-U1 |
| Credit-volume burst across projects to dodge caps | REC-006 | REC-006-U1 (cap computed globally per contributor per period) |
| Anomalous contribution patterns | REC-006 | REC-006-U2 |
| Reconciliation double-counting recovered events | GIT-006 | GIT-006-U1, test_a09 step 3 |
| Scoring-rule change rewriting history | BR-012, REC-002 | BR-012-U2, REC-002-U2 |
| Leaderboard correction without reason (silent tampering) | REC-005, BR-010 | REC-005-U1, BR-010-U1 |
| Devanagari NFD/NFC duplicates creating double records or broken search | DSC-003 | DSC-003-U1, MEM-002-I1 |
| Application to a closed/paused project slipping through | BR-011 | BR-011-U1, DSC-005-I1 |
| Suspension mid-workflow leaving stale sessions active | AUTH-009 | AUTH-009-U1, test_a01 step 4 |
| Audit erasure after privileged misuse | ADM-008, SEC-008, BR-008 | ADM-008-U1, ADM-008-U2, BR-008-U1 |
| Personal content impersonating government identity | BR-001, BR-009, GOV-011 | BR-009-U1, GOV-011-I1, PPR-003-I1 |

---

## 7. Definition of done — coverage gates

1. **Must gate**: before release, produce and review a case-level trace from every Must (and
    Must* business-rule) requirement in §3 to one or more passing automated tests, or to an
    evidence artifact where pytest cannot verify the requirement. Do not infer this gate from a
    test-file count, marker count, or the proposed inventory totals.
2. **Acceptance gate**: `uv run pytest tests/acceptance/` fully green for A1–A10, with the
   in-file manual protocols of A8 and the A10 drill executed and recorded.
3. **Suite gate**: `uv run pytest` green overall; `uv run ruff check .` and
   `uv run ruff format .` clean (AGENTS.md verify commands).
4. **Citation gate**: `tests/test_srs_citations.py` parses the AST of every `test_*` function in
   `apps/*/tests/test_*.py`, `tests/test_*.py`, `tests/acceptance/test_*.py`, and
   `tests/accessibility/test_*.py`. It extracts requirement IDs from `docs/srs-v0.9.txt` and
   requires each function docstring to cite at least one of those IDs. The only file-level
   exclusion is `tests/test_scaffold.py`: it verifies repository bootstrapping rather than a
   product requirement. Factories, fixtures, and other infrastructure helpers are excluded only
   because they are not `test_*` functions. There are no per-app or per-requirement exemptions.
5. **Layer gates**: `uv run pytest -m unit` green per owning domain before cross-domain review;
   GOV-004-U1 must exercise every legal lifecycle transition branch (no partial state-machine
   coverage).
6. **Regression discipline**: any broken existing test is a bug in the change (AGENTS.md);
   anti-gaming cases in §6 may never be skipped or xfailed without coordinator sign-off.
7. **Should gate (release, not per-task)**: all Should requirements in §4 have their cases
   passing or an approved deferral risk recorded; Could items (PPR-006, ANL-005, SEC-014)
   intentionally carry zero cases until scheduled.

---

## 8. Non-automatable verification register (manual / tooling / external)

| ID | Requirement | Kind | Verification method | Reason not in pytest |
|---|---|---|---|---|
| AUTH-003-M1 | AUTH-003 | Manual (deployment) | First Super Admin created via controlled deployment procedure; runbook record | Bootstrap happens outside the running application |
| SEC-002-M1 | SEC-002 | Manual (infra review) | TLS configuration, key management, backup encryption review sign-off | Infrastructure-level property, not observable from the app process |
| SEC-009-M1 | SEC-009 | Pipeline (CI gate) | CI runs SAST/dependency/secret/container/DAST and blocks release at thresholds | The checks run in CI, not inside pytest; workflows are coordinator-owned (`.github` locked) |
| SEC-010-M1 | SEC-010 | Build artifact | SPDX SBOM generated and retained per release | Build-pipeline output, not application behavior |
| SEC-011-M1 | SEC-011 | External pentest | Independent penetration test report + remediation record, pre-launch and after major changes | Independent human testing is the requirement itself |
| SEC-012-M1 | SEC-012 | Manual (content/legal) | Published vulnerability-disclosure policy and security contact reviewed | Published policy content is a legal/editorial artifact (the routing behavior IS automated: SEC-012-U1) |
| SEC-013-M1 | SEC-013 | Manual (ops drill) | Incident runbook exercise: severity, on-call, containment, evidence, comms, recovery, post-incident | Organizational process exercise (the containment automation IS tested: SEC-013-U1) |
| NFR-A11Y-01-M1 | NFR-A11Y-01 | Manual (a11y audit) | Keyboard-only, screen reader, zoom/reflow, reduced motion, Nepali, low-bandwidth audit per §14.2 | SRS itself mandates manual methods alongside automated (axe covers the automatable subset) |
| NFR-MNT-01-M1 | NFR-MNT-01 | Manual (docs review) | APIs/migrations/config/runbooks/dependency-ownership documentation review | Documentation quality is human-judged (drift check IS automated: NFR-MNT-01-U1) |
| NFR-PORT-01-M1 | NFR-PORT-01 | Manual (ops exercise) | Migration to a government-controlled hosting environment rehearsal | Real-environment exercise (export formats ARE automated: NFR-PORT-01-U1) |
| NFR-PERF-01-T1 | NFR-PERF-01 | Tooling (Lighthouse CI) | LCP ≤ 2.5 s p75 on Nepal 4G profile, post-baseline | Percentile field performance needs external harness and network profiling |
| NFR-PERF-02-T1 | NFR-PERF-02 | Tooling (k6/locust) | Read p95 ≤ 500 ms / write p95 ≤ 1 s under launch load | Load generation with realistic concurrency lives outside pytest |
| NFR-AVL-01-M1 | NFR-AVL-01 | Manual (ops SLO) | 99.5 % monthly availability from monitoring | Month-long production measurement |
| NFR-DR-01-M1 | NFR-DR-01 | Manual (ops drill) | Timed backup-restore exercise proving RPO ≤ 24 h / RTO ≤ 8 h | Real infrastructure restore (A10 references it) |
| NFR-SCL-01-M1 | NFR-SCL-01 | Manual (arch review) | Independent scaling review per tier | Deployment-topology property |
| NFR-COMP-01-M1 | NFR-COMP-01 | Manual (compat lab) | Evergreen browser matrix, latest two stable versions | Needs real browser/OS matrix |

**Intentionally deferred (Could priority, zero cases by design):** PPR-006 (collaboration
invites), ANL-005 (public read-only API), SEC-014 (repository posture signals).

---

## 9. Final count summary

- Current pytest collection: **1,024 items**, measured on 2026-09-05 with
  `uv run pytest --collect-only -qq`; `uv run pytest` passed all 1,024 items.
- Current marker counts: **528** `unit`, **430** `integration`, and **64** `acceptance`.
  Marker counts are pytest items, so parametrized functions contribute multiple items; the
  `acceptance` marker includes the 26 deployed-URLconf flow checks under `tests/flows/`.
- The scenario suite in `tests/acceptance/` has **10 files, 24 test functions, and 38 pytest
  items**. It has partial scenario implementations for A1–A10. A8 executes server-rendered
  keyboard/locale route contracts; A10 executes token containment and verifies the external
  restore-evidence boundary. Neither result is evidence that the required assistive-technology or
  timed staging-restore drill has passed. The proposed 41 acceptance functions are not implemented.
- The proposed inventory remains **241 cases** (136 unit + 64 integration + 41 acceptance). It is
  a planning target, not a current collection count or release-coverage result.
- Exact matrix-path status: **30 implemented paths** and **34 planned paths** (§4.15). This result
  intentionally does not credit renamed files toward a matrix row without case-level review.
- Operational/manual requirements: **11 items** in §8 require deployment, infrastructure, policy,
  audit, documentation, operational, or compatibility evidence: AUTH-003-M1; SEC-002-M1;
  SEC-012-M1; SEC-013-M1; NFR-A11Y-01-M1; NFR-MNT-01-M1; NFR-PORT-01-M1; NFR-AVL-01-M1;
  NFR-DR-01-M1; NFR-SCL-01-M1; NFR-COMP-01-M1.
- External-gated/tooling requirements: **5 items** require CI, a build artifact, an independent
  assessor, or a performance harness: SEC-009-M1; SEC-010-M1; SEC-011-M1; NFR-PERF-01-T1;
  NFR-PERF-02-T1. They are not pytest coverage.
- The citation gate passed on 2026-09-05:
  `uv run pytest tests/test_srs_citations.py` (**1 passed**). It validates citations on collected
  applicable test functions; it does not establish that every SRS requirement is implemented.
