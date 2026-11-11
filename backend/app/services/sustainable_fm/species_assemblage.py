"""Per-block species assemblage + stand inputs for Sustainable Forest
Management (P1).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.3 / §5 P1.

Produces one source-agnostic :class:`SfmBlockInputs` per block, resolved from
whichever inventory the forest has:

    1. stem mapping   — inventory_trees (census; exact >=40 cm stock, mother trees)
    2. field inventory — field_inventory_block_summary (+ dbh_class_breakdown ratio)
    3. prior          — forest_species_association for the FRTC type (no yield)

Both inventory tables are a **two-hop join** off ``calculations``:
``calculations.id`` -> ``inventory_calculations.calculation_id`` (unique) ->
``inventory_trees.inventory_calculation_id``; likewise for
``field_inventory_calculations`` -> ``field_inventory_block_summary``.

Stem mapping has no *sapling* (लाथ्रा) stand type, so a stem-mapped-only block
gets ``saplings_per_ha = None`` -> ``regen_adequate = None`` -> P3 picks the
conservative branch (ख). A field regeneration survey unlocks branch (क).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from app.core.dbh_classifier import DbhClassRegistry
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sustainable_fm.sfm_config import SfmParams
from app.services.sustainable_fm.zone_classifier import ZoneResult

logger = logging.getLogger(__name__)

Source = Literal["stem_mapping", "field_inventory", "prior"]

# अनुसूची-१ species groups. genus (first token, lowercase) → group, with a few
# species-level overrides for the pines. Anything unmapped is "OTHER" and does
# not count toward dominant_group (logged for the curator).
_GENUS_GROUP: dict[str, str] = {
    "shorea": "SAL",
    "dalbergia": "SISSOO_KHAIR",
    "acacia": "SISSOO_KHAIR",
    "senegalia": "SISSOO_KHAIR",
    "bombax": "RIVERINE_ASSOC",
    "adina": "RIVERINE_ASSOC",
    "haldina": "RIVERINE_ASSOC",
    "syzygium": "RIVERINE_ASSOC",
    "albizia": "RIVERINE_ASSOC",
    "trewia": "RIVERINE_ASSOC",
    "schima": "HILL_BROADLEAF",
    "castanopsis": "HILL_BROADLEAF",
    "alnus": "HILL_BROADLEAF",
    "myrica": "HILL_BROADLEAF",
    "engelhardtia": "HILL_BROADLEAF",
    "engelhardia": "HILL_BROADLEAF",
    "rhododendron": "HILL_BROADLEAF",
    "quercus": "TEMPERATE_BROADLEAF",
    "lithocarpus": "TEMPERATE_BROADLEAF",
    "juglans": "TEMPERATE_BROADLEAF",
    "acer": "TEMPERATE_BROADLEAF",
    "abies": "TEMPERATE_CONIFER",
    "picea": "TEMPERATE_CONIFER",
    "tsuga": "TEMPERATE_CONIFER",
    "larix": "TEMPERATE_CONIFER",
    "juniperus": "TEMPERATE_CONIFER",
    "cupressus": "TEMPERATE_CONIFER",
}
_SPECIES_GROUP: dict[str, str] = {
    "pinus roxburghii": "PINE_ROX",
    "pinus kesiya": "PINE_ROX",
    "pinus wallichiana": "PINE_WALL",
    "pinus patula": "PINE_PATULA",
}
_BROADLEAF_GROUPS = {"HILL_BROADLEAF", "TEMPERATE_BROADLEAF", "RIVERINE_ASSOC"}
_CODOMINANT_MIN_SHARE = 30.0


def group_for(scientific: Optional[str], genus: Optional[str] = None) -> str:
    """Map a species name to an अनुसूची-१ group (``"OTHER"`` if none fits)."""
    if not scientific:
        return "OTHER"
    s = " ".join(scientific.lower().split())
    if s in _SPECIES_GROUP:
        return _SPECIES_GROUP[s]
    g = (genus or s.split(" ", 1)[0]).lower().strip()
    if g == "pinus":
        # an unlisted pine → treat as roxburghii-style management
        return "PINE_ROX"
    return _GENUS_GROUP.get(g, "OTHER")


# ─────────────────────────────────────────────────────────────────────────────
# Data contract
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SpeciesShare:
    scientific: str
    local: Optional[str]
    genus: str
    group: str
    share_pct: float


@dataclass(frozen=True)
class SfmBlockInputs:
    block_name: str
    area_ha: float
    dominant_species: list[SpeciesShare] = field(default_factory=list)
    associate_species: list[SpeciesShare] = field(default_factory=list)
    dominant_group: Optional[str] = None
    codominant_group: Optional[str] = None
    seedlings_per_ha: Optional[int] = None  # विरुवा
    saplings_per_ha: Optional[int] = None  # लाथ्रा
    regen_adequate: Optional[bool] = None
    growing_stock_m3_per_ha: Optional[float] = None
    gs_ge40_m3_per_ha: Optional[float] = None
    gs_ge40_m3: Optional[float] = None
    mother_trees_per_ha: Optional[float] = None
    crown_density_pct: int = 50
    origin: Literal["natural", "plantation"] = "natural"
    conversion_target: bool = False
    mean_altitude_m: Optional[float] = None
    invasive_present: bool = False
    riparian: bool = False
    source: Source = "prior"
    unmapped_species: list[str] = field(default_factory=list)
    # how many sample plots the block has (field inventory); 0 = none
    plot_count: int = 0
    # ESA WorldCover's suggestion for the block's land class, which the user may override (block_status.py)
    land_class_suggestion: str = "forest"
    land_class_esa_code: Optional[int] = None
    land_class_esa_pct: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────
def _shares_from_counts(
    counts: dict[str, dict[str, Any]], *, by: str
) -> list[SpeciesShare]:
    """``counts`` = ``{scientific: {"local":.., "vol":.., "n":..}}``. Rank by
    ``by`` (``"vol"`` or ``"n"``); ``share_pct`` is of the ranked total."""
    total = sum(max(v.get(by) or 0.0, 0.0) for v in counts.values()) or 1.0
    out: list[SpeciesShare] = []
    for sci, v in counts.items():
        share = round(max(v.get(by) or 0.0, 0.0) / total * 100.0, 2)
        if share <= 0:
            continue
        genus = (sci.split(" ", 1)[0] if sci else "").lower()
        out.append(
            SpeciesShare(
                scientific=sci,
                local=v.get("local"),
                genus=genus,
                group=group_for(sci, genus),
                share_pct=share,
            )
        )
    out.sort(key=lambda s: s.share_pct, reverse=True)
    return out


def _dominant_and_codominant(
    shares: list[SpeciesShare],
) -> tuple[Optional[str], Optional[str], list[str]]:
    """Summed share by group → the top group + a co-dominant (a second group
    with >= 30 % **that is a broadleaf**, for the pine/broadleaf mix rule).
    Returns ``(dominant, codominant, unmapped_names)``."""
    by_group: dict[str, float] = {}
    unmapped: list[str] = []
    for s in shares:
        if s.group == "OTHER":
            unmapped.append(s.scientific)
            continue
        by_group[s.group] = by_group.get(s.group, 0.0) + s.share_pct
    if not by_group:
        return None, None, unmapped
    ranked = sorted(by_group.items(), key=lambda kv: kv[1], reverse=True)
    dominant = ranked[0][0]
    codominant = next(
        (
            g
            for g, sh in ranked[1:]
            if sh >= _CODOMINANT_MIN_SHARE and g in _BROADLEAF_GROUPS
        ),
        None,
    )
    return dominant, codominant, unmapped


def _block_wkt(block_id, db: Session) -> Optional[str]:
    return db.execute(
        text("SELECT ST_AsText(geometry) FROM forest_blocks WHERE id = :id"),
        {"id": str(block_id)},
    ).scalar()


def _metadata_inputs(calculation_id, db: Session) -> dict[str, Any]:
    """The OP plan's metadata form (unique per calculation). ``{}`` when there
    is no plan yet — SFM runs at analysis time, before an OP exists."""
    row = db.execute(
        text("SELECT plan_metadata FROM operational_plans WHERE calculation_id = :cid"),
        {"cid": str(calculation_id)},
    ).first()
    md = (row[0] if row else None) or {}
    return md.get("user_inputs", {}) or {}


def _invasive_present(names: list[str], db: Session) -> bool:
    if not names:
        return False
    try:
        with db.begin_nested():
            hit = db.execute(
                text(
                    "SELECT 1 FROM biodiversity_species "
                    "WHERE is_invasive AND lower(scientific_name) = ANY(:n) LIMIT 1"
                ),
                {"n": [n.lower() for n in names]},
            ).scalar()
        return bool(hit)
    except Exception:  # noqa: BLE001 -- biodiversity_species optional (test DB)
        logger.debug(
            "_invasive_present: biodiversity_species unavailable", exc_info=True
        )
        return False


def _near_river(geom_wkt: str, db: Session, buffer_m: float) -> bool:
    """Is ``geom_wkt`` within ``buffer_m`` metres of any ``river.river84`` line?

    SFM P14 perf fix: the original ``ST_DWithin(r.shape::geography, …)`` casts
    the indexed side of the join to geography, which PostGIS cannot answer from
    ``sidx_river84_shape`` (a geometry GiST index) — every call fell back to a
    parallel sequential scan of the whole 24.8k-row table (~7-12 s, measured).
    Buffering the *one* query geometry in geography space (cheap, accurate
    metres) and transforming the result back to SRID 4326 lets the
    ``&&`` / ``ST_Intersects`` test run natively against the geometry index
    instead — same result, ~0.03 s. Verified identical hit/miss across
    100/1000/5000/20000 m buffers against this table.
    """
    try:
        with db.begin_nested():
            hit = db.execute(
                text(
                    "WITH buf AS ("
                    "  SELECT ST_Transform("
                    "    ST_Buffer(ST_GeomFromText(:wkt, 4326)::geography, :b)::geometry,"
                    "    4326"
                    "  ) AS g"
                    ") "
                    "SELECT 1 FROM river.river84 r, buf "
                    "WHERE r.shape && buf.g AND ST_Intersects(r.shape, buf.g) LIMIT 1"
                ),
                {"wkt": geom_wkt, "b": buffer_m},
            ).scalar()
        return bool(hit)
    except Exception:  # noqa: BLE001 -- river.river84 optional (test DB)
        logger.debug("_near_river: river.river84 unavailable", exc_info=True)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Source 1 — stem mapping (census)
# ─────────────────────────────────────────────────────────────────────────────
def _stem_mapping_inputs(
    calculation_id, block_key: str, area_ha: float, params: SfmParams, db: Session
) -> Optional[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT it.species, it.local_name, it.dia_cm, it.net_volume,
                   it.stand_type, it.remark
            FROM inventory_trees it
            JOIN inventory_calculations ic ON ic.id = it.inventory_calculation_id
            WHERE ic.calculation_id = :cid AND it.block_name = :bk
            """
        ),
        {"cid": str(calculation_id), "bk": block_key},
    ).fetchall()
    if not rows:
        return None

    counts: dict[str, dict[str, Any]] = {}
    gs_all = 0.0
    gs_ge40 = 0.0
    regen_n = 0
    mother_n = 0
    dbh_min = params.harvestable_dbh_min_cm
    have_vol = any(r.net_volume is not None for r in rows)
    for r in rows:
        sci = (r.species or "").strip()
        vol = float(r.net_volume) if r.net_volume is not None else 0.0
        dia = float(r.dia_cm) if r.dia_cm is not None else 0.0
        c = counts.setdefault(sci, {"local": r.local_name, "vol": 0.0, "n": 0})
        c["vol"] += vol
        c["n"] += 1
        gs_all += vol
        if dia >= dbh_min:
            gs_ge40 += vol
        if (r.stand_type or "").lower() == "regeneration":
            regen_n += 1
        if (r.remark or "") == "Mother Tree":
            mother_n += 1

    shares = _shares_from_counts(counts, by="vol" if have_vol else "n")
    dominant, codominant, unmapped = _dominant_and_codominant(shares)
    a = area_ha or 1.0
    return {
        "dominant_species": shares[:5],
        "associate_species": shares[5:10],
        "dominant_group": dominant,
        "codominant_group": codominant,
        "seedlings_per_ha": int(round(regen_n / a)),
        "saplings_per_ha": None,  # stem mapping has no sapling class
        "regen_adequate": None,
        "growing_stock_m3_per_ha": round(gs_all / a, 4) if have_vol else None,
        "gs_ge40_m3_per_ha": round(gs_ge40 / a, 4) if have_vol else None,
        "gs_ge40_m3": round(gs_ge40, 4) if have_vol else None,
        "mother_trees_per_ha": round(mother_n / a, 4),
        "source": "stem_mapping",
        "unmapped_species": unmapped,
        "_species_names": list(counts.keys()),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Source 2 — field inventory (sample plots)
# ─────────────────────────────────────────────────────────────────────────────
# dbh_class_breakdown class keys whose lower bound is >= 40 cm, taken from the
# DBH registry rather than written out here.
#
# The writer builds its class list from the same registry
# (``DbhClassRegistry.get_system("guideline_2061")`` in field_inventory_service,
# line ~2012), so asking it the same question keeps the two ends of this contract
# moving together. A literal list is how this reader came to disagree with the
# writer in the first place -- it had grown to seven spellings of three classes
# ("60+", "60_plus", "60_plus_", ...) to paper over one genuine contract break.
# There is now exactly one place a class name is written down, the fallback below,
# and it is used only if the registry cannot be reached.
_FALLBACK_GE40_KEYS = ("40_50", "50_60", "60_plus")

_GE40_KEYS: Optional[frozenset] = None


def _norm_class_key(key: Any) -> str:
    """``"60+"`` / ``"60_plus_"`` / ``"40-50"`` all normalise to a registry key."""
    text = str(key).strip().lower().replace("+", "_plus_")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _ge40_class_keys() -> frozenset:
    """Normalised class keys >= 40 cm, from the registry the writer itself uses."""
    global _GE40_KEYS
    if _GE40_KEYS is not None:
        return _GE40_KEYS
    keys: frozenset = frozenset()
    try:
        classes = DbhClassRegistry.get_system("guideline_2061")
        if hasattr(classes, "classes"):  # tolerate either shape
            classes = classes.classes
        keys = frozenset(
            _norm_class_key(c.key) for c in classes if float(c.lower or 0) >= 40.0
        )
    except Exception as exc:  # pragma: no cover - registry unavailable
        logger.warning(
            "[sfm] dbh class registry unavailable (%s); using the documented "
            "guideline_2061 >= 40 cm classes %s instead",
            exc,
            list(_FALLBACK_GE40_KEYS),
        )
    if not keys:
        keys = frozenset(_norm_class_key(k) for k in _FALLBACK_GE40_KEYS)
    _GE40_KEYS = keys
    return keys


def _field_inventory_inputs(
    calculation_id, block_key: str, area_ha: float, params: SfmParams, db: Session
) -> Optional[dict[str, Any]]:
    summ = db.execute(
        text(
            """
            SELECT s.regeneration_per_ha, s.sapling_per_ha,
                   s.total_growing_stock_m3_per_ha, s.dbh_class_breakdown
            FROM field_inventory_block_summary s
            JOIN field_inventory_calculations fc
                 ON fc.id = s.field_inventory_calculation_id
            WHERE fc.calculation_id = :cid AND s.block_name = :bk
            """
        ),
        {"cid": str(calculation_id), "bk": block_key},
    ).first()
    if summ is None:
        return None

    spp = db.execute(
        text(
            """
            SELECT m.species_scientific AS sci, m.species_local AS local,
                   COUNT(*) AS n, COALESCE(SUM(m.net_volume), 0) AS vol
            FROM field_inventory_measurements m
            JOIN field_inventory_sample_plots p ON p.id = m.sample_plot_id
            JOIN field_inventory_calculations fc
                 ON fc.id = p.field_inventory_calculation_id
            WHERE fc.calculation_id = :cid AND p.block_name = :bk
              AND m.stand_type IN ('Pole', 'Tree')
            GROUP BY m.species_scientific, m.species_local
            """
        ),
        {"cid": str(calculation_id), "bk": block_key},
    ).fetchall()
    counts = {
        r.sci.strip(): {"local": r.local, "vol": float(r.vol or 0.0), "n": int(r.n)}
        for r in spp
        if r.sci
    }
    have_vol = any(v["vol"] > 0 for v in counts.values())
    shares = _shares_from_counts(counts, by="vol" if have_vol else "n")
    dominant, codominant, unmapped = _dominant_and_codominant(shares)
    plot_count = int(
        db.execute(
            text(
                """
                SELECT COUNT(DISTINCT p.id)
                FROM field_inventory_sample_plots p
                JOIN field_inventory_calculations fc ON fc.id = p.field_inventory_calculation_id
                WHERE fc.calculation_id = :cid AND p.block_name = :bk
                """
            ),
            {"cid": str(calculation_id), "bk": block_key},
        ).scalar()
        or 0
    )

    gs_per_ha = (
        float(summ.total_growing_stock_m3_per_ha)
        if summ.total_growing_stock_m3_per_ha is not None
        else None
    )
    ge40_per_ha, ge40_abs = _ge40_from_breakdown(
        summ.dbh_class_breakdown, gs_per_ha, area_ha
    )

    seed = summ.regeneration_per_ha
    sap = summ.sapling_per_ha
    adequate = (
        (seed >= params.seedling_threshold and sap >= params.sapling_threshold)
        if seed is not None and sap is not None
        else None
    )
    return {
        "dominant_species": shares[:5],
        "associate_species": shares[5:10],
        "dominant_group": dominant,
        "codominant_group": codominant,
        "seedlings_per_ha": int(seed) if seed is not None else None,
        "saplings_per_ha": int(sap) if sap is not None else None,
        "regen_adequate": adequate,
        "growing_stock_m3_per_ha": gs_per_ha,
        "gs_ge40_m3_per_ha": ge40_per_ha,
        "gs_ge40_m3": ge40_abs,
        "mother_trees_per_ha": None,
        "source": "field_inventory",
        "plot_count": plot_count,
        "unmapped_species": unmapped,
        "_species_names": list(counts.keys()),
    }


# The measures a ``dbh_class_breakdown`` value carries, in the order they are
# preferred. One basis is chosen for the whole breakdown, not per class, so a
# volume and a stem count can never end up in the same sum.
#
# This function spent its life looking for ``timber`` and ``count``, which have
# never existed: the writer has always stored ``timber_m3_per_ha`` and
# ``count_per_ha`` (the per-hectare names, P0/P2b). So ``t`` was 0.0 for every
# class, ``total`` was 0.0, and the function returned ``(None, None)`` -- which the
# page renders as *"Indicative - pending inventory"*. The inventory was complete;
# the page was reporting that it could not read one number, in the one phrasing
# that sounds like the data is simply not in yet.
#
# ``firewood_m3_per_ha`` is emitted by the writer and deliberately **not** read
# here: firewood is not growing stock, and adding it to the denominator would
# understate the >= 40 cm share. The bare names are kept as later fallbacks so a
# differently-shaped value is never silently read as zero.
_BREAKDOWN_MEASURE_KEYS = ("timber_m3_per_ha", "timber", "count_per_ha", "count")
_BREAKDOWN_VOLUME_KEYS = ("timber_m3_per_ha", "timber")


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ge40_from_breakdown(
    breakdown: Any, gs_per_ha: Optional[float], area_ha: float
) -> tuple[Optional[float], Optional[float]]:
    """Use ``dbh_class_breakdown`` only for the >= 40 cm *ratio*, then apply it to
    the authoritative per-ha growing stock (D10). ``(None, None)`` when the
    breakdown is missing, or when no recognised measure key is found.

    That second case now **logs**. A breakdown whose shape this function does not
    recognise is a contract break between the writer and the reader, and the old
    behaviour -- total 0.0, return None, page says "pending inventory" -- turned
    that into a silent wrong answer. Silence is what let it survive; the fix is not
    only the key names but refusing to fail quietly.
    """
    if not isinstance(breakdown, dict) or gs_per_ha is None:
        return None, None
    values = [v for v in breakdown.values() if isinstance(v, dict)]
    if not values:
        return None, None
    basis = None
    for candidate in _BREAKDOWN_MEASURE_KEYS:
        if any(_as_float(v.get(candidate)) is not None for v in values):
            basis = candidate
            break
    if basis is None:
        logger.warning(
            "[sfm] dbh_class_breakdown has no recognised measure key "
            "(looked for %s) for %d class(es); growing stock >= 40 cm cannot be "
            "derived and the yield figures will read as pending. Offending keys: %s",
            _BREAKDOWN_MEASURE_KEYS,
            len(breakdown),
            sorted(str(k) for k, v in breakdown.items() if isinstance(v, dict))[:8],
        )
        return None, None
    total = 0.0
    ge40 = 0.0
    unrecognised: list[str] = []
    ge40_keys = _ge40_class_keys()
    for key, val in breakdown.items():
        t = None
        if isinstance(val, dict):
            t = _as_float(val.get(basis))
            if t is None:
                unrecognised.append(str(key))
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            t = float(val)
        if t is None:
            t = 0.0
        total += t
        if _norm_class_key(key) in ge40_keys:
            ge40 += t
    if unrecognised:
        logger.warning(
            "[sfm] %d of %d dbh_class_breakdown entries had no %r and were read "
            "as 0 (measure basis %r): %s",
            len(unrecognised),
            len(breakdown),
            basis,
            basis,
            sorted(unrecognised)[:8],
        )
    if total <= 0:
        return None, None
    ratio = max(0.0, min(1.0, ge40 / total))
    per_ha = round(gs_per_ha * ratio, 4)
    return per_ha, round(per_ha * (area_ha or 1.0), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Source 3 — prior (no inventory)
# ─────────────────────────────────────────────────────────────────────────────
def _prior_inputs(geom_wkt: str, db: Session) -> dict[str, Any]:
    """FRTC forest-type raster → ``forest_species_association`` → names. No
    counts, no yield. Empty assemblage when the raster / tables are absent."""
    shares: list[SpeciesShare] = []
    try:
        with db.begin_nested():
            ftype = db.execute(
                text(
                    """
                    SELECT ft.id
                    FROM (
                        SELECT (pvc).value AS v, SUM((pvc).count) AS c
                        FROM (
                            SELECT ST_ValueCount(
                                ST_Clip(rast, ST_GeomFromText(:wkt, 4326))
                            ) AS pvc
                            FROM rasters.forest_type
                            WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                        ) s
                        WHERE (pvc).value > 0
                        GROUP BY (pvc).value ORDER BY c DESC LIMIT 1
                    ) top
                    JOIN forest_types ft ON ft.pixel_value = top.v
                    """
                ),
                {"wkt": geom_wkt},
            ).scalar()
            if ftype is not None:
                rows = db.execute(
                    text(
                        """
                        SELECT tsc.scientific_name AS sci, tsc.local_name AS local,
                               tsc.genus AS genus, fsa.role AS role,
                               fsa.availability_rank AS rank
                        FROM forest_species_association fsa
                        JOIN tree_species_coefficients tsc ON tsc.id = fsa.species_id
                        WHERE fsa.forest_type_id = :ft
                        ORDER BY fsa.availability_rank NULLS LAST
                        """
                    ),
                    {"ft": ftype},
                ).fetchall()
                n = len(rows) or 1
                for i, r in enumerate(rows):
                    sci = (r.sci or "").strip()
                    if not sci:
                        continue
                    shares.append(
                        SpeciesShare(
                            scientific=sci,
                            local=r.local,
                            genus=(r.genus or sci.split(" ", 1)[0]).lower(),
                            group=group_for(sci, r.genus),
                            share_pct=round((n - i) / n * 100.0, 2),
                        )
                    )
    except Exception:  # noqa: BLE001 -- FRTC raster / association tables optional
        logger.debug(
            "_prior_inputs: FRTC forest-type lookup unavailable", exc_info=True
        )

    dominant, codominant, unmapped = _dominant_and_codominant(shares)
    return {
        "dominant_species": shares[:5],
        "associate_species": shares[5:10],
        "dominant_group": dominant,
        "codominant_group": codominant,
        "source": "prior",
        "unmapped_species": unmapped,
        "_species_names": [s.scientific for s in shares],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def resolve_block_inputs(
    calc,
    block,
    params: SfmParams,
    db: Session,
    *,
    zone: Optional[ZoneResult] = None,
) -> SfmBlockInputs:
    """One :class:`SfmBlockInputs` for ``block`` (a ``ForestBlock`` row).
    ``calc`` is the owning ``Calculation`` (needs ``.id``). Pass ``zone`` if
    already classified, to skip a physiography read for the riparian check."""
    block_key = (block.block_name or block.name or "").strip()
    area_ha = float(block.area_hectares or 0.0)
    geom_wkt = _block_wkt(block.id, db) or ""

    # The block's OWN sample plots decide its forest type (owner, 2026-10-06). Stem mapping is done in one block
    # only, chosen from the plot inventory, so it must not be the basis of a type; without plots the block gets the
    # raster prior as an ESTIMATE only (block_status marks it "inventory missing").
    core = _field_inventory_inputs(calc.id, block_key, area_ha, params, db) or _prior_inputs(geom_wkt, db)
    species_names = core.pop("_species_names", [])

    md = _metadata_inputs(calc.id, db)
    origin = "plantation" if md.get("forest_type") == "वृक्षारोपण" else "natural"
    crown = md.get("avg_crown_density_pct")
    if crown not in (None, ""):
        crown_pct = int(crown)
    elif params.crown_density_estimate_source != "none" and geom_wkt:
        # P10 — no measured value → estimate from the canopy / ESA raster
        from app.services.sustainable_fm.crown_density import estimate_crown_density

        est = estimate_crown_density(geom_wkt, params.crown_density_estimate_source, db)
        crown_pct = est if est is not None else params.crown_density_default
    else:
        crown_pct = params.crown_density_default

    from app.services.sustainable_fm.block_status import esa_land_class

    land_class, esa_code, esa_pct = esa_land_class(db, geom_wkt)

    dom_phys = zone.dom_phys if zone else ""
    mean_alt = zone.mean_altitude_m if zone else None
    riparian = dom_phys == "Inner River Valley" or (
        bool(geom_wkt) and _near_river(geom_wkt, db, params.riparian_buffer_m)
    )

    return SfmBlockInputs(
        block_name=block_key,
        area_ha=area_ha,
        crown_density_pct=crown_pct,
        origin=origin,  # type: ignore[arg-type]
        conversion_target=bool(md.get("conversion_target")),
        mean_altitude_m=mean_alt,
        invasive_present=_invasive_present(species_names, db),
        riparian=riparian,
        land_class_suggestion=land_class,
        land_class_esa_code=esa_code,
        land_class_esa_pct=esa_pct,
        **core,
    )


__all__ = [
    "Source",
    "SpeciesShare",
    "SfmBlockInputs",
    "group_for",
    "resolve_block_inputs",
]
