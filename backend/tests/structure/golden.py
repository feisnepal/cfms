"""Golden snapshots of how the app picks "the units of a forest" TODAY (FS-0.5).

Every phase that moves a reader onto the units module must change *only* what it means to change. The
snapshot records, per fixture forest, what each reader returns now; a later phase re-runs the same probes
and the difference is the change, reviewed before the snapshot is re-baselined.

A probe is ``probe(db, calc) -> JSON-able``. Probes are id-free (unit ids become names) so the file is
stable across runs. A probe that raises is recorded as ``{"error": ...}`` - a crash today is behaviour a
later phase may legitimately fix, and it must show up in the diff, not vanish.

Probes are added as phases add readers; FS-0.5 starts with the ones P1a moves. Table 5 (area detail) needs
the ESA raster, which the test database does not have, so its probe is added in P3a-1 on stubbed cover.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "current.json"
ALLOWLIST_FILE = GOLDEN_DIR / "allowlist.json"

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _clean(value: Any) -> Any:
    """Make a probe result JSON-safe and id-free."""
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return _UUID.sub("<uuid>", value)
    if hasattr(value, "value") and not isinstance(value, (int, bool)):  # enums
        return _clean(value.value)
    return value


# --- probes ---------------------------------------------------------------------------------------
def probe_rows(db, calc):
    rows = db.execute(
        text(
            "SELECT b.name, b.is_compartment, b.division_level, p.name AS parent, b.area_hectares, "
            "       b.working_circle "
            "FROM forest_blocks b LEFT JOIN forest_blocks p ON p.id = b.parent_block_id "
            "WHERE b.calculation_id = :c ORDER BY b.index"
        ),
        {"c": str(calc.id)},
    ).fetchall()
    return [
        {
            "name": r.name,
            "compartment": r.is_compartment,
            "level": r.division_level,
            "parent": r.parent,
            "ha": r.area_hectares,
            "wc": r.working_circle,
        }
        for r in rows
    ]


def probe_dimension(db, calc):
    from app.utils.forest_dimension import get_forest_dimension

    return get_forest_dimension(db, calc.id)


def probe_result_data_arrays(db, calc):
    rd = calc.result_data or {}
    return {
        "blocks": [b.get("name") for b in rd.get("blocks", [])],
        "compartments": [c.get("name") for c in rd.get("compartments", [])],
        "polygon_type": rd.get("polygon_type"),
    }


def probe_sampling_units(db, calc):
    from app.services.sampling import extract_blocks_from_calculation

    return [
        {"number": n, "name": name, "ha": area}
        for n, _wkt, name, area in extract_blocks_from_calculation(db, calc.id)
    ]


def probe_analysis_source(db, calc):
    from app.services.analysis_polygon_source import PolygonSource

    src = PolygonSource.for_result_data(calc.result_data)
    return {
        "key": src.get_metadata_key(),
        "names": [p.get("name") for p in src.get_polygons()],
    }


def probe_sfm_leaf_units(db, calc):
    from app.services.sustainable_fm.sfm_service import _leaf_units

    return [u.name for u in _leaf_units(calc, db)]


def probe_plan_block_index(db, calc):
    from app.services.operational_plan.plan_collector import _block_index

    return sorted(v["name"] for v in _block_index(db, calc.id).values())


PROBES: dict[str, Callable] = {
    "rows": probe_rows,
    "dimension": probe_dimension,
    "result_data_arrays": probe_result_data_arrays,
    "sampling_units": probe_sampling_units,
    "analysis_source": probe_analysis_source,
    "sfm_leaf_units": probe_sfm_leaf_units,
    "plan_block_index": probe_plan_block_index,
}


def snapshot(db, calc) -> dict:
    """Run every probe on one forest. A raising probe is recorded, not propagated."""
    out = {}
    for name, fn in PROBES.items():
        try:
            out[name] = _clean(fn(db, calc))
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- a crash is data in a golden snapshot; it must appear in the diff
            db.rollback()
            out[name] = {
                "error": f"{type(exc).__name__}: {_UUID.sub('<uuid>', str(exc))[:160]}"
            }
    return out


# --- comparison -----------------------------------------------------------------------------------
def load_golden() -> dict:
    return (
        json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
        if GOLDEN_FILE.exists()
        else {}
    )


def save_golden(data: dict) -> None:
    GOLDEN_DIR.mkdir(exist_ok=True)
    GOLDEN_FILE.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_allowlist() -> dict:
    """``{"phase": "P1a", "cells": {"F4/sampling_units": "why this changes"}}`` - cells a phase may change."""
    if not ALLOWLIST_FILE.exists():
        return {"phase": None, "cells": {}}
    return json.loads(ALLOWLIST_FILE.read_text(encoding="utf-8"))


def diff(
    expected: dict, actual: dict, fixture_key: str, allowlist: dict
) -> tuple[list, list]:
    """(unexpected, allowed) differences for one fixture, as ``(probe, expected, actual)`` tuples."""
    unexpected, allowed = [], []
    for probe in sorted(set(expected) | set(actual)):
        if expected.get(probe) == actual.get(probe):
            continue
        cell = f"{fixture_key}/{probe}"
        (allowed if cell in allowlist["cells"] else unexpected).append(
            (probe, expected.get(probe), actual.get(probe))
        )
    return unexpected, allowed
