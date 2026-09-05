# ADR 0001: Django 6.1 modular monolith

Date: 2026-09-03
Status: Accepted

## Context

DevNepal launches as a pilot with a handful of ministries and an invited beta (SRS §15.5),
so realistic load at GA is thousands of members browsing a catalog — not a high-throughput
system. The engineering team is small and partly parallel agents; long-term maintainers are
government teams (NFR-MNT-01, Must: maintainable "without a single vendor or individual").

NFR-SCL-01 asks for independent scaling of public reads, search, background sync,
notifications, and file processing — but it is a *Should*, written as a scaling concern,
not a mandate to decompose the system. Premature microservices would multiply deployment,
auth, observability, and data-consistency surface for load that does not exist, directly
against NFR-MNT-01 and the §2.3 principle of technology neutrality (replaceable, not
maximally distributed).

Core workflows are strongly transactional: project lifecycle transitions must atomically
write review records and audit events (GOV-004, GOV-005), and verified contributions must
update portfolio and recognition together (BR-006, REC-001). Cross-service sagas would add
failure modes to exactly the paths the SRS demands be auditable and atomic.

## Decision

Build a single Django 6.1 deployable (modular monolith):

- Bounded contexts as Django apps under `apps/` (accounts, ministries, projects,
  contributions, github_sync, blogs, recognition, notifications, moderation, audit,
  taxonomy), each with a `services.py` layer holding business logic; views and admin stay
  thin.
- Cross-app coupling goes through service functions and explicit models, never through
  another app's internals; the ownership map in AGENTS.md enforces boundaries.
- The project lifecycle state machine lives in `apps/projects/services.py` (GOV-004).
- Audit writes participate in the same transaction as the privileged action (SEC-008).
- Scaling strategy: stateless instances behind a load balancer, PostgreSQL as the single
  system of record, and out-of-band workers for webhook processing, sync, notifications,
  and file scanning (NFR-SCL-01 satisfied by tier separation, not service decomposition).

## Consequences

Positive: one migration path, transactional integrity for lifecycle + audit, one place for
correlation IDs (NFR-OBS-01), fast deterministic tests, simplest possible path to
government-controlled hosting (NFR-PORT-01), and the smallest cognitive load for new
maintainers (NFR-MNT-01).

Negative/risk: Django does not enforce app boundaries — the services-layer convention and
review discipline must hold, or the monolith degrades into a tangle. Independent scaling
is coarser than microservices; if a subsystem (e.g., search) later proves a need, extract
it then (see ADR 0009), with the monolith as the default.

Relevant SRS: §2.3, §5.1, NFR-SCL-01, NFR-MNT-01, NFR-PORT-01, NFR-AVL-02, NFR-OBS-01,
GOV-004, GOV-005, SEC-008.
