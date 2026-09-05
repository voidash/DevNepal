# Backup And Restore Runbook

**Requirements:** A10, NFR-DR-01, SEC-002, SEC-013, NFR-PORT-01, SRS §§9.3 and 16.2

**Status:** Draft. Do not claim A10 completion until a timed staging exercise is recorded and
the PMO has approved the final RPO and RTO.

## Objective And Scope

The launch baseline proposed by the SRS is RPO <= 24 hours and RTO <= 8 hours. PostgreSQL is
the production system of record (ADR 0002). The backup set must also include private uploaded
objects referenced by the database, deployment configuration, and the recovery instructions.
It must not contain separately stored secrets unless the approved secret-management recovery
process explicitly requires an encrypted escrow copy.

Production restoration is a last resort. Perform drills only in an isolated recovery environment
and restore production only after the incident commander has authorized it.

## External Infrastructure Prerequisites

These are required before this runbook is executable in staging or production. They are not
implemented by this repository.

| Required input | Evidence needed |
| --- | --- |
| Approved PostgreSQL service, named database owner, and private network access | Service record and named break-glass operators |
| Encrypted automated database backups at least every 24 hours, including transaction-log recovery if used | Scheduler configuration and three most recent backup manifests |
| Encrypted, versioned backup or replication for private object storage | Object-store policy and a manifest covering attachments, contribution evidence, avatars, and badge icons |
| Approved key-management and secret-recovery process | Key owner, recovery authorization, and rotation procedure; secrets must never be put in the backup evidence record |
| Isolated recovery PostgreSQL instance and object-storage namespace | Access test showing the recovery environment cannot serve public traffic |
| Approved retention schedule for backups, logs, provider events, audit records, and security reports | Records/legal/privacy approval required by SRS §9.3 |
| Monitoring that timestamps backup completion and alerts on failure or age beyond the RPO | Alert test and on-call owner |

The current settings select PostgreSQL when `POSTGRES_HOST` is set and use `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, and optional `POSTGRES_PORT`. The deployment must provide
these values through approved secret management, not shell history or checked-in files.

## Backup Procedure

1. Record the incident or change ticket, operator, UTC start time, source database identifier,
   backup-object identifier, encryption-key reference, and the most recent successful backup
   completion time.
2. Confirm that the backup target is encrypted, access-controlled, immutable or versioned for
   the approved retention period, and outside the failure domain of the source database.
3. Take a PostgreSQL custom-format logical backup or invoke the approved managed-service backup.
   A logical backup command suitable for the configured PostgreSQL environment is:

```sh
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host="$POSTGRES_HOST" --port="${POSTGRES_PORT:-5432}" --username="$POSTGRES_USER" --format=custom --no-owner --no-privileges --file="$BACKUP_FILE" "$POSTGRES_DB"
```

4. Create a protected manifest containing the backup object URI or immutable version ID, SHA-256
   checksum, PostgreSQL version, database migration version, UTC completion time, and object-store
   backup version. Do not record connection strings, credentials, tokens, webhook bodies, or
   personal data in the manifest.
5. Verify the backup can be listed and its checksum matches. Confirm the corresponding private
   object backup contains all prefixes in use: `project-attachments/`,
   `contribution-evidence/`, member-avatar objects, and badge-icon objects.
6. Alert the on-call owner immediately if the elapsed time since the last successful complete
   backup exceeds the approved RPO.

## Restore Drill Procedure

1. Open a drill ticket. Record the target RPO/RTO, planned start, drill owner, observer, backup
   identifier, recovery database name, recovery object namespace, and explicit confirmation that
   neither target can serve production traffic.
2. Select a backup no older than the approved RPO. Calculate and record its age before restoring.
   If it exceeds the target, stop and record a failed RPO result.
3. Restore the database into an empty recovery database. `createdb` and `pg_restore` below are
   executable PostgreSQL client commands; run them only against the isolated recovery target.

```sh
createdb --host="$RECOVERY_POSTGRES_HOST" --port="${RECOVERY_POSTGRES_PORT:-5432}" --username="$RECOVERY_POSTGRES_USER" "$RECOVERY_DB"
PGPASSWORD="$RECOVERY_POSTGRES_PASSWORD" pg_restore --host="$RECOVERY_POSTGRES_HOST" --port="${RECOVERY_POSTGRES_PORT:-5432}" --username="$RECOVERY_POSTGRES_USER" --dbname="$RECOVERY_DB" --no-owner --no-privileges "$BACKUP_FILE"
```

4. Restore the selected object-store version into the isolated namespace. This action is
   provider-specific and remains an external-infrastructure prerequisite; preserve object keys
   exactly so Django `FileField` references remain valid.
5. Point an isolated application process at the recovery database and object namespace. Apply no
   new migrations. Verify the restored schema is current with:

```sh
POSTGRES_HOST="$RECOVERY_POSTGRES_HOST" POSTGRES_PORT="${RECOVERY_POSTGRES_PORT:-5432}" POSTGRES_DB="$RECOVERY_DB" POSTGRES_USER="$RECOVERY_POSTGRES_USER" POSTGRES_PASSWORD="$RECOVERY_POSTGRES_PASSWORD" uv run manage.py migrate --plan
```

6. Capture counts and timestamps from the source manifest and compare them with the restored
   database. At minimum, compare migration rows, audit events, provider events, projects, and
   contribution records. Execute read-only checks such as:

```sh
PGPASSWORD="$RECOVERY_POSTGRES_PASSWORD" psql --host="$RECOVERY_POSTGRES_HOST" --port="${RECOVERY_POSTGRES_PORT:-5432}" --username="$RECOVERY_POSTGRES_USER" --dbname="$RECOVERY_DB" --tuples-only --command="SELECT COUNT(*) FROM django_migrations;"
PGPASSWORD="$RECOVERY_POSTGRES_PASSWORD" psql --host="$RECOVERY_POSTGRES_HOST" --port="${RECOVERY_POSTGRES_PORT:-5432}" --username="$RECOVERY_POSTGRES_USER" --dbname="$RECOVERY_DB" --tuples-only --command="SELECT COUNT(*) FROM audit_auditevent;"
PGPASSWORD="$RECOVERY_POSTGRES_PASSWORD" psql --host="$RECOVERY_POSTGRES_HOST" --port="${RECOVERY_POSTGRES_PORT:-5432}" --username="$RECOVERY_POSTGRES_USER" --dbname="$RECOVERY_DB" --tuples-only --command="SELECT COUNT(*) FROM github_sync_providerevent;"
```

7. Verify a sample of each private-object class resolves only from the recovery namespace and
   remains non-public. Verify audit rows are readable but no recovery activity has modified or
   deleted historical audit records (ADR 0004).
8. Run repository-level executable checks against the restored application revision. These do not
   prove the infrastructure restore, but they prove the checked-out application test contract:

```sh
uv run pytest
uv run pytest -m unit
uv run ruff check .
uv run ruff format --check .
```

9. Stop the timer only when the recovery environment has passed the recorded data-integrity
   checks and the incident commander confirms the service could be safely handed back. Record
   actual RPO, actual RTO, deviations, remediation owner, and due date. A10 passes only when the
   approved targets are met in the documented exercise.

## Evidence Record

Store the drill record in the approved restricted operations repository or ticketing system:

| Field | Required value |
| --- | --- |
| Drill date and UTC start/end | Actual timestamps and calculated RTO |
| Backup and object version identifiers | Immutable identifiers only, never credentials |
| Backup age | Calculated RPO and pass/fail against approved target |
| Restore environment | Isolated target identifier and operator confirmation |
| Integrity results | Source and restored counts, file-sample results, migration plan output |
| Security controls | Encryption, access-control, and deletion confirmation |
| Sign-off | Drill owner, security/operations observer, and PMO approver |
| Follow-up | Defects, risk acceptance if any, owner, and due date |

## Failure Conditions

Treat the drill as failed and escalate through the incident runbook if a backup is missing,
cannot be decrypted, exceeds the RPO, cannot restore, lacks required objects, exposes objects
publicly, changes audit history, or cannot meet the RTO. Do not substitute a successful local
SQLite test run for a PostgreSQL and object-store restoration exercise.
