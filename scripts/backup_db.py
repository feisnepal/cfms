#!/usr/bin/env python
"""Back up `cf_db`, and prove the backup restores (H5.3 / H5.4 · S2-29).

Written 2026-08-24, before any other Phase 5 work, because the phase that builds
the safety net is the phase most able to destroy the thing it protects. There
was no backup of `cf_db` at all until this ran.

## Why it defaults to the `public` schema only

`cf_db` is 12 GB, and 11.8 GB of that is static GIS reference data spread over
fifteen schemas — buildings, river, landcover, admin, infrastructure, base,
soil, forest, ecology, climate, agriculture, terrain, geology, hazards, rasters.
The application never writes to any of them; they were loaded once from source
files.

Everything the application owns lives in `public`, and it is **228 MB, dumping
to 19 MB in about four seconds**. So the default is a fast dump of the data that
actually changes. `--full` takes everything, and is what you want before a
server move or a PostgreSQL upgrade — not before an ordinary day's work.

**This means the GIS layers are NOT covered by the default.** If they are not
reproducible from their source files, run `--full` at least once and keep it
somewhere off this machine.

## Why it verifies

An unverified backup is a belief, not a backup. `--verify` restores into a
scratch database and compares row counts against the live one, then drops the
scratch. It never writes to `cf_db`; the scratch name is asserted against the
live name before anything runs.

Expect one ignorable error on restore: `createdb` already creates a `public`
schema, so the dump's own `CREATE SCHEMA public` collides and pg_restore exits
1. Row counts are the real signal.

Usage:
    python scripts/backup_db.py                 # public schema, ~4s
    python scripts/backup_db.py --full          # everything, including 11.8 GB of GIS
    python scripts/backup_db.py --verify        # dump, then prove it restores
    python scripts/backup_db.py --retention 14  # prune dumps older than 14 days
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Deliberately outside the repository: a dump of `public` carries household rows,
# and a backup directory inside a git tree is one `git add -A` from being
# committed. It is also then safe from `git clean`.
DEFAULT_DEST = Path("D:/forest_management_backups")
SCRATCH_DB = "cf_db_restore_test"
VERIFY_TABLES = [
    "calculations", "forest_blocks", "household_information", "inventory_trees",
    "users", "translations", "sampling_designs", "refresh_tokens",
]


def database_url() -> str:
    for candidate in (REPO / "backend" / ".env", REPO / ".env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL"):
                    return line.partition("=")[2].strip()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not found in backend/.env, .env, or the environment")
    return url


def connection_parts(url: str):
    u = urllib.parse.urlparse(url.replace("postgresql+psycopg2", "postgresql"))
    return {
        "host": u.hostname or "localhost",
        "port": str(u.port or 5432),
        "user": u.username or "postgres",
        # Never passed on a command line — it would be visible in the process
        # list to every other user on the machine.
        "password": urllib.parse.unquote(u.password or ""),
        "dbname": (u.path or "/cf_db").lstrip("/"),
    }


def run(cmd: list[str], password: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def dump(parts: dict, dest: Path, full: bool) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    scope = "full" if full else "public"
    target = dest / f"cf_db_{scope}_{stamp}.dump"

    cmd = [
        "pg_dump", "-h", parts["host"], "-p", parts["port"], "-U", parts["user"],
        "-d", parts["dbname"], "--format=custom", "--compress=6", "--file", str(target),
    ]
    if not full:
        cmd.insert(-2, "--schema=public")

    print(f"dumping {'everything' if full else 'the public schema'} from {parts['dbname']} ...")
    started = time.time()
    result = run(cmd, parts["password"])
    if result.returncode != 0:
        sys.exit(f"pg_dump failed:\n{result.stderr[-1500:]}")
    size_mb = target.stat().st_size / 1024 / 1024
    print(f"  {target}\n  {size_mb:,.1f} MB in {time.time() - started:,.1f}s")
    return target


def verify(parts: dict, dump_path: Path) -> bool:
    """Restore into a scratch database and compare. Never touches the live one."""
    if SCRATCH_DB == parts["dbname"]:
        sys.exit("refusing to run: the scratch database name equals the live one")

    base = ["-h", parts["host"], "-p", parts["port"], "-U", parts["user"]]
    pw = parts["password"]
    print(f"\nverifying by restoring into {SCRATCH_DB} ...")

    run(["psql", *base, "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], pw)
    created = run(["createdb", *base, SCRATCH_DB], pw)
    if created.returncode != 0:
        sys.exit(f"could not create the scratch database:\n{created.stderr[-800:]}")
    run(["psql", *base, "-d", SCRATCH_DB, "-c", "CREATE EXTENSION IF NOT EXISTS postgis"], pw)

    started = time.time()
    restored = run(["pg_restore", *base, "-d", SCRATCH_DB, "--no-owner",
                    "--no-privileges", str(dump_path)], pw)
    elapsed = time.time() - started
    # Exit 1 is expected: see the module docstring. Row counts decide.
    print(f"  pg_restore exit {restored.returncode} in {elapsed:,.1f}s  (RTO for this scope)")

    import psycopg2

    def counts(db: str) -> dict:
        cur = psycopg2.connect(host=parts["host"], port=parts["port"], user=parts["user"],
                               password=pw, dbname=db).cursor()
        out = {}
        for table in VERIFY_TABLES:
            try:
                cur.execute(f'select count(*) from public."{table}"')
                out[table] = cur.fetchone()[0]
            except Exception:
                out[table] = "ERR"
        return out

    live, copy = counts(parts["dbname"]), counts(SCRATCH_DB)
    ok = True
    print(f"\n  {'table':26s} {'live':>10s} {'restored':>10s}")
    for table in VERIFY_TABLES:
        match = live[table] == copy[table]
        ok &= match
        print(f"  {table:26s} {str(live[table]):>10s} {str(copy[table]):>10s}   "
              f"{'ok' if match else 'MISMATCH'}")

    run(["psql", *base, "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {SCRATCH_DB}"], pw)
    print(f"\n  {'VERIFIED — this dump restores' if ok else 'FAILED — this dump did NOT restore correctly'}")
    print(f"  scratch database dropped")
    return ok


def prune(dest: Path, days: int) -> None:
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for path in sorted(dest.glob("cf_db_*.dump")):
        if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink()
            removed += 1
    print(f"\npruned {removed} dump(s) older than {days} days")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true",
                    help="include the 11.8 GB of static GIS schemas, not just public")
    ap.add_argument("--verify", action="store_true",
                    help="restore into a scratch database and compare row counts")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--retention", type=int, metavar="DAYS",
                    help="delete dumps older than DAYS after a successful run")
    args = ap.parse_args()

    parts = connection_parts(database_url())
    path = dump(parts, args.dest, args.full)

    ok = True
    if args.verify:
        ok = verify(parts, path)
    if args.retention and ok:
        prune(args.dest, args.retention)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
