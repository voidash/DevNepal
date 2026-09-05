# User Stories — Core Access, Profiles, Publishing and Discovery (01)

Source: `docs/srs-v0.9.txt` (SRS v0.9, 2 September 2026).
Scope: Table 7A (AUTH-001..010), Table 7B (MEM-001..010), Table 7C (GOV-001..012), Table 7D (PPR-001..006), Table 7E (DSC-001..010), informed by the §4.2 authorization matrix (SRS L154-L217), the §6.1 government project lifecycle (SRS L246-L277), the §6.2/§6.3 workflows, §8 business rules, and Appendix A project fields.
Format: each story keeps the SRS requirement ID and MoSCoW priority verbatim (§7, SRS L291); acceptance criteria are Given/When/Then statements derived only from SRS text, cited as `(SRS L<n>)`.

## Epic breakdown (user journeys)

- **Epic A — Join and stay secure (AUTH-001..010).** A visitor becomes a member through federated sign-in, manages provider connections and sessions, and can export or delete the account; Super Admins and Ministry Publishers are provisioned under stricter, audited controls.
- **Epic B — Build a trusted public identity (MEM-001..010).** A member curates a public profile — username, taxonomy skills, allowlisted links, portfolio sections — controls field-by-field visibility, and can contest impersonation.
- **Epic C — Publish and steward a government project (GOV-001..012).** A Ministry Publisher drafts within its assigned ministry, passes Super Admin review, publishes a complete listing, keeps it responsive, and closes or archives it explicitly.
- **Epic D — List a community project (PPR-001..006).** A member lists personal work that is clearly labeled as non-government, optionally verifies repository ownership, and accepts automated checks and moderation.
- **Epic E — Discover, apply, and participate (DSC-001..010).** A public visitor browses anonymously; a member searches in Nepali and English, bookmarks, expresses interest or applies per project mode, and tracks an auditable activity timeline.

Cross-cutting: who may act is governed by the §4.2 authorization matrix (SRS L154-L217); government project transitions are governed by the §6.1 lifecycle (SRS L246-L277); every privileged/state-changing action is attributable to a named person in the audit log (SRS L217), and the Audit event entity carries actor, action, object, before/after reference, timestamp, source, result, and correlation ID (SRS L683-L684).

---

## Table 7A — Identity, authentication and authorization (SRS L292-L325)

### AUTH-001 — Federated member sign-in (Must)
As a **member** I want to sign in with an approved federated provider (Google/GitHub) so that I do not need a new password.
**Acceptance criteria (Given/When/Then):**
- Given an unauthenticated visitor on the sign-in page, when they choose an enabled provider, then they are redirected through the provider's OAuth/OIDC flow and returned with a verified email claim. (SRS L297, L723)
- Given a provider disabled by configuration, when the sign-in page renders, then that provider's button is absent. (SRS L297)
- Given the MVP provider decision, when providers are configured, then GitHub and Google are enabled for members and Facebook is enabled only after privacy/security/operational approval. (SRS L1022-L1023)
- Given the Facebook provider, when it is approved for production, then it can be disabled by configuration. (SRS L726)

### AUTH-002 — Independent GitHub connection (Must)
As a **member** I want to connect or disconnect my GitHub account independently of the provider I use to sign in so that GitHub features work no matter how I authenticate.
**Acceptance criteria (Given/When/Then):**
- Given a member who signed in with one provider, when they connect or disconnect GitHub, then the GitHub connection changes without changing their sign-in provider. (SRS L300)
- Given a member disconnecting a connected GitHub account, when disconnection completes, then synchronization stops, tokens are invalidated/deleted, and the profile shows a disconnected state. (SRS L300, L496)

### AUTH-003 — Controlled Super Admin provisioning (Must)
As a **Super Admin** I want the first Super Admin provisioned through a controlled deployment process and every subsequent Super Admin grant audited so that the highest privilege is never self-assigned silently.
**Acceptance criteria (Given/When/Then):**
- Given a fresh deployment, when the first Super Admin is provisioned, then this happens through a controlled deployment process. (SRS L303)
- Given any subsequent Super Admin grant, when it is made, then the grant is auditable. (SRS L303)
- Given a privileged user, when they attempt to erase the audit record of their own action through the application interface, then it is not possible. (SRS L600-L601)

### AUTH-004 — Ministry and publisher lifecycle management (Must)
As a **Super Admin** I want to be the only role that creates, activates, suspends, or revokes ministry organizations and their named publisher accounts so that ministry identity on the platform is trusted.
**Acceptance criteria (Given/When/Then):**
- Given a Super Admin, when they create, activate, suspend, or revoke a ministry organization or a named publisher account, then the action succeeds and is attributable to a named person in the audit log. (SRS L306, L217)
- Given a Ministry Publisher or Member, when they attempt ministry-organization or officer-management actions, then they are denied; publishers only view their own organization. (SRS L306, L161-L170)
- Given a ministry organization, when it operates, then it has one or more named publisher accounts and credentials are never shared. (SRS L217, L78)
- Given a ministry with two named publishers, when one publisher is revoked, then the other publisher is unaffected and all actions are audited. (SRS L934)

### AUTH-005 — MFA and verified contacts for privileged accounts (Must)
As a **Super Admin** I want Super Admin and Ministry Publisher accounts to require multi-factor authentication and verified official contact information so that privileged actions cannot be performed with a stolen password alone.
**Acceptance criteria (Given/When/Then):**
- Given a Super Admin or Ministry Publisher account, when it authenticates, then multi-factor authentication is required. (SRS L309)
- Given a privileged account, when it is provisioned, then its official contact information is verified. (SRS L309)
- Given the MVP scope, when privileged accounts are delivered, then named ministry users operate with MFA, audit, consent, and account lifecycle controls. (SRS L910)

### AUTH-006 — Server-side authorization enforcement (Must)
As a **member** I want authorization enforced server-side for every protected object and action, including ownership and ministry boundaries, so that no one can reach another member's or another ministry's data by crafting requests.
**Acceptance criteria (Given/When/Then):**
- Given any protected object or action, when a request is processed, then authorization is enforced server-side including ownership and ministry boundaries. (SRS L312)
- Given a Ministry Publisher, when they act on government projects, then they can create/edit only for their own ministry and can only submit for approval. (SRS L171-L179)
- Given an API route, when it is called, then object-level and function-level authorization is enforced, including ministry ownership and moderation actions. (SRS L805)

### AUTH-007 — Session revocation, timeout, and step-up authentication (Must)
As a **privileged user** I want secure session revocation, device/session listing, inactivity timeout, and re-authentication for high-risk actions so that a stolen or abandoned session cannot perform damage.
**Acceptance criteria (Given/When/Then):**
- Given a privileged user, when they review their account security, then they can see their devices/sessions and revoke sessions securely. (SRS L315)
- Given an authenticated session, when the inactivity timeout elapses, then the session is no longer valid. (SRS L315)
- Given a high-risk action, when it is initiated, then re-authentication is required before the action proceeds. (SRS L315)

### AUTH-008 — Provider connection records without token exposure (Must)
As a **member** I want provider connections recorded with consent, scopes, timing, and revocation status so that I can see what was authorized while tokens are never exposed to me or in logs.
**Acceptance criteria (Given/When/Then):**
- Given a connected provider, when the connection is stored, then provider consent, scopes, connection time, last synchronization, and revocation status are recorded. (SRS L318)
- Given provider tokens, when the platform stores or uses them, then they are never exposed to users or written to logs. (SRS L318, L700-L702)
- Given a provider disconnection/revocation, when it is processed, then OAuth tokens and provider secrets are deleted promptly. (SRS L710)

### AUTH-009 — Immediate suspension effect (Must)
As a **Super Admin** I want a suspended account to lose authenticated access immediately while its public records follow moderation and retention policy so that abuse stops without destroying records.
**Acceptance criteria (Given/When/Then):**
- Given an account that is suspended, when suspension takes effect, then the account loses authenticated access immediately. (SRS L321)
- Given a suspended account's public records, when suspension is applied, then those records follow moderation and retention policy rather than automatic deletion. (SRS L321)
- Given an account suspension, when it is imposed, then it is done with a defined reason and audit history. (SRS L588)

### AUTH-010 — Data export and deletion request (Should)
As a **member** I want to export my profile and contribution records and request account deletion so that I keep control over my personal data.
**Acceptance criteria (Given/When/Then):**
- Given a member, when they request an export, then they receive their profile and contribution records. (SRS L324)
- Given a member, when they request account deletion, then the request is honored subject to lawful and audit retention. (SRS L324)
- Given a deletion request, when it is processed, then it is recorded, authorized, and verifiable. (SRS L712, L840)

---

## Table 7B — Member profile (SRS L327-L360)

### MEM-001 — Unique username and immutable identifier (Must)
As a **member** I want a unique public username backed by an immutable internal identifier so that my identity is stable, unambiguous, and safely referenceable.
**Acceptance criteria (Given/When/Then):**
- Given a new member joining, when a public username is chosen, then it is unique across the platform. (SRS L332)
- Given an existing member, when their record is referenced over time, then the internal identifier never changes. (SRS L332)
- Given public references to a member, when they are displayed, then the public username is what appears, not the internal identifier. (SRS L332)

### MEM-002 — Complete profile fields (Must)
As a **member** I want my profile to hold name, photograph, headline, biography, location, preferred language, skills, education, experience band, availability, interests, and contribution preferences so that ministries and peers understand who I am and how I work.
**Acceptance criteria (Given/When/Then):**
- Given a member editing their profile, when the editor renders, then it supports name, photograph, headline, biography, location, preferred language, skills, education, experience band, availability, interests, and contribution preferences. (SRS L335)
- Given the member profile entity, when it is stored, then it carries public/private profile fields, skills, education, interests, links, preferences, and visibility. (SRS L659-L660)

### MEM-003 — Field-level privacy controls (Must)
As a **member** I want to control the visibility of optional profile fields, with email, authentication provider, and private contact information non-public by default, so that only what I choose is public.
**Acceptance criteria (Given/When/Then):**
- Given optional profile fields, when a member configures visibility, then the public profile reflects those choices. (SRS L338)
- Given a newly created profile, when it is saved for the first time, then email, authentication provider, and private contact information are non-public by default. (SRS L338)
- Given the public member directory, when a member has not opted in to discoverability, then public profile visibility remains controlled field by field. (SRS L1048-L1049)

### MEM-004 — Taxonomy-driven skills with suggestions (Must)
As a **member** I want to select skills from an admin-managed taxonomy and optionally suggest missing terms so that my skills are consistent and searchable across the directory.
**Acceptance criteria (Given/When/Then):**
- Given a member selecting skills, when the skill selector loads, then the options come from the admin-managed taxonomy. (SRS L341)
- Given a term missing from the taxonomy, when a member cannot find it, then they can submit an optional suggestion for the missing term. (SRS L341)
- Given the skills/tags taxonomy, when it needs changes, then it is managed by Super Admin. (SRS L579)

### MEM-005 — Portfolio sections on the public profile (Must)
As a **member** I want my profile to display government and personal projects, technical blogs, verified contributions, badges, and connected external links in separate sections so that my public work is organized and credible.
**Acceptance criteria (Given/When/Then):**
- Given a public member profile, when it renders, then government and personal projects, technical blogs, verified contributions, badges, and connected external links appear in separate sections. (SRS L344)
- Given the contributions section, when it displays, then it shows verified contributions rather than self-reported activity. (SRS L344, L533)

### MEM-006 — Allowlisted external links (Must)
As a **member** I want to link GitHub, Medium, my personal website, a portfolio, and other allowlisted URL types so that my external presence is discoverable from my profile.
**Acceptance criteria (Given/When/Then):**
- Given a member editing profile links, when they add a link, then GitHub, Medium, personal website, portfolio, and other allowlisted URL types are supported. (SRS L347)
- Given a submitted external URL, when it is saved, then only allowlisted URL types are accepted. (SRS L347)

### MEM-007 — Safe external URL handling (Must)
As a **visitor** I want external URLs validated, normalized, checked against unsafe schemes, and clearly labeled so that links on profiles are safe to follow.
**Acceptance criteria (Given/When/Then):**
- Given a member submitting an external URL, when it is saved, then it is validated, normalized, and checked against unsafe schemes. (SRS L350)
- Given a saved external URL, when it is rendered, then it carries clear external-link labeling. (SRS L350)

### MEM-008 — Public profile preview (Should)
As a **member** I want to preview my public profile before publishing changes so that I never expose something unintentionally.
**Acceptance criteria (Given/When/Then):**
- Given a member with pending profile changes, when they choose preview, then they see the public profile as it would appear once published. (SRS L353)
- Given a previewed public profile, when the member is satisfied, then they publish the changes explicitly. (SRS L353)

### MEM-009 — Profile completeness guidance (Should)
As a **member** I want profile completeness guidance so that I can improve how ministries see me without being forced to reveal sensitive optional data.
**Acceptance criteria (Given/When/Then):**
- Given a member profile, when completeness is evaluated, then the platform offers guidance toward completeness. (SRS L356)
- Given sensitive optional profile data, when guidance is presented, then that data is not made mandatory. (SRS L356)

### MEM-010 — Impersonation reporting and identity verification (Must)
As a **member** I want to report impersonation and request verification of a disputed identity or project ownership claim so that false identities do not stand unchallenged.
**Acceptance criteria (Given/When/Then):**
- Given a member who observes impersonation, when they report it, then the report is filed using structured reasons. (SRS L359, L585)
- Given a disputed identity or project ownership claim, when a member requests verification, then the platform provides a verification path for the dispute. (SRS L359)
- Given impersonation cases, when moderation handles them, then documented service levels and escalation apply. (SRS L868)

---

## Table 7C — Government project publishing (SRS L362-L401)

### GOV-001 — Ministry-scoped project drafting (Must)
As a **ministry publisher** I want to create and edit project drafts only for the ministry organizations my account is assigned to so that publishing authority stays within my ministry's boundary.
**Acceptance criteria (Given/When/Then):**
- Given a Ministry Publisher, when creating or editing project drafts, then only the ministry organizations the account is assigned to are available. (SRS L367)
- Given a project in Draft state, when visibility is evaluated, then it is visible only to the owning ministry and Super Admin. (SRS L251-L252)
- Given a Ministry Publisher, when they target a project of another ministry, then the action is denied because government-project creation is limited to "own ministry". (SRS L171-L174, L312)

### GOV-002 — Structured project metadata (Must)
As a **ministry publisher** I want the project form to capture the structured fields defined in Appendix A so that listings are complete, comparable, and reviewable.
**Acceptance criteria (Given/When/Then):**
- Given a government project form, when it is completed, then structured fields per Appendix A are captured, including outcome, requirements, contribution types, maintainer, repository, license, data classification, milestones, and response expectations. (SRS L370, L1055-L1082)
- Given a government project's title and summary, when they are entered, then both English and Nepali are provided. (SRS L899)
- Given license selection, when a license is chosen, then it comes from a PMO-approved SPDX allowlist rather than free text. (SRS L846, L1031)

### GOV-003 — Controlled project attachments (Must)
As a **ministry publisher** I want to attach proposals, requirements, architecture, design, and other approved documents with version, file type, size, and malware controls so that project documentation is safe and traceable.
**Acceptance criteria (Given/When/Then):**
- Given a project attachment of an approved type (proposal, requirements, architecture, design, or other approved), when it is uploaded, then version, file type, and size controls apply. (SRS L373)
- Given an uploaded attachment, when it is processed, then it is scanned for malware and failures are quarantined. (SRS L373, L807)
- Given stored attachments, when they are catalogued, then version, language, accessibility, and classification metadata accompany them. (SRS L1080)

### GOV-004 — Full lifecycle action set (Must)
As a **ministry publisher** I want save-as-draft, preview, submit, change-request, approve, schedule, publish, pause, complete, cancel, archive, and restore actions according to the lifecycle so that a project is governed end to end.
**Acceptance criteria (Given/When/Then):**
- Given a Draft project, when the ministry submits it for review, then it enters In review, where Super Admin can approve, request changes, or reject based on completeness, suitability, licensing, security classification, and readiness. (SRS L253-L256)
- Given a project in Changes requested, when the ministry edits and resubmits, then it returns to review. (SRS L257-L259)
- Given an Approved project, when Super Admin acts, then they publish it or revoke approval; publication may be scheduled for a future date. (SRS L260-L262)
- Given an Open for contribution project, when the owner acts, then pause, mark in progress, complete, cancel, or archive transitions are available. (SRS L263-L265)
- Given a Paused project, when it is public, then its status stays visible, new applications are disabled, existing work is retained, and resume/complete/cancel/archive are available. (SRS L266-L268, L648)
- Given an Archived project, when restoration is requested, then only Super Admin can restore it. (SRS L275-L277)

### GOV-005 — Auditable review actions (Must)
As a **Super Admin** I want every review action to record actor, timestamp, decision, reason/comment, and before/after version so that approval decisions are fully traceable.
**Acceptance criteria (Given/When/Then):**
- Given any review action, when it is recorded, then actor, timestamp, decision, and reason/comment are captured. (SRS L379)
- Given any review action, when it is recorded, then before/after version references are captured. (SRS L379)
- Given a bilingual project submission, when Super Admin requests changes and the ministry resubmits, then approval publishes exactly the approved version. (SRS L936)

### GOV-006 — Material edits return to review (Must)
As a **Super Admin** I want material edits to a published project to return it to review or require Super Admin approval so that the published substance never changes silently.
**Acceptance criteria (Given/When/Then):**
- Given a published project, when license, repository, data classification, scope, contribution agreement, or public-contact information is materially edited, then the project returns to review or requires Super Admin approval. (SRS L382)
- Given a Ministry Publisher editing a published own-ministry project, when the edit is material, then it may re-enter review per the authorization matrix. (SRS L183)
- Given a material edit, when it is decided, then the decision is attributable to a named person in the audit log. (SRS L217)

### GOV-007 — Open-project readiness information (Must)
As a **member** I want each open project to expose contribution instructions, communication channel, expected first-response time, difficulty, effort, prerequisites, and at least one actionable task so that I can start contributing without guessing.
**Acceptance criteria (Given/When/Then):**
- Given an Open for contribution project, when its page is viewed, then contribution instructions, a communication channel, and expected first-response time are exposed. (SRS L385)
- Given an open project, when a member evaluates fit, then difficulty, effort, and prerequisites are exposed. (SRS L385)
- Given an open project, when a member looks for work, then at least one actionable task or workstream is exposed. (SRS L385)
- Given a project missing a named ministry owner, public maintainer/contact path, approved contribution mode, response expectation, or suitability clearance, when publication is attempted, then it is blocked. (SRS L630)

### GOV-008 — Code and non-code contribution categories (Must)
As a **member** I want projects to support code and non-code contribution categories so that my UI/UX, QA, documentation, or research work counts as a first-class contribution path.
**Acceptance criteria (Given/When/Then):**
- Given a government project, when contribution categories are defined, then code and non-code categories are supported, including engineering, UI/UX, QA, security, data, documentation, localization, research, and community support. (SRS L388)
- Given approved non-code contribution types, when recognition is computed, then design, QA, documentation, translation, security, and research work is not disadvantaged. (SRS L554)

### GOV-009 — Progress updates and contributor credit (Should)
As a **ministry publisher** I want to post progress updates, milestone status, release/result links, a completion summary, and contributor acknowledgements so that transparency is maintained through closure.
**Acceptance criteria (Given/When/Then):**
- Given an active project, when the publisher posts an update, then progress updates, milestone status, and release/result links can be published. (SRS L391)
- Given a project reaching completion, when it is closed, then a completion summary and contributor acknowledgements are posted. (SRS L391, L1082)
- Given a Completed project, when the outcome is published, then no new work is accepted. (SRS L270)

### GOV-010 — Explicit deadline handling (Must)
As a **ministry publisher** I want an expired deadline never to silently close my project so that the next state is always an explicit owner decision.
**Acceptance criteria (Given/When/Then):**
- Given a project whose deadline expires, when the deadline passes, then the project does not silently close. (SRS L394)
- Given an expired deadline, when the owner acts, then they explicitly extend, pause, complete, cancel, or archive the project. (SRS L394)

### GOV-011 — Official badge on approved projects only (Must)
As a **public visitor** I want the official-government badge displayed only on Super Admin-approved ministry projects so that I can trust what is genuinely governmental.
**Acceptance criteria (Given/When/Then):**
- Given a Super Admin-approved ministry project, when it is displayed, then it shows the official-government badge. (SRS L397)
- Given a project that is not Super Admin approved, when it is displayed, then no official ministry identity or Government of Nepal endorsement is shown. (SRS L397, L628)

### GOV-012 — Maintainer SLA flagging (Should)
As a **Super Admin** I want projects with no maintainer response within the configured SLA flagged to the ministry and Super Admin so that stale listings are addressed before volunteer trust collapses.
**Acceptance criteria (Given/When/Then):**
- Given a configured maintainer-response SLA, when no maintainer response occurs within it, then the project is flagged to the ministry and Super Admin. (SRS L400)
- Given operational dashboards, when Super Admin reviews them, then stale projects and response-SLA indicators are visible. (SRS L594)

---

## Table 7D — Member-owned projects (SRS L403-L424)

### PPR-001 — Manage my personal project listing (Must)
As a **member** I want to create, edit, unpublish, and archive my own personal project listings so that I can showcase work I own or maintain.
**Acceptance criteria (Given/When/Then):**
- Given a member, when they create a personal project, then the listing is theirs to edit. (SRS L408)
- Given a member's own personal project, when they act on it, then unpublish and archive are available. (SRS L408)
- Given a member, when they attempt to modify another member's personal project, then the action is denied because members own only their own listings. (SRS L189, L312)

### PPR-002 — Personal project fields (Must)
As a **member** I want my personal project listing to support title, summary, description, role, status, technology, skills, dates, images, and external URLs so that it describes my work adequately.
**Acceptance criteria (Given/When/Then):**
- Given a personal project form, when it is filled, then title, summary, description, role, status, technology, skills, dates, images, and external URLs are supported. (SRS L411)
- Given personal and government projects, when they are stored, then they share the common Project record distinguished by type (government or personal). (SRS L663-L664)

### PPR-003 — Community-project labeling (Must)
As a **public visitor** I want personal projects clearly labeled as community projects that never imply Government of Nepal endorsement so that I am never misled about what is official.
**Acceptance criteria (Given/When/Then):**
- Given a personal project, when it is displayed, then it is clearly labeled as a community project. (SRS L414)
- Given a personal project, when it is displayed, then it never implies Government of Nepal endorsement. (SRS L414, L644)
- Given the public site navigation, when a visitor browses, then community projects are clearly separated from official government projects. (SRS L876-L879)

### PPR-004 — GitHub ownership verification (Should)
As a **member** I want the platform to attempt ownership verification for connected GitHub repositories and record verified/unverified status so that my ownership claim is credible.
**Acceptance criteria (Given/When/Then):**
- Given a personal project with a connected GitHub repository, when verification runs, then the platform attempts ownership verification and records verified or unverified status. (SRS L417)
- Given the available verification paths, when ownership is verified, then it may be through the connected GitHub account, domain verification, or manual moderation. (SRS L289)

### PPR-005 — Moderation of personal projects (Must)
As a **Super Admin** I want personal projects subject to automated link/file checks, community reports, and Super Admin moderation so that the community catalog stays safe and truthful.
**Acceptance criteria (Given/When/Then):**
- Given a personal project, when it is published or updated, then automated link/file checks apply to it. (SRS L420)
- Given a personal project, when community reports are filed against it, then Super Admin moderation applies. (SRS L420)
- Given misleading government branding, unsafe links, copied content, or unlawful material on a personal project, when detected, then it is prohibited. (SRS L289)

### PPR-006 — Inviting collaboration (Could)
As a **member** I may invite collaboration on my personal project once I have accepted the community terms and published contribution/contact instructions so that collaborators have clear ground rules.
**Acceptance criteria (Given/When/Then):**
- Given a personal project owner, when they invite collaboration, then the invitation is permitted only after the community terms are accepted. (SRS L423)
- Given accepted community terms, when collaboration is invited, then contribution and contact instructions must be published first. (SRS L423)

---

## Table 7E — Discovery, application and participation (SRS L426-L459)

### DSC-001 — Browse without signing in (Must)
As a **public visitor** I want to browse approved projects without signing in so that I can explore opportunities before registering.
**Acceptance criteria (Given/When/Then):**
- Given an unauthenticated public visitor, when they browse the catalog, then approved projects are viewable without signing in. (SRS L431)
- Given a public visitor, when they browse the platform, then public projects, member profiles where permitted, blogs, results, and public reports are accessible. (SRS L152)
- Given a public visitor, when they attempt to contribute or apply, then they cannot, because contributing/applying is a Member capability. (SRS L191-L195)

### DSC-002 — Search and filters (Must)
As a **member** I want search with title, summary, ministry, technology, skill, contribution type, status, difficulty, effort, deadline, and language filters so that I can find projects relevant to me.
**Acceptance criteria (Given/When/Then):**
- Given project search, when a visitor or member filters results, then title, summary, ministry, technology, skill, contribution type, status, difficulty, effort, deadline, and language filters are supported. (SRS L434)
- Given a query in either script, when matching runs, then Devanagari and Latin text match without corrupting highlights or sorting. (SRS L900)

### DSC-003 — Nepali Unicode search and stable slugs (Must)
As a **member** I want search and URLs to support Nepali Unicode with stable, human-readable project slugs so that Nepali titles work everywhere links are shared.
**Acceptance criteria (Given/When/Then):**
- Given Nepali search input, when a member searches, then Nepali Unicode is supported by search. (SRS L437)
- Given a project, when its URL is generated, then the slug is stable and human-readable. (SRS L437)
- Given Devanagari and Latin text in the index, when search and URLs operate, then slugs are not corrupted. (SRS L900, L767)

### DSC-004 — Bookmarks and change notifications (Should)
As a **member** I want to bookmark projects and receive opt-in change notifications so that I can track opportunities I care about.
**Acceptance criteria (Given/When/Then):**
- Given a member viewing a project, when they bookmark it, then the bookmark is saved. (SRS L440)
- Given a bookmarked project, when it changes, then the member receives notifications only if they opted in. (SRS L440)

### DSC-005 — Interest, application, or direct contribution (Must)
As a **member** I want to express interest, apply to a controlled workstream, or follow direct-contribution instructions according to the project mode so that I can participate the way the project allows.
**Acceptance criteria (Given/When/Then):**
- Given a project with a controlled workstream, when a member wants in, then they can express interest or apply to it. (SRS L443)
- Given a project in direct-contribution mode, when a member wants to help, then they follow the published direct-contribution instructions (e.g., starting a labeled task). (SRS L443, L282)
- Given a paused, completed, cancelled, or archived project, when a member attempts to apply, then new applications are not accepted. (SRS L648)

### DSC-006 — Project-relevant application forms (Must)
As a **member** I want application forms to capture only project-relevant information with ministry-configured screening questions so that applying is fair and minimally intrusive.
**Acceptance criteria (Given/When/Then):**
- Given an application form, when it is presented, then it captures only project-relevant information. (SRS L446)
- Given screening questions configured by the ministry, when a member applies, then those questions are part of the form. (SRS L446)

### DSC-007 — Applicant decisions and templates (Should)
As a **ministry publisher** I want to accept, waitlist, decline, or request information from applicants with auditable status and reusable response templates so that applicants get consistent, traceable responses.
**Acceptance criteria (Given/When/Then):**
- Given an applicant, when the Ministry Publisher decides, then accept, waitlist, decline, or request-information is available. (SRS L449)
- Given an application decision, when it is recorded, then its status is auditable. (SRS L449)
- Given recurring applicant communications, when publishers respond, then reusable response templates are supported. (SRS L449)

### DSC-008 — Application/activity timeline (Must)
As a **member** I want a preserved application/activity timeline visible to me and authorized ministry users so that the history of my participation is transparent and auditable.
**Acceptance criteria (Given/When/Then):**
- Given a member's application or participation, when events occur over time, then an application/activity timeline is preserved. (SRS L452)
- Given the timeline, when the member views it, then it is visible to them. (SRS L452)
- Given the timeline, when an authorized ministry user views it, then it is visible to them. (SRS L452)
- Given a member who applied or started an open task, when they receive status updates, then the experience forms an auditable timeline. (SRS L940)

### DSC-009 — Maintainer activity indicators (Should)
As a **public visitor** I want public project pages to show maintainer activity indicators and stale-project warnings so that I avoid investing in abandoned projects.
**Acceptance criteria (Given/When/Then):**
- Given a public project page, when it renders, then maintainer activity indicators are displayed. (SRS L455)
- Given a stale project, when its public page renders, then a stale-project warning is displayed without exposing private operational data. (SRS L455)

### DSC-010 — Explainable recommendations (Should)
As a **member** I want recommendations based on my explicit profile skills, interests, language, and effort matched to project needs so that suggestions make sense and are not opaque AI scoring.
**Acceptance criteria (Given/When/Then):**
- Given a member's explicit profile skills, interests, language, and effort, when recommendations are produced, then they are based on those attributes and project needs. (SRS L458)
- Given a recommendation, when it is displayed, then it is explainable rather than opaque AI scoring. (SRS L458)
