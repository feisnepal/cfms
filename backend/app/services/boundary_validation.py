"""Forest-boundary upload validation (UNIFIED_UPLOAD_PLAN.md §5).

One entry point — :func:`validate_forest_boundary` — runs a fixed set of checks
against a candidate boundary WKT (EPSG:4326) and returns a structured report of
``error`` (blocks the upload) and ``warning`` (notify the user, allow) findings.

Rules, in order:
  R0  geometry is valid, non-empty, polygonal; latitude/longitude not swapped.
  R1  the boundary is measured against the ``admin.province`` union:
        - fully inside (bar a <0.5% border sliver) → accepted unchanged;
        - fully outside → rejected (error);
        - straddling the border → the outside part is **clipped away**, the
          inside part kept, and a warning tells the user what was removed.
      The rest of the checks then run on the clipped geometry.
  R2  the (clipped) area does not exceed ``MAX_AREA_HA`` (1000 ha).
  R3  built-up + cropland is at most ``MAX_BUILTUP_CROPLAND_PCT`` (40%) of the
      area, from ``rasters.esa_world_cover`` (ESA WorldCover classes 50 + 40).
  R4  if the boundary overlaps a protected area it must lie in a Buffer Zone;
      non-Buffer-Zone protected land up to ``PA_NON_BUFFER_TOLERANCE_PCT`` (5%)
      is a warning, beyond that an error
      (``admin.protected_area.description``).

Each check runs in its own SAVEPOINT: a missing reference table degrades to an
``info`` finding — a deployment without the admin/raster layers must not block
every upload — and one failed check never poisons the request's transaction.

:func:`check_forest_boundary` returns a :class:`BoundaryCheckResult` carrying the
report *and* the effective (possibly clipped) geometry; :func:`enforce_boundary_rules`
is the same but raises :class:`BoundaryRulesViolation` on any error.
:func:`validate_forest_boundary` is kept as a report-only shim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.upload.schema import (
    ESA_BUILT_UP as _ESA_BUILT_UP,
    ESA_CROPLAND as _ESA_CROPLAND,
    MAX_AREA_HA,
    MAX_BUILTUP_CROPLAND_PCT,
    NEPAL_OUTSIDE_TOLERANCE_PCT,
    PA_NON_BUFFER_TOLERANCE_PCT,
)

logger = logging.getLogger(__name__)

# Thresholds live in the canonical upload schema (app.services.upload.schema) so
# the Workbook generator, the validator and this module all agree. Re-exported
# above; only the bounding box is local.
#
# generous envelope of the country; the precise test is R1's polygon check.
NEPAL_BBOX = (79.9, 26.3, 88.4, 30.6)  # lon_min, lat_min, lon_max, lat_max

__all__ = [
    "MAX_AREA_HA",
    "MAX_BUILTUP_CROPLAND_PCT",
    "PA_NON_BUFFER_TOLERANCE_PCT",
    "NEPAL_OUTSIDE_TOLERANCE_PCT",
    "NEPAL_BBOX",
    "Finding",
    "BoundaryReport",
    "BoundaryCheckResult",
    "BoundaryRulesViolation",
    "validate_forest_boundary",
    "check_forest_boundary",
    "enforce_boundary_rules",
]


@dataclass
class Finding:
    code: str
    level: str  # "error" | "warning" | "info"
    message_en: str
    message_ne: str
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "level": self.level,
            "message_en": self.message_en,
            "message_ne": self.message_ne,
            "detail": self.detail,
        }


@dataclass
class BoundaryReport:
    findings: list[Finding] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def add(self, *a, **kw) -> None:
        self.findings.append(Finding(*a, **kw))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [f.as_dict() for f in self.errors],
            "warnings": [f.as_dict() for f in self.warnings],
            "info": [f.as_dict() for f in self.findings if f.level == "info"],
            "facts": self.facts,
        }


# ── individual checks — each may raise; the orchestrator isolates them ───
def _check_geometry(db: Session, wkt: str, rep: BoundaryReport) -> bool:
    """R0. Returns False when the geometry is unusable (skip the rest)."""
    row = db.execute(
        text(
            """
            SELECT ST_IsValid(g) AS valid,
                   ST_IsValidReason(g) AS reason,
                   GeometryType(g) AS gtype,
                   ST_IsEmpty(g) AS empty,
                   ST_NumGeometries(g) AS nparts,
                   ST_XMin(g) AS xmin, ST_XMax(g) AS xmax,
                   ST_YMin(g) AS ymin, ST_YMax(g) AS ymax
            FROM (SELECT ST_GeomFromText(:wkt, 4326) AS g) s
            """
        ),
        {"wkt": wkt},
    ).first()

    if row is None or row.empty:
        rep.add("boundary.empty", "error", "The boundary is empty.", "सिमाना खाली छ।")
        return False

    if (row.gtype or "").upper() not in ("POLYGON", "MULTIPOLYGON"):
        rep.add(
            "boundary.not_polygon",
            "error",
            f"The boundary must be a polygon, not {row.gtype}.",
            f"सिमाना बहुभुज हुनुपर्छ, {row.gtype} होइन।",
            {"geometry_type": row.gtype},
        )
        return False

    if not row.valid:
        rep.add(
            "boundary.invalid_geometry",
            "error",
            f"The boundary polygon is invalid: {row.reason}.",
            f"सिमाना बहुभुज अमान्य छ: {row.reason}।",
            {"reason": row.reason},
        )
        return False

    if (row.nparts or 1) > 1:
        rep.add(
            "boundary.multipart",
            "warning",
            f"The boundary has {row.nparts} separate parts — confirm this is one forest.",
            f"सिमानाका {row.nparts} अलग-अलग भाग छन् — यो एउटै वन हो कि पुष्टि गर्नुहोस्।",
            {"parts": int(row.nparts)},
        )

    in_bbox = (
        NEPAL_BBOX[0] <= row.xmin
        and row.xmax <= NEPAL_BBOX[2]
        and NEPAL_BBOX[1] <= row.ymin
        and row.ymax <= NEPAL_BBOX[3]
    )
    if not in_bbox:
        swapped_in_bbox = (
            NEPAL_BBOX[0] <= row.ymin
            and row.ymax <= NEPAL_BBOX[2]
            and NEPAL_BBOX[1] <= row.xmin
            and row.xmax <= NEPAL_BBOX[3]
        )
        if swapped_in_bbox:
            # A clean swap lands the whole polygon in Nepal's box mirrored —
            # that is a data error, not a border case, so stop here.
            rep.add(
                "boundary.latlon_swapped",
                "error",
                "The coordinates look like latitude and longitude are swapped.",
                "निर्देशांकमा अक्षांश र देशान्तर साटिएको जस्तो देखिन्छ।",
            )
            return False
        # Otherwise: outside the rough envelope, but the precise verdict — and
        # any border clipping — is R1's job against admin.province.
    return True


def _nepal_clip(db: Session, wkt: str, rep: BoundaryReport) -> Optional[str]:
    """R1 — measure the boundary against the ``admin.province`` union.

    Returns the **clipped** WKT (intersection with Nepal, as a valid
    (multi)polygon) when the boundary straddles the border, ``None`` when it is
    left unchanged. Adds an ``error`` when the boundary is entirely outside
    Nepal, and an ``info`` when the province layer is unavailable.
    """
    row = db.execute(
        text(
            """
            WITH b AS (SELECT ST_MakeValid(ST_GeomFromText(:wkt, 4326)) g),
                 np AS (SELECT ST_Union(shape) g FROM admin.province)
            SELECT
                ST_Area(b.g::geography) / 10000.0 AS total_ha,
                ST_Area(
                    ST_Intersection(b.g, np.g)::geography
                ) / 10000.0 AS inside_ha,
                ST_AsText(
                    ST_Multi(
                        ST_CollectionExtract(
                            ST_MakeValid(ST_Intersection(b.g, np.g)), 3
                        )
                    )
                ) AS inside_wkt
            FROM b, np
            """
        ),
        {"wkt": wkt},
    ).first()
    if row is None or row.total_ha in (None, 0):
        return None

    total = float(row.total_ha)
    inside = float(row.inside_ha or 0.0)
    outside = max(total - inside, 0.0)
    outside_pct = 100.0 * outside / total if total else 0.0
    rep.facts["outside_nepal_pct"] = round(outside_pct, 3)

    # entirely outside — nothing to keep
    if inside <= 0.0 or not row.inside_wkt or "EMPTY" in row.inside_wkt:
        rep.add(
            "boundary.outside_nepal",
            "error",
            "The forest boundary is outside Nepal.",
            "वन सिमाना नेपालबाहिर छ।",
            {"outside_pct": round(outside_pct, 2)},
        )
        return None

    # inside, bar a hairline border sliver — accept as posted
    if outside_pct <= NEPAL_OUTSIDE_TOLERANCE_PCT:
        return None

    # straddles the border — keep the inside part, tell the user
    rep.add(
        "boundary.clipped_to_nepal",
        "warning",
        f"{outside_pct:.1f}% of the boundary ({outside:,.1f} ha) fell outside "
        f"Nepal and was removed; the remaining {inside:,.1f} ha was kept.",
        f"सिमानाको {outside_pct:.1f}% ({outside:,.1f} हेक्टर) नेपालबाहिर परेकाले "
        f"हटाइयो; बाँकी {inside:,.1f} हेक्टर राखियो।",
        {
            "removed_ha": round(outside, 2),
            "removed_pct": round(outside_pct, 2),
            "kept_ha": round(inside, 2),
        },
    )
    return row.inside_wkt


def _check_area(db: Session, wkt: str, rep: BoundaryReport) -> None:
    """R2 — area must not exceed MAX_AREA_HA."""
    area_ha = db.execute(
        text("SELECT ST_Area(ST_GeomFromText(:wkt, 4326)::geography) / 10000.0"),
        {"wkt": wkt},
    ).scalar()
    if area_ha is None:
        return
    area_ha = float(area_ha)
    rep.facts["area_ha"] = round(area_ha, 2)
    if area_ha > MAX_AREA_HA:
        rep.add(
            "boundary.area_exceeds_limit",
            "error",
            f"The forest area is {area_ha:,.0f} ha — the limit is {MAX_AREA_HA:,.0f} ha.",
            f"वन क्षेत्रफल {area_ha:,.0f} हेक्टर छ — सीमा {MAX_AREA_HA:,.0f} हेक्टर हो।",
            {"area_ha": round(area_ha, 2), "limit_ha": MAX_AREA_HA},
        )
    elif area_ha < 0.1:
        rep.add(
            "boundary.area_implausibly_small",
            "warning",
            f"The forest area is only {area_ha:.3f} ha — check the units and CRS.",
            f"वन क्षेत्रफल केवल {area_ha:.3f} हेक्टर छ — एकाइ र CRS जाँच्नुहोस्।",
            {"area_ha": round(area_ha, 4)},
        )


def _check_builtup_cropland(db: Session, wkt: str, rep: BoundaryReport) -> None:
    """R3 — built-up + cropland ≤ MAX_BUILTUP_CROPLAND_PCT of the area, from
    ESA WorldCover (rasters.esa_world_cover). Mirrors analysis.analyze_landcover_geometry
    but inlined so a failure raises into this check's savepoint."""
    rows = db.execute(
        text(
            """
            SELECT (pvc).value AS code, SUM((pvc).count) AS n
            FROM (
                SELECT ST_ValueCount(
                    ST_Clip(rast, ST_GeomFromText(:wkt, 4326))
                ) AS pvc
                FROM rasters.esa_world_cover
                WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            ) s
            WHERE (pvc).value IS NOT NULL AND (pvc).value > 0
            GROUP BY (pvc).value
            """
        ),
        {"wkt": wkt},
    ).fetchall()
    total = sum(int(r.n) for r in rows)
    if total <= 0:
        rep.add(
            "boundary.landcover_no_coverage",
            "info",
            "The land-cover raster does not cover this location.",
            "भू-आवरण रास्टरले यो स्थान समेट्दैन।",
        )
        return
    by_code = {int(r.code): int(r.n) for r in rows}
    built = 100.0 * by_code.get(_ESA_BUILT_UP, 0) / total
    crop = 100.0 * by_code.get(_ESA_CROPLAND, 0) / total
    non_forest = round(built + crop, 2)
    rep.facts["built_up_pct"] = round(built, 2)
    rep.facts["cropland_pct"] = round(crop, 2)
    rep.facts["built_up_plus_cropland_pct"] = non_forest
    if non_forest > MAX_BUILTUP_CROPLAND_PCT:
        rep.add(
            "boundary.builtup_cropland_exceeds_limit",
            "error",
            f"{non_forest:.0f}% of the area is built-up or cultivated "
            f"(built-up {built:.0f}% + cropland {crop:.0f}%) — the limit is "
            f"{MAX_BUILTUP_CROPLAND_PCT:.0f}%.",
            f"क्षेत्रको {non_forest:.0f}% बस्ती वा खेतीयोग्य छ "
            f"(बस्ती {built:.0f}% + कृषि {crop:.0f}%) — सीमा "
            f"{MAX_BUILTUP_CROPLAND_PCT:.0f}% हो।",
            {
                "built_up_pct": round(built, 2),
                "cropland_pct": round(crop, 2),
                "total_pct": non_forest,
                "limit_pct": MAX_BUILTUP_CROPLAND_PCT,
            },
        )


def _check_protected_area(db: Session, wkt: str, rep: BoundaryReport) -> None:
    """R4 — overlap with a protected area must be within its Buffer Zone."""
    row = db.execute(
        text(
            """
            WITH b AS (SELECT ST_MakeValid(ST_GeomFromText(:wkt, 4326)) g),
                 pa AS (
                     SELECT p.description AS descr,
                            p."protected area name" AS pname,
                            ST_Intersection(b.g, ST_MakeValid(p.geom)) AS ig
                     FROM admin.protected_area p, b
                     WHERE ST_Intersects(b.g, p.geom)
                 )
            SELECT
                ST_Area((SELECT g FROM b)::geography) / 10000.0 AS total_ha,
                COALESCE(SUM(CASE WHEN descr = 'Buffer Zone'
                    THEN ST_Area(ig::geography) END), 0) / 10000.0 AS bz_ha,
                COALESCE(SUM(CASE WHEN descr <> 'Buffer Zone'
                    THEN ST_Area(ig::geography) END), 0) / 10000.0 AS non_bz_ha,
                string_agg(DISTINCT descr, ', ') AS descrs,
                string_agg(DISTINCT pname, ', ') AS names
            FROM pa
            """
        ),
        {"wkt": wkt},
    ).first()
    if row is None:
        return
    total_ha = float(row.total_ha or 0)
    bz_ha = float(row.bz_ha or 0)
    non_bz_ha = float(row.non_bz_ha or 0)
    if total_ha <= 0 or (bz_ha <= 0 and non_bz_ha <= 0):
        rep.facts["protected_area"] = "outside"
        return

    names = row.names or "a protected area"
    descrs = row.descrs or ""
    non_bz_pct = 100.0 * non_bz_ha / total_ha if total_ha else 0.0
    rep.facts["protected_area"] = {
        "names": names,
        "types": descrs,
        "buffer_zone_ha": round(bz_ha, 2),
        "non_buffer_ha": round(non_bz_ha, 2),
        "non_buffer_pct": round(non_bz_pct, 2),
    }

    if non_bz_ha <= 0:
        rep.add(
            "boundary.protected_area_buffer_zone",
            "info",
            f"The boundary lies within the Buffer Zone of {names}.",
            f"सिमाना {names} को मध्यवर्ती क्षेत्रभित्र पर्छ।",
        )
        return

    non_buffer_types = ", ".join(
        d for d in (descrs or "").split(", ") if d and d != "Buffer Zone"
    )
    if non_bz_pct <= PA_NON_BUFFER_TOLERANCE_PCT:
        rep.add(
            "boundary.protected_area_non_buffer_tolerance",
            "warning",
            f"{non_bz_pct:.1f}% of the forest falls inside {names} "
            f"({non_buffer_types}), outside its Buffer Zone. This is within the "
            f"{PA_NON_BUFFER_TOLERANCE_PCT:.0f}% tolerance — confirm it is intended.",
            f"वनको {non_bz_pct:.1f}% भाग {names} ({non_buffer_types}) भित्र, "
            f"मध्यवर्ती क्षेत्रबाहिर पर्छ। यो {PA_NON_BUFFER_TOLERANCE_PCT:.0f}% "
            f"सहनशीलता भित्र छ — यो जानाजानी हो कि पुष्टि गर्नुहोस्।",
            {"non_buffer_pct": round(non_bz_pct, 2)},
        )
    else:
        rep.add(
            "boundary.protected_area_outside_buffer_zone",
            "error",
            f"{non_bz_pct:.1f}% of the forest is inside {names} ({non_buffer_types}), "
            f"outside its Buffer Zone — the limit is {PA_NON_BUFFER_TOLERANCE_PCT:.0f}%. "
            f"A community forest inside a protected area must lie within the Buffer Zone.",
            f"वनको {non_bz_pct:.1f}% भाग {names} ({non_buffer_types}) भित्र, "
            f"मध्यवर्ती क्षेत्रबाहिर पर्छ — सीमा {PA_NON_BUFFER_TOLERANCE_PCT:.0f}% हो। "
            f"संरक्षित क्षेत्रभित्रको सामुदायिक वन मध्यवर्ती क्षेत्रभित्रै हुनुपर्छ।",
            {
                "non_buffer_pct": round(non_bz_pct, 2),
                "limit_pct": PA_NON_BUFFER_TOLERANCE_PCT,
            },
        )


# ── orchestrator ────────────────────────────────────────────────────────
_UNAVAILABLE = {
    "_nepal_clip": (
        "boundary.nepal_check_unavailable",
        "Could not verify the boundary is inside Nepal (reference layer unavailable).",
        "सिमाना नेपालभित्र छ भनी पुष्टि गर्न सकिएन (सन्दर्भ तह उपलब्ध छैन)।",
    ),
    "_check_area": (
        "boundary.area_check_unavailable",
        "Could not compute the boundary area.",
        "सिमानाको क्षेत्रफल गणना गर्न सकिएन।",
    ),
    "_check_builtup_cropland": (
        "boundary.landcover_unavailable",
        "Could not check land cover (raster layer unavailable).",
        "भू-आवरण जाँच्न सकिएन (रास्टर तह उपलब्ध छैन)।",
    ),
    "_check_protected_area": (
        "boundary.protected_area_check_unavailable",
        "Could not check protected areas (reference layer unavailable).",
        "संरक्षित क्षेत्र जाँच्न सकिएन (सन्दर्भ तह उपलब्ध छैन)।",
    ),
}


@dataclass
class BoundaryCheckResult:
    """Outcome of :func:`check_forest_boundary`."""

    report: BoundaryReport
    #: the geometry to actually store — the input WKT, or its clip to Nepal
    effective_wkt: str
    #: True when R1 removed an out-of-Nepal part
    clipped: bool = False


def check_forest_boundary(
    db: Session, wkt: str, *, forest_name: Optional[str] = None
) -> BoundaryCheckResult:
    """Run every boundary rule against *wkt* (EPSG:4326).

    Never raises. R1 may replace the geometry with its clip to the
    ``admin.province`` union; R2–R4 then run on that clipped geometry. Each
    check runs in its own SAVEPOINT; one that cannot run (missing reference
    table, no raster coverage) degrades to an ``info`` finding and leaves the
    request transaction usable.
    """
    rep = BoundaryReport()
    if forest_name:
        rep.facts["forest_name"] = forest_name

    try:
        with db.begin_nested():
            usable = _check_geometry(db, wkt, rep)
    except Exception:  # noqa: BLE001
        logger.warning("boundary geometry check failed", exc_info=True)
        rep.add(
            "boundary.unreadable",
            "error",
            "The boundary geometry could not be read.",
            "सिमानाको ज्यामिति पढ्न सकिएन।",
        )
        return BoundaryCheckResult(rep, wkt, False)
    if not usable:
        return BoundaryCheckResult(rep, wkt, False)

    # R1 — Nepal province clip. Its result (a clipped WKT) feeds R2–R4.
    effective = wkt
    clipped = False
    try:
        with db.begin_nested():
            _clip = _nepal_clip(db, wkt, rep)
        if _clip:
            effective, clipped = _clip, True
    except Exception:  # noqa: BLE001
        logger.warning("boundary check _nepal_clip failed", exc_info=True)
        code, en, ne = _UNAVAILABLE["_nepal_clip"]
        rep.add(code, "info", en, ne)

    if rep.errors:  # fully outside Nepal — no point measuring area / cover
        return BoundaryCheckResult(rep, effective, clipped)

    for check in (_check_area, _check_builtup_cropland, _check_protected_area):
        try:
            with db.begin_nested():
                check(db, effective, rep)
        except Exception:  # noqa: BLE001 -- one failed check must not sink the report
            logger.warning("boundary check %s failed", check.__name__, exc_info=True)
            code, en, ne = _UNAVAILABLE[check.__name__]
            rep.add(code, "info", en, ne)

    return BoundaryCheckResult(rep, effective, clipped)


def validate_forest_boundary(
    db: Session, wkt: str, *, forest_name: Optional[str] = None
) -> BoundaryReport:
    """Report-only shim over :func:`check_forest_boundary` (never raises)."""
    return check_forest_boundary(db, wkt, forest_name=forest_name).report


# ── enforcement wrapper — one contract for every boundary-write path ────
class BoundaryRulesViolation(ValueError):
    """Raised by :func:`enforce_boundary_rules` when the boundary has errors.

    Carries ``.report`` (the :class:`BoundaryReport`) and ``.detail`` — the
    ``{code, message, boundary_validation}`` dict every endpoint returns as the
    body of its HTTP 422.
    """

    def __init__(self, report: "BoundaryReport"):
        self.report = report
        self.detail = {
            "code": "boundary_validation_failed",
            "message": "; ".join(f.message_en for f in report.errors)
            or "The forest boundary did not pass validation.",
            "boundary_validation": report.as_dict(),
        }
        super().__init__(self.detail["message"])


def enforce_boundary_rules(
    db: Session, wkt: str, *, forest_name: Optional[str] = None
) -> BoundaryCheckResult:
    """Run the boundary rules and raise :class:`BoundaryRulesViolation` on any
    error; otherwise return the :class:`BoundaryCheckResult` — whose
    ``effective_wkt`` the caller must store (it may be the input clipped to
    Nepal) and whose ``report`` may still carry warnings to surface. The single
    gate for every path that sets a forest boundary — upload, draw, import,
    edit, overlap-confirm, draft convert.
    """
    result = check_forest_boundary(db, wkt, forest_name=forest_name)
    if not result.report.ok:
        raise BoundaryRulesViolation(result.report)
    return result
