# DevNepal Decision Log

Coordinator rulings on SRS ambiguities surfaced by swarm agents. Status `default` = working decision by coordinator, revisitable by the product owner; SRS v1.0 should incorporate these.

| # | SRS ref | Ambiguity | Ruling | Status |
|---|---|---|---|---|
| D1 | AUTH-002 (L300) | Behavior when disconnecting GitHub while it is the sole sign-in provider | Disconnect is blocked until the member adds another sign-in provider or a verified email+password fallback. Fail-safe over convenience. | default |
| D2 | GOV-006 (L382) | Material edit: "return to review OR require Super Admin approval" — which path? | Always return to `IN_REVIEW`. Super Admin may then fast-track approval; there is exactly one re-review path, no bypass. Keeps the state machine single-pathed. | default |
| D3 | AUTH-005 (L309) | "Verified official contact information" mechanism | Email round-trip to an address on the ministry's official domain, plus Super Admin attestation recorded in audit at provisioning time. | default |
| D4 | MEM-004 (L341) | Skill suggestions workflow | Suggestions queue for Super Admin approval (`SkillSuggestion` → `Skill`). No auto-creation. | default |
| D5 | GOV-012 (L400) | Default maintainer response SLA | 5 business days first response, configurable via settings (`DEFAULT_RESPONSE_SLA_DAYS`). Stale > 2× SLA flags to ministry + Super Admin. | default |
| D6 | GIT-005/012 (L505, L500) | Webhook deduplication key composition | `(provider, delivery_id)` unique — `X-GitHub-Delivery` GUID; plus `(provider, event_id)` unique as second key. Both checked; first hit wins, second is recorded as duplicate evidence. | default |
| D7 | GIT-007 vs GIT-008 (L487-493) | "Qualifying commits to default branch" undefined, tension with no-commit-credit | MVP verified events: PR merged, issue closed-as-completed, approved review, release published. Raw/direct commits generate NO verified contributions. Qualifying-commit support deferred to Phase 2 with explicit policy. | default |
| D8 | REC-003 (L539) | Rolling leaderboard window default | 90 days, configurable. | default |
| D9 | BR-007 (L641) | Secondary approval actor for maintainer self-credit | Any other Ministry Publisher of the same ministry OR a Super Admin. Automated authoritative events (D7 list) satisfy this automatically. | default |
| D10 | ANL-003 (L615) | Suppression threshold for small-group aggregation | Minimum group size 5; groups smaller than 5 are suppressed in public reporting. | default |

Additional coordinator rulings:

| # | Topic | Ruling |
|---|---|---|
| D11 | Facebook sign-in (AUTH-001) | Excluded from MVP and from configuration surface entirely. Google + GitHub only. Rationale: privacy-review burden vs. zero marginal reach. |
| D12 | Leaderboard scope | No public leaderboard in MVP. Verified contributions render on member profiles only. Recognition views (REC-003) ship behind a disabled feature flag. |
| D13 | Blogs scope (BLG tables) | Full Markdown editor deferred to Phase 2. MVP allows external-article link listings (BLG-005 subset) only. Safe-render pipeline ships with the Phase 2 editor. |
| D14 | AUTH-004 (re-grant) | Re-granting a revoked publisher creates a NEW assignment row; revoked rows are retained as history. DB constraint becomes partial: unique (user, ministry) among non-revoked statuses. Implementation pending — ministries follow-up. |
| D15 | DSC-003 (Devanagari nukta) | NFC does not unify precomposed nukta forms (U+0958–095F) with decomposed equivalents (composition-excluded in Unicode). Accepted limitation: NFC everywhere (input AND query sides identically), so equivalence holds for round-trip cases; nukta variants remain distinct terms. Do not use NFKC. |
