# User Stories — Platform Capabilities (02)

Source: `docs/srs-v0.9.txt` (SRS v0.9, 2 September 2026).
Scope: Table 7F (GIT-001..012), Table 7G (BLG-001..007), Table 7H (REC-001..008), Table 7I (NTF-001..004), Table 7J (ADM-001..008), Table 7K (ANL-001..005), §8 Business Rules (BR-001..012), and §6.2 end-to-end contribution workflow.
Format: each story keeps the SRS requirement ID and MoSCoW priority verbatim (§7, SRS L291); acceptance criteria are Given/When/Then statements derived only from SRS text, cited as `(SRS L<n>)`. Business rules carry no MoSCoW priority in the SRS and none is invented here.

---

## Table 7F — GitHub integration (SRS L461-L500)

### GIT-001 — Registered GitHub App with minimum permissions (Must)
As a **platform operator** I want repository-level GitHub integration through a single registered GitHub App with the minimum permissions required so that the platform never holds more GitHub access than its features need.
**Acceptance criteria (Given/When/Then):**
- Given the platform's GitHub integration, when it is configured, then it operates through a registered GitHub App providing repository-level integration and user authorization. (SRS L466)
- Given the GitHub App, when its permissions are granted, then they are the minimum required for the selected DevNepal features. (SRS L466)
- Given the integration inventory, when controls are reviewed, then least privilege, expiring tokens, and secret vault handling apply to the GitHub App/APIs integration. (SRS L718-L720)

### GIT-002 — Consent-scoped profile and activity import (Must)
As a **member** I want GitHub connection to import only the profile fields and public activity I consented to and that the selected features need so that my private GitHub data is not pulled into DevNepal.
**Acceptance criteria (Given/When/Then):**
- Given a member connecting GitHub, when the connection is authorized, then only consented profile fields are imported. (SRS L469)
- Given the selected DevNepal features, when activity is imported, then only the public activity needed for those features is imported. (SRS L469)
- Given the synchronization boundary decision, when import runs, then there is no full private-history mirror of the member's Git history. (SRS L239, L1025)

### GIT-003 — User-selected repository access (Must)
As a **GitHub user or repository owner** I want to select which repositories the GitHub App may access so that repositories I do not enroll are never synchronized.
**Acceptance criteria (Given/When/Then):**
- Given a connected user or repository owner, when the GitHub App installation is configured, then they can select which repositories the App may access. (SRS L472)
- Given a repository that was not selected, when synchronization runs, then the platform does not access that repository. (SRS L472, L1025)

### GIT-004 — Webhook subscription with signature validation (Must)
As a **platform operator** I want event delivery through signed webhooks rather than polling-only so that verified events arrive promptly and cannot be forged.
**Acceptance criteria (Given/When/Then):**
- Given the GitHub App installation, when repository events occur, then the platform receives them via webhook subscription rather than relying only on polling. (SRS L475)
- Given an incoming webhook delivery, when it is processed, then its signature is validated using a high-entropy secret. (SRS L475)
- Given a delivery whose signature is invalid, when validation runs, then the delivery is not accepted for processing. (SRS L475)
- Given production readiness testing, when webhook replay is exercised, then signature validation protects the platform. (SRS L959)

### GIT-005 — Idempotent webhook processing (Must)
As a **platform operator** I want webhook processing to be idempotent and replay-safe so that duplicate GitHub deliveries never create duplicate contribution records.
**Acceptance criteria (Given/When/Then):**
- Given a webhook payload already processed (known delivery/event ID), when the same payload is delivered again, then no new provider event or contribution record is created. (SRS L478, L499)
- Given processing failure mid-way, when the job retries, then state converges without partial duplicates. (SRS L478)
- Given webhook deliveries, when they are received, then they are acknowledged quickly, queued, processed asynchronously, and timestamped. (SRS L478, L749)
- Given a signed webhook for a merged pull request followed by a duplicate delivery, when both are processed, then exactly one candidate contribution is created. (SRS L942)

### GIT-006 — Periodic reconciliation within rate limits (Must)
As a **platform operator** I want periodic reconciliation of selected repositories so that events missed by webhooks are recovered without abusing the GitHub API.
**Acceptance criteria (Given/When/Then):**
- Given selected repositories, when the periodic reconciliation runs, then missed webhook events are recovered. (SRS L481)
- Given GitHub rate limits, when reconciliation runs, then it respects those limits. (SRS L481)
- Given a GitHub outage, when service returns, then queued sync resumes without data loss or duplicate credit. (SRS L950, L978)

### GIT-007 — Configured verified project activity events (Must)
As a **ministry publisher** I want verified project activity limited to configured event types (pull-request merged, issue closed, approved review, release, qualifying commits to the default branch) so that project activity reflects real, meaningful repository events.
**Acceptance criteria (Given/When/Then):**
- Given the configured event types, when a pull-request merged, issue closed, approved review, release, or qualifying commit to the default branch occurs in a listed repository, then it is recorded as verified project activity. (SRS L484)
- Given the set of verified event types, when administrators configure them, then the set is configurable. (SRS L484)
- Given an event type that is not configured, when it is received, then it does not produce verified project activity. (SRS L484)

### GIT-008 — No leaderboard credit for raw, automated, or duplicate events (Must)
As a **member** I want raw commits, merge commits, bot events, and duplicates excluded from direct leaderboard credit so that recognition reflects accepted impact rather than activity spam.
**Acceptance criteria (Given/When/Then):**
- Given a raw commit or merge commit event, when it is processed, then it does not directly generate leaderboard credit. (SRS L487)
- Given an automated or bot event, when it is processed, then it does not directly generate leaderboard credit. (SRS L487)
- Given a duplicated event, when it is detected, then it does not directly generate additional leaderboard credit. (SRS L487)
- Given the platform's recognition basis, when leaderboards are computed, then they rely on verified accepted events rather than raw commit volume. (SRS L77, L533)

### GIT-009 — Annual GitHub contribution summary with labels (Should)
As a **member** I want to optionally display an annual GitHub contribution calendar or summary with clear source and freshness labels so that visitors understand what it does and does not represent.
**Acceptance criteria (Given/When/Then):**
- Given a member who consents to the display, when the profile is viewed, then an annual GitHub contribution calendar or summary may be shown where supported. (SRS L490)
- Given a displayed calendar or summary, when it is rendered, then source and freshness labels are shown. (SRS L490)
- Given the display, when it is presented, then it is not presented as an exact all-time work record. (SRS L490)
- Given provider authorization for the display, when it is shown, then a clear DevNepal notice and revocable consent still govern it. (SRS L838)

### GIT-010 — Private repository data never public (Must)
As a **GitHub user with private repositories** I want private repository names, code, issue content, commit messages, and URLs kept non-public so that connecting GitHub never leaks my private work.
**Acceptance criteria (Given/When/Then):**
- Given private repository names, code, issue content, commit messages, or URLs, when any public view is rendered, then they are never made public. (SRS L493)
- Given private activity counts, when profile or activity views are displayed, then they are omitted unless explicitly authorized and policy-approved. (SRS L493)

### GIT-011 — Revocation stops sync and deletes tokens (Must)
As a **member** I want revoking GitHub authorization or uninstalling the App to immediately stop synchronization and delete tokens so that disconnection is real, not cosmetic.
**Acceptance criteria (Given/When/Then):**
- Given a user revokes GitHub authorization or uninstalls the App, when the platform learns of it, then synchronization stops. (SRS L496)
- Given revocation or uninstall, when it is handled, then tokens are invalidated and deleted promptly. (SRS L496, L710)
- Given a disconnected account, when the profile is viewed, then it shows a disconnected state. (SRS L496)
- Given a member who connected GitHub and then disconnects, when the flow completes, then sync stops and tokens are removed. (SRS L938)

### GIT-012 — Event provenance retained for audit and deduplication (Must)
As an **auditor** I want every imported event to retain its provider event ID, repository ID, actor mapping, received time, processing state, and verification provenance so that contribution records are traceable and safely deduplicable.
**Acceptance criteria (Given/When/Then):**
- Given an imported event, when it is stored, then provider event ID, repository ID, actor mapping, received time, processing state, and verification provenance are retained. (SRS L499, L674)
- Given a repeated delivery of the same event, when deduplication is checked, then the retained provider event ID and deduplication key prevent a second record. (SRS L499, L674)
- Given an audit of a contribution, when its source event is reviewed, then signature result, delivery time, and processing state are available. (SRS L674)

---

## Table 7G — Technical blogs (SRS L502-L526)

### BLG-001 — Full blog post lifecycle for members (Must)
As a **member** I want to create, preview, save, publish, edit, unpublish, and archive my technical blog posts so that I can publish technical writing and keep it current.
**Acceptance criteria (Given/When/Then):**
- Given a signed-in member, when writing, then they can create, preview, save, and publish a technical blog post. (SRS L507)
- Given a published post, when the author edits or unpublishes it, then the edit or unpublish takes effect. (SRS L507)
- Given an existing post, when the author archives it, then it is archived. (SRS L507)
- Given a member-published post, when it is public, then it remains subject to moderation. (SRS L199, L522)

### BLG-002 — Safe Markdown editor (Must)
As a **member blogger** I want a Markdown editor supporting code blocks, images, links, headings, and tables with accessible alternative text so that my technical writing is expressive and accessible.
**Acceptance criteria (Given/When/Then):**
- Given the blog editor, when composing, then safe Markdown, code blocks, images, links, headings, and tables are supported. (SRS L510)
- Given images in a post, when authoring, then accessible alternative text is supported. (SRS L510, L893)
- Given Markdown-generated blogs, when they are rendered, then they follow accessible authoring guidance and validation. (SRS L895)

### BLG-003 — Sanitized rendering and stored-XSS protection (Must)
As a **platform operator** I want rendered blog content sanitized, with executable scripts and iframes prohibited by default, so that a malicious post cannot attack readers.
**Acceptance criteria (Given/When/Then):**
- Given submitted blog content, when it is rendered, then HTML is sanitized. (SRS L513)
- Given executable scripts or iframes in submitted content, when the post is rendered under default policy, then they are prohibited. (SRS L513)
- Given a malicious blog payload, when it is submitted, then it is rejected or sanitized so stored cross-site scripting is prevented. (SRS L513, L946)

### BLG-004 — Structured post metadata (Must)
As a **reader** I want posts to carry title, excerpt, cover image, tags, language, reading time, publication date, and canonical external URL so that I can discover and evaluate technical writing.
**Acceptance criteria (Given/When/Then):**
- Given a blog post, when it is created or edited, then it supports title, excerpt, cover image, tags, language, reading time, publication date, and canonical external URL. (SRS L516)
- Given the Tech Blogs area, when browsing, then technical writing can be browsed by topic, language, and author. (SRS L883)

### BLG-005 — External article links before import (Should)
As a **member** I want to list an external Medium or other article as a link without copying its full text so that I can reference my published writing without reproducing it unlawfully.
**Acceptance criteria (Given/When/Then):**
- Given an external Medium or other article, when a member lists it, then it appears as a link without the full text being copied. (SRS L519)
- Given an attempt to import full text, when import is performed, then rights confirmation and a supported API/format are required. (SRS L519)

### BLG-006 — Moderation states with version/audit history (Must)
As a **moderator** I want blog posts to have moderation states, community reporting, and preserved version/audit history so that I can review content with full context.
**Acceptance criteria (Given/When/Then):**
- Given blog posts, when they are moderated, then moderation states are supported. (SRS L522)
- Given a community member who finds a problematic post, when they report it, then the report is captured. (SRS L522, L585)
- Given moderator review of a post, when history is needed, then version/audit history is preserved for moderators. (SRS L522, L676)

### BLG-007 — Distinct official publishing permission and label (Must)
As a **public visitor** I want government or project-official posts to require an explicit official publishing permission and to carry a visual label distinct from personal member writing so that I can tell official communication from individual opinion.
**Acceptance criteria (Given/When/Then):**
- Given a government or project-official post, when it is published, then an explicit official publishing permission is required. (SRS L525)
- Given an officially published post, when it is displayed, then a visual label distinguishes it from personal member writing. (SRS L525)
- Given a member without official publishing permission, when they attempt to publish as official, then the attempt is denied. (SRS L525)

---

## Table 7H — Recognition and leaderboard (SRS L528-L555)

### REC-001 — Recognition based on verified accepted contributions (Must)
As a **member** I want recognition computed from verified accepted contribution records rather than total commits or self-reported activity so that the leaderboard reflects genuine accepted impact.
**Acceptance criteria (Given/When/Then):**
- Given the recognition calculation, when it runs, then it is based on verified accepted contribution records. (SRS L533)
- Given total commit counts or self-reported activity, when recognition is computed, then they are not the basis for recognition. (SRS L533)
- Given official leaderboards, when they are built, then they rely on verified events such as merged pull requests, accepted documentation/design/QA work, completed issues, and maintainer-approved non-code contributions. (SRS L77)

### REC-002 — Documented, versioned, approved scoring policy (Must)
As a **product owner** I want the scoring policy publicly documented, configurable, versioned, and approved by me before activation so that recognition rules are transparent and never change silently.
**Acceptance criteria (Given/When/Then):**
- Given the scoring policy, when it is defined, then it is publicly documented. (SRS L536)
- Given the scoring policy, when configuration changes, then it is configurable and versioned. (SRS L536, L650)
- Given a new or changed scoring policy, when activation is attempted, then it activates only after product owner approval. (SRS L536)

### REC-003 — Multiple leaderboard views without private data (Should)
As a **community member** I want rolling-period, annual, ministry, project, contribution-type, and lifetime leaderboard views so that I can see impact at the scale that matters to me.
**Acceptance criteria (Given/When/Then):**
- Given the leaderboard, when views are displayed, then rolling-period, annual, ministry, project, contribution-type, and lifetime views are supported. (SRS L539)
- Given any leaderboard view, when it is rendered, then private data is not exposed. (SRS L539)

### REC-004 — Leaderboard opt-out with private history retained (Must)
As a **member** I want to opt out of public leaderboard display while keeping my private contribution history so that participation does not force public ranking.
**Acceptance criteria (Given/When/Then):**
- Given a member who opts out, when the public leaderboard is rendered, then the member is not displayed. (SRS L542)
- Given an opted-out member, when they view their own account, then their private contribution history is retained. (SRS L542)

### REC-005 — Reversible recognition corrections with audit (Must)
As a **moderator** I want to reverse, correct, or invalidate recognition with a reason and audit record so that mistakes and gaming can be fixed transparently.
**Acceptance criteria (Given/When/Then):**
- Given a recognition outcome that must be undone, when a moderator acts, then they can reverse, correct, or invalidate it. (SRS L545)
- Given such a moderation action, when it is applied, then a reason and audit record are captured. (SRS L545, L217)
- Given any recognition or leaderboard change, when it is made, then it remains auditable and reversible. (SRS L286)

### REC-006 — Anti-gaming controls (Must)
As a **platform operator** I want rate caps, bot exclusion, duplicate detection, maintainer separation-of-duties, and anomaly review so that the leaderboard cannot be gamed.
**Acceptance criteria (Given/When/Then):**
- Given unusually rapid contribution activity, when rate caps are evaluated, then they limit gaming. (SRS L548)
- Given automated or bot events, when recognition is computed, then bot exclusion applies. (SRS L548, L487)
- Given duplicated contributions, when they are detected, then duplicate detection prevents repeated credit. (SRS L548)
- Given a maintainer's own contribution, when credit would be awarded, then separation-of-duties requires secondary approval or an automated authoritative event. (SRS L548, L640)
- Given anomalous patterns, when they are flagged, then anomaly review occurs. (SRS L548)

### REC-007 — Badges with criteria, evidence, and revocation state (Should)
As a **member** I want badges that carry documented criteria, evidence, issuer, issue date, and revocation state so that every badge is explainable and trustworthy.
**Acceptance criteria (Given/When/Then):**
- Given a badge type, when it is defined, then its criteria are documented. (SRS L551)
- Given a badge award, when it is issued, then criteria version, evidence, issuer, and issue date are recorded. (SRS L551, L678)
- Given a revoked badge, when its state is reviewed, then the revocation state is recorded. (SRS L551, L678)

### REC-008 — Non-code contributions recognized (Must)
As a **non-code contributor** I want approved design, QA, documentation, translation, security, and research work recognized so that non-code contribution is not disadvantaged against code.
**Acceptance criteria (Given/When/Then):**
- Given approved non-code contributions in design, QA, documentation, translation, security, or research, when recognition is computed, then they are recognized. (SRS L554)
- Given an accepted non-code contribution verified by a maintainer, when it is credited, then it appears on the profile with the correct contribution type and without requiring a Git commit. (SRS L554, L944)
- Given the recognition basis, when official views are built, then accepted impact includes non-code work rather than raw commit volume. (SRS L77, L1028)

---

## Table 7I — Notifications (SRS L557-L572)

### NTF-001 — In-app notifications for material workflow events (Must)
As a **platform user** I want in-app notifications for approvals, review comments, applications, assignments, contribution verification, moderation, and security events so that I learn about workflow events that concern me.
**Acceptance criteria (Given/When/Then):**
- Given an approval, review comment, application, assignment, contribution verification, moderation event, or security event, when it concerns a user, then an in-app notification is provided. (SRS L562)
- Given material workflow events, when notifications are designed, then both in-app and email channels cover them. (SRS L230)

### NTF-002 — User-controlled email categories; mandatory notices locked (Must)
As a **user** I want to control non-essential email categories and digest frequency so that I receive only the email I want, while mandatory security and administrative notices still reach me.
**Acceptance criteria (Given/When/Then):**
- Given non-essential email categories, when a user sets preferences, then they can control the categories and digest frequency. (SRS L565)
- Given mandatory security or administrative notices, when a user attempts to disable them, then they cannot be disabled. (SRS L565)

### NTF-003 — Sensitive-content-safe notification messages (Must)
As a **member** I want notification emails to keep sensitive content out of subject lines and link to authenticated detail so that my notification email itself does not expose private information.
**Acceptance criteria (Given/When/Then):**
- Given a notification email, when it is composed, then the subject line avoids sensitive content. (SRS L568)
- Given a notification whose detail is sensitive, when the user needs it, then the email links to authenticated detail. (SRS L568)

### NTF-004 — Logged, retried delivery without duplicates (Should)
As a **platform operator** I want delivery failures logged and retried without producing duplicate user-visible notifications so that users reliably receive each notification exactly once.
**Acceptance criteria (Given/When/Then):**
- Given a notification delivery failure, when it occurs, then it is logged. (SRS L571)
- Given a failed delivery, when it is retried, then the user eventually receives the notification without duplicate user-visible notifications. (SRS L571)
- Given the email service integration, when failures and bounces occur, then retry and bounce handling apply. (SRS L729)

---

## Table 7J — Administration and moderation (SRS L574-L601)

### ADM-001 — Central Super Admin configuration management (Must)
As a **Super Admin** I want to manage ministries, named publisher accounts, skills/tags, project categories, approved licenses, contribution types, badges, moderation reasons, and feature flags so that platform reference data and behavior stay controlled.
**Acceptance criteria (Given/When/Then):**
- Given a Super Admin, when managing organizations, then ministries and their named publisher accounts can be created and managed. (SRS L579, L306)
- Given taxonomy and reference data (skills/tags, project categories, approved licenses, contribution types, badges, moderation reasons), when they need maintenance, then Super Admin can manage them. (SRS L579)
- Given feature flags, when platform behavior must be toggled, then Super Admin controls them. (SRS L579)
- Given taxonomy changes, when they are made, then they are versioned and do not silently rewrite historical meaning. (SRS L650)

### ADM-002 — Queued review workspace with SLA indicators (Must)
As a **Super Admin** I want to review project submissions and user-generated content using queues, filters, assignment, comments, and service-level indicators so that review work is organized and timely.
**Acceptance criteria (Given/When/Then):**
- Given the review workspace, when a Super Admin opens it, then project submissions and user-generated content are presented in queues. (SRS L582)
- Given a queue, when working an item, then filters, assignment, and comments are available. (SRS L582)
- Given queues, when monitoring workload, then service-level indicators are visible. (SRS L582)
- Given a submitted government project, when review completes, then the decision with review comments is recorded. (SRS L582, L379)

### ADM-003 — Structured reporting for all content types (Must)
As a **user** I want to report a profile, project, blog, link, comment/evidence record, or security concern using structured reasons so that reports land in the right queue with usable context.
**Acceptance criteria (Given/When/Then):**
- Given a reportable object (profile, project, blog, link, or comment/evidence record), when a user reports it, then structured reasons are used. (SRS L585)
- Given a security concern, when it is reported, then the structured report path routes it correctly. (SRS L585)
- Given a report on a malicious blog payload or unsafe file/link, when it is handled, then it reaches the correct moderation queue without exposing evidence publicly. (SRS L946)

### ADM-004 — Graduated moderation actions with reason and audit (Must)
As a **moderator** I want moderation actions covering no action, warning, content restriction, unpublish, account suspension, and escalation — each with reason and audit history — so that responses are proportionate and accountable.
**Acceptance criteria (Given/When/Then):**
- Given a moderation case, when a decision is made, then the available actions include no action, warning, content restriction, unpublish, account suspension, and escalation. (SRS L588)
- Given any moderation action, when it is applied, then a reason and audit history are recorded. (SRS L588, L217)
- Given a choice among actions, when moderating, then the least restrictive action that protects people, the platform, and public trust is used. (SRS L864)

### ADM-005 — Controlled, logged privileged search and export (Must)
As a **Super Admin** I want privileged search and exports to be access-controlled, purpose-limited, logged, and protected from bulk misuse so that administrative data access cannot be abused.
**Acceptance criteria (Given/When/Then):**
- Given privileged search or export functionality, when it is used, then it is access-controlled. (SRS L591)
- Given an authorized privileged search or export, when it runs, then it is purpose-limited and logged. (SRS L591)
- Given potential bulk misuse, when protections are evaluated, then bulk misuse is prevented. (SRS L591)
- Given production data access, when it occurs, then it is restricted to authorized named personnel with privileged access and exports logged. (SRS L841)

### ADM-006 — Operational dashboards for Super Admin (Should)
As a **Super Admin** I want operational dashboards covering active projects, stale projects, response SLA, sync failures, reports, security alerts, and adoption metrics so that I can see and fix operational problems early.
**Acceptance criteria (Given/When/Then):**
- Given the Super Admin dashboards, when viewed, then active projects, stale projects, response SLA, and sync failures are displayed. (SRS L594)
- Given the same dashboards, when viewed, then reports, security alerts, and adoption metrics are displayed. (SRS L594)
- Given a project with no maintainer response within the configured SLA, when the dashboard is refreshed, then it is flagged to the ministry and Super Admin. (SRS L400)

### ADM-007 — Correction, appeal, and reinstatement workflows (Should)
As an **affected user** I want data correction, appeal, and content reinstatement workflows so that moderation and data mistakes have a remedy.
**Acceptance criteria (Given/When/Then):**
- Given an affected user contesting a decision, when they appeal, then an appeal workflow is available. (SRS L597, L646)
- Given incorrect data, when correction is needed, then a data correction workflow is available. (SRS L597)
- Given removed content that should not have been removed, when reinstatement is warranted, then a content reinstatement workflow is available. (SRS L597)
- Given an appeal, when it is processed, then the affected user receives a reason and appeal path unless disclosure would create a security, legal, or safety risk. (SRS L866)

### ADM-008 — Audit records cannot be self-erased (Must)
As an **oversight body** I want no privileged user to be able to erase the audit record of their own action through the application interface so that accountability cannot be covered up.
**Acceptance criteria (Given/When/Then):**
- Given a privileged user, when using the application interface, then they cannot erase the audit record of their own action. (SRS L600)
- Given audit records for privileged actions, when any application-level operation is performed, then they remain tamper-evident. (SRS L600, L814)
- Given audit events, when retention is applied, then they follow the approved records schedule with separate rules for audit/security records. (SRS L708, L1053)

---

## Table 7K — Analytics and reporting (SRS L603-L621)

### ANL-001 — Clean analytics with documented definitions (Must)
As a **data steward** I want analytics built on documented event definitions that exclude authentication secrets, private repository content, and unnecessary personal data so that measurement does not create privacy or security risk.
**Acceptance criteria (Given/When/Then):**
- Given analytics events, when they are defined, then event definitions are documented. (SRS L608)
- Given analytics collection, when it processes data, then authentication secrets, private repository content, and unnecessary personal data are excluded. (SRS L608)
- Given metrics, logs, and alerts, when they are produced, then they identify failure without recording secrets or unnecessary personal data. (SRS L776)

### ANL-002 — Ministry-scoped dashboards (Must)
As a **ministry publisher** I want analytics restricted to my ministry's own projects plus authorized cross-government aggregates so that I get insight without seeing other ministries' internal data.
**Acceptance criteria (Given/When/Then):**
- Given a ministry user, when they view dashboards, then they see only their ministry's own projects. (SRS L611, L214)
- Given cross-government aggregates, when they are displayed to a ministry user, then only authorized aggregates are shown. (SRS L611)
- Given ministry analytics as a data class, when they are handled, then they remain internal: authenticated access with ministry/role boundaries and no public indexing. (SRS L694-L696)

### ANL-003 — Aggregation and suppression in public reporting (Must)
As a **public visitor** I want public reporting to use aggregation and suppression thresholds so that small-group metrics cannot identify individual members.
**Acceptance criteria (Given/When/Then):**
- Given public reports, when they are generated, then aggregation and suppression thresholds are applied. (SRS L614)
- Given small groups in reported data, when thresholds apply, then members cannot be identified. (SRS L614)
- Given inclusion metrics (province, skill area, language preference, experience band), when reported, then they are reported only at privacy-safe aggregation levels. (SRS L123)

### ANL-004 — Self-describing analytics exports (Should)
As an **analyst** I want exports that include source, generation time, filters, field definitions, and a license/usage notice so that exported data is interpretable and usable correctly.
**Acceptance criteria (Given/When/Then):**
- Given an analytics export, when it is generated, then it includes source, generation time, filters, field definitions, and a license/usage notice. (SRS L617)

### ANL-005 — Public read-only project metadata API (Could)
As an **open-data consumer** I want a public read-only API for approved project metadata so that civic tools can reuse the project catalog — but only after proper review.
**Acceptance criteria (Given/When/Then):**
- Given the proposed public read-only API, when it is considered for introduction, then security, rate-limit, privacy, and open-data review happen first. (SRS L620)
- Given the API, when it is available, then it exposes only approved project metadata. (SRS L620)

---

## §8 — Business rules (SRS L623-L650)

### BR-001 — Official identity only on approved government projects
As a **public visitor** I want official ministry identity or Government of Nepal endorsement displayed only on Super Admin-approved government projects so that I know exactly what is official.
**Acceptance criteria (Given/When/Then):**
- Given a government project that has not been approved by Super Admin, when it is displayed, then it shows no official ministry identity or Government of Nepal endorsement. (SRS L628)
- Given a Super Admin-approved ministry project, when it is displayed, then the official-government badge may be shown. (SRS L628, L397)
- Given a personal project or blog, when it is displayed, then it never carries official endorsement. (SRS L628, L644)

### BR-002 — Publication blocked without mandatory ownership and readiness fields
As a **Super Admin** I want publication blocked until a project has a named ministry owner, public maintainer/contact path, approved contribution mode, response expectation, and suitability clearance so that no half-prepared project goes public.
**Acceptance criteria (Given/When/Then):**
- Given a project missing any of a named ministry owner, public maintainer/contact path, approved contribution mode, response expectation, or suitability clearance, when publication is attempted, then it is blocked. (SRS L630)
- Given a project with all required fields, when publication is considered, then the gate is satisfied. (SRS L630)

### BR-003 — Repository readiness baseline before "ready"
As a **ministry publisher** I want the repository readiness baseline enforced before a project is marked ready so that contributors arrive at a well-prepared repository.
**Acceptance criteria (Given/When/Then):**
- Given a government repository, when readiness is assessed, then it must have an approved license, README, CONTRIBUTING guide, code of conduct, security reporting path, issue/task entry point, and branch/review controls. (SRS L632)
- Given a repository missing any required item, when the project is being marked ready, then it cannot be marked ready. (SRS L632)
- Given the readiness checklist, when it is reviewed in detail, then it follows Appendix B items such as labeled starter issues, protected branches, required review, automated tests, and named maintainers with confirmed capacity. (SRS L1084-L1094)

### BR-004 — Self-declared skills are not government-verified credentials
As a **public visitor** I want self-declared skills and education clearly not treated as government-verified credentials so that profile claims are not mistaken for official attestation.
**Acceptance criteria (Given/When/Then):**
- Given a member's self-declared skills and education, when they are displayed, then they are not treated as government-verified credentials. (SRS L634)
- Given no separately approved verification process, when profile data is shown, then no government verification is implied. (SRS L634)

### BR-005 — GitHub graph and DevNepal verified record labeled separately
As a **member** I want the GitHub contribution graph and DevNepal's verified contribution record labeled as different measures so that neither inflates the meaning of the other.
**Acceptance criteria (Given/When/Then):**
- Given a displayed GitHub contribution graph, when it is shown, then it is labeled separately from DevNepal's verified contribution record. (SRS L636)
- Given a profile showing both measures, when they are rendered, then they do not merge into a single measure. (SRS L636, L490)

### BR-006 — Official contribution requires authoritative verification
As a **ministry publisher** I want a contribution to become official only after an authoritative repository event or authorized maintainer acceptance so that self-submission alone never counts as verification.
**Acceptance criteria (Given/When/Then):**
- Given a self-submitted contribution, when no authoritative repository event or authorized maintainer acceptance exists, then it remains evidence, not official verification. (SRS L638)
- Given an authoritative repository event or authorized maintainer acceptance, when it is recorded, then the contribution becomes official. (SRS L638, L1117)
- Given a verified contribution, when it is recorded, then its source, project, contributor mapping, and approval provenance are recorded. (SRS L1131)

### BR-007 — No self-credit without secondary approval
As a **platform operator** I want ministry maintainers barred from awarding credit to themselves without secondary approval or an automated authoritative event so that maintainer power cannot be self-dealing.
**Acceptance criteria (Given/When/Then):**
- Given a ministry maintainer's own contribution, when credit would be awarded by that same maintainer, then secondary approval or an automated authoritative event is required. (SRS L640)
- Given separation-of-duties controls, when recognition is computed, then maintainer self-credit without secondary approval is blocked. (SRS L640, L548)

### BR-008 — Deletion does not erase retained evidence
As an **auditor** I want deleting or unpublishing a project to preserve audit, security, and contribution evidence required by policy so that removal cannot destroy accountability.
**Acceptance criteria (Given/When/Then):**
- Given a project deletion or unpublish action, when it is executed, then audit, security, and contribution evidence that policy requires retaining are not erased. (SRS L642)
- Given the records schedule, when retention is applied, then it covers contribution evidence, audit events, provider events, logs, backups, moderation cases, and security reports. (SRS L708)
- Given backups, when they expire, then they follow the schedule and do not become a method of indefinite retention. (SRS L711)

### BR-009 — No government branding on personal content
As a **public visitor** I want personal projects and personal blogs barred from official seals, logos, or endorsement-implying wording so that community content cannot masquerade as government communication.
**Acceptance criteria (Given/When/Then):**
- Given a personal project or personal blog, when it is created or edited, then official seals, logos, or wording implying government endorsement are prohibited. (SRS L644, L289)
- Given a personal project, when it is displayed, then it is clearly labeled as a community project and never implies Government of Nepal endorsement. (SRS L644, L414)
- Given misleading government branding on personal content, when detected, then it is subject to moderation. (SRS L289, L420)

### BR-010 — Defined reasons and appeal path for enforcement actions
As an **affected user** I want takedowns, suspensions, and leaderboard corrections to use defined reasons and offer an appeal path so that enforcement is accountable — except during urgent security containment.
**Acceptance criteria (Given/When/Then):**
- Given a content takedown, suspension, or leaderboard correction, when it is applied, then a defined reason is used. (SRS L646)
- Given an affected user, when they appeal, then an appeal path exists, except during urgent security containment. (SRS L646)
- Given moderation principles, when reasons are communicated, then the affected user gets a reason and appeal path unless disclosure would create a security, legal, or safety risk. (SRS L866)

### BR-011 — Closed-lifecycle projects accept no new applications
As a **member** I want paused, completed, cancelled, or archived projects to reject new applications while existing records stay visible so that project state is honest and history is preserved.
**Acceptance criteria (Given/When/Then):**
- Given a project in paused, completed, cancelled, or archived state, when a member attempts to apply, then new applications are not accepted. (SRS L648)
- Given a paused project, when it is displayed, then the public status is visible and existing work is retained. (SRS L648, L267)
- Given existing application/participation records, when the project is in one of these states, then they remain visible according to permissions. (SRS L648)

### BR-012 — Versioned taxonomy and scoring rules
As a **product owner** I want taxonomy and scoring-rule changes versioned so that historical records never silently change meaning.
**Acceptance criteria (Given/When/Then):**
- Given a taxonomy or scoring-rule change, when it is made, then it is versioned. (SRS L650)
- Given historical records referencing an earlier version, when a new version is activated, then their historical meaning is not silently rewritten. (SRS L650)
- Given the scoring policy, when it changes, then activation requires product owner approval before taking effect. (SRS L650, L536)

---

## §6.2 — End-to-end contribution workflow (epic) (SRS L279-L287)

### SRS-6.2 — End-to-end contribution workflow (epic)
As a **member** I want a complete contribution path — from ministry preparation through verified recognition to published outcomes — so that my public contribution produces a verified, credited record.
**Acceptance criteria (Given/When/Then):**
- Given a ministry that has prepared a project with maintainers, an approved repository and license, contribution types and tasks, when it submits the listing, then Super Admin verifies suitability and completeness, records review comments, and approves publication. (SRS L280-L281)
- Given a member who discovers the project, when they review prerequisites and contribution instructions, then they can connect GitHub if needed and express interest or start a labeled task, and the ministry/maintainer acknowledges participation and assigns or confirms work where assignment is required. (SRS L282-L283)
- Given a contribution made through GitHub or evidence submitted for approved non-code work, when a webhook or ministry reviewer creates the candidate contribution record, then the maintainer accepts, rejects, or requests clarification with a reason. (SRS L284-L285)
- Given accepted work, when it is recorded, then the member's verified portfolio and project metrics update, and recognition/leaderboard changes remain auditable and reversible. (SRS L286)
- Given project progress or completion, when the ministry publishes outcomes, then progress updates, completion summary, and contributor acknowledgements are published and the listing is archived when appropriate. (SRS L287, L391)
