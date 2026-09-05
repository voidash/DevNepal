# DevNepal

Public collaboration and developer-community platform for the Government of Nepal —
Office of the Prime Minister and Council of Ministers, Digital Collaboration Initiative.

DevNepal is a trusted registry and collaboration layer, not a replacement for GitHub.
Source code, branches, issues, pull requests, CI, and code review stay in approved
repositories. DevNepal provides identity, project discovery, structured project
metadata, applications and participation records, verified contribution events,
community content, recognition, governance, and reporting.

## Repository contents

| Path | Description |
| --- | --- |
| [`docs/DevNepal_Requirements_and_Scope_v0.9.docx`](docs/DevNepal_Requirements_and_Scope_v0.9.docx) | Software Requirements Specification and Project Scope, v0.9 (2 Sep 2026) — draft for stakeholder validation |
| [`prototype/index.html`](prototype/index.html) | Self-contained clickable prototype (single bundled HTML file, no build step) |

## Viewing the prototype

Open `prototype/index.html` directly in a browser, or serve it locally:

```
python3 -m http.server 8000
```

then visit http://localhost:8000/prototype/

## Running the Django application

The prototype flows are implemented in Django 6 with Python 3.12. From the
repository root:

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py seed_prototype_demo
uv run python manage.py runserver 0.0.0.0:9999
```

Open <http://127.0.0.1:9999/en/>. `seed_prototype_demo` is idempotent: rerunning
it updates the source-of-truth prototype records without duplicating them. The
default development configuration uses
SQLite; setting `POSTGRES_HOST` switches to PostgreSQL and reads the standard
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_PORT`
variables.

GitHub sign-in and repository integration are enabled only when their credentials
are supplied through the process environment. Keep these values in local or
managed secret storage; never commit them or the development SQLite database.

```bash
export GITHUB_CLIENT_ID=...
export GITHUB_CLIENT_SECRET=...
export GITHUB_APP_ID=...
export GITHUB_APP_PRIVATE_KEY=...
export GITHUB_WEBHOOK_SECRET=...
uv run python manage.py runserver 0.0.0.0:9999
```

The OAuth App authorization callback URL must target
`http://127.0.0.1:9999/en/accounts/github/login/callback/` for local development,
or the same path on the deployed HTTPS origin. GitHub login remains unavailable
when the OAuth credentials are absent.

Run the complete verification suite with:

```bash
uv run pytest
uv run ruff check .
uv run python manage.py makemigrations --check --dry-run
node static/src/design_check.mjs
```

The cross-role source-of-truth journey is executable in
`tests/flows/test_prototype_main_flow.py`: ministry draft, PMO review and
approval, public discovery, member application, publisher decision,
contribution evidence, maintainer verification, recognition, progress update,
and project completion.

## Status

The requirements document is **v0.9, draft for stakeholder validation**. It does not by
itself approve policy, procurement, data processing, hosting, open-source licensing, or
public release of any government system. Validation is pending across business
ownership, ministry operating model, security and hosting, privacy and legal, and
community governance.

## Roles

Three authorization roles are defined: **Super Admin**, **Ministry Publisher**, and
**Member**. Public visitors are an unauthenticated access state, not an administrative
role. Ministries are represented by an organization record with named officer accounts —
shared ministry credentials are not acceptable.
