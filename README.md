# Community Forest Management System

Geospatial forest management for community forests in Nepal — boundary
digitisation, block and compartment structuring, tree inventory, sampling
design, household survey, and operational-plan generation, bilingual in Nepali
and English.

> **Stub (H1.1).** Enough to run, test and orient. The full README — architecture,
> contribution guide, deployment — is task 6.7 in [`HARDENING_PLAN.md`](HARDENING_PLAN.md).

---

## Supported stack

These versions are not suggestions. Dev, CI and Compose must agree; when they
did not, the backend suite was green on one machine and 317-tests-red on
another, and "does it work?" had no answer. The backend logs both at startup and
warns on a mismatch.

| | Version | Declared in |
|---|---|---|
| Python | **3.11** | [`.python-version`](.python-version) |
| PostgreSQL | **16** | `docker-compose.yml`, `ci.yml` |
| PostGIS | **3.4** | as above |
| Node | **20** | `ci.yml` |

## Running it

The container stack is the supported path. Open the repo in a devcontainer, or:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

| Service | URL |
|---|---|
| Backend | http://localhost:8001 · docs at `/docs` |
| Frontend | http://localhost:3001 |
| Database | `postgresql://postgres@localhost:5432/cf_db` |

`start_all.bat` and `start_all_with_redis.bat` run the stack against a local
interpreter instead. They still work, but they are the path that produced the
drift above — prefer Compose.

## Testing

```bash
cd backend && pytest tests/          # 1,297 tests
cd frontend && npx vitest run
cd frontend && npx playwright test   # needs the stack running
```

The backend harness builds its schema by running the **real migrations** against
a scratch database, so tests and production cannot silently diverge. One
consequence: two concurrent `pytest` runs destroy each other, because the
harness drops and recreates a fixed-name `cf_db_test WITH (FORCE)`. Run one at a
time until task 1.7 makes the name per-worker.

## Database

```bash
cd backend
alembic upgrade head      # builds from an empty database
alembic downgrade base    # and reverses cleanly
alembic check             # model/migration drift
```

`alembic/env.py` takes its target from `DATABASE_URL`. If that is unset it falls
back to `alembic.ini`, which points at a local `cf_db` — always set it
explicitly when the target is not your local database.

## Where things are

| | |
|---|---|
| [`industry_grade_report.md`](industry_grade_report.md) | Readiness audit — 70 verified findings, evidence, severity |
| [`HARDENING_PLAN.md`](HARDENING_PLAN.md) | How each finding gets closed |
| [`HARDENING_TRACKER.md`](HARDENING_TRACKER.md) | Where that work currently stands |
| [`CURRENT_PLAN.md`](CURRENT_PLAN.md) | The active feature plan |
| `docs/` | Architecture, ADRs, runbooks, guides |

> `AGENTS.md` and `CLAUDE.md` also name a "current plan", and the three do not
> agree. `CURRENT_PLAN.md` is the newest and is treated as authoritative;
> reconciling them is task 6.7 (report S3-51).
