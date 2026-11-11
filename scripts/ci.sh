#!/usr/bin/env bash
# Run the CI gates locally (task H-CI-local).
#
# `.github/workflows/ci.yml` defines ten jobs. None has ever executed, because
# this repository has no git remote — GitHub Actions runs on GitHub. Eight of
# the ten are just commands, so they can run here and tell you where you stand
# without an account, a push, or any credential.
#
# The two that cannot:
#   compose-smoke   needs Docker, which is not installed on this machine
#   openapi-types   needs a live backend to fetch /openapi.json from
# Both are reported as SKIPPED rather than passed. A gate that did not run is
# not a gate that passed, and this script will not pretend otherwise.
#
#   scripts/ci.sh              # everything runnable
#   scripts/ci.sh --fast       # skip the slow database gates (~1 min)
#   scripts/ci.sh lint test    # named gates only
#
# Exit code is 1 if any gate fails. Skipped gates do not fail the run, but they
# are counted and printed in the summary.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
SCRATCH_DB="cf_ci_local"

PY311_WIN='C:\Users\Rajkumar\AppData\Local\Programs\Python\Python311\python.exe'

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
declare -a NAMES=() RESULTS=() TIMES=()

have()  { command -v "$1" >/dev/null 2>&1; }
banner() { printf '\n%s── %s %s\n' "$DIM" "$1" "$OFF"; }

# record <name> <status> <seconds>
record() { NAMES+=("$1"); RESULTS+=("$2"); TIMES+=("$3"); }

# run <name> <command...>
# Exit 99 from a gate means "the preconditions were not there" — no server, no
# database — and is recorded as SKIP, not FAIL. This script already refuses to
# report a gate that did not run as a gate that passed; 99 is how a gate says
# that about itself rather than the caller guessing.
readonly RC_NOT_RUN=99

run() {
  local name="$1"; shift
  banner "$name"
  local t0 rc verdict
  t0=$SECONDS
  "$@"
  rc=$?
  if [ $rc -eq $RC_NOT_RUN ]; then
    verdict=SKIP
  elif [ $rc -eq 0 ]; then
    verdict=PASS
  else
    verdict=FAIL
  fi
  record "$name" "$verdict" "$((SECONDS - t0))"
  return 0   # never abort the run; the summary reports everything
}

skip() { banner "$1"; printf '  %sSKIPPED — %s%s\n' "$YELLOW" "$2" "$OFF"; record "$1" "SKIP" 0; }

# --- database helper -------------------------------------------------------
# The migration and drift gates need an empty PostGIS database. Build one from
# DATABASE_URL rather than assuming a name, and never touch the configured one.
reset_scratch() {
  cd "$BACKEND" || return 1
  python - "$SCRATCH_DB" <<'PY'
import os, sys, sqlalchemy as sa
from dotenv import load_dotenv
load_dotenv('.env')
name = sys.argv[1]
url = os.environ.get('DATABASE_URL')
if not url:
    sys.exit("DATABASE_URL is not set")
admin = url.rsplit('/', 1)[0] + '/postgres'
with sa.create_engine(admin).connect().execution_options(isolation_level='AUTOCOMMIT') as c:
    c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    c.execute(sa.text(f'CREATE DATABASE "{name}"'))
tgt = url.rsplit('/', 1)[0] + '/' + name
with sa.create_engine(tgt).connect().execution_options(isolation_level='AUTOCOMMIT') as c:
    for s in ("CREATE EXTENSION IF NOT EXISTS postgis",
              "CREATE EXTENSION IF NOT EXISTS postgis_raster",
              "CREATE SCHEMA IF NOT EXISTS admin",
              "CREATE EXTENSION IF NOT EXISTS postgis SCHEMA admin"):
        c.execute(sa.text(s))
print(tgt)
PY
}

scratch_url() {
  cd "$BACKEND" && python - "$SCRATCH_DB" <<'PY'
import os, sys
from dotenv import load_dotenv
load_dotenv('.env')
print(os.environ['DATABASE_URL'].rsplit('/', 1)[0] + '/' + sys.argv[1])
PY
}

# --- gates -----------------------------------------------------------------

gate_deps() {   # mirrors the deps-lock job
  cd "$BACKEND" || return 1
  local bad
  bad=$(grep -vE '^\s*#|^\s*$' requirements.in | grep -vE '==|>=.*,<' || true)
  if [ -n "$bad" ]; then
    printf '  unpinned direct dependencies:\n%s\n' "$bad"; return 1
  fi
  echo "  no unpinned direct dependencies"
  if [ ! -s requirements.lock ]; then echo "  requirements.lock missing"; return 1; fi
  echo "  lock present: $(grep -c '^[a-zA-Z]' requirements.lock) pins, $(grep -c -- '--hash' requirements.lock) hashes"
  # Full regeneration takes ~10 min; CI does that. Here, verify it installs.
  if [ -x "$PY311_WIN" ] || [ -f "$PY311_WIN" ]; then
    "$PY311_WIN" -m pip install --require-hashes --dry-run -q -r requirements.lock || return 1
    echo "  installs on Python 3.11 with --require-hashes"
  else
    echo "  ${YELLOW}note:${OFF} Python 3.11 not found — skipped the install check"
  fi
}

gate_migrations() {   # mirrors migrations-from-empty (G-DB-1, G-DB-2)
  local url; url=$(reset_scratch | tail -1) || return 1
  cd "$BACKEND" || return 1
  export DATABASE_URL="$url"
  python -m alembic upgrade head >/dev/null 2>&1 || { echo "  upgrade head FAILED"; return 1; }
  echo "  upgrade head from empty: OK"
  local heads; heads=$(python -m alembic heads 2>/dev/null | grep -c '(head)')
  [ "$heads" -eq 1 ] || { echo "  expected 1 head, found $heads"; return 1; }
  echo "  exactly one head"
  local out; out=$(python -m alembic upgrade head 2>&1)
  if echo "$out" | grep -q "Running upgrade"; then echo "  NOT idempotent"; return 1; fi
  echo "  re-run is a no-op"
  python -m alembic downgrade base >/dev/null 2>&1 || { echo "  downgrade base FAILED"; return 1; }
  echo "  downgrade base: OK"
  python -m alembic upgrade head >/dev/null 2>&1 || { echo "  round-trip upgrade FAILED"; return 1; }
  echo "  round-trip: OK"
}

gate_drift() {   # mirrors alembic-check, now the ratchet (G-DB-3)
  cd "$BACKEND" || return 1
  local url; url=$(scratch_url) || return 1
  export DATABASE_URL="$url"
  python -m alembic current 2>/dev/null | grep -q head || {
    echo "  scratch DB not at head — run the migrations gate first"; return 1; }
  python scripts/check_schema_drift.py
}

gate_lint_backend() {
  cd "$BACKEND" || return 1
  local rc=0
  python scripts/check_ruff_baseline.py            || rc=1
  python scripts/check_black_baseline.py           || rc=1
  python scripts/check_blocking_handlers.py --gate || rc=1   # G-PERF-1
  python scripts/check_silent_handlers.py  --gate  || rc=1   # G-QUAL-1
  return $rc
}

gate_gates() {
  # The two route-table gates. They import app.main, so ci.yml runs them in
  # test-backend rather than lint-backend, both with continue-on-error for a
  # reason not yet diagnosed. Locally there is no such constraint.
  cd "$BACKEND" || return 1
  local rc=0
  python scripts/check_unmounted_routers.py    --gate || rc=1
  python scripts/check_idempotency_coverage.py --gate || rc=1   # G-SYNC-1
  return $rc
}

gate_live() {
  # Behaviour checks against a RUNNING backend: the four rows that used to be
  # "open the app and try it". Exit 2 means the server is not up, which is a
  # SKIP -- a gate that did not run is not a gate that passed, and this script
  # says so elsewhere too.
  cd "$BACKEND" || return 1
  python scripts/verify_live.py --api "${SMOKE_API:-http://localhost:8001}"
  local rc=$?
  [ $rc -eq 2 ] && return $RC_NOT_RUN
  return $rc
}

gate_test_backend() {
  cd "$BACKEND" || return 1
  # --cov here, not a separate run: H4.2's coverage gates need coverage.xml
  # from the SAME suite run everything else was just checked against, not a
  # second pytest invocation that could disagree with the first about which
  # tests exist right now.
  python -m pytest tests/ -q --no-header -p no:cacheprovider --tb=line -n 2 -p randomly --timeout=300     --cov=app --cov-report=xml
}

gate_coverage() {   # H4.2 / S1-22 — ratchet on the coverage.xml test-backend just wrote
  cd "$BACKEND" || return 1
  [ -f coverage.xml ] || { echo "  coverage.xml missing — run test-backend first"; return $RC_NOT_RUN; }
  local rc=0
  python scripts/check_coverage_baseline.py || rc=1
  python scripts/check_diff_coverage.py      || rc=1
  return $rc
}

gate_lint_frontend() {
  cd "$FRONTEND" || return 1
  # Ratchet against the recorded baseline rather than demanding zero errors:
  # tsconfig has strict:false and the project knowingly carries 7. Fails on NEW
  # errors only. See scripts/check-tsc-baseline.mjs.
  npm run --silent typecheck || return 1
  # Same correction as the backend: 4.1 shipped check-eslint-baseline.mjs, so
  # this ratchets rather than printing a warning nobody acts on.
  node scripts/check-eslint-baseline.mjs || return 1
}

gate_test_frontend() { cd "$FRONTEND" && npx vitest run --reporter=dot; }

gate_build() {
  cd "$FRONTEND" || return 1
  npm run build >/dev/null 2>&1 || { echo "  build FAILED"; return 1; }
  echo "  build OK"
  npm run bundle:budget
}

# --- selection -------------------------------------------------------------
FAST=0
declare -a WANT=()
for a in "$@"; do
  case "$a" in
    --fast) FAST=1 ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) WANT+=("$a") ;;
  esac
done
wanted() { [ ${#WANT[@]} -eq 0 ] && return 0; for w in "${WANT[@]}"; do [ "$w" = "$1" ] && return 0; done; return 1; }

printf '%sRunning CI gates locally.%s\n' "$DIM" "$OFF"
printf '%s.github/workflows/ci.yml has never executed — this repo has no git remote.%s\n' "$DIM" "$OFF"

START=$SECONDS
wanted deps      && { [ $FAST -eq 1 ] && skip "deps-lock" "--fast" || run "deps-lock" gate_deps; }
wanted migrations&& { [ $FAST -eq 1 ] && skip "migrations-from-empty" "--fast" || run "migrations-from-empty" gate_migrations; }
wanted drift     && { [ $FAST -eq 1 ] && skip "schema-drift" "--fast" || run "schema-drift" gate_drift; }
wanted lint      && run "lint-backend" gate_lint_backend
wanted gates     && run "route-gates" gate_gates
wanted live      && { [ $FAST -eq 1 ] && skip "live-behaviour" "--fast" || run "live-behaviour" gate_live; }
wanted test      && { [ $FAST -eq 1 ] && skip "test-backend" "--fast" || run "test-backend" gate_test_backend; }
wanted coverage  && { [ $FAST -eq 1 ] && skip "coverage" "--fast" || run "coverage" gate_coverage; }
wanted lint      && run "lint-frontend" gate_lint_frontend
wanted test      && run "test-frontend" gate_test_frontend
wanted build     && run "build" gate_build
wanted compose   && skip "compose-smoke" "Docker not installed on this machine"
wanted openapi   && skip "openapi-types" "needs a running backend on :8001"

# --- summary ---------------------------------------------------------------
printf '\n%s──────────────────────────────────────────────%s\n' "$DIM" "$OFF"
fails=0; skips=0
for i in "${!NAMES[@]}"; do
  case "${RESULTS[$i]}" in
    PASS) printf '  %sPASS%s  %-24s %ss\n' "$GREEN" "$OFF" "${NAMES[$i]}" "${TIMES[$i]}" ;;
    FAIL) printf '  %sFAIL%s  %-24s %ss\n' "$RED"   "$OFF" "${NAMES[$i]}" "${TIMES[$i]}"; fails=$((fails+1)) ;;
    SKIP) printf '  %sSKIP%s  %-24s\n'     "$YELLOW" "$OFF" "${NAMES[$i]}"; skips=$((skips+1)) ;;
  esac
done
printf '%s──────────────────────────────────────────────%s\n' "$DIM" "$OFF"
printf '  %d gate(s), %d failed, %d skipped, %ss total\n' "${#NAMES[@]}" "$fails" "$skips" "$((SECONDS - START))"
[ "$skips" -gt 0 ] && printf '  %sSkipped gates have NOT passed.%s\n' "$YELLOW" "$OFF"
exit $([ "$fails" -eq 0 ] && echo 0 || echo 1)
