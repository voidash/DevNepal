# ADR 0010: Observability — correlation IDs, metrics, health checks, dashboards

Date: 2026-09-05
Status: Accepted

## Context

NFR-OBS-01 (Must) requires every request and background job to carry a correlation ID and
requires metrics, logs, traces, and alerts to identify failure without recording secrets or
unnecessary personal data. NFR-AVL-02 (Must) requires health checks and graceful
degradation. The production-readiness evidence checklist's "Observability and
availability" gate (docs/operations/production-readiness-evidence-checklist.md) lists
correlation IDs, dashboards, alert routing, health checks, and worker monitoring as
required evidence, and the checklist's "Known External Blocks" section recorded that no
monitoring stack existed in this repository at all before this change.

Before this change: no `LOGGING` configuration existed (Django's default logging was
active), no `/metrics` or health-check endpoints existed, and every call site that passed
a `correlation_id` to `apps.audit.services.record_audit` minted its own `uuid.uuid4().hex`
independently — request handling, the audit row it produced, and any logs emitted during
that request shared no common identifier. Background work runs as cron-invoked Django
management commands (`process_github_events`, `reconcile_repositories`,
`send_pending_notifications`, `publish_scheduled`, `flag_stale_projects`), not long-lived
workers, so a pull-based Prometheus scrape can never observe one directly while it runs.

## Decision

- **`apps.observability`** (new app) owns correlation IDs, OpenTelemetry traces, structured
  logging, Prometheus metrics, health checks, and job-run tracking. It is the one place cross-cutting
  observability code lives, rather than duplicating it per domain app.
- **Correlation ID**: `apps.observability.context` holds a `ContextVar`.
  `CorrelationIdMiddleware` (first in `MIDDLEWARE`, so it also covers redirects issued by
  `SecurityMiddleware`) mints an ID for every public request. It accepts a syntactically valid
  inbound `X-Correlation-ID` only when `OBSERVABILITY_TRUST_INBOUND_CORRELATION_IDS=true`,
  which is for an explicitly trusted internal proxy; public callers cannot choose values that
  enter audit rows or logs. The ID is echoed on the response and reset at the end of the
  request. `InstrumentedCommand` does the equivalent for management commands: one
  correlation ID per command run.
  `apps.audit.services.record_audit` now falls back to the ambient correlation ID instead
  of an empty string when a caller doesn't pass one explicitly, so audit rows created
  during a request or job are actually linked to it (NFR-OBS-01-U1). Two call sites in
  `apps.accounts.services` (`account.data_export`, `account.deletion_requested` /
  `account.anonymized`) that previously minted their own throwaway UUID now use the
  ambient ID for the same reason. `apps.github_sync.services` keeps minting its own
  per-delivery-event correlation ID deliberately: a webhook delivery and its later
  asynchronous processing by `process_github_events` are different units of work, and the
  per-event ID is what `ProviderEvent.correlation_id` already exists to carry end to end
  across the outage/replay runbook.
- **Traces**: OpenTelemetry SDK creates a W3C trace for every HTTP request and instrumented
  management command. Completed spans emit safe trace IDs, parent span IDs, names, statuses,
  and durations to the protected JSON log pipeline; setting
  `OBSERVABILITY_OTLP_TRACES_ENDPOINT` additionally exports the same spans to an approved
  OTLP collector. Public trace context is minted server-side; inbound trace context is only
  extracted when the trusted-proxy setting above is enabled. Responses carry `traceparent`.
- **Logging**: `LOGGING` in `config/settings/base.py` emits single-line JSON via
  `apps.observability.logging.JsonFormatter`, with `CorrelationIdFilter` attaching the
  ambient ID and `SecretScrubbingFilter` (`apps.observability.scrub`) redacting
  token/password/secret/Authorization-shaped substrings before they reach the log sink
  (NFR-OBS-01-U2). This is a stdlib `logging.Formatter`, not a third-party structured
  logging library. Allowlisted operational fields such as command, error code, duration, and
  trace IDs are retained; arbitrary `extra` fields are not serialized. `django.server` uses
  the same protected handler rather than Django's default request-log handler.
- **Metrics**: `prometheus_client` (the only new dependency) backs `/metrics`. HTTP RED
  metrics (`http_requests_total`, `http_request_duration_seconds`,
  `http_requests_in_progress`) are recorded by the same middleware, labeled by
  `resolver_match.route` (the URL pattern, e.g. `en/projects/<slug:slug>/`) rather than the
  raw path or any user/session identifier, to keep cardinality bounded and avoid recording
  personal data in a metric label. Every view wrapped in `i18n_patterns` therefore
  produces one label series per language (`en/...` and `ne/...`) rather than one series
  covering both — still bounded (cardinality scales with routes × 2 languages, not with
  requests), and arguably useful on a bilingual platform, but worth knowing before reading
  the "by route" panels on the HTTP dashboard. Job metrics (`background_job_runs_total`,
  `background_job_duration_seconds`) are recorded by `InstrumentedCommand`. Gauges that
  reflect current database state — `background_job_seconds_since_last_success`,
  `background_job_last_run_success`, and `queue_depth` (github_sync pending events,
  notification backlog, aging moderation cases, stale projects, 24h audit
  failures/denials) — are computed at scrape time in `apps.observability.metrics`, reusing
  the same domain models `apps.audit.ops.build_ops_panels` already queries for the
  Super Admin ops dashboard, so the two views of the same operational state cannot drift
  out of sync by definition. `/metrics` requires a bearer token
  (`OBSERVABILITY_METRICS_TOKEN`, compared with `hmac.compare_digest`) and fails closed
  (403) if the token is unset, since this is a public government site and the endpoint
  would otherwise leak route inventory and error rates to anyone. The distinct
  `http_user_requests_total` series excludes health, readiness, and scrape requests, and
  is the numerator and denominator for every user-facing availability/error-rate SLI.
- **Database metrics**: `DatabaseMetricsMiddleware` wraps every SQL execution on the
  default connection via Django's `connection.execute_wrapper()` hook (independent of
  `DEBUG`, unlike `connection.queries`), recording `db_queries_total` (by outcome),
  `db_query_duration_seconds`, and `db_queries_per_request` — the last one is a direct N+1
  detector: a rising p95 on the Database dashboard means a view started issuing an
  unbounded number of queries. `db_pending_migrations` is computed at scrape time from
  `MigrationExecutor.migration_plan()` against the default connection — the concrete,
  checkable "is there a maintenance task outstanding" signal.
- **Health checks**: `/healthz` (liveness — no dependency checks) and `/readyz`
  (readiness — one `SELECT 1`, returning 503 with no error detail on failure) satisfy
  NFR-AVL-02. Both, and `/metrics`, are registered outside `i18n_patterns` in
  `config/urls.py` — a load balancer or Prometheus should never need a language prefix to
  reach a probe.
- **Worker monitoring**: `apps.observability.models.JobRun` persists one row per command
  run (command name, correlation ID, status, timestamps, and an allowlisted error code).
  Raw exception text is never persisted. `purge_observability_job_runs`, scheduled daily,
  deletes completed rows older than `OBSERVABILITY_JOB_RUN_RETENTION_DAYS` (30 by default)
  while retaining running rows. This is the
  only way to see a cron-style command's outcome between runs; it also backs the two gauge
  families above. Read-only in the admin.
- **Recurring commands** (`process_github_events`, `reconcile_repositories`,
  `send_pending_notifications`, `publish_scheduled`, `flag_stale_projects`) now subclass
  `apps.observability.commands.InstrumentedCommand` instead of Django's `BaseCommand`;
  `handle()` is unchanged. `bootstrap_super_admin` is a one-time interactive bootstrap, not
  a recurring job, and is left on `BaseCommand`.
- **Deployable stack**: `ops/observability/` holds a `docker-compose.yml` (Prometheus +
  Grafana, not part of the application's own deployment — this repo has no
  infrastructure-as-code yet, see ADR 0001/0002), Prometheus scrape config and alert rules,
  and Grafana provisioning for a datasource plus five dashboards checked into
  `ops/observability/grafana/dashboards/`:
  - **HTTP (RED)**: request rate, latency percentiles, and error rate by route — the
    engineer's view of "is the site fast and correct."
  - **Database & Maintenance**: query rate/latency/error-rate, the N+1 detector, and
    pending migrations — "is the database healthy, is there maintenance outstanding."
  - **Jobs & Maintenance**: per-command staleness/success and operational queue depths,
    plus the same pending-migrations panel.
  - **Availability**: uptime, 30-day error budget against the 99.5% NFR-AVL-01 target.
  - **Executive Overview**: a non-engineer view — system status, uptime, reliability,
    average response time, a 30-day reliability trend, and the operational backlogs in
    plain English, deliberately excluding route/method/percentile breakdowns.
  This was run locally against a live `runserver` process during development of this
  change and confirmed to show real series pulled from `/metrics` — this is not
  hand-authored JSON that has never been loaded into Grafana. One real bug was caught this
  way and fixed in every dashboard that had it: `sum()` over zero matching series (e.g. zero
  5xx responses ever) returns no data, not zero, so an error-rate expression without
  `or vector(0)` renders a blank panel on a fully healthy system — the worst failure mode
  for a panel meant to reassure someone that things are fine.

## Consequences

Positive: request handling, its traces, logs, and any audit rows it produces now share one
correlation ID (NFR-OBS-01-U1); secrets/tokens are redacted before they reach a log sink
(NFR-OBS-01-U2); dashboards exist and are backed by real metrics rather than a mockup;
worker monitoring exists where none did; database query health (rate, latency, N+1 risk,
error rate) and pending migrations — the concrete "maintenance tools" signal — are now
observable per-request rather than invisible until something breaks in production.

Negative/risk, explicitly deferred:

- **Multiprocess gunicorn**: `prometheus_client`'s default registry is per-process. Behind
  a multi-worker gunicorn, `/metrics` on one worker will not reflect counters incremented
  on another unless `PROMETHEUS_MULTIPROC_DIR` is set (the code already branches on this
  env var and uses `prometheus_client.multiprocess` when set) and gunicorn's
  `child_exit` hook is wired per the `prometheus_client` documentation. This repo has no
  WSGI/deployment configuration yet (see the evidence checklist's "Known External Blocks");
  whoever adds one must wire this or the dashboards will silently undercount.
- **Alert routing**: `ops/observability/prometheus/alerts.yml` defines alerting *rules*.
  No Alertmanager or on-call routing is configured — that depends on the operational owner
  roster and paging tool, neither approved yet per the evidence checklist.
- **Job-staleness thresholds** in `alerts.yml` use a generic 24h default for all five
  commands. Tune per command once each command's actual cron cadence is fixed
  operationally; the alert file says so inline.
- `OBSERVABILITY_METRICS_TOKEN` is a shared bearer token, not per-caller auth. Acceptable
  for a single internal Prometheus scraper; revisit if multiple untrusted scrapers need
  access.

Relevant SRS: NFR-OBS-01, NFR-OBS-01-U1, NFR-OBS-01-U2, NFR-AVL-01, NFR-AVL-02, NFR-MNT-01.
