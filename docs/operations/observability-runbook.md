# Observability Runbook

**Requirements:** NFR-OBS-01, NFR-AVL-01, NFR-AVL-02, SRS §16.2

**Status:** Local/dev stack implemented and verified (docs/adr/0010-observability.md). Not
yet deployed to any managed environment; no Alertmanager routing or on-call roster exists.

## What exists

- `GET /healthz` — liveness, no dependency checks.
- `GET /readyz` — readiness; 503 if the database is unreachable.
- `GET /metrics` — Prometheus exposition. Requires `Authorization: Bearer
  <OBSERVABILITY_METRICS_TOKEN>`; returns 403 if the token is unset or wrong.
- Every response carries a server-minted `X-Correlation-ID` and W3C `traceparent`; every
  request and instrumented command emits a completed OpenTelemetry span to the protected JSON
  log pipeline. Set `OBSERVABILITY_OTLP_TRACES_ENDPOINT` to export spans to an approved OTLP
  collector. Only an explicitly trusted proxy may supply inbound correlation/trace context.
- Every log line is one JSON object with correlation and trace fields; token/secret-shaped text
  is redacted and only allowlisted structured fields are emitted.
- `apps.observability.models.JobRun` records one row per run of `process_github_events`,
  `reconcile_repositories`, `send_pending_notifications`, `publish_scheduled`,
  `flag_stale_projects`, and `purge_observability_job_runs`, visible read-only in
  `/admin/observability/jobrun/`. Completed history is retained for 30 days by default;
  schedule `purge_observability_job_runs` daily.
- Every request's database queries are counted, timed, and checked for errors
  (`db_queries_total`, `db_query_duration_seconds`, `db_queries_per_request`), independent
  of `DEBUG`. `db_pending_migrations` reports unapplied migrations on the running process.

## Running the dashboards locally

```sh
export OBSERVABILITY_METRICS_TOKEN="$(openssl rand -hex 32)"
export GRAFANA_ADMIN_PASSWORD="$(openssl rand -base64 24)"
token_file="$(mktemp)"
printf '%s' "$OBSERVABILITY_METRICS_TOKEN" > "$token_file"
export OBSERVABILITY_METRICS_TOKEN_FILE="$token_file"
export DJANGO_SETTINGS_MODULE=config.settings.dev
uv run python manage.py runserver 0.0.0.0:8000

cd ops/observability
docker compose up -d
```

Prometheus: http://localhost:9090 (Status → Targets should show `django` as `up`). If
port 8000 is already in use by another `runserver` on this machine, run this one on a
free port instead and update the target in `prometheus/prometheus.yml` to match — revert
it to `8000` once that's no longer needed, since that's the port the rest of this doc and
`docker-compose.yml`'s default assume.
Grafana: http://localhost:3000 (admin / the required `GRAFANA_ADMIN_PASSWORD`). Prometheus
and Grafana bind to localhost only. Remove the temporary metrics-token file after stopping
the stack.
Five dashboards are provisioned under the "DevNepal" folder:

| Dashboard | Answers |
| --- | --- |
| HTTP (RED) | Is the site serving requests, at what latency, with what error rate? |
| Database & Maintenance | Is the database fast and error-free, is a view issuing an N+1 query pattern, are there unapplied migrations? |
| Jobs & Maintenance | Are the six recurring commands still running, is any operational backlog growing, are there unapplied migrations? |
| Availability | Are we inside the NFR-AVL-01 99.5% error budget, and what does the ops-panel backlog look like right now? |
| Executive Overview | Non-engineer view: is the platform up, reliable, and growing, and is anything stuck — no metric jargon. |

`docker.internal` DNS resolution (used by the Prometheus scrape target) requires
`host.docker.internal` to be reachable from the Docker daemon in use — verified here against
Docker Desktop / colima on macOS. A Linux Docker host needs `extra_hosts:
["host.docker.internal:host-gateway"]`, which `docker-compose.yml` already sets.

## Reading the Jobs & Maintenance dashboard

`background_job_seconds_since_last_success` is the primary worker-monitoring signal: a
command that stops running goes stale and this number climbs without bound. It reports
`+Inf` — not "no data" — until that command has succeeded at least once, so
`BackgroundJobStale` fires on a fresh environment whose cron was never wired up, rather
than staying silently green forever. `background_job_last_run_success` is `NaN` (no data)
in that same never-run state, since there is no run yet to report success or failure of.
`db_pending_migrations` on this dashboard and the Database dashboard is the same series —
non-zero means `uv run manage.py migrate` needs to run against that environment.

## Reading the Database & Maintenance dashboard

"Queries per request (p95) — N+1 risk" is the one panel worth checking after any change to
a list view or template that iterates over related objects: a step change upward usually
means a `select_related`/`prefetch_related` was missed. Query error rate should sit at
0% outside a deploy or an outage; anything else means SQL is failing (bad migration state,
a constraint violation, a dropped connection) that a 200-status HTTP response won't reveal.

## Known gaps before this can be evidence for the production-readiness checklist

1. No Alertmanager or paging is configured — `ops/observability/prometheus/alerts.yml`
   defines rules only. See docs/adr/0010-observability.md.
2. Job-staleness thresholds are a generic 24h default, not tuned to each command's real
   operational cadence.
3. Behind a multi-process production WSGI server, `PROMETHEUS_MULTIPROC_DIR` must be set
   and the gunicorn `child_exit` hook wired (see `prometheus_client` docs) or per-process
   counters will undercount. Not exercised here — this repo has no WSGI deployment config.
4. The 99.5% monthly availability measurement plan (NFR-AVL-01) still needs an owner and a
   long-window (30 day+) recording rule once real production traffic exists; the
   Availability dashboard's daily ratio panel is a starting point, not that plan.
