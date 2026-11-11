"""Loader for the committed species master snapshot.

Shared by migrations 101 (first load) and 102 (adds missing columns, then
re-loads). Kept as a plain module beside the data file rather than inside a
migration so the two migrations do not each carry their own copy of the column
list, and rather than in `app/` so an old migration does not break when
application code moves on.

Import it by path, not by name -- Alembic does not put the versions directory on
`sys.path`:

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_species_master_loader", Path(__file__).parent / "data" / "species_master_loader.py"
    )
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

SNAPSHOT_NAME = "species_master.jsonl"
SNAPSHOT_PATH = Path(__file__).parent / SNAPSHOT_NAME

# Columns refreshed on conflict. `id` is excluded: the primary key is not data,
# and nothing in the codebase holds a foreign key to it.
UPSERT_COLUMNS = [
    "local_name", "family", "genus", "aliases",
    "a", "b", "c", "a1", "b1", "s", "m", "bg",
    "wood_density_gm_cm3", "wood_density_source",
    "max_dbh_cm", "max_height_m",
    "typical_hd_ratio_min", "typical_hd_ratio_max",
    "min_altitude_m", "max_altitude_m",
    "species_code", "growth_rate", "economic_value", "nitrogen_fixing",
    "main_uses", "ecological_role", "rarity_status",
    "is_active", "is_tree_species", "full_stem_merchantable",
    "created_at", "updated_at",
]


def load_snapshot(path: Path | None = None) -> list[dict]:
    """Read the snapshot, one JSON object per species.

    Raises rather than returning a partial list. A half-loaded species master is
    worse than none: the missing species would simply be absent from reports,
    with nothing to indicate why.
    """
    path = path or SNAPSHOT_PATH
    if not path.exists():
        raise RuntimeError(
            f"species master snapshot missing: {path}. The species master is the "
            "single source of truth for species; if it cannot be loaded from the "
            "repository then a fresh database gets the wrong one."
        )
    rows: list[dict] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path}:{lineno} is not valid JSON: {exc}") from exc
            name = (record.get("scientific_name") or "").strip()
            if not name:
                raise RuntimeError(
                    f"{path}:{lineno} has no scientific_name; every line must name "
                    "the species it describes"
                )
            if name in seen:
                raise RuntimeError(
                    f"{path}:{lineno} repeats {name!r}; scientific_name is the "
                    "master's natural key and must be unique in the snapshot"
                )
            record["scientific_name"] = name
            seen.add(name)
            rows.append(record)
    if not rows:
        raise RuntimeError(f"{path} is empty")
    return rows


def drop_unsatisfiable_species_code_unique(bind) -> list[str]:
    """Remove a UNIQUE constraint on `species_code` if one exists.

    Needed before the snapshot can be loaded at all. `species_code` is a coarse
    code, not an identifier: the real master has 861 species across 23 distinct
    codes, so 838 of them share a code with another species. Migration
    `004_add_species_code_column` created a UNIQUE constraint on it, which the
    real data cannot satisfy -- and which production does not have, so it must
    have been dropped by hand at some point.

    Left here rather than in a migration body because both 101 (which loads) and
    any future reload need it, and forgetting it makes the load fail with an
    error that reads like a data problem rather than a stale constraint.
    """
    rows = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'tree_species_coefficients'::regclass "
            "  AND contype = 'u' "
            "  AND pg_get_constraintdef(oid) LIKE '%species_code%'"
        )
    ).fetchall()
    dropped = []
    for (name,) in rows:
        bind.execute(
            sa.text(f'ALTER TABLE tree_species_coefficients DROP CONSTRAINT "{name}"')
        )
        dropped.append(name)
    return dropped


def load_into_master(bind, rows: list[dict], strict: bool = False) -> dict:
    """Upsert the snapshot into `tree_species_coefficients` and drop extras.

    `strict=False` loads only the columns the table actually has and reports the
    rest. That is what lets migration 101 run on a database whose master schema
    predates migration 102; `strict=True` is for the migration that has just
    created the missing columns and expects a complete load.

    Returns a small report so the caller can print what happened.
    """
    master = sa.Table("tree_species_coefficients", sa.MetaData(), autoload_with=bind)
    present = {c.name for c in master.columns}

    if "scientific_name" not in present:
        raise RuntimeError(
            "tree_species_coefficients has no scientific_name column; the master "
            "table is not what this loader expects"
        )

    snapshot_cols = {c for r in rows for c in r}
    skipped = sorted(snapshot_cols - present)
    if skipped and strict:
        raise RuntimeError(
            "the snapshot has columns the master does not: "
            f"{skipped}. Either the schema or the snapshot is stale."
        )

    usable = [c for c in UPSERT_COLUMNS if c in present]
    payload = [
        {k: v for k, v in record.items() if k in present}
        for record in rows
    ]

    # Batched, because one statement carrying 861 rows x 33 columns is ~28k bind
    # parameters. That is under PostgreSQL's 65535 limit but past the point where
    # the driver and the compiler agree on how to send it -- the statement comes
    # back with generated parameter names like `max_height_m_m860` and fails.
    # 100 rows is 3.3k parameters, comfortably inside every layer.
    batch_size = 100
    for start in range(0, len(payload), batch_size):
        chunk = payload[start : start + batch_size]
        stmt = pg_insert(master).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["scientific_name"],
            set_={col: getattr(stmt.excluded, col) for col in usable},
        )
        bind.execute(stmt)

    names = [r["scientific_name"] for r in rows]
    deleted = bind.execute(
        sa.text(
            "DELETE FROM tree_species_coefficients "
            "WHERE scientific_name <> ALL(CAST(:names AS text[]))"
        ),
        {"names": names},
    ).rowcount

    total = bind.execute(
        sa.text("SELECT count(*) FROM tree_species_coefficients")
    ).scalar()

    return {
        "loaded": len(rows),
        "skipped_columns": skipped,
        "deleted": deleted,
        "total": total,
    }
