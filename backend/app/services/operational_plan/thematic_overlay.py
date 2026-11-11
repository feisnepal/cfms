"""Thematic map renderer — turns a ThematicMapSpec into a PNG.

THEMATIC_MAP_VARIABLES_PLAN §3.7 / P1. A sibling of
``plan_map_service.generate_standard_map`` (the legacy ``map:*`` renderer) —
kept separate so the legacy path is byte-for-byte untouched (the P1 invariant).
Reuses the legacy module's geometry helpers, frame primitives and disk cache.

P1 techniques: ``choropleth`` (numeric + categorical), ``choropleth_div``
(diverging), ``bivariate`` (3×3), ``dasymetric`` (choropleth clipped to the
operable area), ``alpha`` (value-by-alpha), ``graduated`` /
``graduated_nested`` (proportional centroid symbols), plus ``show_value_labels``.
Centroid glyphs, small multiples, surfaces, flow and ``opsmap`` land in P5+.

P1 renders on a white ground (data + boundary + graticule); the basemap policy
(§3.5.2 — ``canvas_light`` / ``hillshade`` / …) is wired in P5a.
"""

from __future__ import annotations

import io
import logging
import math
from uuid import UUID

from sqlalchemy.orm import Session

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from shapely.geometry import MultiPolygon, Polygon

from app.core import semantic_palettes as sp
from app.core.fonts import dev_bold_font_prop, dev_font_prop
from app.core.text_shaping import save_figure
from app.utils.number_format import format_devanagari
from app.services.management_plan_docx import plan_map_service as pms
from app.services.operational_plan import prereq_check
from app.services.operational_plan import user_map_colours as ucm
from app.services.operational_plan.thematic_map_spec import ThematicMapSpec, spec_hash

logger = logging.getLogger(__name__)

_FILL_ALPHA = 0.70
_STROKE = "#3a3a3a"


# ── data ─────────────────────────────────────────────────────────────────
def _load_unit_values(db: Session, calculation_id: UUID) -> dict[str, dict]:
    """``{block_name: {measure_key: value}}`` from the field-inventory collector.

    Joins on ``block_name`` (§3.7). Derived measures (``_stems_total``,
    ``_field_minus_satellite``) are computed here — transient, no
    ``OP_DATA_CACHE_VERSION`` bump (§4.2).
    """
    from app.services.operational_plan.data_collector import get_field_inventory_data

    try:
        fi = get_field_inventory_data(db, calculation_id)
    except (
        Exception
    ):  # noqa: BLE001 -- collector failure → empty; caller renders a placeholder
        logger.warning(
            "field-inventory collector failed for %s", calculation_id, exc_info=True
        )
        return {}

    rows = (fi or {}).get("fi_block_summaries") or []
    out: dict[str, dict] = {}
    for r in rows:
        name = (r.get("block_name") or "").strip()
        if not name or name.lower().startswith(("grand total", "जम्मा")):
            continue
        gs = float(r.get("total_growing_stock_m3_per_ha") or 0)
        sat = float(r.get("satellite_volume_m3_per_ha") or 0)
        d = dict(r)
        d["_stems_total"] = float(r.get("tree_per_ha") or 0) + float(
            r.get("pole_per_ha") or 0
        )
        d["_field_minus_satellite"] = round(gs - sat, 2)
        pole_v, tree_v = float(r.get("pole_total_m3_per_ha") or 0), float(r.get("tree_total_m3_per_ha") or 0)
        if pole_v + tree_v > 0:
            d["tree_share_pct"] = round(100.0 * tree_v / (pole_v + tree_v), 1)
        if r.get("forest_condition") and r.get("regeneration_condition"):
            d["condition_pair"] = f"{r['forest_condition']}|{r['regeneration_condition']}"
        # derived composition totals for P5b glyphs
        d["_timber_total"] = float(r.get("pole_timber_m3_per_ha") or 0) + float(
            r.get("tree_timber_m3_per_ha") or 0
        )
        d["_firewood_total"] = float(r.get("pole_firewood_m3_per_ha") or 0) + float(
            r.get("tree_firewood_m3_per_ha") or 0
        )
        out[name] = d

    # dbh_class_breakdown (8-class) — not in the collector's _block_row; pull it
    # straight off the summary table, keyed by block_name (P5b centroid glyphs).
    try:
        from app.models.field_inventory import (
            FieldInventoryBlockSummary as _BS,
            FieldInventoryCalculation as _FC,
        )

        q = (
            db.query(_BS.block_name, _BS.dbh_class_breakdown)
            .join(_FC, _BS.field_inventory_calculation_id == _FC.id)
            .filter(_FC.calculation_id == calculation_id)
        )
        for bn, bd in q.all():
            key = (bn or "").strip()
            if key in out and bd:
                out[key]["dbh_class_breakdown"] = bd
    except Exception:  # noqa: BLE001 -- glyphs degrade to a placeholder without it
        logger.warning(
            "dbh_class_breakdown load failed for %s", calculation_id, exc_info=True
        )
    # species per unit (poles and trees, by volume) — the species maps
    try:
        from app.services.operational_plan import unit_species

        for bn, shares in unit_species.shares_by_unit(db, calculation_id).items():
            if bn in out and shares:
                out[bn]["species_shares"] = shares
                out[bn]["dominant_species"] = shares[0]["key"]
                out[bn]["dominant_species_name"] = shares[0]["name"]
    except Exception:  # noqa: BLE001 -- the species maps degrade to "no data"
        logger.warning("species shares load failed for %s", calculation_id, exc_info=True)
    return out


def _load_sfm_unit_values(
    db: Session, calculation_id: UUID, *, variant: str = "baseline"
) -> dict[str, dict]:
    """``{block_name: {effective_type_no, orientation, gs_ge40_m3_per_ha, ...}}``
    from ``result_data['sfm']['blocks']`` (baseline) or
    ``result_data['sfm_user']['blocks']`` (user variant) (SFM P5). Joins on
    ``block_name`` (§3.7). Read-only — the SFM tab / OP collector own building
    the block.  SV-1.6: ``variant`` selects the data key."""
    from app.services.sustainable_fm.sfm_service import SFM_RESULT_KEY, SFM_USER_KEY

    data_key = SFM_USER_KEY if variant == "user" else SFM_RESULT_KEY
    from app.models.calculation import Calculation

    row = (
        db.query(Calculation.result_data)
        .filter(Calculation.id == calculation_id)
        .first()
    )
    sfm_blob = ((row[0] if row else None) or {}).get(data_key, {})
    blocks = sfm_blob.get("blocks") or []
    zone_by_block = sfm_blob.get("zone_by_block") or {}
    out: dict[str, dict] = {}
    for b in blocks:
        name = (b.get("block_name") or "").strip()
        if not name:
            continue
        inp = b.get("inputs") or {}
        out[name] = {
            "effective_type_no": b.get("effective_type_no"),
            "state": b.get("state") or "classified",
            "slope_band": (zone_by_block.get(name) or {}).get("slope_band"),
            "plot_count": b.get("plot_count") or 0,
            "proposed_type_no": b.get("proposed_type_no"),
            "orientation": b.get("orientation"),
            "gs_ge40_m3_per_ha": inp.get("gs_ge40_m3_per_ha"),
            "needs_review": bool(b.get("needs_review")),
        }
    return out


def _units_with_geometry(db: Session, calculation_id: UUID) -> list[dict]:
    """The forest's units - the leaf view (every unit not divided further; FS-1a.8). Each dict gains
    ``area_ha`` (from geometry) and an ``id`` for labelling."""
    units = pms._get_leaf_units_with_geometry(db, calculation_id)
    total = 0.0
    for u in units:
        try:
            u["_geom_area_ha"] = _geodesic_area_ha(u["geometry"])
        except Exception:  # noqa: BLE001
            u["_geom_area_ha"] = float(u.get("area_ha") or 0)
        total += u["_geom_area_ha"]
    for u in units:
        u["area_ha"] = u["_geom_area_ha"]
        u["area_share_pct"] = (
            round(100.0 * u["_geom_area_ha"] / total, 2) if total else 0.0
        )
    return units


def _geodesic_area_ha(geom) -> float:
    """Rough planar→ha via a local equal-area scaling (good enough for classing)."""
    c = geom.centroid
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(c.y))
    return abs(geom.area) * m_per_deg_lat * m_per_deg_lon / 10_000.0


# ── classification ───────────────────────────────────────────────────────
def _numeric_series(units, values, spec: ThematicMapSpec):
    series = {}
    for u in units:
        name = u["name"]
        if spec.source == "geometry":
            v = u.get(spec.measure)
        else:
            v = (values.get(name) or {}).get(spec.measure)
        series[name] = float(v) if v is not None and _is_num(v) else None
    return series


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _breaks(nums: list[float], spec: ThematicMapSpec) -> list[float]:
    if spec.fixed_breaks:
        return list(spec.fixed_breaks)
    fn = sp.BREAK_METHODS.get(spec.class_method, sp.quantile_breaks)
    return fn(nums, spec.class_count)


def _class_index(v: float, breaks: list[float]) -> int:
    for i, b in enumerate(breaks):
        if v <= b:
            return i
    return len(breaks)


def _colour_map(units, values, spec: ThematicMapSpec):
    """Return ``(feature_colour: {name: hex|None}, legend_rows: [(hex,label)])``."""
    if spec.viz == "bivariate":
        return _bivariate_colours(units, values, spec)
    if spec.value_kind == "categorical":
        return _categorical_colours(units, values, spec)
    return _sequential_colours(units, values, spec)


def _species_classes(values) -> list[dict]:
    """The forest's own species classes (largest first) with their default colours — the 'species_dynamic' palette."""
    from app.services.operational_plan import unit_species

    return unit_species.scheme(values)


OTHER_SPECIES_COLOUR = "#bdbdbd"
OTHER_SPECIES_KEY = "other_species"
OTHER_SPECIES_LABEL_NE = "अन्य प्रजाति"


def _species_categorical(units, values, spec):
    """Dominant-species map: a colour per species of THIS forest (any saved colour is keyed by the species key)."""
    own = spec.colour_overrides or {}
    classes = _species_classes(values)
    colour = {c["key"]: own.get(c["key"]) or c["color"] for c in classes}
    feat: dict[str, str] = {}
    seen: dict[str, int] = {}
    for u in units:
        raw = (values.get(u["name"]) or {}).get(spec.measure)
        key = "" if raw in (None, "") else str(raw)
        feat[u["name"]] = colour.get(key) or (own.get(OTHER_SPECIES_KEY) or OTHER_SPECIES_COLOUR if key else sp.NO_DATA_FILL)
        if key:
            seen[key] = seen.get(key, 0) + 1
    rows = [(colour[c["key"]], c["name"]) for c in classes if c["key"] in seen]
    if any(k not in colour for k in seen):
        rows.append((own.get(OTHER_SPECIES_KEY) or OTHER_SPECIES_COLOUR, OTHER_SPECIES_LABEL_NE))
    if any((values.get(u["name"]) or {}).get(spec.measure) in (None, "") for u in units):
        rows.append((sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE))
    return feat, rows


def _categorical_colours(units, values, spec):
    if spec.palette == "species_dynamic":
        return _species_categorical(units, values, spec)
    feat: dict[str, str] = {}
    seen: list[str] = []
    for u in units:
        raw = (values.get(u["name"]) or {}).get(spec.measure)
        key = "" if raw in (None, "") else str(raw)
        col = (spec.colour_overrides or {}).get(key) or sp.color_for_category(spec.palette, key)
        feat[u["name"]] = col
        if key and key not in seen:
            seen.append(key)
    scheme = sp.CATEGORICAL.get(spec.palette, {})
    own = spec.colour_overrides or {}
    rows = [
        (
            own.get(k) or scheme.get(k, sp.CATEGORICAL_OTHER.get(spec.palette, "#bdbdbd")),
            sp.category_label(spec.palette, k),
        )
        for k in scheme
        if k in seen
    ]
    if any(
        (values.get(u["name"]) or {}).get(spec.measure) in (None, "") for u in units
    ):
        rows.append((sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE))
    return feat, rows


def _sequential_colours(units, values, spec):
    series = _numeric_series(units, values, spec)
    nums = sorted(v for v in series.values() if v is not None)
    if not nums:
        return {u["name"]: sp.NO_DATA_FILL for u in units}, [
            (sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE)
        ]

    if spec.viz == "choropleth_div":
        ref = spec.reference_value if spec.reference_value is not None else 0.0
        colours = [(spec.colour_overrides or {}).get(str(i)) or c for i, c in enumerate(sp.DIVERGING.get(spec.palette, sp.DIVERGING["deviation"]))]
        lo, hi = min(nums), max(nums)
        span = max(abs(lo - ref), abs(hi - ref)) or 1.0
        breaks = [ref - span / 2, ref - span / 6, ref + span / 6, ref + span / 2]
    else:
        breaks = _breaks(nums, spec)
        colours = sp.sample_ramp(spec.palette, len(breaks) + 1)
        colours = [(spec.colour_overrides or {}).get(str(i)) or c for i, c in enumerate(colours)]

    feat = {
        name: (colours[_class_index(v, breaks)] if v is not None else sp.NO_DATA_FILL)
        for name, v in series.items()
    }
    rows = _range_legend(breaks, colours)
    if any(v is None for v in series.values()):
        rows.append((sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE))
    return feat, rows


def _bivariate_colours(units, values, spec):
    a = _numeric_series(
        units,
        values,
        ThematicMapSpec(key="_a", measure=spec.measure, source=spec.source),
    )
    b = _numeric_series(
        units,
        values,
        ThematicMapSpec(
            key="_b", measure=spec.bivariate_measure or "", source=spec.source
        ),
    )
    # categorical A (condition) → map to 0/1/2
    cond_rank = {"Weak": 0, "Moderate": 1, "Good": 2}
    a_idx = {}
    for u in units:
        raw = (values.get(u["name"]) or {}).get(spec.measure)
        a_idx[u["name"]] = (
            cond_rank.get(str(raw), None)
            if raw in cond_rank
            else _tercile(a.get(u["name"]), a)
        )
    b_idx = {n: _tercile(v, b) for n, v in b.items()}
    swatches = sp.BIVARIATE.get(spec.palette, sp.BIVARIATE["bivariate_gp"])
    feat = {}
    for u in units:
        ai, bi = a_idx.get(u["name"]), b_idx.get(u["name"])
        feat[u["name"]] = (
            swatches[ai * 3 + bi] if ai is not None and bi is not None else None
        )
    rows = [(swatches[i], f"A{i // 3 + 1}·B{i % 3 + 1}") for i in range(9)]
    return feat, rows


def _tercile(v, series: dict):
    nums = sorted(x for x in series.values() if x is not None)
    if v is None or not nums:
        return None
    q1 = nums[len(nums) // 3]
    q2 = nums[2 * len(nums) // 3]
    return 0 if v <= q1 else (1 if v <= q2 else 2)


def _range_legend(breaks, colours):
    rows = []
    for i, col in enumerate(colours):
        lo = None if i == 0 else breaks[i - 1]
        hi = breaks[i] if i < len(breaks) else None
        if lo is None:
            lbl = f"≤ {format_devanagari(hi, 2)}"
        elif hi is None:
            lbl = f"> {format_devanagari(lo, 2)}"
        else:
            lbl = f"{format_devanagari(lo, 2)} – {format_devanagari(hi, 2)}"
        rows.append((col, lbl))
    return rows


# ── drawing ──────────────────────────────────────────────────────────────
def _poly_list(geom):
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, (MultiPolygon,)) or hasattr(geom, "geoms"):
        out = []
        for g in geom.geoms:
            out.extend(_poly_list(g))
        return out
    return []


def _fill_unit(ax, geom, colour, *, hatch="", alpha=_FILL_ALPHA, edge=_STROKE, lw=0.4):
    for poly in _poly_list(geom):
        xs, ys = poly.exterior.xy
        ax.fill(
            xs,
            ys,
            facecolor=colour or sp.NO_DATA_FILL,
            edgecolor=edge,
            linewidth=lw,
            alpha=alpha,
            hatch=hatch or None,
            zorder=3,
        )
        for ring in poly.interiors:
            rx, ry = ring.xy
            ax.fill(
                rx, ry, facecolor="white", edgecolor=_STROKE, linewidth=0.4, zorder=3
            )


# SFM maps: how much to trust a block, drawn as a hatch over its colour
_SFM_STATE_HATCH = {"provisional": "....", "inventory_missing": "xxxx"}
_SFM_STATE_LEGEND = {
    "provisional": ("#ffffff", "अस्थायी — ५ प्लट भन्दा कम", "...."),
    "inventory_missing": ("#d0d0d0", "नमुना प्लट छैन — वन प्रकार निर्धारण भएन", "xxxx"),
    "non_forest": ("#d0d0d0", "वन जमिन होइन", ""),
}
# what each class MEANS for the harvest, so the legend answers "so what?" and not only "which colour"
_SFM_ORIENTATION_NOTE_NE = {
    "उत्पादन": "उत्पादन — नियमित कटान",
    "संरक्षण": "संरक्षण — सीमित कटान",
    "प्रतिरक्षा": "प्रतिरक्षा — कटान छैन",
}


def _sfm_legend_rows(spec: ThematicMapSpec, rows, units, values) -> list:
    """Add meaning to the SFM legends and the evidence-status swatches for the states that occur on this map."""
    if spec.source != "sustainable_fm":
        return rows
    out = []
    for r in rows:
        c, lbl = r[0], r[1]
        if spec.palette == "sfm_orientation":
            lbl = _SFM_ORIENTATION_NOTE_NE.get(lbl, lbl)
        out.append((c, lbl) + tuple(r[2:]))
    if spec.unit_label_kind == "stock":  # the harvest % per step depends on the forest type, so say "step"
        notes = ("कटान: न्यूनतम तह", "कटान: मध्यम तह", "कटान: उच्चतम तह")
        out = [(r[0], f"{r[1]} — {notes[i]}") if i < len(notes) else r for i, r in enumerate(out)]  # no arrow: the Devanagari font lacks it
    present = {(values.get(u["name"]) or {}).get("state") for u in units}
    out.extend(_SFM_STATE_LEGEND[s] for s in ("provisional", "inventory_missing", "non_forest") if s in present)
    return out


def _thematic_legend(ax, spec: ThematicMapSpec, rows: list[tuple[str, str]], title_extra: str = ""):
    """Appendix C.1 — bottom-right swatch list, bilingual title."""
    if not rows:
        return
    import matplotlib.patches as mpatches

    handles = [
        mpatches.Patch(
            facecolor=r[0],
            edgecolor=(r[3] if len(r) > 3 and r[3] else "#555555"),
            linewidth=(1.0 if len(r) > 3 and r[3] else 0.5),
            label=r[1],
            hatch=(r[2] if len(r) > 2 and r[2] else None),
        )
        for r in rows
    ]
    title = (spec.legend_title_ne or spec.label_ne or "").strip()
    if title_extra:
        title = f"{title}\n{title_extra}" if title else title_extra
    leg = ax.legend(
        handles=handles,
        loc="lower right",
        fontsize=7,
        title=title or None,
        title_fontsize=8,
        framealpha=0.9,
        edgecolor="#555555",
        fancybox=True,
        prop=dev_font_prop(7),
    )
    if leg and leg.get_title():
        leg.get_title().set_fontproperties(dev_font_prop(8))


def _title_and_caption(
    fig, ax, spec: ThematicMapSpec, forest_name: str, source_note: str
):
    ne = (spec.label_ne or spec.key).strip()
    en = (spec.label_en or spec.key).strip()
    ttl = f"{forest_name} — {ne}".strip(" —") if forest_name else ne
    ax.set_title(
        ttl,
        fontsize=13,
        fontweight="bold",
        color="#1b5e20",
        pad=22,  # clear the top-edge longitude tick labels with a comfortable gap
        fontproperties=dev_bold_font_prop(13),
    )
    fig.text(
        0.5,
        0.012,
        f"{en}  ·  {source_note}  ·  CRS EPSG:4326",
        ha="center",
        fontsize=7,
        color="#666666",
        fontproperties=dev_font_prop(7),
    )


def _placeholder_png(
    spec: ThematicMapSpec, forest_name: str, msg_ne: str, dpi: int
) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=pms.FIG_SIZE_INCHES, dpi=dpi)
    ax.axis("off")
    ax.text(
        0.5,
        0.55,
        (spec.label_ne or spec.key),
        ha="center",
        va="center",
        fontsize=12,
        fontproperties=dev_bold_font_prop(12),
        color="#333333",
    )
    ax.text(
        0.5,
        0.42,
        msg_ne or sp.NO_DATA_LABEL_NE,
        ha="center",
        va="center",
        fontsize=9,
        fontproperties=dev_font_prop(9),
        color="#888888",
    )
    ax.add_patch(
        plt.Rectangle(
            (0.04, 0.04),
            0.92,
            0.92,
            fill=False,
            edgecolor="#cccccc",
            linewidth=1.0,
            transform=ax.transAxes,
        )
    )
    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── entry point ──────────────────────────────────────────────────────────
_HEX = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")


def _with_user_colours(db: Session, calculation_id: UUID, spec: ThematicMapSpec) -> ThematicMapSpec:
    """The spec with this forest's own colours applied (the ones the user set in the workspace's Analysis maps group,
    saved in ``result_data.layer_renderers['analysis:<id>']``), or ``spec`` itself when there are none.

    Only colours that DIFFER from the system palette are carried, so an untouched map keeps its old cache key, and the
    carried colours join the spec hash: changing a colour re-renders, and "Default colours" goes back to the old PNG.
    Never raises: a malformed saved renderer is ignored (the document must still build)."""
    map_id = ucm.SPEC_TO_ANALYSIS.get(spec.key)
    if map_id is None:
        return spec
    if map_id.startswith(("hazard_", "chart_", "fi_")):  # indexed colours (soil, landslide, stability, factors, charts, field-inventory maps)
        out = ucm.indexed_overrides(ucm.saved_renderer(db, calculation_id, map_id))
        return spec.model_copy(update={"colour_overrides": out}) if out else spec
    if spec.source != "sustainable_fm":
        return spec
    try:
        from app.models.calculation import Calculation

        calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
        saved = ((calc.result_data or {}).get("layer_renderers") or {}).get(f"analysis:{map_id}") if calc else None
        if not isinstance(saved, dict):
            return spec
        out: dict[str, str] = {}
        if saved.get("mode") == "categorized":
            default = sp.CATEGORICAL.get(spec.palette, {})
            for c in saved.get("classes") or []:
                v, col = str(c.get("value")), c.get("color")
                if v in default and isinstance(col, str) and _HEX.match(col) and col.lower() != default[v].lower():
                    out[v] = col
        elif saved.get("mode") == "graduated":
            default = sp.sample_ramp(spec.palette, len(saved.get("colors") or []))
            for i, col in enumerate(saved.get("colors") or []):
                if isinstance(col, str) and _HEX.match(col) and i < len(default) and col.lower() != default[i].lower():
                    out[str(i)] = col
        return spec.model_copy(update={"colour_overrides": out}) if out else spec
    except Exception:  # noqa: BLE001 -- a bad saved colour must never stop a document build
        logger.warning("could not read the user's map colours for %s", spec.key, exc_info=True)
        return spec


def generate_thematic_map(
    db: Session,
    calculation_id: UUID,
    spec: ThematicMapSpec,
    forest_name: str = "",
    dpi: int | None = None,
    use_cache: bool = True,
    *,
    variant: str = "baseline",
) -> io.BytesIO:
    """Render *spec* for a forest → PNG BytesIO. Never raises; a data/prereq
    problem yields a captioned placeholder.

    ``variant`` selects which SFM blob to read (``"baseline"`` or ``"user"``).
    SV-1.6: the cache key includes the variant so user-blob PNGs don't collide
    with the immutable baseline cache."""
    dpi = dpi or pms.DPI
    spec = _with_user_colours(db, calculation_id, spec)
    base_key = f"thememap__{spec.key}__{spec_hash(spec)}"
    cache_key = base_key if variant == "baseline" else f"{base_key}__{variant}"
    if use_cache:
        cached = pms._map_cache_get(calculation_id, cache_key, dpi)
        if cached:
            return cached

    try:
        buf = _render(db, calculation_id, spec, forest_name, dpi, variant=variant)
    except Exception:  # noqa: BLE001 -- a renderer bug must not 500 an OP export
        logger.exception("thematic render failed for %s / %s", calculation_id, spec.key)
        buf = _placeholder_png(spec, forest_name, "नक्सा बनाउन सकिएन", dpi)

    if use_cache:
        buf.seek(0)
        pms._map_cache_set(calculation_id, cache_key, buf, dpi)
    buf.seek(0)
    return buf


_FIXTURE_CACHE: dict[tuple, bytes] = {}  # (token, spec_hash, dpi) -> png bytes


def render_from_fixture(spec: ThematicMapSpec, dpi: int | None = None) -> io.BytesIO:
    """Render *spec* against the synthetic 5-unit fixture (no DB). Used by the
    reference-page preview endpoint when no ``calc_id`` is given (§3.9).

    In-process cached — the reference page requests ~50 of these on load and
    the fixture is static."""
    from app.services.operational_plan import _thememap_fixture as fx

    dpi = dpi or 96
    ck = (spec.token, spec_hash(spec), dpi)
    hit = _FIXTURE_CACHE.get(ck)
    if hit is not None:
        return io.BytesIO(hit)
    if spec.source in ("soil_grid", "hazard_grid"):
        try:
            buf = (
                _render_soil_grid_fixture(spec, dpi)
                if spec.source == "soil_grid"
                else _render_hazard_grid_fixture(spec, dpi)
            )
        except Exception:  # noqa: BLE001
            logger.exception("%s fixture render failed for %s", spec.source, spec.key)
            buf = _placeholder_png(spec, "", "पूर्वावलोकन बनाउन सकिएन", dpi)
        data = buf.getvalue()
        if len(_FIXTURE_CACHE) < 400:
            _FIXTURE_CACHE[ck] = data
        return io.BytesIO(data)
    fx_values = fx.PLAN_PER_UNIT if spec.source == "plan" else fx.VALUES
    fx_features = fx_by_year = None
    if spec.source == "plan":
        if (
            spec.layer == "feature"
            or spec.viz in FEATURE_TECHNIQUES
            or (spec.layout == "grid")
        ):
            fx_features = fx.plan_features(year=spec.year, kind=spec.feature_kind)
        if spec.layout == "grid":
            fx_by_year = fx.PLAN_BY_YEAR
            if fx_features is None:
                fx_features = fx.plan_features()
        if spec.viz == "qaflag":
            fx_values = {**fx_values, "__qa__": fx.PLAN_QA_MISSING}
    try:
        buf = compose(
            spec,
            fx.units(),
            fx_values,
            fx.WORKING_CIRCLE,
            fx.BBOX,
            fx.BOUNDARY,
            [],
            "",
            dpi,
            plot_points=(
                fx.plot_points() if spec.viz in POINT_SURFACE_TECHNIQUES else None
            ),
            features=fx_features,
            by_year=fx_by_year,
            allow_tiles=False,  # synthetic coords — no real tiles to fetch
        )
    except Exception:  # noqa: BLE001 -- a fixture render must never 500 the page
        logger.exception("fixture render failed for %s", spec.key)
        buf = _placeholder_png(spec, "", "पूर्वावलोकन बनाउन सकिएन", dpi)
    data = buf.getvalue()
    if len(_FIXTURE_CACHE) < 400:
        _FIXTURE_CACHE[ck] = data
    return io.BytesIO(data)


# ═══════════════════════════════════════════════════════════════════════════
# RUSLE soil-loss — a computed continuous raster surface (§2 P2 / P5)
# ═══════════════════════════════════════════════════════════════════════════
# soil_grid spec key suffix → (array attr on SoilLossResult, ramp, is the
# severity-classed A surface?). No suffix = the A surface clipped to the CF.
_SOIL_BANDS = {
    "__factor_r": ("r", "blues", False),
    "__factor_k": ("k", "oranges", False),
    "__factor_ls": ("ls", "purples", False),
    "__factor_c": ("c", "greens", False),
}


def _quantile_breaks(arr, n: int) -> list[float]:
    import numpy as np

    v = np.asarray(arr, dtype="float64")
    v = v[np.isfinite(v)]
    if v.size == 0:
        return [0.0]
    qs = np.quantile(v, [i / n for i in range(1, n)])
    out, last = [], None
    for q in qs:
        q = round(float(q), 4)
        if last is None or q > last:
            out.append(q)
            last = q
    return out or [round(float(v.mean()), 4)]


def _draw_raster_surface(
    ax, arr, grid_bounds, breaks, colours, boundary, *, labels_ne=None, cell_area_ha=None, mask=None, show_range=True
) -> list[tuple[str, str]]:
    """imshow ``arr`` classified by ``breaks``, clipped to ``boundary``. Returns
    ``[(hex, label), ...]`` for the classes present. ``labels_ne`` (the severity
    names) is used for the A surface; factor bands fall back to numeric ranges."""
    import numpy as np
    from matplotlib.colors import ListedColormap

    from app.services.operational_plan import soil_erosion as se

    cls = se.classify_severity(arr, breaks).astype("float64")
    cls[cls < 0] = np.nan
    n = len(colours)
    cmap = ListedColormap(colours)
    cmap.set_bad(alpha=0.0)
    minx, miny, maxx, maxy = grid_bounds
    im = ax.imshow(
        np.ma.masked_invalid(cls),
        extent=(minx, maxx, miny, maxy),
        origin="upper",
        cmap=cmap,
        vmin=-0.5,
        vmax=n - 0.5,
        interpolation="nearest",
        zorder=-5,
        alpha=0.82,
    )
    clip = _boundary_clip_path(ax, boundary)
    if clip is not None:
        im.set_clip_path(clip, transform=ax.transData)

    present = {int(v) for v in np.unique(cls[np.isfinite(cls)])}
    # area and share per class, within the forest (when the caller says where the forest is)
    ha_by_class: dict[int, float] = {}
    total_ha = 0.0
    if cell_area_ha is not None and mask is not None:
        inside = mask & np.isfinite(cls)
        for i in range(n):
            ha_by_class[i] = float(cell_area_ha[inside & (cls == i)].sum())
        total_ha = sum(ha_by_class.values())
    edges = [0.0, *list(breaks)]
    rows: list[tuple[str, str]] = []
    for i in range(n):
        if i not in present:
            continue
        lo = edges[i]
        hi = breaks[i] if i < len(breaks) else None
        rng = f"≥{lo:g}" if hi is None else f"{lo:g}–{hi:g}"
        if labels_ne and i < len(labels_ne):
            rng = f"{rng} · {labels_ne[i]}" if show_range else labels_ne[i]
        if total_ha > 0 and ha_by_class.get(i, 0.0) > 0:
            rng = f"{rng} · {format_devanagari(ha_by_class[i], 1)} हे. ({100.0 * ha_by_class[i] / total_ha:.0f}%)"
        rows.append((colours[i], rng))
    return rows


def _boundary_cell_mask(grid, boundary):
    """Which grid cells lie inside ``boundary`` (every part of it); ``None`` when that cannot be worked out."""
    try:
        from rasterio.features import geometry_mask
        from shapely.geometry import mapping

        return geometry_mask(
            [mapping(boundary)], (grid.height, grid.width), grid.transform, invert=True, all_touched=True
        )
    except Exception:  # noqa: BLE001 -- the legend shares and the extras are conveniences, never a reason to fail
        return None


def _unit_masks(units, grid) -> dict:
    out = {}
    try:
        from rasterio.features import geometry_mask
        from shapely.geometry import mapping

        for u in units or []:
            out[u["name"]] = geometry_mask(
                [mapping(u["geometry"])], (grid.height, grid.width), grid.transform, invert=True, all_touched=False
            )
    except Exception:  # noqa: BLE001
        logger.warning("unit masks unavailable", exc_info=True)
    return out


# a stability map is read for its dangerous cells, so they get colours that stand out against hill-shading
_FS_COLOURS = ["#c62828", "#f57c00", "#4f9fd6"]  # unstable · marginal · stable
_NODATA_HATCH_ROW = ("#ffffff", "तथ्याङ्क उपलब्ध छैन", "////")


def _draw_surface_extras(ax, arr, grid, boundary, *, units, unit_texts, danger=None, danger_label="", imagery=False):
    """What turns a bare surface into something a reader can act on (owner, 2026-10-06):

    * the cells with NO value inside the forest are hatched, so a gap is shown as a gap and never as 'fine'
    * the dangerous cells get a dark outline, so a handful of unstable cells cannot hide
    * each unit gets a thin outline and a small halo label: its name and what this map says about it

    Returns the extra legend rows (the hatch) for the caller to add."""
    import numpy as np

    rows: list = []
    minx, miny, maxx, maxy = grid.bounds
    ext = (minx, maxx, miny, maxy)
    cell_mask = _boundary_cell_mask(grid, boundary)
    clip = _boundary_clip_path(ax, boundary)
    if cell_mask is not None:
        nodata = cell_mask & ~np.isfinite(arr)
        if nodata.any():
            with plt.rc_context({"hatch.color": "#6b6b6b"}):
                cs = ax.contourf(
                    nodata.astype(float), levels=[0.5, 1.5], colors="none", hatches=["////"],
                    extent=ext, origin="upper", zorder=-4,
                )
            rows.append(_NODATA_HATCH_ROW)
        if danger is not None:
            dm = (danger & cell_mask).astype(float)
            if dm.any():
                cs = ax.contour(
                    dm, levels=[0.5], colors="#5d0000", linewidths=1.0, extent=ext, origin="upper", zorder=-3,
                )
                if danger_label:
                    rows.append(("#ffffff", danger_label, "", "#5d0000"))
    if units:
        edge = "#ffffff" if imagery else "#444444"
        for u in units:
            for poly in _poly_list(u["geometry"]):
                xs, ys = poly.exterior.xy
                ax.plot(xs, ys, color=edge, linewidth=0.5, alpha=0.8, zorder=4)
        _place_two_line_labels(ax, units, unit_texts, imagery)
    return rows


def _surface_unit_texts(kind, arr, grid, units, *, classes=None, labels=None):
    """``{unit name: text}`` for the line under the unit name. ``kind``: ``soil`` (mean loss) · ``lsi`` (dominant
    class) · ``fs`` / ``prone`` (share of cells that are unsafe)."""
    import numpy as np

    texts: dict[str, str | None] = {}
    for name, m in _unit_masks(units, grid).items():
        if not m.any():
            continue
        if kind == "soil":
            v = arr[m]
            v = v[np.isfinite(v)]
            texts[name] = f"{float(v.mean()):.0f} t/ha/yr" if v.size else None
        elif kind == "lsi" and classes is not None:
            c = classes[m]
            c = c[c >= 0].astype(int)
            if c.size:
                dom = int(np.bincount(c).argmax())
                texts[name] = labels[dom] if labels and dom < len(labels) else str(dom)
        elif kind in ("fs", "prone") and classes is not None:
            c = classes[m]
            c = c[np.isfinite(c) & (c >= 0)] if kind == "fs" else c[np.isfinite(c)]
            if c.size:
                unsafe = float((c <= 1).mean()) if kind == "fs" else float((c == 1).mean())
                texts[name] = f"{100.0 * unsafe:.0f}% " + ("उच्च" if kind == "prone" else "जोखिम")
    return texts


def _compose_soil_grid(
    res, spec, forest_name, bbox, boundary, dpi, *, allow_tiles: bool, band: str = "a", units=None
) -> io.BytesIO:
    """Frame + classed surface for a ``source == "soil_grid"`` spec. ``band`` is
    ``"a"`` (the severity-classed soil-loss surface) or an ``_SOIL_BANDS`` factor
    key. Shared by the DB path and the fixture preview."""
    import numpy as np

    from app.services.operational_plan.soil_erosion_config import SEVERITY_LABELS_NE

    if band == "a":
        arr = res.a
        breaks = list(res.params.severity_breaks)
        ramp = spec.palette or "reds"
        labels = SEVERITY_LABELS_NE
    else:
        attr, ramp, _ = _SOIL_BANDS[band]
        arr = getattr(res, attr)
        breaks = _quantile_breaks(arr, 5)
        labels = None

    if not np.isfinite(arr).any():
        return _placeholder_png(spec, forest_name, sp.NO_DATA_LABEL_NE, dpi)
    colours = ucm.apply(sp.sample_ramp(ramp, len(breaks) + 1), spec.colour_overrides)  # the user's own colours, if any

    min_lon, min_lat, max_lon, max_lat = bbox
    fig, ax = plt.subplots(figsize=pms.FIG_SIZE_INCHES, dpi=dpi)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.87, bottom=0.08)
    ax.set_facecolor("white")
    slon = pms.compute_snapped_grid(min_lon, max_lon)
    slat = pms.compute_snapped_grid(min_lat, max_lat)
    ax.set_xlim(slon[2], slon[3])
    ax.set_ylim(slat[2], slat[3])
    ax.set_aspect("equal")

    _draw_basemap(ax, spec, allow_tiles=allow_tiles)
    cell_mask = _boundary_cell_mask(res.grid, boundary)
    legend_rows = _draw_raster_surface(
        ax, arr, res.grid.bounds, breaks, colours, boundary, labels_ne=labels,
        cell_area_ha=res.grid.cell_area_ha, mask=cell_mask,
    )
    # soil loss is read against the tolerable limit: the cells above it are outlined; each unit says its mean loss
    severe = float(list(res.params.severity_breaks)[-2]) if band == "a" and len(res.params.severity_breaks) > 1 else None
    legend_rows += _draw_surface_extras(
        ax, arr, res.grid, boundary, units=units,
        unit_texts=_surface_unit_texts("soil", arr, res.grid, units) if band == "a" else {},
        danger=(arr >= severe) if severe is not None else None,
        danger_label=f"≥{format_devanagari(severe, 0)} — रेखाङ्कित (गम्भीर)" if severe is not None else "",
    )
    pms._add_boundary_outline(ax, boundary)

    pms._add_grid(ax, min_lon, max_lon, min_lat, max_lat)
    pms._add_neatline(ax, slon[2], slon[3], slat[2], slat[3])
    ax.axis("off")
    pms._add_north_arrow(ax)
    pms._add_scale_bar(ax, min_lon, max_lon, min_lat, max_lat)
    _thematic_legend(ax, spec, legend_rows)

    note = "स्रोत: RUSLE (DEM · माटो · वर्षा · भू-आवरण)"
    note += f" · ग्रिड कक्ष ≈ {format_devanagari(res.grid.dx_m, 0)} मि."
    if (band in ("lsi", "prone")) and getattr(getattr(res.params, "landslide", None), "class_method", "fixed") != "fixed":
        note += " · वर्ग सापेक्ष (यही वनभित्र), पूर्ण जोखिम होइन"
    if getattr(res.params, "is_customised", lambda: False)():
        note += " · प्यारामिटर समायोजित"
    _title_and_caption(fig, ax, spec, forest_name, note)

    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _soil_band_for(spec) -> str:
    for suffix, _ in _SOIL_BANDS.items():
        if spec.key.endswith(suffix):
            return suffix
    return "a"


def _render_soil_grid(db, calculation_id, spec, forest_name, dpi, boundary, bbox):
    from app.services.operational_plan import soil_erosion as se

    band = _soil_band_for(spec)
    # the __user_group variant clips the A surface to the user-group extent
    if spec.key.endswith("__user_group"):
        ug = se._user_group_geom(db, calculation_id)
        if ug is None or ug.is_empty:
            return _placeholder_png(spec, forest_name, "उपभोक्ता क्षेत्रको सिमाना छैन", dpi)
        boundary, bbox = ug, ug.bounds

    try:
        res = se.compute_soil_loss(db, calculation_id)
    except (
        Exception
    ):  # noqa: BLE001 -- a compute failure yields a placeholder, not a 500
        logger.exception("soil-loss compute failed for %s", calculation_id)
        return _placeholder_png(spec, forest_name, "माटो क्षय गणना असफल", dpi)
    try:
        units = _units_with_geometry(db, calculation_id)
    except Exception:  # noqa: BLE001 -- unit labels are an extra
        units = None
    return _compose_soil_grid(
        res, spec, forest_name, bbox, boundary, dpi, allow_tiles=True, band=band, units=units
    )


def _render_soil_grid_fixture(spec, dpi) -> io.BytesIO:
    from app.services.operational_plan import _thememap_fixture as fx

    res = fx.soil_loss_result()
    return _compose_soil_grid(
        res,
        spec,
        "",
        fx.BBOX,
        fx.BOUNDARY,
        dpi,
        allow_tiles=False,
        band=_soil_band_for(spec),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Landslide hazard + household vulnerability — computed surfaces (§2 P4)
# ═══════════════════════════════════════════════════════════════════════════
# spec.key → which array of the LSI/FS result to classify, plus its ramp and
# the class labels. `hazard__lsi_factor_<f>` handled separately.
_HAZARD_LSI_FACTOR_PREFIX = "hazard__lsi_factor_"


def _hazard_band_for(spec) -> str:
    k = spec.key
    if k.startswith(_HAZARD_LSI_FACTOR_PREFIX):
        return "lsi_factor"
    if k.startswith("hazard__landslide_prone_area"):
        return "prone"
    if k.startswith("hazard__landslide_susceptibility"):
        return "lsi"
    if k.startswith("hazard__factor_of_safety"):
        return "fs"
    if k.startswith("hh__"):
        return "dots"
    return "lsi"


def _compose_hazard_grid(
    spec, band, *, res, forest_name, bbox, boundary, dpi, allow_tiles, units=None
) -> io.BytesIO:
    """Frame + classed LSI / FS / factor surface (reuses ``_draw_raster_surface``
    via the shared severity classifier)."""
    import numpy as np

    from app.services.operational_plan.hazard_vuln_config import (
        FS_CLASS_LABELS_NE,
        LSI_CLASS_LABELS_NE,
    )

    relative_classes = False
    if band == "lsi":
        # Colour the surface by the SAME classes the OP tables, the prone map and the household scoring use. It used
        # to be coloured by the fixed breaks while those used relative (quantile) classes, so one forest showed
        # "no high class" here and "40% prone" next to it.
        lp = res.params.landslide
        arr = np.where(res.classes >= 0, res.classes.astype("float64"), np.nan)
        n_cls = len(LSI_CLASS_LABELS_NE)
        breaks = [i + 0.5 for i in range(n_cls - 1)]
        ramp = spec.palette or "spectral_r"
        relative_classes = lp.class_method != "fixed"
        labels = list(LSI_CLASS_LABELS_NE)
        if relative_classes:
            cf = _boundary_cell_mask(res.grid, boundary)
            for i in range(len(labels)):
                sel = (res.classes == i) & np.isfinite(res.lsi)
                if cf is not None:
                    sel &= cf
                if sel.any():
                    labels[i] = f"{labels[i]} (LSI {res.lsi[sel].min():.1f}–{res.lsi[sel].max():.1f})"
        if not relative_classes:
            e = [0.0, *list(lp.class_breaks_fixed)]
            labels = [
                f"{labels[i]} ({e[i]:g}–{e[i + 1]:g})" if i + 1 < len(e) else f"{labels[i]} (≥{e[i]:g})"
                for i in range(len(labels))
            ]
        note = "स्रोत: LSI भारित ओभरले (भिरालोपन · शिलावर्ग · TWI · दूरी · भू-आवरण)"
    elif band == "fs":
        arr = res.fs
        breaks = list(res.params.factor_of_safety.fs_class_breaks)
        ramp, labels = spec.palette or "spectral", FS_CLASS_LABELS_NE
        note = "स्रोत: अनन्त-ढलान FS · मनसुनी संतृप्त परिदृश्य"
    elif band == "prone":
        arr = np.where(
            res.classes >= (res.params.landslide.prone_class_min - 1), 1.0, 0.0
        ).astype("float64")
        arr = np.where(res.classes >= 0, arr, np.nan)
        breaks = [0.5]
        ramp, labels = spec.palette or "reds", ["कम सापेक्ष संवेदनशीलता", "सापेक्ष रूपमा उच्च संवेदनशील"]
        note = "स्रोत: LSI ≥ उच्च वर्ग"
    else:  # lsi_factor
        fkey = spec.key[len(_HAZARD_LSI_FACTOR_PREFIX) :]
        arr = res.ratings.get(fkey)
        breaks = _quantile_breaks(arr, 5) if arr is not None else [3.0]
        ramp, labels = spec.palette or "oranges", None
        note = f"स्रोत: LSI कारक रेटिङ ({fkey})"

    if arr is None or not np.isfinite(arr).any():
        return _placeholder_png(spec, forest_name, sp.NO_DATA_LABEL_NE, dpi)
    colours = sp.sample_ramp(ramp, len(breaks) + 1)
    if band == "fs" and len(colours) == len(_FS_COLOURS):
        colours = list(_FS_COLOURS)  # unstable / marginal must stand out: the ramp's pale middle vanished
    colours = ucm.apply(colours, spec.colour_overrides)  # the user's own colours, if any

    min_lon, min_lat, max_lon, max_lat = bbox
    fig, ax = plt.subplots(figsize=pms.FIG_SIZE_INCHES, dpi=dpi)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.87, bottom=0.08)
    ax.set_facecolor("white")
    slon = pms.compute_snapped_grid(min_lon, max_lon)
    slat = pms.compute_snapped_grid(min_lat, max_lat)
    ax.set_xlim(slon[2], slon[3])
    ax.set_ylim(slat[2], slat[3])
    ax.set_aspect("equal")

    _draw_basemap(ax, spec, allow_tiles=allow_tiles)
    cell_mask = _boundary_cell_mask(res.grid, boundary)
    legend_rows = _draw_raster_surface(
        ax, arr, res.grid.bounds, breaks, colours, boundary, labels_ne=labels,
        cell_area_ha=res.grid.cell_area_ha, mask=cell_mask, show_range=(band not in ("lsi", "prone")),
    )
    # the unsafe cells are outlined; each unit says how much of it is unsafe (or its dominant class)
    # classes as the SURFACE shows them (its own breaks), so the outline and labels agree with the colours drawn
    from app.services.operational_plan import soil_erosion as _se

    surf = _se.classify_severity(arr, breaks).astype("float64")
    surf[surf < 0] = np.nan
    danger = unit_texts = None
    danger_label = ""
    if band == "fs":
        danger = np.nan_to_num(surf, nan=9.0) <= 1
        unit_texts = _surface_unit_texts("fs", arr, res.grid, units, classes=surf)
        danger_label = "अस्थिर वा सीमान्त कक्ष — रेखाङ्कित"
    elif band == "prone":
        danger = arr == 1.0
        unit_texts = _surface_unit_texts("prone", arr, res.grid, units, classes=arr)
        danger_label = "सापेक्ष रूपमा उच्च — रेखाङ्कित"
    elif band == "lsi":
        high = res.params.landslide.prone_class_min - 1
        danger = np.nan_to_num(surf, nan=-1.0) >= high  # surf == res.classes here
        unit_texts = _surface_unit_texts("lsi", arr, res.grid, units, classes=surf, labels=labels)
        danger_label = "उच्च वा सोभन्दा बढी (सापेक्ष) — रेखाङ्कित"
    legend_rows += _draw_surface_extras(
        ax, arr, res.grid, boundary, units=units, unit_texts=unit_texts or {}, danger=danger,
        danger_label=danger_label,
    )
    if band in ("lsi", "prone") and getattr(res.params.landslide, "class_method", "fixed") != "fixed":
        legend_rows.append(("#ffffff", "वर्ग सापेक्ष: यही वनभित्र तुलना", ""))
    pms._add_boundary_outline(ax, boundary)
    pms._add_grid(ax, min_lon, max_lon, min_lat, max_lat)
    pms._add_neatline(ax, slon[2], slon[3], slat[2], slat[3])
    ax.axis("off")
    pms._add_north_arrow(ax)
    pms._add_scale_bar(ax, min_lon, max_lon, min_lat, max_lat)
    _thematic_legend(ax, spec, legend_rows)

    note += f" · ग्रिड कक्ष ≈ {format_devanagari(res.grid.dx_m, 0)} मि."
    if getattr(res.params, "is_customised", lambda: False)():
        note += " · प्यारामिटर समायोजित"
    _title_and_caption(fig, ax, spec, forest_name, note)

    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _compose_hazard_dots(
    spec, *, hh_result, lsi_res, forest_name, bbox, boundary, dpi, allow_tiles
) -> io.BytesIO:
    """Household / settlement points graduated by vulnerability score over a
    faint LSI backdrop. No point labels (PII)."""
    import numpy as np

    settlement = spec.layer == "settlement"
    if settlement:
        rows = hh_result.settlement_rollup
        pts = [
            (r.get("_lon"), r.get("_lat"), r.get("mean_score"), r.get("n_households"))
            for r in rows
        ]
    else:
        pts = [
            (h["longitude"], h["latitude"], h.get("score"), 1)
            for h in hh_result.households
        ]
    pts = [
        (lon, lat, s, n)
        for lon, lat, s, n in pts
        if lon is not None and lat is not None and s is not None
    ]
    if not pts:
        return _placeholder_png(spec, forest_name, sp.NO_DATA_LABEL_NE, dpi)

    min_lon, min_lat, max_lon, max_lat = bbox
    fig, ax = plt.subplots(figsize=pms.FIG_SIZE_INCHES, dpi=dpi)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.87, bottom=0.08)
    ax.set_facecolor("white")
    slon = pms.compute_snapped_grid(min_lon, max_lon)
    slat = pms.compute_snapped_grid(min_lat, max_lat)
    ax.set_xlim(slon[2], slon[3])
    ax.set_ylim(slat[2], slat[3])
    ax.set_aspect("equal")
    _draw_basemap(ax, spec, allow_tiles=allow_tiles)

    if lsi_res is not None and np.isfinite(lsi_res.lsi).any():
        _draw_raster_surface(
            ax,
            lsi_res.lsi,
            lsi_res.grid.bounds,
            list(lsi_res.params.landslide.class_breaks_fixed),
            sp.sample_ramp("greys", 5),
            boundary,
        )

    lons = np.array([p[0] for p in pts])
    lats = np.array([p[1] for p in pts])
    scores = np.array([p[2] for p in pts], dtype="float64")
    counts = np.array([p[3] or 1 for p in pts], dtype="float64")
    from matplotlib.colors import Normalize

    cmap = plt.get_cmap("Reds")
    norm = Normalize(vmin=float(scores.min()), vmax=max(float(scores.max()), 1e-6))
    sizes = (
        40.0 + (counts / max(counts.max(), 1.0)) * 160.0
        if settlement
        else np.full(len(pts), 46.0)
    )
    ax.scatter(
        lons,
        lats,
        s=sizes,
        c=scores,
        cmap=cmap,
        norm=norm,
        edgecolors="#333333",
        linewidths=0.6,
        zorder=6,
        alpha=0.92,
    )
    pms._add_boundary_outline(ax, boundary)
    pms._add_grid(ax, min_lon, max_lon, min_lat, max_lat)
    pms._add_neatline(ax, slon[2], slon[3], slat[2], slat[3])
    ax.axis("off")
    pms._add_north_arrow(ax)
    pms._add_scale_bar(ax, min_lon, max_lon, min_lat, max_lat)

    lo, hi = float(scores.min()), float(scores.max())
    rows = [
        (sp.sample_ramp("reds", 3)[0], f"{lo:.2f} — कम जोखिम"),
        (sp.sample_ramp("reds", 3)[2], f"{hi:.2f} — उच्च जोखिम"),
    ]
    _thematic_legend(ax, spec, rows)
    n = len({p for p in pts})
    note = f"स्रोत: घरधुरी जोखिम अंक · {format_devanagari(n)} बिन्दु · नाम/जात/निर्देशांक बिना"
    _title_and_caption(fig, ax, spec, forest_name, note)

    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _render_hazard_grid(db, calculation_id, spec, forest_name, dpi, boundary, bbox):
    from app.services.operational_plan import landslide_susceptibility as lsm
    from app.services.operational_plan import slope_stability as ssm
    from app.services.operational_plan import soil_erosion as se

    band = _hazard_band_for(spec)
    if spec.key.endswith("__user_group"):
        ug = se._user_group_geom(db, calculation_id)
        if ug is None or ug.is_empty:
            return _placeholder_png(spec, forest_name, "उपभोक्ता क्षेत्रको सिमाना छैन", dpi)
        boundary, bbox = ug, ug.bounds

    try:
        if band == "fs":
            res = ssm.compute_fs(db, calculation_id)
        elif band == "dots":
            from app.services.operational_plan import household_vulnerability as hvm

            hh_result = hvm.compute_household_vulnerability(db, calculation_id)
            lsi_res = None
            try:
                lsi_res = lsm.compute_lsi(db, calculation_id)
            except Exception:  # noqa: BLE001
                logger.debug("hh dot map: no LSI backdrop", exc_info=True)
            return _compose_hazard_dots(
                spec,
                hh_result=hh_result,
                lsi_res=lsi_res,
                forest_name=forest_name,
                bbox=bbox,
                boundary=boundary,
                dpi=dpi,
                allow_tiles=True,
            )
        else:  # lsi / prone / lsi_factor
            res = lsm.compute_lsi(db, calculation_id)
    except Exception:  # noqa: BLE001 -- a compute failure yields a placeholder
        logger.exception("hazard compute failed for %s / %s", calculation_id, spec.key)
        return _placeholder_png(spec, forest_name, "जोखिम गणना असफल", dpi)

    try:
        units = _units_with_geometry(db, calculation_id)
    except Exception:  # noqa: BLE001 -- unit labels are an extra
        units = None
    return _compose_hazard_grid(
        spec,
        band,
        res=res,
        forest_name=forest_name,
        bbox=bbox,
        boundary=boundary,
        dpi=dpi,
        allow_tiles=True,
        units=units,
    )


def _render_hazard_grid_fixture(spec, dpi) -> io.BytesIO:
    from app.services.operational_plan import _thememap_fixture as fx

    band = _hazard_band_for(spec)
    if band == "dots":
        return _compose_hazard_dots(
            spec,
            hh_result=fx.household_vuln_result(),
            lsi_res=fx.lsi_result(),
            forest_name="",
            bbox=fx.BBOX,
            boundary=fx.BOUNDARY,
            dpi=dpi,
            allow_tiles=False,
        )
    res = fx.fs_result() if band == "fs" else fx.lsi_result()
    return _compose_hazard_grid(
        spec,
        band,
        res=res,
        forest_name="",
        bbox=fx.BBOX,
        boundary=fx.BOUNDARY,
        dpi=dpi,
        allow_tiles=False,
    )


def _render(db, calculation_id, spec, forest_name, dpi, *, variant: str = "baseline") -> io.BytesIO:
    pr = prereq_check.check_spec(db, calculation_id, spec)
    if not pr.met:
        return _placeholder_png(
            spec, forest_name, pr.reason_ne or sp.NO_DATA_LABEL_NE, dpi
        )

    bbox = pms._get_forest_bbox(db, calculation_id)
    if not bbox:
        return _placeholder_png(spec, forest_name, "वन सिमाना उपलब्ध छैन", dpi)

    # RUSLE soil-loss — a computed continuous raster (§2 P2). Doesn't use the
    # per-unit `compose` path; renders the classed grid under the shared frame.
    if spec.source == "soil_grid":
        boundary = pms._get_forest_geometry(db, calculation_id)
        return _render_soil_grid(
            db, calculation_id, spec, forest_name, dpi, boundary, bbox
        )

    # Landslide hazard + household vulnerability — computed surfaces (§2 P4).
    if spec.source == "hazard_grid":
        boundary = pms._get_forest_geometry(db, calculation_id)
        return _render_hazard_grid(
            db, calculation_id, spec, forest_name, dpi, boundary, bbox
        )

    units = _units_with_geometry(db, calculation_id)
    if not units:
        return _placeholder_png(spec, forest_name, "एकाइ (ब्लक/कम्पार्टमेन्ट) छैन", dpi)
    if spec.source == "geometry":
        values = {}
    elif spec.source == "plan":  # opsmap — P5c
        from app.services.operational_plan import plan_collector

        values = plan_collector.per_unit(db, calculation_id)
    elif spec.source == "raster_zonal":  # S9 — P6z
        from app.services.operational_plan import raster_zonal

        values = raster_zonal.per_unit_zonal(db, units, spec)
    elif spec.source == "sustainable_fm":  # SFM P5
        values = _load_sfm_unit_values(db, calculation_id, variant=variant)
    else:
        values = _load_unit_values(db, calculation_id)
    boundary = pms._get_forest_geometry(db, calculation_id)
    wc = _load_working_circle(db, calculation_id)
    excluded = _excluded_polys(db, calculation_id) if spec.viz == "dasymetric" else []
    if spec.viz in POINT_SURFACE_TECHNIQUES:
        plot_points = (
            _load_tree_points(db, calculation_id, spec.tree_filter or "all")
            if spec.layer == "tree"
            else _load_ntfp_plot_points(db, calculation_id)
            if spec.layer == "ntfp_plot"
            else _load_plot_points(db, calculation_id)
        )
    else:
        plot_points = None
    hydro_lines = None
    if spec.viz == "hydrolines":
        from app.services.operational_plan import raster_zonal

        hydro_lines = raster_zonal.hydro_lines_for_forest(db, calculation_id)
    # P7 — opsmap drawn features + the 1..10 year axis
    features = by_year = None
    if spec.source == "plan":
        from app.services.operational_plan import plan_collector

        if spec.layer == "feature" or spec.viz in FEATURE_TECHNIQUES:
            features = plan_collector.features(
                db, calculation_id, year=spec.year, kind=spec.feature_kind
            )
        if spec.layout == "grid":
            by_year = plan_collector.by_year(db, calculation_id)
            if features is None:
                features = plan_collector.features(db, calculation_id)
        if spec.viz == "qaflag":
            values = {
                **(values or {}),
                "__qa__": plan_collector.qa_missing_map(db, calculation_id),
            }
    return compose(
        spec,
        units,
        values,
        wc,
        bbox,
        boundary,
        excluded,
        forest_name,
        dpi,
        plot_points=plot_points,
        features=features,
        by_year=by_year,
        hydro_lines=hydro_lines,
    )


# ── contextual basemap (§3.5.2) ─────────────────────────────────────────
# spec.basemap → BASEMAP_SOURCES key in plan_map_service (which owns tile
# fetch + a cache + an offline grey fallback).
_BASEMAP_KEY = {
    "canvas_light": "canvas_light",  # Esri WorldGrayCanvas (muted grey)
    "osm": "boundary",  # OpenStreetMap.Mapnik
    "topo": "topo",  # OpenTopoMap
    "hillshade": "hillshade",  # Esri WorldShadedRelief (grey relief)
    "imagery": "imagery",  # Esri WorldImagery (satellite)
}
_CANVAS_LIGHT = "#f4f3ef"
# data-heavy techniques: hold the basemap right back so the data still reads.
_DATA_VIZ = frozenset(
    {
        "choropleth",
        "choropleth_div",
        "bivariate",
        "dasymetric",
        "alpha",
        "graduated",
        "graduated_nested",
    }
)


def _draw_basemap(ax, spec, *, allow_tiles: bool) -> None:
    """Honour ``spec.basemap`` (§3.5.2). ``none`` → white; ``canvas_light`` →
    a muted offline ground; ``osm`` / ``topo`` / ``hillshade`` / ``imagery`` →
    cached XYZ tiles at low alpha, falling back to ``canvas_light`` when offline
    or on the synthetic fixture (``allow_tiles=False``)."""
    kind = (getattr(spec, "basemap", None) or "canvas_light").lower()
    if kind == "none":
        ax.set_facecolor("white")
        return
    tile_key = _BASEMAP_KEY.get(kind)
    if tile_key is None or not allow_tiles:
        ax.set_facecolor(_CANVAS_LIGHT)
        return

    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    is_data = spec.viz in _DATA_VIZ or spec.value_kind == "categorical"
    if kind == "canvas_light":  # Positron is already muted — can go a bit stronger
        alpha = 0.45 if is_data else 0.6
    else:
        alpha = 0.30 if is_data else 0.5
    if getattr(spec, "basemap_alpha", None) is not None:
        alpha = float(spec.basemap_alpha)
    try:
        ok = pms._add_basemap(ax, tile_key, alpha=alpha)
    except Exception:  # noqa: BLE001 -- never let a basemap break the render
        ok = False
    if not ok:
        ax.set_facecolor(_CANVAS_LIGHT)
    for im in ax.get_images():  # tiles sit behind data, grid and boundary
        im.set_zorder(-20)
    ax.set_xlim(x0, x1)  # imshow widened the view to whole tiles — restore it
    ax.set_ylim(y0, y1)


def compose(
    spec,
    units,
    values,
    wc,
    bbox,
    boundary,
    excluded,
    forest_name,
    dpi,
    plot_points=None,
    features=None,
    by_year=None,
    hydro_lines=None,
    *,
    allow_tiles: bool = True,
) -> io.BytesIO:
    """Pure matplotlib composition — no DB. `units` is a list of dicts with
    ``name`` + ``geometry`` (shapely) [+ ``area_ha``/``area_share_pct`` for
    ``source == "geometry"``]; ``values`` is ``{name: {measure: value}}``;
    ``wc`` is ``{name: "production"|"protection"}``; ``bbox`` is
    ``(min_lon, min_lat, max_lon, max_lat)``; ``plot_points`` is the list from
    ``_load_plot_points`` for point / surface techniques (P6); ``features`` /
    ``by_year`` feed the P7 ``opsmap`` drawn-feature + year-panel maps.
    Tested directly."""
    min_lon, min_lat, max_lon, max_lat = bbox

    is_glyph = spec.viz in GLYPH_TECHNIQUES
    is_point = spec.viz in POINT_SURFACE_TECHNIQUES
    is_vector = spec.viz == "vector"  # P6z — one downslope arrow per unit
    is_hydro = spec.viz == "hydrolines"  # S9 — real river.river84 line geometry
    is_feature = spec.layer == "feature" or spec.viz in FEATURE_TECHNIQUES  # P7
    is_qa = spec.viz == "qaflag"  # P7 — S19 "activity needs a map but has none"
    # P7 — a plan grid spec renders one mini-map per plan year.
    if spec.source == "plan" and spec.layout == "grid":
        return _compose_plan_small_multiples(
            spec,
            units,
            values,
            by_year or {},
            features or [],
            wc,
            bbox,
            boundary,
            forest_name,
            dpi,
        )
    # P5b — glyph maps with many units fall back to a panel grid.
    if spec.viz == "smallmultiples" or (
        is_glyph and spec.layout != "single" and len(units) > _GLYPH_MAX_UNITS
    ):
        return _compose_small_multiples(spec, units, values, wc, bbox, forest_name, dpi)

    if is_glyph:
        feat_colour, legend_rows = {}, _glyph_legend(spec, values)
    elif is_point or is_vector or is_feature or is_hydro:
        feat_colour, legend_rows = {}, []
    elif is_qa:
        qa = (values or {}).get("__qa__") or {}
        feat_colour = {
            u["name"]: ("#c62828" if qa.get(u["name"]) else "#c8e6c9") for u in units
        }
        legend_rows = [
            ("#c62828", "नक्सा चाहिने तर नकोरिएको / needs a map — none drawn"),
            ("#c8e6c9", "ठीक / OK"),
        ]
    else:
        feat_colour, legend_rows = _colour_map(units, values, spec)
    numeric_series = (
        _numeric_series(units, values, spec) if spec.value_kind != "categorical" else {}
    )

    fig, ax = plt.subplots(figsize=pms.FIG_SIZE_INCHES, dpi=dpi)
    # top=0.87 (was 0.9) leaves a clear band between the top-edge longitude
    # labels and the title (they used to almost touch).
    fig.subplots_adjust(left=0.06, right=0.98, top=0.87, bottom=0.08)
    ax.set_facecolor("white")

    slon = pms.compute_snapped_grid(min_lon, max_lon)  # (lines, labels, start, end)
    slat = pms.compute_snapped_grid(min_lat, max_lat)
    ax.set_xlim(slon[2], slon[3])
    ax.set_ylim(slat[2], slat[3])
    ax.set_aspect("equal")

    _draw_basemap(ax, spec, allow_tiles=allow_tiles)

    for u in units:
        geom = u["geometry"]
        if excluded:
            for ex in excluded:
                try:
                    geom = geom.difference(ex)
                except Exception:  # noqa: BLE001
                    pass
        hatch = "////" if wc.get(u["name"]) == "protection" else ""
        if spec.source == "sustainable_fm":
            hatch = _SFM_STATE_HATCH.get((values.get(u["name"]) or {}).get("state"), hatch)
        if is_glyph or is_point or is_vector or is_feature or is_hydro:
            base = "#f4f4f4"
            a = 0.9
            if is_feature and spec.combine_with == "coupe":
                fy = (values.get(u["name"]) or {}).get("felling_year")
                if fy is not None and (spec.year is None or fy == spec.year):
                    base, a = sp.sample_ramp("increment", 5)[3], 0.55
            _fill_unit(ax, geom, base, hatch=hatch, alpha=a)
            continue
        colour = feat_colour.get(u["name"])
        a = spec.fill_alpha if spec.fill_alpha is not None else _FILL_ALPHA
        if spec.viz == "alpha" and spec.alpha_measure:
            aw = (values.get(u["name"]) or {}).get(spec.alpha_measure)
            a = _alpha_from(aw, values, spec.alpha_measure)
        _fill_unit(
            ax, geom, colour, hatch=hatch, alpha=a,
            edge=spec.edge_color or _STROKE, lw=spec.edge_width or 0.4,
        )

    pms._add_boundary_outline(
        ax, boundary, color=spec.boundary_color or "#1b5e20", linewidth=2.5 if not spec.boundary_color else 1.8
    )

    if is_glyph:
        _draw_glyphs(ax, units, values, spec)
    if is_point:
        legend_rows = _draw_point_surface(
            ax, spec, plot_points or [], units, values, boundary, bbox
        )
    if is_vector:
        legend_rows = _draw_vector_field(ax, units, values, spec)
    if is_hydro:
        legend_rows = _draw_hydro_lines(ax, hydro_lines or [])
    if is_feature:
        legend_rows = _draw_activity_features(ax, features or [], spec)

    # P5b — one fill + one centroid glyph (§3.5.1). `combine_with` names another
    # spec whose glyph is drawn over this choropleth.
    if spec.combine_with and not is_glyph:
        from app.services.operational_plan.thematic_map_spec import resolve_spec

        other = resolve_spec(spec.combine_with)
        if other is not None and other.viz in GLYPH_TECHNIQUES:
            _draw_glyphs(ax, units, values, other)

    if spec.viz in ("graduated", "graduated_nested"):
        _draw_proportional(ax, units, values, spec, numeric_series)

    if spec.show_value_labels:
        _draw_value_labels(ax, units, numeric_series)
    if spec.show_unit_labels:
        _draw_unit_type_labels(ax, units, values, spec)

    pms._add_grid(ax, min_lon, max_lon, min_lat, max_lat)
    pms._add_neatline(ax, slon[2], slon[3], slat[2], slat[3])
    ax.axis("off")
    pms._add_north_arrow(ax)
    pms._add_scale_bar(ax, min_lon, max_lon, min_lat, max_lat)  # P5a
    _thematic_legend(ax, spec, _sfm_legend_rows(spec, legend_rows, units, values))
    if any(v == "protection" for v in wc.values()):
        _add_protection_note(ax)

    _title_and_caption(
        fig,
        ax,
        spec,
        forest_name,
        {
            "field_inventory": "स्रोत: क्षेत्र सर्वेक्षण",
            "sustainable_fm": "स्रोत: दिगो वन व्यवस्थापन वर्गीकरण",
        }.get(spec.source, "स्रोत: ज्यामिति"),
    )

    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════
# P5b — centroid glyphs + small multiples
# ═══════════════════════════════════════════════════════════════════════════
GLYPH_TECHNIQUES = frozenset(
    {
        "pie",
        "donut",
        "stackbar",
        "radar",
        "waffle",
        "sparkline",
        "ternary",
        "rose",
    }
)
_GLYPH_MAX_UNITS = 15  # above this, auto small-multiples (§3.5.5)

_DBH_LABELS_NP = {
    "0_4": "बिरुवा",
    "4_10": "लाथ्रा",
    "10_20": "सानो खाँवा",
    "20_30": "ठुलो खाँवा",
    "30_40": "सानो रुख",
    "40_50": "मझौला रुख",
    "50_60": "ठुलो रुख",
    "60_plus": "अति ठुलो रुख",
}


def _glyph_point(geom):
    """Pole of inaccessibility — the visual centre, always inside the polygon."""
    try:
        from shapely.ops import polylabel

        p = polylabel(geom, tolerance=max(geom.bounds[2] - geom.bounds[0], 1e-4) / 100)
        return p.x, p.y
    except Exception:  # noqa: BLE001
        p = geom.representative_point()
        return p.x, p.y


def _composition(unit_name: str, values: dict, spec: ThematicMapSpec):
    """``[(label_ne, value, hex)]`` for one unit's composition glyph."""
    rec = values.get(unit_name) or {}
    m = spec.measure or ""
    _zonal_key = {
        "slope_classes": "_slope_glyph",
        "landcover_classes": "_landcover_glyph",
        "aspect_bins": "_aspect_glyph",
    }.get(m)
    if _zonal_key:
        # S9 / P6z — raster_zonal pre-builds the (label, value, hex) triples so
        # the glyph colours come straight from the raster class palettes.
        return list(rec.get(_zonal_key) or rec.get("_zonal_glyph") or [])
    if m == "species:share":  # each unit's top species by share of volume, the rest as "other"
        own = spec.colour_overrides or {}
        classes = {c["key"]: c for c in _species_classes(values)}
        shares = rec.get("species_shares") or []
        out = []
        other = 0.0
        for i, s in enumerate(shares):
            c = classes.get(s["key"])
            if i < 5 and c:
                out.append((s["name"], float(s["value"]), own.get(s["key"]) or c["color"]))
            else:
                other += float(s["value"])
        if other > 0:
            out.append((OTHER_SPECIES_LABEL_NE, other, own.get("other_species") or OTHER_SPECIES_COLOUR))
        return out
    if m == "dbh10:stock":  # trees from 10 cm up: timber + firewood m3/ha per class, spectral colours
        bd = rec.get("dbh_class_breakdown") or {}
        own = spec.colour_overrides or {}
        out = []
        for i, (k, hexv) in enumerate(sp.CATEGORICAL["dbh_classes_10plus"].items()):
            cell = bd.get(k) or {}
            vol = float(cell.get("timber_m3_per_ha") or 0) + float(cell.get("firewood_m3_per_ha") or 0)
            out.append((_DBH_LABELS_NP.get(k, k), vol, own.get(str(i)) or hexv))
        return out
    if m.startswith("dbh:"):  # dbh:count | dbh:timber | dbh:firewood
        sub = {
            "count": "count_per_ha",
            "timber": "timber_m3_per_ha",
            "firewood": "firewood_m3_per_ha",
        }.get(m.split(":", 1)[1], "count_per_ha")
        bd = rec.get("dbh_class_breakdown") or {}
        palette = sp.CATEGORICAL.get("dbh_classes", {})
        out = []
        own = spec.colour_overrides or {}
        for i, (k, hexv) in enumerate(palette.items()):
            cell = bd.get(k) or {}
            out.append((_DBH_LABELS_NP.get(k, k), float(cell.get(sub) or 0), own.get(str(i)) or hexv))
        return out
    comps = spec.components or []
    if spec.palette in sp.CATEGORICAL:
        pal = list(sp.CATEGORICAL[spec.palette].values())
    else:
        pal = sp.sample_ramp(spec.palette, max(1, len(comps)))
    own = spec.colour_overrides or {}
    return [
        (c.replace("_", " ").strip(), float(rec.get(c) or 0), own.get(str(i)) or pal[i % len(pal)])
        for i, c in enumerate(comps)
    ]


def _glyph_legend(spec: ThematicMapSpec, values: dict):
    """One shared swatch list for a glyph map (Appendix C.8)."""
    any_unit = next(iter(values), None)
    if spec.measure == "species:share":  # the forest-wide species list, not one unit's
        own = spec.colour_overrides or {}
        rows = [(own.get(c["key"]) or c["color"], c["name"]) for c in _species_classes(values)[:5]]
        rows.append((own.get("other_species") or OTHER_SPECIES_COLOUR, OTHER_SPECIES_LABEL_NE))
        rows.append(("#ffffff00", "— एक एकाइ = एक चित्र —"))
        return rows
    comps = _composition(any_unit, values, spec) if any_unit else []
    rows = [(hexv, lbl) for lbl, _v, hexv in comps]
    rows.append(("#ffffff00", "— एक एकाइ = एक चित्र —"))
    return rows


def _draw_glyphs(ax, units, values, spec: ThematicMapSpec):
    """Draw one glyph per unit at its pole of inaccessibility."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    gsize = min(x1 - x0, y1 - y0) * 0.11  # data-units glyph half-extent

    # a shared magnitude scale for stackbar / waffle
    totals = []
    for u in units:
        comps = _composition(u["name"], values, spec)
        totals.append(sum(v for _l, v, _c in comps))
    tmax = max(totals) or 1.0

    for u in units:
        cx, cy = _glyph_point(u["geometry"])
        comps = _composition(u["name"], values, spec)
        vals = [v for _l, v, _c in comps]
        cols = [c for _l, _v, c in comps]
        if not any(vals):
            continue
        if spec.viz in ("pie", "donut"):
            # pies read much larger than the other glyphs at the same half-extent
            _g_pie(ax, cx, cy, gsize * 0.55, vals, cols, donut=(spec.viz == "donut"))
        elif spec.viz == "stackbar":
            _g_stackbar(ax, cx, cy, gsize, vals, cols, sum(vals) / tmax)
        elif spec.viz == "waffle":
            _g_waffle(ax, cx, cy, gsize, vals, cols)
        elif spec.viz == "sparkline":
            _g_sparkline(ax, cx, cy, gsize, vals)
        elif spec.viz == "radar":
            _g_radar(ax, cx, cy, gsize, u["name"], values, spec)
        elif spec.viz == "ternary":
            _g_ternary(ax, cx, cy, gsize, vals, cols)
        elif spec.viz == "rose":
            _g_rose(ax, cx, cy, gsize, vals, cols)


def _g_pie(ax, cx, cy, s, vals, cols, *, donut=False):
    tot = sum(vals) or 1.0
    a0 = 90.0
    from matplotlib.patches import Wedge

    for v, c in zip(vals, cols):
        if v <= 0:
            continue
        a1 = a0 - 360.0 * v / tot
        ax.add_patch(
            Wedge(
                (cx, cy),
                s,
                a1,
                a0,
                width=(s * 0.5 if donut else None),
                facecolor=c,
                edgecolor="white",
                linewidth=0.4,
                zorder=8,
            )
        )
        a0 = a1


def _g_stackbar(ax, cx, cy, s, vals, cols, height_frac):
    tot = sum(vals) or 1.0
    w = s * 0.7
    h = 2 * s * max(0.15, height_frac)
    y = cy - h / 2
    for v, c in zip(vals, cols):
        seg = h * v / tot
        ax.add_patch(
            plt.Rectangle(
                (cx - w / 2, y),
                w,
                seg,
                facecolor=c,
                edgecolor="white",
                linewidth=0.3,
                zorder=8,
            )
        )
        y += seg


def _g_waffle(ax, cx, cy, s, vals, cols, n=5):
    tot = sum(vals) or 1.0
    cells = []
    for v, c in zip(vals, cols):
        cells += [c] * max(0, round(n * n * v / tot))
    cells = cells[: n * n] + ["#eeeeee"] * (n * n - len(cells))
    cw = 2 * s / n
    for i, c in enumerate(cells):
        r, col = divmod(i, n)
        ax.add_patch(
            plt.Rectangle(
                (cx - s + col * cw, cy - s + r * cw),
                cw * 0.85,
                cw * 0.85,
                facecolor=c,
                edgecolor="none",
                zorder=8,
            )
        )


def _g_sparkline(ax, cx, cy, s, vals):
    n = len(vals)
    if n < 2:
        return
    vmax = max(vals) or 1.0
    xs = [cx - s + 2 * s * i / (n - 1) for i in range(n)]
    ys = [cy - s * 0.6 + 1.2 * s * (v / vmax) for v in vals]
    ax.plot(xs, ys, color="#333333", linewidth=1.0, zorder=8)
    ax.plot(xs[-1], ys[-1], "o", ms=2.5, color="#c62828", zorder=8)


_RADAR_AXES = (
    "forest_condition",
    "regeneration_condition",
    "mai_percent",
    "basal_area_m2_per_ha",
    "carbon_stock_tc_per_ha",
)
_COND_RANK = {"Weak": 0.2, "Moderate": 0.6, "Good": 1.0}


def _g_radar(ax, cx, cy, s, name, values, spec):
    axes = spec.glyph_axes or list(_RADAR_AXES)
    # normalise each axis 0..1 over all units
    norm = {}
    for a in axes:
        vs = []
        for rec in values.values():
            v = rec.get(a)
            vs.append(
                _COND_RANK.get(str(v))
                if v in _COND_RANK
                else (float(v) if _is_num(v) else None)
            )
        real = [x for x in vs if x is not None]
        norm[a] = (min(real) if real else 0, max(real) if real else 1)
    rec = values.get(name) or {}
    pts = []
    k = len(axes)
    for i, a in enumerate(axes):
        v = rec.get(a)
        x = (
            _COND_RANK.get(str(v))
            if v in _COND_RANK
            else (float(v) if _is_num(v) else None)
        )
        lo, hi = norm[a]
        f = 0.0 if x is None or hi <= lo else max(0.0, min(1.0, (x - lo) / (hi - lo)))
        ang = math.pi / 2 - 2 * math.pi * i / k
        pts.append((cx + s * f * math.cos(ang), cy + s * f * math.sin(ang)))
    for ring in (0.5, 1.0):
        ax.add_patch(
            plt.Circle(
                (cx, cy),
                s * ring,
                fill=False,
                edgecolor="#cccccc",
                linewidth=0.3,
                zorder=7,
            )
        )
    poly = plt.Polygon(
        pts,
        closed=True,
        facecolor=sp.CATEGORICAL["condition"]["Moderate"],
        alpha=0.35,
        edgecolor="#1b5e20",
        linewidth=0.8,
        zorder=8,
    )
    ax.add_patch(poly)


def _g_ternary(ax, cx, cy, s, vals, cols):
    if len(vals) != 3 or sum(vals) <= 0:
        return
    a, b, c = (v / sum(vals) for v in vals)
    # triangle corners
    top = (cx, cy + s)
    left = (cx - s * 0.87, cy - s * 0.5)
    right = (cx + s * 0.87, cy - s * 0.5)
    ax.add_patch(
        plt.Polygon(
            [top, left, right],
            closed=True,
            fill=False,
            edgecolor="#999999",
            linewidth=0.5,
            zorder=7,
        )
    )
    px = a * top[0] + b * left[0] + c * right[0]
    py = a * top[1] + b * left[1] + c * right[1]
    ax.plot(px, py, "o", ms=4, color="#2e7d32", zorder=8)


def _g_rose(ax, cx, cy, s, vals, cols):
    """8-petal wind/aspect rose — ``vals`` in COMPASS order (N, NE, … NW),
    N at the top, going clockwise; petal length ∝ share."""
    from matplotlib.patches import Wedge

    if not vals or sum(vals) <= 0:
        return
    n = len(vals)
    vmax = max(vals) or 1.0

    step = 360.0 / n
    for i, (v, c) in enumerate(zip(vals, cols)):
        if v <= 0:
            continue
        centre = (90.0 - i * step) % 360.0  # N at top, clockwise
        r = s * (0.25 + 0.75 * v / vmax)
        ax.add_patch(
            Wedge(
                (cx, cy),
                r,
                centre - step / 2 + 3,
                centre + step / 2 - 3,
                facecolor=c,
                edgecolor="white",
                linewidth=0.4,
                zorder=8,
            )
        )
    ax.add_patch(
        plt.Circle((cx, cy), s * 0.06, facecolor="#444444", edgecolor="none", zorder=9)
    )


def _compose_small_multiples(spec, units, values, wc, bbox, forest_name, dpi):
    """One mini-panel per unit — used when a glyph map has too many units, or
    for ``spec.viz == "smallmultiples"``."""
    n = len(units)
    cols = min(5, max(2, math.ceil(math.sqrt(n))))
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(pms.FIG_SIZE_INCHES[0], pms.FIG_SIZE_INCHES[1] * rows / cols * 1.05),
        dpi=dpi,
    )
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]
    glyph_spec = spec.model_copy(
        update={"viz": spec.viz if spec.viz in GLYPH_TECHNIQUES else "stackbar"}
    )
    for i, ax in enumerate(axes):
        ax.set_axis_off()
        if i >= n:
            continue
        u = units[i]
        gx0, gy0, gx1, gy1 = u["geometry"].bounds
        pad = max(gx1 - gx0, gy1 - gy0) * 0.15 or 0.001
        ax.set_xlim(gx0 - pad, gx1 + pad)
        ax.set_ylim(gy0 - pad, gy1 + pad)
        ax.set_aspect("equal")
        _fill_unit(
            ax,
            u["geometry"],
            "#f2f2f2",
            hatch="////" if wc.get(u["name"]) == "protection" else "",
            alpha=0.9,
        )
        _draw_glyphs(ax, [u], values, glyph_spec)
        ax.set_title(u["name"], fontsize=7, fontproperties=dev_font_prop(7), pad=2)
    ttl = (f"{forest_name} — " if forest_name else "") + (spec.label_ne or spec.key)
    fig.suptitle(
        ttl,
        fontsize=12,
        fontweight="bold",
        fontproperties=dev_bold_font_prop(12),
        color="#1b5e20",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════
# P6 — point / density / surface techniques
# ═══════════════════════════════════════════════════════════════════════════
POINT_SURFACE_TECHNIQUES = frozenset(
    {"dotcat", "dotdensity", "hexbin", "heatmap", "isopleth"}
)


def _load_plot_points(db, calculation_id) -> list[dict]:
    """``[{lon, lat, block_name, zone_type, gs_raw, plot_number}]`` for the
    forest's field-inventory sample plots. ``gs_raw`` = Σ(net_volume·count) of
    Pole+Tree measurements — a density proxy for the interpolated surface."""
    try:
        from geoalchemy2.shape import to_shape
        from sqlalchemy import func

        from app.models.field_inventory import (
            FieldInventoryCalculation as _FC,
            FieldInventoryMeasurement as _M,
            FieldInventorySamplePlot as _P,
        )
    except Exception:  # noqa: BLE001
        return []

    try:
        vol_sub = (
            db.query(
                _M.sample_plot_id.label("pid"),
                func.coalesce(
                    func.sum(
                        func.coalesce(_M.net_volume, 0) * func.coalesce(_M.count, 1)
                    ),
                    0,
                ).label("v"),
            )
            .filter(_M.stand_type.in_(("Pole", "Tree")))
            .group_by(_M.sample_plot_id)
            .subquery()
        )
        rows = (
            db.query(
                _P.location,
                _P.block_name,
                _P.zone_type,
                _P.sample_plot_number,
                func.coalesce(vol_sub.c.v, 0),
            )
            .join(_FC, _P.field_inventory_calculation_id == _FC.id)
            .outerjoin(vol_sub, vol_sub.c.pid == _P.id)
            .filter(_FC.calculation_id == calculation_id)
            .all()
        )
    except Exception:  # noqa: BLE001 -- missing table / bad geom → no points
        logger.warning("plot-point load failed for %s", calculation_id, exc_info=True)
        return []

    out = []
    for loc, bn, zt, num, vol in rows:
        try:
            p = to_shape(loc)
            out.append(
                {
                    "lon": p.x,
                    "lat": p.y,
                    "block_name": (bn or "").strip(),
                    "zone_type": (zt or "productive"),
                    "plot_number": num,
                    "gs_raw": float(vol or 0),
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return out


# stem-map dot colours: the printed plans draw felling trees red and mother trees green
_TREE_GROUP_COLOURS = {"Felling Tree": "#d32f2f", "Mother Tree": "#2e7d32", "Protected Tree": "#1565c0", "Other": "#6d4c41"}
_TREE_GROUP_LABELS = {"Felling Tree": "कटान (FT) रुख", "Mother Tree": "माउ (MT) रुख", "Protected Tree": "संरक्षित (PT) रुख", "Other": "अन्य रुख"}


def _load_tree_points(db, calculation_id, which: str = "all") -> list[dict]:
    """``[{lon, lat, remark_group}]`` for the forest's stem-mapped trees (``inventory_trees``, stand type Tree).

    ``which``: all | felling | mother | protected (a Tree with no felling / mother remark). Dots only - no
    attributes are drawn, so a 1,200-tree unit stays readable.
    """
    from sqlalchemy import text

    wanted = {"felling": ("Felling Tree",), "mother": ("Mother Tree",), "protected": (None,)}.get(which)
    try:
        rows = db.execute(
            text(
                """
                SELECT ST_X(t.location::geometry), ST_Y(t.location::geometry), t.remark
                  FROM inventory_trees t
                  JOIN inventory_calculations ic ON ic.id = t.inventory_calculation_id
                 WHERE ic.calculation_id = :cid AND t.stand_type = 'Tree'
                """
            ),
            {"cid": str(calculation_id)},
        ).all()
    except Exception:  # noqa: BLE001 -- missing table / bad geometry -> no points; the map says "no data"
        logger.warning("tree-point load failed for %s", calculation_id, exc_info=True)
        return []
    out = []
    for lon, lat, remark in rows:
        if wanted is not None and (remark or None) not in wanted:
            continue
        group = remark if remark in ("Felling Tree", "Mother Tree") else ("Protected Tree" if which == "protected" else "Other")
        out.append({"lon": lon, "lat": lat, "remark_group": group})
    return out


_NTFP_GROUP_COLOURS = {"Recorded": "#2e7d32", "Partly recorded": "#fb8c00", "Not visited": "#9e9e9e"}
_NTFP_GROUP_LABELS = {"Recorded": "अभिलेख पूरा", "Partly recorded": "आंशिक अभिलेख", "Not visited": "भ्रमण भएको छैन"}


def _load_ntfp_plot_points(db, calculation_id) -> list[dict]:
    """``[{lon, lat, status_group}]`` for the NTFP survey's sample plots (stored design and records only)."""
    from app.services import ntfp_records_service

    try:
        return ntfp_records_service.plot_points(db, calculation_id)
    except Exception:  # noqa: BLE001 -- missing table / bad geometry -> no points; the map says "no data"
        logger.warning("ntfp plot-point load failed for %s", calculation_id, exc_info=True)
        return []


def _boundary_clip_path(ax, boundary):
    """A matplotlib Path of the whole boundary (every part), for clipping filled contours."""
    try:
        from matplotlib.path import Path as MplPath

        polys = _poly_list(boundary) if boundary is not None else []
        if not polys:
            return None
        # EVERY part of the boundary, not just the first: a forest of two polygons used to show its surface in one
        # of them only, and the part left blank was the one with the higher erosion. Holes are wound the opposite way
        # so they stay cut out.
        from shapely.geometry.polygon import orient

        verts: list = []
        codes: list = []
        for poly in polys:
            poly = orient(poly, sign=1.0)  # exterior counter-clockwise, holes clockwise: holes stay cut out
            for ring in [poly.exterior, *poly.interiors]:
                pts = list(ring.coords)
                verts.extend(pts)
                codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(pts) - 2) + [MplPath.CLOSEPOLY])
        return MplPath(verts, codes)
    except Exception:  # noqa: BLE001
        return None


def _draw_point_surface(ax, spec, points, units, values, boundary, bbox):
    """Render a point / density / surface technique; return legend rows."""
    x0, y0, x1, y1 = bbox

    if spec.viz == "dotdensity":
        return _draw_dot_density(ax, spec, units, values)

    if not points:
        ax.text(
            0.5,
            0.5,
            sp.NO_DATA_LABEL_NE,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontproperties=dev_font_prop(10),
            color="#999999",
        )
        return [(sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE)]

    lons = [p["lon"] for p in points]
    lats = [p["lat"] for p in points]

    if spec.viz == "dotcat":
        field = spec.measure or "zone_type"
        cats: list[str] = []
        for p in points:
            v = str(p.get(field, ""))
            if v not in cats:
                cats.append(v)
        cats.sort()
        pal = (
            list(sp.CATEGORICAL[spec.palette].values())
            if spec.palette in sp.CATEGORICAL
            else sp.sample_ramp(spec.palette or "species_qual", max(1, len(cats)))
        )
        cmap = {c: pal[i % len(pal)] for i, c in enumerate(cats)}
        is_tree = spec.layer == "tree"
        is_ntfp = spec.layer == "ntfp_plot"
        if is_tree:  # stem maps use the printed-plan colours, and smaller dots (hundreds of trees)
            cmap = {c: _TREE_GROUP_COLOURS.get(c, "#6d4c41") for c in cats}
        if is_ntfp:  # grey = not visited, amber = partly recorded, green = recorded: the same colours as the workspace layer
            cats = [c for c in _NTFP_GROUP_COLOURS if c in cats]
            cmap = dict(_NTFP_GROUP_COLOURS)
        for c in cats:
            xs = [p["lon"] for p in points if str(p.get(field, "")) == c]
            ys = [p["lat"] for p in points if str(p.get(field, "")) == c]
            ax.scatter(
                xs, ys, s=5 if is_tree else 30 if is_ntfp else 14, c=cmap[c], edgecolors="none" if is_tree else "white",
                linewidths=0.4, zorder=8
            )
        return [(cmap[c], (_TREE_GROUP_LABELS.get(c, c) if is_tree else _NTFP_GROUP_LABELS.get(c, c) if is_ntfp else c) or "—") for c in cats]

    if spec.viz == "hexbin":
        hb = ax.hexbin(
            lons,
            lats,
            gridsize=14,
            cmap="Reds",
            mincnt=1,
            edgecolors="none",
            zorder=7,
            alpha=0.85,
        )
        counts = hb.get_array()
        lo = int(counts.min()) if len(counts) else 0
        hi = int(counts.max()) if len(counts) else 0
        pal = sp.sample_ramp("reds", 4)
        return [(pal[0], f"{lo}"), (pal[-1], f"{hi}"), ("#ffffff00", "प्रति हेक्स गणना")]

    if spec.viz == "heatmap":
        w = [max(p.get("gs_raw", 0), 1e-6) for p in points]
        _kde_fill(ax, lons, lats, w, bbox, boundary, ramp="reds")
        pal = sp.sample_ramp("reds", 3)
        return [(pal[0], "न्यून"), (pal[-1], "उच्च")]

    if spec.viz == "isopleth":
        z = [p.get("gs_raw", 0) for p in points]
        ramp = (
            spec.palette
            if spec.palette in sp.RAMPS or spec.palette in sp.SEQUENTIAL
            else "greens"
        )
        levels = _idw_contourf(ax, lons, lats, z, bbox, boundary, ramp=ramp)
        pal = (
            sp.sample_ramp(ramp, len(levels) + 1) if levels else sp.sample_ramp(ramp, 5)
        )
        rows = []
        for i, c in enumerate(pal):
            lo = None if i == 0 else levels[i - 1]
            hi = levels[i] if i < len(levels) else None
            lbl = (
                f"≤ {format_devanagari(hi, 0)}"
                if lo is None
                else (
                    f"> {format_devanagari(lo, 0)}"
                    if hi is None
                    else f"{format_devanagari(lo, 0)}–{format_devanagari(hi, 0)}"
                )
            )
            rows.append((c, lbl))
        return rows
    return []


def _draw_dot_density(ax, spec, units, values):
    """N random dots inside each unit polygon, N ∝ the unit's numeric value."""
    import random

    series = _numeric_series(units, values, spec)
    nums = [v for v in series.values() if v is not None]
    if not nums:
        return [(sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE)]
    per_dot = max(1.0, (sum(nums) / len(nums)) / 12.0)
    colour = sp.sample_ramp(spec.palette or "oranges", 5)[-1]
    rng = random.Random(42)
    for u in units:
        v = series.get(u["name"])
        if not v:
            continue
        n = int(v / per_dot)
        g = u["geometry"]
        gx0, gy0, gx1, gy1 = g.bounds
        placed = 0
        tries = 0
        from shapely.geometry import Point

        while placed < n and tries < n * 30:
            px = rng.uniform(gx0, gx1)
            py = rng.uniform(gy0, gy1)
            tries += 1
            if g.contains(Point(px, py)):
                ax.plot(px, py, "o", ms=1.6, color=colour, zorder=8)
                placed += 1
    return [(colour, f"१ थोप्लो ≈ {format_devanagari(per_dot, 0)}")]


def _draw_vector_field(ax, units, values, spec):
    """P6z — one arrow per unit centroid pointing in the dominant-aspect
    (downslope) compass direction. ``values[name]['_aspect_angle_deg']`` is a
    matplotlib-convention angle (0°=E, CCW) from ``raster_zonal``."""
    import math

    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    L = min(x1 - x0, y1 - y0) * 0.10
    drawn = 0
    for u in units:
        rec = values.get(u["name"]) or {}
        ang = rec.get("_aspect_angle_deg")
        if ang is None:
            continue
        cx, cy = _glyph_point(u["geometry"])
        dx = L * math.cos(math.radians(ang))
        dy = L * math.sin(math.radians(ang))
        ax.annotate(
            "",
            xy=(cx + dx, cy + dy),
            xytext=(cx - dx * 0.2, cy - dy * 0.2),
            arrowprops=dict(arrowstyle="-|>", color="#1a1a1a", lw=1.6),
            zorder=9,
        )
        lbl = rec.get("aspect_dominant")
        if lbl:
            ax.text(
                cx + dx * 1.15,
                cy + dy * 1.15,
                str(lbl),
                fontproperties=dev_font_prop(8),
                ha="center",
                va="center",
                color="#1a1a1a",
                zorder=9,
            )
        drawn += 1
    if not drawn:
        ax.text(
            0.5,
            0.5,
            sp.NO_DATA_LABEL_NE,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontproperties=dev_font_prop(10),
            color="#999999",
        )
        return [(sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE)]
    return [("#1a1a1a", "मोहडा दिशा (तल्लो ढलान)")]


def _draw_hydro_lines(ax, lines):
    """Draw river / stream geometry (``river.river84``, already clipped to the
    forest) as blue lines. ``lines`` is ``[(shapely_geom, name), …]``."""
    from shapely.geometry import LineString, MultiLineString

    drawn = 0
    names: list[str] = []
    for geom, nm in lines or []:
        parts = getattr(geom, "geoms", [geom])
        for part in parts:
            if isinstance(part, (LineString, MultiLineString)) and not part.is_empty:
                for seg in getattr(part, "geoms", [part]):
                    try:
                        xs, ys = seg.xy
                    except Exception:  # noqa: BLE001
                        continue
                    ax.plot(
                        xs,
                        ys,
                        color="#1565c0",
                        linewidth=1.4,
                        solid_capstyle="round",
                        zorder=8,
                    )
                    drawn += 1
        if nm and nm not in names:
            names.append(nm)
    if not drawn:
        ax.text(
            0.5,
            0.5,
            sp.NO_DATA_LABEL_NE,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontproperties=dev_font_prop(10),
            color="#999999",
        )
        return [(sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE)]
    label = "नदी / खोला — " + ", ".join(names[:3]) if names else "नदी / खोला"
    return [("#1565c0", label)]


def _clip_contourf(cf, clip, ax):
    """Clip a filled-contour set to a path — matplotlib ≥3.10 dropped
    ``QuadContourSet.collections``; the set is itself a clippable artist now."""
    if clip is None:
        return
    try:
        colls = cf.collections  # matplotlib < 3.10
    except AttributeError:
        colls = [cf]
    for coll in colls:
        coll.set_clip_path(clip, transform=ax.transData)


def _idw_contourf(ax, xs, ys, zs, bbox, boundary, *, ramp="greens", power=2, n=60):
    """Inverse-distance-weighted surface → filled contours, clipped to boundary."""
    import numpy as np

    pts = [(x, y, z) for x, y, z in zip(xs, ys, zs) if z is not None]
    if len(pts) < 3:
        return []
    x0, y0, x1, y1 = bbox
    gx = np.linspace(x0, x1, n)
    gy = np.linspace(y0, y1, n)
    GX, GY = np.meshgrid(gx, gy)
    px = np.array([p[0] for p in pts])
    py = np.array([p[1] for p in pts])
    pz = np.array([p[2] for p in pts], dtype=float)
    Z = np.zeros_like(GX)
    for i in range(n):
        for j in range(n):
            d2 = (GX[i, j] - px) ** 2 + (GY[i, j] - py) ** 2
            d2 = np.where(d2 < 1e-12, 1e-12, d2)
            w = 1.0 / d2 ** (power / 2)
            Z[i, j] = float((w * pz).sum() / w.sum())
    breaks = sp.quantile_breaks(list(pz), 5)
    levels = [float(pz.min())] + list(breaks) + [float(pz.max()) + 1e-6]
    levels = sorted(set(levels))
    if len(levels) < 3:
        return []
    colours = sp.sample_ramp(ramp, len(levels) - 1)
    cf = ax.contourf(GX, GY, Z, levels=levels, colors=colours, alpha=0.75, zorder=6)
    _clip_contourf(cf, _boundary_clip_path(ax, boundary), ax)
    return breaks


def _kde_fill(ax, xs, ys, w, bbox, boundary, *, ramp="reds", n=60):
    """Gaussian KDE of weighted points → filled density, clipped to boundary."""
    import numpy as np

    if len(xs) < 3:
        return
    x0, y0, x1, y1 = bbox
    try:
        from scipy.stats import gaussian_kde

        k = gaussian_kde(np.vstack([xs, ys]), weights=np.array(w, dtype=float))
        gx = np.linspace(x0, x1, n)
        gy = np.linspace(y0, y1, n)
        GX, GY = np.meshgrid(gx, gy)
        Z = k(np.vstack([GX.ravel(), GY.ravel()])).reshape(GX.shape)
    except Exception:  # noqa: BLE001 -- no scipy → a coarse binned density
        gx = np.linspace(x0, x1, n)
        gy = np.linspace(y0, y1, n)
        Z, _, _ = np.histogram2d(xs, ys, bins=[gx, gy], weights=w)
        Z = Z.T
        GX, GY = np.meshgrid(gx[:-1], gy[:-1])
    colours = sp.sample_ramp(ramp, 6)
    cf = ax.contourf(GX, GY, Z, levels=6, colors=colours, alpha=0.7, zorder=6)
    _clip_contourf(cf, _boundary_clip_path(ax, boundary), ax)


# ── helpers used by _render ──────────────────────────────────────────────
def _load_working_circle(db, calculation_id) -> dict[str, str]:
    try:
        from app.services.operational_plan.data_collector import (
            _fetch_block_working_circle,
        )

        return _fetch_block_working_circle(db, str(calculation_id)) or {}
    except Exception:  # noqa: BLE001
        return {}


def _excluded_polys(db, calculation_id):
    out = []
    for sa in pms._get_sub_areas_with_geometry(db, calculation_id):
        if sa.get("is_excluded"):
            out.append(sa["geometry"])
    return out


def _alpha_from(w, values, key) -> float:
    nums = [float((r or {}).get(key) or 0) for r in values.values()]
    hi = max(nums) if nums else 0
    if not hi or w is None:
        return 0.35
    return 0.35 + 0.6 * min(1.0, float(w) / hi)


def _draw_proportional(ax, units, values, spec, series):
    absolute = {}
    for u in units:
        per_ha = series.get(u["name"])
        if per_ha is None:
            continue
        area = u.get("area_ha") or 0
        absolute[u["name"]] = per_ha * area if spec.normalize == "per_area" else per_ha
    if not absolute:
        return
    vmax = max(absolute.values()) or 1.0
    colours = sp.sample_ramp(spec.palette, 5)
    for u in units:
        v = absolute.get(u["name"])
        if not v:
            continue
        c = u["geometry"].centroid
        r = (
            3 + (26 - 3) * (v / vmax) ** 0.57
            if spec.scale_by == "flannery"
            else 3 + 23 * (v / vmax)
        )
        ax.scatter(
            [c.x],
            [c.y],
            s=math.pi * r * r,
            facecolor=colours[-1],
            edgecolor="#333333",
            linewidth=0.5,
            alpha=0.8,
            zorder=6,
        )


# A unit smaller than this share of the map gets no label (it would only smudge); one smaller than the second
# gets the type alone, without its name.
_LABEL_MIN_FRAC = 0.002
_LABEL_NAME_MIN_FRAC = 0.015


_SLOPE_BAND_LABEL = {1: "<19°", 2: "19–31°", 3: "31–45°", 4: ">45°"}


def _unit_label_second_line(kind: str, info: dict) -> str | None:
    """The line under the unit name for each of the three SFM maps; ``None`` = nothing to say for this unit."""
    type_no = info.get("effective_type_no")
    state = info.get("state")
    if kind == "stock":
        gs = info.get("gs_ge40_m3_per_ha")
        return f"{float(gs):.0f} m³/ha" if gs is not None else "—"
    if type_no is None and state not in ("non_forest", "inventory_missing"):
        return None
    if type_no is None:  # not forest land, or no sample plots of its own: say why
        return "Non-forest" if state == "non_forest" else "No plots"
    if kind == "orientation":
        o = info.get("orientation")
        return sp.CATEGORY_LABELS_NE["sfm_orientation"].get(o, o) if o else None
    band = _SLOPE_BAND_LABEL.get(info.get("slope_band"))
    text = f"Type-{int(type_no)}" + (f" · {band}" if band else "")
    if state == "provisional":  # fewer than 5 plots: say how many, next to the hatch
        text += f" · {int(info.get('plot_count') or 0)} plots"
    return text


def _place_two_line_labels(ax, units, second_by_name, on_imagery):
    """Small plain halo text on each unit: its name, and under it ``second_by_name[name]``.

    Over satellite imagery the text is white with a dark halo (dark text would vanish on forest); otherwise dark with
    a white halo. Placed on a point guaranteed to lie INSIDE the polygon; sized to fit: a unit too small gets the
    second line only, or nothing.

    Two separate texts, one above the other: a newline character inside Devanagari text does not break the line (it
    renders as a missing-glyph box and the two lines run together), so the name and the second line are placed by
    offsets instead."""
    colour, halo_colour = ("#ffffff", "#0d1b0f") if on_imagery else ("#1b1b1b", "#ffffff")
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    map_area = abs((x1 - x0) * (y1 - y0)) or 1.0
    halo = [pe.withStroke(linewidth=1.8, foreground=halo_colour)]
    for u in units:
        second = second_by_name.get(u["name"])
        if second is None:
            continue
        frac = u["geometry"].area / map_area
        if frac < _LABEL_MIN_FRAC:
            continue
        p = u["geometry"].representative_point()
        two_lines = frac >= _LABEL_NAME_MIN_FRAC and bool(u.get("name"))
        common = dict(
            xy=(p.x, p.y),
            textcoords="offset points",
            ha="center",
            fontsize=5.5,
            fontproperties=dev_font_prop(5.5),
            color=colour,
            path_effects=halo,
            zorder=8,
        )
        if two_lines:
            ax.annotate(u["name"], xytext=(0, 1.5), va="bottom", **common)
            ax.annotate(second, xytext=(0, -1.5), va="top", **common)
        else:
            ax.annotate(second, xytext=(0, 0), va="center", **common)


def _draw_unit_type_labels(ax, units, values, spec=None):
    """The SFM maps' labels: the unit name and, under it, what this map is about.

    * forest type map: ``Type-7 · 19–31°`` (the type and the block's dominant slope band)
    * orientation map: the working-circle orientation
    * stock map: the ≥40 cm growing stock, ``210 m³/ha``"""
    kind = getattr(spec, "unit_label_kind", "type") or "type"
    on_imagery = (getattr(spec, "basemap", "") or "").lower() == "imagery"
    seconds = {u["name"]: _unit_label_second_line(kind, values.get(u["name"]) or {}) for u in units}
    _place_two_line_labels(ax, units, seconds, on_imagery)


def _draw_value_labels(ax, units, series):
    for u in units:
        v = series.get(u["name"])
        if v is None:
            continue
        c = u["geometry"].centroid
        ax.annotate(
            format_devanagari(v, 1),
            xy=(c.x, c.y),
            ha="center",
            va="center",
            fontsize=7,
            fontproperties=dev_font_prop(7),
            color="#1b1b1b",
            bbox=dict(
                boxstyle="round,pad=0.15",
                facecolor="white",
                edgecolor="#1b5e20",
                alpha=0.85,
                linewidth=0.4,
            ),
            zorder=7,
        )


def _add_protection_note(ax):
    # A small hatched swatch + a bilingual-friendly note; no exotic glyph
    # (Noto Devanagari / DejaVu Sans lack box-drawing fill characters).
    ax.add_patch(
        plt.Rectangle(
            (0.02, 0.022),
            0.02,
            0.02,
            transform=ax.transAxes,
            facecolor="none",
            edgecolor="#166534",
            hatch="////",
            linewidth=0.4,
            zorder=12,
            clip_on=False,
        )
    )
    ax.text(
        0.045,
        0.03,
        "संरक्षित कार्य वृत्त — कटान छैन",
        transform=ax.transAxes,
        fontsize=6.5,
        fontproperties=dev_font_prop(6.5),
        color="#166534",
        va="center",
        ha="left",
    )


# ═══════════════════════════════════════════════════════════════════════════
# P7 — opsmap drawn features + the 1..10 year axis
# ═══════════════════════════════════════════════════════════════════════════
FEATURE_TECHNIQUES = frozenset({"features", "featurecat", "qaflag"})


def _draw_activity_features(ax, features, spec, *, small=False):
    """Draw ``ActivityDrawnFeature`` geometry with the Appendix C.6 symbology;
    return legend rows for the kinds actually present."""
    from app.services.operational_plan.feature_kinds import style_for
    from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon

    if not features:
        if not small:
            ax.text(
                0.5,
                0.5,
                sp.NO_DATA_LABEL_NE,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontproperties=dev_font_prop(10),
                color="#999999",
            )
        return [(sp.NO_DATA_FILL, sp.NO_DATA_LABEL_NE)]

    present: dict[str, tuple] = {}
    sz = 0.7 if small else 1.0
    for f in features:
        st = style_for(f.get("kind") or "", f.get("feature_type") or "point")
        geom = f.get("geometry")
        if geom is None:
            continue
        present.setdefault(f.get("kind") or "", (st.color, st.label_en))
        try:
            if isinstance(geom, (Polygon, MultiPolygon)):
                for poly in getattr(geom, "geoms", [geom]):
                    xs, ys = poly.exterior.xy
                    ax.fill(
                        xs,
                        ys,
                        facecolor=st.color,
                        alpha=st.alpha or 0.3,
                        edgecolor=st.color,
                        hatch=st.hatch or None,
                        linewidth=1.0 * sz,
                        zorder=st.zorder,
                    )
            elif isinstance(geom, (LineString, MultiLineString)):
                for line in getattr(geom, "geoms", [geom]):
                    xs, ys = line.xy
                    ax.plot(
                        xs,
                        ys,
                        linestyle=st.linestyle,
                        color=st.color,
                        linewidth=st.size * sz,
                        solid_capstyle="round",
                        zorder=st.zorder,
                    )
            else:  # point
                p = geom.centroid if hasattr(geom, "centroid") else geom
                ax.plot(
                    p.x,
                    p.y,
                    marker=st.marker or "o",
                    markersize=st.size * sz,
                    markerfacecolor=st.color,
                    markeredgecolor="white",
                    markeredgewidth=0.6,
                    linestyle="None",
                    zorder=st.zorder,
                )
        except Exception:  # noqa: BLE001 -- one bad feature must not kill the map
            continue

    rows = [(c, lbl) for _k, (c, lbl) in sorted(present.items())]
    rows.append(("#ffffff00", "— प्रस्तावित सुविधाहरू / proposed features —"))
    return rows


def _compose_plan_small_multiples(
    spec, units, values, by_year, features, wc, bbox, boundary, forest_name, dpi
):
    """One mini-map per plan year (§3.4B.1 example 2). Each panel: unit
    outlines + that year's coupe blocks filled + that year's drawn features."""
    years = sorted(by_year) or list(range(1, 11))
    n = len(years)
    cols = 5 if n > 6 else max(2, n)
    nrows = math.ceil(n / cols)
    fig, axes = plt.subplots(
        nrows,
        cols,
        figsize=(pms.FIG_SIZE_INCHES[0], pms.FIG_SIZE_INCHES[1] * nrows / cols * 1.15),
        dpi=dpi,
    )
    axes = axes.ravel() if hasattr(axes, "ravel") else [axes]
    min_lon, min_lat, max_lon, max_lat = bbox
    coupe_col = sp.sample_ramp("increment", 5)[3]

    for i, ax in enumerate(axes):
        ax.set_axis_off()
        if i >= n:
            continue
        y = years[i]
        ax.set_xlim(min_lon, max_lon)
        ax.set_ylim(min_lat, max_lat)
        ax.set_aspect("equal")
        coupe = set((by_year.get(y) or {}).get("coupe_blocks") or [])
        for u in units:
            prot = wc.get(u["name"]) == "protection"
            filled = u["name"] in coupe
            _fill_unit(
                ax,
                u["geometry"],
                coupe_col if filled else "#f4f4f4",
                hatch="////" if prot else "",
                alpha=0.6 if filled else 0.85,
            )
        pms._add_boundary_outline(ax, boundary)
        yf = [f for f in (features or []) if not f.get("years") or y in f.get("years")]
        _draw_activity_features(ax, yf, spec, small=True)
        ax.set_title(
            f"वर्ष {format_devanagari(y, 0)}",
            fontsize=8,
            fontproperties=dev_font_prop(8),
            pad=2,
        )

    ttl = (f"{forest_name} — " if forest_name else "") + (spec.label_ne or spec.key)
    fig.suptitle(
        ttl,
        fontsize=12,
        fontweight="bold",
        fontproperties=dev_bold_font_prop(12),
        color="#1b5e20",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    buf = io.BytesIO()
    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
