"""Repair units that overlap their siblings: the SMALLER unit keeps the contested ground (owner decision 2026-10-19).

Dry run by default - it prints exactly what would move and changes nothing:

    ../venv/Scripts/python.exe scripts/repair_unit_overlaps.py <calc-id>
    ../venv/Scripts/python.exe scripts/repair_unit_overlaps.py <calc-id> --apply

``--apply`` first copies the forest's ``forest_blocks`` rows and its ``calculations`` row into two backup tables
(``forest_blocks_backup_<date>_<id8>``, ``calculations_backup_<date>_<id8>``; they are never touched again, and restoring is a
plain ``UPDATE ... FROM``), then makes the change through ``structure_write`` - the funnel every structure edit uses - so the
derived arrays, sub-area breakdown, caches and the geometry clock are brought up to date, and an edit that would make the structure
worse is refused. It refuses to run when a cut would leave a unit in more than one piece (it never discards ground silently).

Only siblings of ONE parent are compared, and Auto-Block trial layers (``raster_layer_id`` set) are left alone: those are
alternatives to each other and are meant to overlap.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geoalchemy2.shape import from_shape, to_shape  # noqa: E402
from shapely.geometry import mapping  # noqa: E402
from sqlalchemy import text, update  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.calculation import Calculation  # noqa: E402
from app.models.forest_block import ForestBlock  # noqa: E402
from app.services.audit_service import log_geometry_audit  # noqa: E402
from app.services.forest_units import invariants  # noqa: E402
from app.services.forest_units.overlap_repair import Unit, resolve  # noqa: E402
from app.services.forest_units.write import structure_write  # noqa: E402
from app.utils.geometry_utils import calculate_area_geodesic_from_shapely  # noqa: E402


def _ha(geom) -> float:
    return calculate_area_geodesic_from_shapely(geom)[1]


def _plan(db, calc_id):
    rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc_id, ForestBlock.raster_layer_id.is_(None), ForestBlock.geometry.isnot(None))
        .all()
    )
    groups = defaultdict(list)
    for r in rows:
        groups[r.parent_block_id].append(r)
    by_id = {r.id: r for r in rows}
    plan = []
    for parent_id, sibs in groups.items():
        if len(sibs) < 2:
            continue
        units = [Unit(r.id, r.block_name or r.name, to_shape(r.geometry), _ha(to_shape(r.geometry))) for r in sibs]
        for ch in resolve(units):
            plan.append((parent_id, by_id[ch.id], ch))
    return plan


MAX_STRAY_M2 = 500.0       # a fragment this small, outside the parent, is an artefact
MAX_INSIDE_PARENT = 0.05   # ... and at most this share of it may lie inside the parent


def _stray(db, parent_id, fragment):
    """(droppable, share of it inside the parent, its area in m2) for a fragment a cut left behind."""
    sqm = calculate_area_geodesic_from_shapely(fragment)[0]
    parent = db.query(ForestBlock).filter(ForestBlock.id == parent_id).first() if parent_id else None
    if parent is None or parent.geometry is None:
        return False, 1.0, sqm
    share = fragment.intersection(to_shape(parent.geometry)).area / fragment.area if fragment.area else 1.0
    return (share <= MAX_INSIDE_PARENT and sqm <= MAX_STRAY_M2), share, sqm


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("calculation_id")
    ap.add_argument("--apply", action="store_true", help="write the change (after taking a backup); default is a dry run")
    ap.add_argument("--drop-stray-fragments", action="store_true",
                    help="allow dropping a cut-off fragment that lies outside the unit's parent and is small")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        calc = db.query(Calculation).filter(Calculation.id == args.calculation_id).first()
        if calc is None:
            print("no such calculation")
            return 2
        before = invariants.find_violations(db, calc.id)
        print(f"{calc.forest_name}: {len(before)} structure violation(s) now")
        for v in before:
            print(f"  {v.code} {v.unit}: {v.message}")

        plan = _plan(db, calc.id)
        if not plan:
            print("no sibling overlap to repair")
            return 0
        print(f"\n{len(plan)} unit(s) give ground to a smaller neighbour:")
        moved = 0.0
        for _parent, row, ch in plan:
            old, new = _ha(to_shape(row.geometry)), _ha(ch.geometry)
            moved += old - new
            was = len(getattr(to_shape(row.geometry), "geoms", [0]))
            flag = f"   !! {ch.parts_dropped} new fragment(s)" if ch.parts_dropped else (f"   (stays {was}-part, as it was stored)" if was > 1 else "")
            print(f"  {ch.name:>12}: {old:8.4f} ha -> {new:8.4f} ha  (-{(old - new) * 10000:7.0f} m2)  gave to {', '.join(ch.lost_to)}{flag}")
        print(f"  ground moved in total: {moved * 10000:.0f} m2")
        blocked = False
        for parent_id, _row, ch in plan:
            for frag in ch.fragments or []:
                ok, share, sqm = _stray(db, parent_id, frag)
                print(f"  fragment of {ch.name}: {sqm:.0f} m2, {share * 100:.0f}% of it inside its parent -> "
                      + ("a stray piece outside the parent" if ok else "NOT a stray piece"))
                blocked = blocked or not ok or not args.drop_stray_fragments
        if blocked:
            print("\nA cut leaves a unit in more than one piece. Nothing is applied: a fragment is dropped only with"
                  " --drop-stray-fragments, and only when it lies outside the parent and is small.")
            return 1
        if not args.apply:
            print("\nDry run - nothing changed. Add --apply to write it (a backup is taken first).")
            return 0

        tag = f"{date.today():%Y%m%d}_{str(calc.id)[:8]}"
        db.execute(text(f"CREATE TABLE forest_blocks_backup_{tag} AS SELECT * FROM forest_blocks WHERE calculation_id = :c"), {"c": str(calc.id)})  # noqa: S608
        db.execute(text(f"CREATE TABLE calculations_backup_{tag} AS SELECT * FROM calculations WHERE id = :c"), {"c": str(calc.id)})  # noqa: S608
        db.commit()
        print(f"\nbackup taken: forest_blocks_backup_{tag}, calculations_backup_{tag}")

        with structure_write(db, calc, change="repair_unit_overlaps"):
            for _parent, row, ch in plan:
                previous = mapping(to_shape(row.geometry))
                sqm, ha = calculate_area_geodesic_from_shapely(ch.geometry)
                if ch.geometry.geom_type == "Polygon":
                    row.geometry = from_shape(ch.geometry, srid=4326)
                    row.area_sqm = round(sqm, 4)
                    row.area_hectares = round(ha, 4)
                else:
                    # a unit that was ALREADY stored in several parts keeps them: the ORM single-part guard is for new writes, and
                    # splitting it into rows is a separate decision. A Core UPDATE does not run the ORM guard.
                    db.execute(
                        update(ForestBlock).where(ForestBlock.id == row.id)
                        .values(geometry=from_shape(ch.geometry, srid=4326), area_sqm=round(sqm, 4), area_hectares=round(ha, 4))
                    )
                    db.expire(row)
                log_geometry_audit(
                    db=db, calculation_id=str(calc.id), layer_type="compartments" if row.is_compartment else "blocks", operation="CLIP",
                    feature_id=str(row.id), previous_geometry=previous, new_geometry=mapping(ch.geometry), user_id=str(calc.user_id),
                    metadata={"reason": "repair_unit_overlaps", "gave_ground_to": ch.lost_to},
                )
        db.commit()

        after = invariants.find_violations(db, calc.id)
        print(f"\nafter: {len(after)} structure violation(s)")
        for v in after:
            print(f"  {v.code} {v.unit}: {v.message}")
        remaining = sum(1 for _p, _r, _c in _plan(db, calc.id))
        print(f"units still overlapping a sibling: {remaining}")
        return 0 if remaining == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
