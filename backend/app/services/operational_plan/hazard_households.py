"""Household vulnerability and priority-settlement dots for the workspace "Analysis maps" group.

Same data and same scores as the print maps (``hh__vulnerability`` / ``hh__priority_settlements``), as a small GeoJSON
FeatureCollection the browser draws as dots. Rules:

* **Only when the hazard grids are already cached.** The household score samples the soil-loss, landslide and stability
  surfaces; ``compute_household_vulnerability`` would compute any that are missing, and a map layer must not start a
  multi-minute computation. No cached grids → ``{"state": "not_computed"}``.
* **No identifiers.** A household dot carries its score and whether it is a priority household: no house number, no
  name, no caste. Settlement dots carry the tole name and counts, at the roll-up's own ~100 m rounded centroid (it is
  rounded on purpose so it cannot pin a single household).
* ``compute_household_vulnerability`` writes an access-audit row each call, so the result is memoised in this process
  for a few minutes: dragging the opacity or toggling the layer must not flood the audit trail.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

KINDS = ("households", "settlements")
_TTL_S = 300
_MEMO: dict[tuple, tuple[float, Any]] = {}
_LOCK = threading.Lock()


def _grids_cached(db: Any, calculation_id: UUID) -> bool:
    from app.services.operational_plan import hazard_tiles as ht

    return all(ht.load_surface(db, calculation_id, key) is not None for key in ("soil", "lsi", "fs"))


def _result(db: Any, calculation_id: UUID, signature: str) -> Any:
    from app.services.operational_plan import household_vulnerability as hvm

    key = (str(calculation_id), signature)
    now = time.monotonic()
    with _LOCK:
        hit = _MEMO.get(key)
        if hit and now - hit[0] < _TTL_S:
            return hit[1]
    res = hvm.compute_household_vulnerability(db, calculation_id)
    with _LOCK:
        _MEMO[key] = (now, res)
        if len(_MEMO) > 6:
            _MEMO.pop(min(_MEMO, key=lambda k: _MEMO[k][0]))
    return res


def clear_memo() -> None:
    with _LOCK:
        _MEMO.clear()


def _signature(db: Any, calculation_id: UUID) -> str:
    """Changes when anything the score depends on does (parameters, the cached grids)."""
    from app.services.operational_plan import hazard_vuln_config as hc
    from app.services.operational_plan import landslide_susceptibility as lsm
    from app.services.operational_plan import soil_erosion as se

    params = hc.resolve_params(db, calculation_id)
    parts = [hc.params_hash(params)]
    for path in (lsm._cache_path(calculation_id, params),):  # noqa: SLF001
        parts.append(str(path.stat().st_mtime_ns) if path.exists() else "0")
    sp = se.resolve_params(db, calculation_id)
    sp_path = se._cache_path(calculation_id, sp)  # noqa: SLF001
    parts.append(str(sp_path.stat().st_mtime_ns) if sp_path.exists() else "0")
    return "|".join(parts)


def _in_area(geom: Any, lon: float, lat: float) -> bool:
    from shapely.geometry import Point

    return geom is None or geom.contains(Point(lon, lat))


def points(db: Any, calculation_id: UUID, kind: str, area: str = "forest") -> dict[str, Any]:
    """``{"state": "ready", "kind", "features": GeoJSON points, "min", "max", "count", "n_priority"}`` or
    ``{"state": "not_computed" | "no_user_group" | "no_data"}``."""
    from app.services.operational_plan import soil_erosion as se

    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    ug = None
    if area == "user_group":
        ug = se._user_group_geom(db, calculation_id)  # noqa: SLF001
        if ug is None or ug.is_empty:
            return {"state": "no_user_group", "kind": kind}
    if not _grids_cached(db, calculation_id):
        return {"state": "not_computed", "kind": kind}

    res = _result(db, calculation_id, _signature(db, calculation_id))
    feats: list[dict] = []
    if kind == "households":
        for h in res.households:
            lon, lat, score = h.get("longitude"), h.get("latitude"), h.get("score")
            if lon is None or lat is None or score is None or not _in_area(ug, lon, lat):
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(float(lon), 6), round(float(lat), 6)]},
                "properties": {"score": round(float(score), 4), "priority": bool(h.get("priority"))},
            })
    else:
        for r in res.settlement_rollup:
            lon, lat, score = r.get("_lon"), r.get("_lat"), r.get("mean_score")
            if lon is None or lat is None or score is None or not _in_area(ug, lon, lat):
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "score": score, "name": r.get("tole"), "n": int(r.get("n_households") or 0),
                    "n_priority": int(r.get("n_priority") or 0),
                },
            })
    if not feats:
        return {"state": "no_data", "kind": kind}
    scores = [f["properties"]["score"] for f in feats]
    return {
        "state": "ready",
        "kind": kind,
        "area": area,
        "basis": (res.summary or {}).get("basis"),
        "count": len(feats),
        "n_priority": sum(1 for f in feats if f["properties"].get("priority")),
        "min": min(scores),
        "max": max(scores),
        "features": feats,
    }
