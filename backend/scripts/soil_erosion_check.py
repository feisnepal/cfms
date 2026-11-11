"""Dev harness for the RUSLE soil-loss compute (P1) — not wired into any route.

    python -m scripts.soil_erosion_check <calculation_id> [--force] [--regression]

Prints per-unit + CF / user-group summaries and the GeoTIFF path. Use it to
eyeball a forest before P2 (the map) exists. Read-only apart from writing the
cache GeoTIFF under ``uploads/soil_erosion_cache/``.
"""

from __future__ import annotations

import sys
from uuid import UUID

from app.core.database import SessionLocal
from app.services.operational_plan import soil_erosion as se
from app.services.operational_plan.soil_erosion_config import (
    SEVERITY_LABELS_EN,
    resolve_params,
)


def _fmt_summary(s: dict) -> str:
    if s["mean"] is None:
        return "  (no valid cells)"
    sev = ", ".join(
        f"{SEVERITY_LABELS_EN[i] if i < len(SEVERITY_LABELS_EN) else i}={p}%"
        for i, p in sorted(s["pct_by_severity"].items())
    )
    return (
        f"  mean {s['mean']:>8.2f} t/ha/yr | total {s['total_t_yr']:>12.1f} t/yr"
        f" | area {s['area_ha']:>9.2f} ha\n    {sev}"
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    calc_id = UUID(sys.argv[1])
    force = "--force" in sys.argv
    regression = "--regression" in sys.argv

    db = SessionLocal()
    try:
        params = resolve_params(db, calc_id)
        if regression:
            params = params.model_copy(update={"r_method": "annual_regression"})
        print(f"calc {calc_id}")
        print(
            f"r_method={params.r_method}  k_method={params.k_method}  "
            f"ls_method={params.ls_method}  breaks={params.severity_breaks}"
        )
        prov = {k: v for k, v in params._provenance.items() if v != "default"}
        print(f"customised params: {prov or 'none'}\n")

        if regression:
            # bypass the cache key mismatch — recompute in-process
            grid = se.build_grid(db, calc_id)
            r = se.factor_r_grid(db, grid, params)
            k = se.factor_k_grid(db, grid, params)
            ls, slope = se.factor_ls_grid(db, grid, params)
            c, esa = se.factor_c_grid(db, grid, params)
            p = se.factor_p_grid(esa, slope, params)
            a = se.soil_loss(r, k, ls, c, p)
            res = se.SoilLossResult(grid, params, a, r, k, ls, c, p, geotiff_path=None)  # type: ignore[arg-type]
        else:
            res = se.compute_soil_loss(db, calc_id, force=force)

        import numpy as np

        for name, arr in (
            ("R", res.r),
            ("K", res.k),
            ("LS", res.ls),
            ("C", res.c),
            ("P", res.p),
            ("A", res.a),
        ):
            v = arr[np.isfinite(arr)]
            if v.size:
                print(
                    f"  {name:>2}: min {v.min():.4g}  mean {v.mean():.4g}  "
                    f"max {v.max():.4g}  (valid {100*v.size/arr.size:.0f}%)"
                )
        print(f"\nGeoTIFF: {res.geotiff_path}\n")

        from app.services.operational_plan.thematic_overlay import _units_with_geometry

        units = _units_with_geometry(db, calc_id)
        if units:
            print(f"per-unit ({len(units)}):")
            for name, s in se.zonal_summary(res, units).items():
                print(f" {name}\n{_fmt_summary(s)}")
        print("\nCF boundary:")
        print(_fmt_summary(se.aoi_summary(res, res.grid.cf_mask)))
        if res.grid.ug_mask is not None:
            print("\nuser-group extent:")
            print(_fmt_summary(se.aoi_summary(res, res.grid.ug_mask)))
            print("\nuser-group MINUS CF:")
            print(
                _fmt_summary(se.aoi_summary(res, res.grid.ug_mask & ~res.grid.cf_mask))
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
