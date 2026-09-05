# AGENTS.md — Swarm Contract for DevNepal

Every subagent working in this repo MUST read this file completely before writing any code.
This project is built by parallel agents. The contract below is what makes that possible. Violating it corrupts other agents' work.

## Project

DevNepal — Government of Nepal public collaboration and developer-community platform.
Source of truth for requirements: `docs/srs-v0.9.txt` (the SRS, 1,134 lines). Requirement IDs (AUTH-001, GOV-004, GIT-005, BR-007, A1–A10, ...) are the universal mapping key between SRS, user stories, tests, and code.

Stack (decided, see `docs/adr/`): Django 6.1 modular monolith, PostgreSQL in production (SQLite in tests), pytest + factory-boy, server-rendered templates with a Swiss International design system (see `docs/design/`). Bilingual English + Nepali (नेपाली). WCAG 2.2 AA.

## Verify commands (run before you finish, all must pass)

```
uv run pytest                    # full suite
uv run pytest -m unit            # only your layer
uv run ruff check .
uv run ruff format .
```

If your change breaks an existing test, that is a bug in YOUR change unless a coordinator explicitly said otherwise.

## Hard rules

1. **Write only inside your ownership.** The ownership map below defines what you may create/modify. Shared files are LOCKED. If you believe a shared file must change, stop and report the needed change in your final message instead of making it.
2. **Test-first.** For every behavior you build: write the failing test first. Every test's docstring cites the SRS requirement ID it verifies, e.g. `"""GOV-006: material edit returns published project to review."""`. Tests without an SRS citation get deleted in review.
3. **No code comments** unless a docstring is genuinely needed (public API, test docstrings). Code must be self-explanatory.
4. **No comments, credentials, or secrets** in code. Secret-looking values go to settings/env.
5. **i18n**: every user-facing string goes through `django.utils.translation.gettext`/templates `{% trans %}`. Never hardcode UI text. Nepali translations are added to `locale/ne/LC_MESSAGES/django.po` via `uv run manage.py makemessages -l ne` when templates exist.
6. **Unicode normalization**: all user text that becomes searchable or slug-relevant must be NFC-normalized on save (`unicodedata.normalize("NFC", value)`). Devanagari input arrives mixed NFC/NFD across platforms; this is a hard SRS-correctness rule (DSC-003).
7. **Audit**: any privileged/state-changing action (publish, approve, verify, suspend, moderate) calls `apps.audit.services.record_audit(...)`. Audit rows are immutable — never bulk-update/delete `AuditEvent`.
8. **Time**: `USE_TZ=True`. Store UTC aware datetimes; render in `Asia/Kathmandu`.
9. **Migrations**: always run `uv run manage.py makemigrations <yourapp>` after model changes and commit the migration with your change. Never edit an applied migration.
10. **Query discipline**: no N+1 (use `select_related`/`prefetch_related` in views/serializers that list things).

## Ownership map

| Domain | Owns (create/modify freely) | Locked for this domain |
|---|---|---|
| accounts / auth / roles / MFA | `apps/accounts/**`, `tests/acceptance/test_a01*.py` | everything else |
| ministries / publishers | `apps/ministries/**` | everything else |
| projects / lifecycle / applications | `apps/projects/**`, `tests/acceptance/test_a04*.py` | everything else |
| contributions / verification | `apps/contributions/**`, `tests/acceptance/test_a05*.py`, `test_a06*.py` | everything else |
| github sync / webhooks | `apps/github_sync/**`, `tests/acceptance/test_a09*.py` | everything else |
| blogs | `apps/blogs/**` | everything else |
| recognition / badges / leaderboard | `apps/recognition/**` | everything else |
| notifications | `apps/notifications/**` | everything else |
| moderation / reports | `apps/moderation/**`, `tests/acceptance/test_a07*.py` | everything else |
| audit | `apps/audit/**` | everything else |
| taxonomy | `apps/taxonomy/**` | everything else |
| UI shell / design system / i18n | `templates/**`, `static/src/**`, `config/urls.py` (template-level only) | app logic |
| docs | `docs/**` per assigned file | other docs files |

**Permanently locked (coordinator-only):** `pyproject.toml`, `config/settings/**`, `config/urls.py` (route additions need coordinator), `manage.py`, `.github/**`, `AGENTS.md`, `apps/*/apps.py`, the `User` model class inside `apps/accounts/models.py` (the rest of that file is owned by the accounts domain), `apps/audit/models.py`.

## Conventions

- Models: `BigAutoField` pk (default), UUID pks only where the ID is exposed publicly or immutability matters (audit, provider events).
- Every model gets `__str__`. Chooses `Meta.verbose_name` in English; Nepali comes from translations, not the DB.
- Tests live in `apps/<app>/tests/test_*.py` (unit/integration) and `tests/acceptance/` (cross-app SRS scenarios). Replace the placeholder `apps/<app>/tests.py` by deleting it when you add a real tests package.
- Factories: `apps/<app>/tests/factories.py` using factory-boy `DjangoModelFactory`. Never build fixtures JSON.
- Services: business logic goes in `apps/<app>/services.py` (or a `services/` package) — views and admin stay thin. The lifecycle state machine lives in `apps/projects/services.py`.
- Enums: `models.TextChoices` with SRS-aligned names; never bare strings in logic.
- Errors: exceptions must be explicit and typed (`class ProjectLifecycleError(Exception)`); never swallow. Log with context (`logger.exception`) at boundaries.
- Frontend: server-rendered Django templates + the Swiss design system in `static/src/`. No JS framework. Progressive enhancement only. Devanagari webfont: Noto Sans Devanagari; Latin: Inter.

## Definition of done (each agent, every task)

1. New tests written first, citing SRS IDs, now passing.
2. Full `uv run pytest` green. `uv run ruff check .` and `uv run ruff format .` clean.
3. Migrations created if models changed.
4. No file outside ownership touched (`git status` proves it).
5. Final message lists: files created/modified, tests added, SRS IDs covered, anything blocked.
