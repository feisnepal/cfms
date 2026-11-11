"""Single boundary-write point (PB-3).

All confirm / edit / import boundary persists route through ``persist_boundary``
so that geometry_version bump, ``result_data.geometry``, and geodesic area are
consistent across every path (forests.update_boundary_geometry,
boundary.confirm_boundary, editing._persist_boundary_geometry).

No unit is auto-created from the boundary (C1-C3 / Q5: "no automatic single
block for a new forest"; the forest stands boundary-only until the user
explicitly creates a unit in whichever stream they choose - blocks OR
compartments - via the workspace's auto-create / import-from-boundary tools).

**Clip (2026-08-28 rework):** unless ``clip_against_neighbours=False``,
``persist_boundary`` first subtracts the union of every adjoining registered
forest within 200 m — so import, vertex edit and boundary extension all clip
identically and no forest can ever store land another forest already holds.
``BoundaryFullyInsideExisting`` is raised when nothing survives.

No DB ``commit`` is performed here; every caller wraps this in its own
transaction.
"""

from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from ..models.calculation import Calculation
from .geometry_edit_service import bump_geometry_version
from ..utils.geometry_utils import calculate_area_geodesic_from_shapely

logger = logging.getLogger(__name__)


class BoundaryFullyInsideExisting(ValueError):
    """The proposed boundary is entirely inside existing forest land — nothing
    remains after clipping. Endpoints turn this into a 409."""


def _clip_against_neighbours(db, calc, polygon):
    """Return ``polygon`` minus the union of forests within 200 m (excl. self).

    Keeps every surviving piece (a neighbour that splits the boundary yields a
    MultiPolygon). Raises :class:`BoundaryFullyInsideExisting` when empty.
    """
    from geoalchemy2 import Geography
    from geoalchemy2.shape import to_shape

    wkt = polygon.wkt
    q = db.query(Calculation).filter(
        Calculation.boundary_geom.isnot(None),
        func.ST_DWithin(
            Calculation.boundary_geom.cast(Geography),
            func.ST_GeomFromText(wkt, 4326).cast(Geography),
            200.0,
        ),
    )
    calc_id = getattr(calc, "id", None)
    if calc_id is not None:
        q = q.filter(Calculation.id != calc_id)

    from types import SimpleNamespace

    neighbours = [
        SimpleNamespace(
            id=str(f.id),
            boundary_geom=to_shape(f.boundary_geom),
            forest_name=f.forest_name,
            name_np=None,
        )
        for f in q.all()
        if f.boundary_geom is not None
    ]
    if not neighbours:
        return polygon

    from .overlap_resolver import resolve_overlap

    res = resolve_overlap(polygon.__geo_interface__, neighbours)
    if res.resolved is None:
        raise BoundaryFullyInsideExisting(
            "boundary is entirely within existing forest land"
        )
    return res.resolved  # shapely geometry in EPSG:4326


def persist_boundary(
    db,
    calc,
    polygon,
    area_hectares: float = None,
    clip_against_neighbours: bool = True,
    validate: bool = False,
    reclip_sub_areas: bool = True,
) -> dict:
    """Write ``polygon`` (shapely, EPSG:4326) as the forest boundary, THE one way.

    - sets ``calc.boundary_geom`` (SRID 4326),
    - refreshes ``result_data["geometry"]`` and sets ``result_data["area_hectares"]``
      — geodesically when no ``area_hectares`` is supplied (never silently zeroed),
      otherwise honouring the caller's value (the edit/import PUT historically
      trusts the client area; kept for PB-3 behaviour parity),
    - bumps ``geometry_version``.

    No unit row is created here — the boundary is never silently minted into a
    block (C1-C3 / Q5: "no automatic single block for a new forest"). Creating
    the first unit is the user's explicit choice: the "Create one block /
    compartment from the forest area" affordance in whichever stream they are
    working in, or the workspace's whole-forest auto-create / root-divide tools.

    Returns a dict with ``area_sqm``, ``area_ha``, ``area_hectares`` (4dp),
    and the stored ``geometry`` mapping.

    When ``validate`` is true the four forest-boundary rules (within Nepal,
    ≤ 1000 ha, ≤ 40 % built-up + cropland, protected-area / Buffer Zone) run
    against the *stored* polygon — after neighbour clipping — and a
    :class:`~app.services.boundary_validation.BoundaryRulesViolation` is raised
    on any error; warnings/info ride along on
    ``result_data["boundary_validation"]``. It defaults to ``False``: the
    reshape / vertex-edit callers operate on an already-checked boundary, so
    only the establish/import endpoints (``PUT .../boundary``,
    ``/boundary/confirm``, ``/forests/upload``, draft-convert, merge) pass
    ``validate=True``.
    """
    from geoalchemy2.shape import from_shape
    from shapely.geometry import mapping

    if clip_against_neighbours:
        polygon = _clip_against_neighbours(db, calc, polygon)

    bv_report = None
    if validate and not polygon.is_empty:
        from app.services.boundary_validation import enforce_boundary_rules

        _bv = enforce_boundary_rules(
            db, polygon.wkt, forest_name=getattr(calc, "forest_name", None)
        )
        bv_report = _bv.report
        if _bv.clipped:
            # R1 removed an out-of-Nepal part — store the clipped polygon.
            from shapely import wkt as _wkt_mod

            polygon = _wkt_mod.loads(_bv.effective_wkt)

    geom_wkb = from_shape(polygon, srid=4326)
    calc.boundary_geom = geom_wkb

    from .boundary_pieces_service import sync_boundary_pieces

    sync_boundary_pieces(db, calc, polygon)

    result_data = dict(calc.result_data or {})
    result_data["geometry"] = mapping(polygon)
    if bv_report is not None:
        result_data["boundary_validation"] = bv_report.as_dict()
    area_sqm, area_ha = calculate_area_geodesic_from_shapely(polygon)
    if area_hectares is None or area_hectares == 0:
        area_hectares = round(area_ha, 4)
    result_data["area_hectares"] = round(area_hectares, 4)
    calc.result_data = result_data
    flag_modified(calc, "result_data")

    # Every boundary write clips the sub-areas on record to the new boundary: the
    # first boundary (sub-areas recorded before it are finally checked), and any
    # later one that is smaller than the last. A caller that does its own re-clip
    # and reports it (edit-geometry, PUT /boundary) passes ``reclip_sub_areas=False``:
    # running it here first would leave nothing for it to report, and its
    # "sub-areas were clipped" warning would come back empty.
    sub_areas_reclip = None
    if (
        reclip_sub_areas
        and not polygon.is_empty
        and (result_data.get("sub_areas") or [])
    ):
        from app.services.sub_area_reclip_service import reclip_sub_areas_to_boundary

        sub_areas_reclip = reclip_sub_areas_to_boundary(db, calc, polygon)

    bump_geometry_version(calc)

    return {
        "area_sqm": area_sqm,
        "area_ha": area_ha,
        "area_hectares": round(area_hectares, 4),
        "geometry": result_data["geometry"],
        # the validation report (warnings such as "clipped to Nepal" ride here
        # even on the success path so the caller can tell the user)
        "boundary_validation": bv_report.as_dict() if bv_report is not None else None,
        # what the boundary did to sub-areas already on record
        # ({clipped, dropped, unchanged}); None when there was nothing to do
        "sub_areas_reclip": sub_areas_reclip,
    }
