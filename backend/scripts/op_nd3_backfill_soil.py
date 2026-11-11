"""ND-3 backfill — whole-forest soil texture % distribution for every calc.

Computes the area-weighted USDA soil texture distribution
(analyze_soil_texture_zonal) from rasters.soilgrids_isric for every
calculation that has a boundary and merges soil_percentages /
soil_dominant_type into result_data. Idempotent: re-running recomputes.
Calcs with no soil coverage are left untouched so the plan keeps its
honest "no data" marker.

Run:  python scripts/op_nd3_backfill_soil.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.calculation import Calculation  # noqa: E402
from app.services.analysis import analyze_soil_texture_zonal  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        calcs = db.execute(
            text(
                "SELECT id, forest_name FROM calculations "
                "WHERE boundary_geom IS NOT NULL ORDER BY created_at"
            )
        ).fetchall()
        print(f"{len(calcs)} calculation(s) with a boundary")
        for cid, fname in calcs:
            wkt = db.execute(
                text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :i"),
                {"i": cid},
            ).scalar()
            rec = analyze_soil_texture_zonal(wkt, db)
            if not rec:
                print(f"  {cid}  {fname}: no soil coverage — left untouched")
                continue
            calc = db.get(Calculation, str(cid))
            rd = dict(calc.result_data or {})
            rd.update(rec)
            calc.result_data = rd
            flag_modified(calc, "result_data")
            db.commit()
            print(f"  {cid}  {fname}: {rec['soil_dominant_type']} {rec['soil_percentages']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
