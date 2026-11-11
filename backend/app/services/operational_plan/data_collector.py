"""OP data collection from all system modules.

Central collector that gathers all data needed to populate an Operational
Plan document: field inventory, species breakdown, DBH classes, blocks,
compartments, sub-areas, yearly activities, biodiversity, household/demand-
supply, sampling points, and fieldbook records.

Key function:
    collect_all_op_data() — entry point that caches results per calculation.

See also:
    .variable_registry — variable definitions sourced from this data
    .variable_resolver — resolves {{variable}} patterns using this data
    app.services.report.data_collector — upstream collector for report module
"""

import logging
import math
import time
from collections import Counter
from typing import Dict, Any, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

from app.core.constants import (
    METERS_PER_DEGREE_LAT,
    AAH_MULTIPLIER,
    MAI_PCT_MATRIX,
    MAI_PCT_DEFAULT,
    REGEN_PLOT_AREA_SQM,
    SAPLING_PLOT_AREA_SQM,
    POLE_PLOT_AREA_SQM,
    TREE_PLOT_AREA_SQM,
    SQM_PER_HA,
)
from app.core import harvest_groups
from app.core.sub_area_kinds import real_sub_areas
from app.core.dbh_classifier import DbhClassRegistry, FALLBACK_LABEL_FORMATS

# business: per-ha computation per CFMG formula: value / total_plots / plot_area * SQM_PER_HA
# NOTE: plot areas — regeneration=4m², sapling=25m², pole=100m², tree=500m²

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.services.analysis_polygon_source import PolygonSource
from app.models.fieldbook import Fieldbook
from app.models.yearly_activities import (
    ProposedYearlyActivity,
    ActivityYearDetail,
    PotentialActivity,
    ActivitySpatialAssignment,
    ActivityDrawnFeature,
)
from app.services.report.data_collector import (
    collect_all_data as _collect_all_data,
)
from app.services.operational_plan.section_generators import collect_section_content
from app.services.sustainable_fm import sfm_narration

from app.services.forest_units.model import DEPTH_TOP_COMPARTMENT

# The inventory_trees compartment-hierarchy SNAPSHOT's own encoding (FS-1c.4):
# the snapshot's per-tree level key (the write site calls it 'effective_level') is:
#   1 = a top compartment, 2 = a sub-compartment. This is NOT a forest_blocks
# depth read - the column's value changes only when inventory re-snapshots trees.
_INV_SNAP_BOUNDARY = DEPTH_TOP_COMPARTMENT

from app.utils.forest_dimension import (
    ForestDimension,
    get_forest_dimension,
    dimension_label,
    dimension_label_plural,
    dimension_name_header_np,
)

# NOTE: bump this when data_collector or any collector changes schema/keys
OP_DATA_CACHE_VERSION = 32  # 32: RB-4 - plan_extras carries the stored river banks (river_bank_table, totals, fire lines + banks together). 31: FL-6 - plan_extras carries the stored fire lines (fire_line_table and totals). 30: ND-3 — raster_analysis.soil now carries the whole-forest USDA texture distribution (soil_percentages / soil_dominant_type) collected from result_data; 29: 1984 land use read from the polygons into raster_analysis.landcover_historical (+ area per class); 28: more plan_extras keys (unit counts, species names...); 27: plan_extras + species x stage tables added; 26: hazard_aoi_comparison columns renamed (relative high-susceptibility), 25: ya_total_budget_by_year / ya_budget_year_trend hold all ten years

# business: Nepali DBH class labels per CFMG classification — sourced from SSOT dbh_classifier
# NOTE: covers both detailed ("Sm. Pole (10-20)") and space_dash ("10-20 Sm.Pole") key formats
_NP_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")

_guideline_2061 = DbhClassRegistry.get_system("guideline_2061")
DBH_CLASS_NP = {}
DBH_CLASS_NP_CHART = {}
for _c in _guideline_2061:
    _det = DbhClassRegistry.format_label(_c.key, "detailed")
    _spd = DbhClassRegistry.format_label(_det, "space_dash")
    _np_label = DbhClassRegistry.format_label(_c.key, "np_detailed")
    DBH_CLASS_NP[_det] = DBH_CLASS_NP[_spd] = _np_label
    _lo = str(int(_c.lower)).translate(_NP_DIGITS)
    _hi = str(int(_c.upper)).translate(_NP_DIGITS) if _c.upper is not None else ""
    DBH_CLASS_NP_CHART[_spd] = f"{_lo}-{_hi} से.मी." if _c.upper else f">{_lo} से.मी."


# business: CFMG §X.Y — species breakdown by block for growing stock report
# NOTE: per-ha = sum / total_block_plots / plot_area * 10000; divide by ALL plots not species-specific
def _fetch_species_block_breakdown(
    db: Session, fi_calc_id: str, block_areas: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """Block + species level growing stock (Pole + Tree), matching Excel pivot.

    If block_areas is provided, weighted grand total rows per species are appended.
    """
    fi_calc_id_str = str(fi_calc_id)
    pole_area = 100.0
    tree_area = 500.0

    query = text(
        """
        WITH block_total_plots AS (
            SELECT block_name, COUNT(DISTINCT id) as total_plots
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :fi_id
            GROUP BY block_name
        ),
        species_data AS (
            SELECT
                sp.block_name,
                m.species_scientific,
                m.species_local,
                m.stand_type,
                SUM(m.count) as total_count,
                SUM(COALESCE(m.net_volume, 0)) as total_timber,
                SUM(COALESCE(m.firewood_m3, 0)) as total_firewood
            FROM public.field_inventory_sample_plots sp
            JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
            WHERE sp.field_inventory_calculation_id = :fi_id
            GROUP BY sp.block_name, m.species_scientific, m.species_local, m.stand_type
        )
        SELECT
            sd.block_name,
            sd.species_scientific,
            sd.species_local,
            btp.total_plots,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_count ELSE 0 END) as pole_count,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_count ELSE 0 END) as tree_count,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_timber ELSE 0 END) as pole_timber,
            SUM(CASE WHEN sd.stand_type = 'Pole' THEN sd.total_firewood ELSE 0 END) as pole_firewood,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_timber ELSE 0 END) as tree_timber,
            SUM(CASE WHEN sd.stand_type = 'Tree' THEN sd.total_firewood ELSE 0 END) as tree_firewood
        FROM species_data sd
        JOIN block_total_plots btp ON btp.block_name = sd.block_name
        GROUP BY sd.block_name, sd.species_scientific, sd.species_local, btp.total_plots
        ORDER BY sd.block_name, sd.species_scientific
    """
    )
    results = db.execute(query, {"fi_id": fi_calc_id_str}).fetchall()

    rows = []
    for row in results:
        tp = row.total_plots or 1
        # business: per-ha = sum / total_block_plots / plot_area * 10000; pole=100m², tree=500m²
        pole_count_ha = (
            int((float(row.pole_count or 0) / tp / pole_area) * SQM_PER_HA)
            if row.pole_count
            else 0
        )
        tree_count_ha = (
            int((float(row.tree_count or 0) / tp / tree_area) * SQM_PER_HA)
            if row.tree_count
            else 0
        )
        pole_timber_ha = (
            (float(row.pole_timber or 0) / tp / pole_area) * SQM_PER_HA
            if row.pole_timber
            else 0
        )
        pole_firewood_ha = (
            (float(row.pole_firewood or 0) / tp / pole_area) * SQM_PER_HA
            if row.pole_firewood
            else 0
        )
        tree_timber_ha = (
            (float(row.tree_timber or 0) / tp / tree_area) * SQM_PER_HA
            if row.tree_timber
            else 0
        )
        tree_firewood_ha = (
            (float(row.tree_firewood or 0) / tp / tree_area) * SQM_PER_HA
            if row.tree_firewood
            else 0
        )

        rows.append(
            {
                "block_name": row.block_name,
                "species_scientific": row.species_scientific,
                "species_local": row.species_local or "",
                "count_per_ha": pole_count_ha + tree_count_ha,
                "timber_m3_per_ha": round(pole_timber_ha + tree_timber_ha, 2),
                "fuelwood_m3_per_ha": round(pole_firewood_ha + tree_firewood_ha, 2),
                "total_volume_m3_per_ha": round(
                    pole_timber_ha
                    + pole_firewood_ha
                    + tree_timber_ha
                    + tree_firewood_ha,
                    2,
                ),
            }
        )

    # ── Weighted grand total per species ──
    if block_areas:
        total_area = sum(block_areas.values())
        if total_area > 0:
            species_agg: Dict[str, Dict] = {}
            species_order: List[str] = []
            for r in rows:
                key = (
                    (r["species_scientific"] or "") + "||" + (r["species_local"] or "")
                )
                if key not in species_agg:
                    species_agg[key] = {
                        "sci": r["species_scientific"],
                        "loc": r["species_local"],
                        "cnt": 0.0,
                        "tim": 0.0,
                        "fuel": 0.0,
                        "tot": 0.0,
                    }
                    species_order.append(key)
                area = block_areas.get(r["block_name"], 0)
                species_agg[key]["cnt"] += r["count_per_ha"] * area
                species_agg[key]["tim"] += r["timber_m3_per_ha"] * area
                species_agg[key]["fuel"] += r["fuelwood_m3_per_ha"] * area
                species_agg[key]["tot"] += r["total_volume_m3_per_ha"] * area
            for key in species_order:
                s = species_agg[key]
                rows.append(
                    {
                        "block_name": "Grand Total (Weighted)",
                        "species_scientific": s["sci"],
                        "species_local": s["loc"],
                        "count_per_ha": int(s["cnt"] / total_area),
                        "timber_m3_per_ha": round(s["tim"] / total_area, 2),
                        "fuelwood_m3_per_ha": round(s["fuel"] / total_area, 2),
                        "total_volume_m3_per_ha": round(s["tot"] / total_area, 2),
                    }
                )

    return rows


# business: CFMG §X.Y — DBH class distribution for stand structure analysis
# constraint: standard Nepal DBH classes: seedling (0-4), sapling (4-10), small pole (10-20), large pole (20-30), small tree (30-40), medium tree (40-50), large tree (50-60), very large tree (>60) cm
def _fetch_dbh_class_breakdown(
    db: Session, fi_calc_id: str, block_areas: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """Block + DBH class wise growing stock, matching Excel pivot table values.

    Net timber and firewood already account for tree_class quality factors
    per Forest Regulation 2079 (a=80%, b=60%, c=30%, d=0%).
    Timber = net_volume, fuelwood = tree_volume - timber.

    If block_areas is provided (block_name → effective hectares),
    weighted grand average rows are appended at the end.
    """
    fi_calc_id_str = str(fi_calc_id)

    query = text(
        """
        WITH block_total_plots AS (
            SELECT block_name, COUNT(DISTINCT id) as total_plots
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :fi_id
            GROUP BY block_name
        )
        SELECT
            sp.block_name,
            m.dbh_class,
            m.stand_type,
            btp.total_plots,
            SUM(m.count) as total_count,
            SUM(COALESCE(m.tree_volume, 0)) as total_tree,
            SUM(COALESCE(m.net_volume, 0)) as total_timber
        FROM public.field_inventory_sample_plots sp
        JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
        JOIN block_total_plots btp ON btp.block_name = sp.block_name
        WHERE sp.field_inventory_calculation_id = :fi_id
        GROUP BY sp.block_name, m.dbh_class, m.stand_type, btp.total_plots
        ORDER BY sp.block_name,
          CASE m.stand_type
            WHEN 'Regeneration' THEN 1 WHEN 'Sapling' THEN 2 WHEN 'Pole' THEN 3 ELSE 4 END,
          CASE m.dbh_class
            WHEN 'Sm. Pole (10-20)' THEN 1 WHEN 'Lg. Pole (20-30)' THEN 2
            WHEN 'Sm. Tree (30-40)' THEN 3 WHEN 'Med. Tree (40-50)' THEN 4
            WHEN 'Lg. Tree (50-60)' THEN 5 WHEN 'V. Lg. Tree (60+)' THEN 6
            ELSE 9 END
    """
    )
    results = db.execute(query, {"fi_id": fi_calc_id_str}).fetchall()

    rows = []
    for row in results:
        tp = float(row.total_plots or 1)
        st = str(row.stand_type or "")
        dcl = str(row.dbh_class or "")

        # Map to DBH class labels matching Excel col 39 pivot
        if dcl == "Seedling (0-4)" or (dcl == "Regeneration" and st == "Regeneration"):
            label = "0-4 Seedling"
        elif dcl == "Sapling (4-10)" or (dcl == "Regeneration" and st == "Sapling"):
            label = "4-10 Sapling"
        elif dcl == "Sm. Pole (10-20)":
            label = "10-20 Sm.Pole"
        elif dcl == "Lg. Pole (20-30)":
            label = "20-30 Lg.Pole"
        elif dcl == "Sm. Tree (30-40)":
            label = "30-40 Sm.Tree"
        elif dcl == "Med. Tree (40-50)":
            label = "40-50 Med.Tree"
        elif dcl == "Lg. Tree (50-60)":
            label = "50-60 Lg.Tree"
        elif dcl == "V. Lg. Tree (60+)":
            label = "60+ V.Lg.Tree"
        else:
            label = dcl

        if st == "Regeneration":
            plot_area = REGEN_PLOT_AREA_SQM
        elif st == "Sapling":
            plot_area = SAPLING_PLOT_AREA_SQM
        elif st == "Pole":
            plot_area = POLE_PLOT_AREA_SQM
        else:
            plot_area = TREE_PLOT_AREA_SQM

        # business: per-ha = sum / total_block_plots / plot_area * 10000; stand-type dependent area
        count_ha = (float(row.total_count or 0) / tp / plot_area) * SQM_PER_HA
        timber_ha = (float(row.total_timber or 0) / tp / plot_area) * SQM_PER_HA
        tree_ha = (float(row.total_tree or 0) / tp / plot_area) * SQM_PER_HA
        fuel_ha = tree_ha - timber_ha

        rows.append(
            {
                "block_name": row.block_name,
                "dbh_class": label,
                "count_per_ha": round(count_ha, 2),
                "timber_m3_per_ha": round(timber_ha, 2),
                "fuelwood_m3_per_ha": round(fuel_ha, 2),
                "total_volume_m3_per_ha": round(tree_ha, 2),
            }
        )

    # ── Weighted grand average per DBH class ──
    if block_areas:
        total_area = sum(block_areas.values())
        if total_area > 0:
            classes = {}
            order = []
            for r in rows:
                cls = r["dbh_class"]
                if cls not in classes:
                    classes[cls] = {"cnt": 0.0, "tim": 0.0, "fuel": 0.0, "tot": 0.0}
                    order.append(cls)
                area = block_areas.get(r["block_name"], 0)
                classes[cls]["cnt"] += r["count_per_ha"] * area
                classes[cls]["tim"] += r["timber_m3_per_ha"] * area
                classes[cls]["fuel"] += r["fuelwood_m3_per_ha"] * area
                classes[cls]["tot"] += r["total_volume_m3_per_ha"] * area
            for cls in order:
                c = classes[cls]
                rows.append(
                    {
                        "block_name": "Grand Total (Weighted)",
                        "dbh_class": cls,
                        "count_per_ha": round(c["cnt"] / total_area, 2),
                        "timber_m3_per_ha": round(c["tim"] / total_area, 2),
                        "fuelwood_m3_per_ha": round(c["fuel"] / total_area, 2),
                        "total_volume_m3_per_ha": round(c["tot"] / total_area, 2),
                    }
                )

    return rows


def _fetch_dbh_class_breakdown_np(
    db: Session, fi_calc_id: str, block_areas: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """Nepali version of DBH class growing stock with dash for zero values."""
    rows = _fetch_dbh_class_breakdown(db, fi_calc_id, block_areas)
    # Keyed by the canonical class key rather than by the collector's display
    # label. The words belong here -- this is a translation surface and there is
    # no i18n bundle behind the OP's Nepali output -- but the *set of classes* is
    # not this function's to decide. Keyed by display string it was a fifth copy
    # of the class list, and one that would silently render a class untranslated
    # the day a label was renamed; keyed canonically, a class added to the
    # database has no entry here and `test_every_class_has_a_nepali_word` says
    # so instead.
    np_label_map = {
        "0_4": "बिरुवा (०-४)",
        "4_10": "लाथ्रा (४-१०)",
        "10_20": "सानो खाँवा (१०-२०)",
        "20_30": "ठुलो खाँवा (२०-३०)",
        "30_40": "सानो रुख (३०-४०)",
        "40_50": "मझौला रुख (४०-५०)",
        "50_60": "ठुलो रुख (५०-६०)",
        "60_plus": "अति ठुलो रुख (>६०)",
    }

    def _dash(val):
        return "—" if val == 0 else val

    def _block_name(bn):
        return "कुल जम्मा (भारित)" if bn == "Grand Total (Weighted)" else bn

    return [
        {
            "वन खण्ड": _block_name(r["block_name"]),
            "ब्यास क्लास": np_label_map.get(
                    harvest_groups.resolve_class_key(r["dbh_class"]), r["dbh_class"]
                ),
            "संख्या /हे.": _dash(r["count_per_ha"]),
            "काठ (घ.मी. /हे.)": _dash(r["timber_m3_per_ha"]),
            "दाउरा (घ.मी. /हे.)": _dash(r["fuelwood_m3_per_ha"]),
            "जम्मा (घ.मी. /हे.)": _dash(r["total_volume_m3_per_ha"]),
        }
        for r in rows
    ]


def _prepare_dbh_class_chart_data(
    db: Session, fi_calc_id: str, block_areas: dict
) -> List[Dict[str, Any]]:
    """Forest-wide DBH class (pole+tree) per-hectare volume for bar chart, Nepali labels."""
    rows = _fetch_dbh_class_breakdown(db, fi_calc_id, block_areas)
    result = []
    for r in rows:
        if r["block_name"] != "Grand Total (Weighted)":
            continue
        label = DBH_CLASS_NP_CHART.get(r["dbh_class"])
        if not label:
            continue
        result.append(
            {
                "label": label,
                "count_per_ha": round(r["count_per_ha"], 2),
                "timber_m3_per_ha": round(r["timber_m3_per_ha"], 2),
                "fuelwood_m3_per_ha": round(r["fuelwood_m3_per_ha"], 2),
                "total_volume_m3_per_ha": round(r["total_volume_m3_per_ha"], 2),
            }
        )
    return result


def _fetch_dbh_class_breakdown_ag_np(
    db: Session,
    fi_calc_id: str,
    blocks: List[Any],
    block_areas: Dict[str, float],
) -> List[Dict[str, Any]]:
    """DBH class grouped into Advance Growth (10-40 cm) and Mature Tree (>40 cm), Nepali.

    - एड्भान्स ग्रोथ (१०-४० से.मी.) = Sm.Pole + Lg.Pole + Sm.Tree
    - परिपक्व रूख (>४० से.मी.) = Med.Tree + Lg.Tree + V.Lg.Tree
    Grand total area-weighted over every block in the table (D11/P6).
    """
    per_block_rows = _fetch_dbh_class_breakdown(db, fi_calc_id, None)

    # The grouping now lives in `app.core.harvest_groups` (DBH_SSOT_P2b) and
    # returns **neutral keys with no presentation**; only the Nepali headings stay
    # here. The grouping used to be derived inline below this point, which made it
    # unusable anywhere else -- lifting that as-is would have handed the Field
    # Inventory pane untranslatable strings, the defect D10 forbids.
    #
    # The rendered output is deliberately unchanged, and that identity is the
    # phase's gate rather than an aspiration:
    #   * Regeneration is still omitted. `harvest_groups` computes all three
    #     groups because D12 requires Field Inventory to show Regeneration with an
    #     explicit non-harvestable marker; this formatter filters to the two it
    #     has always printed.
    #   * An all-zero group is still skipped, and zero still renders as "-".
    #
    # **The grand total is the one thing that did change**, and deliberately: it
    # was weighted by sample-plot count, which is a sampling-intensity mean rather
    # than a forest mean, and is now area-weighted over every block (D11/P6). The
    # other three bullets above are about *which rows* appear; this one is about a
    # figure, so it does not belong under "the rendered output is unchanged".
    grouped = harvest_groups.group_rollup(
        [
            {
                "block_name": r["block_name"],
                "dbh_class": r["dbh_class"],
                "count_per_ha": r["count_per_ha"],
                "timber_m3_per_ha": r["timber_m3_per_ha"],
                "firewood_m3_per_ha": r["fuelwood_m3_per_ha"],
                "total_volume_m3_per_ha": r["total_volume_m3_per_ha"],
            }
            for r in per_block_rows
        ]
    )

    # Downstream code (the row loop and the grand total) indexes `block_data` by
    # "ag"/"mt". Those keys are left exactly as they were and the neutral group key
    # is mapped onto them here, so the row structure is unchanged -- which is what
    # makes "which rows appear is unchanged" checkable rather than merely intended.
    # The grand total's *weighting* did change, as noted above; its shape did not.
    _SLOT = {
        harvest_groups.ADVANCE_GROWTH: "ag",
        harvest_groups.MATURE_TREE: "mt",
    }
    np_groups = [
        ("ag", "एड्भान्स ग्रोथ (१०-४० से.मी.)"),
        ("mt", "परिपक्व रूख (>४० से.मी.)"),
    ]

    # Aggregate per block
    block_data: Dict[str, Dict] = {}
    block_order: List[str] = []
    for r in grouped:
        slot = _SLOT.get(r["group_key"])
        if slot is None:
            continue  # Regeneration: computed, not printed here
        bn = r["block_name"]
        if bn not in block_data:
            block_data[bn] = {
                "ag": {"cnt": 0, "tim": 0, "fuel": 0, "tot": 0},
                "mt": {"cnt": 0, "tim": 0, "fuel": 0, "tot": 0},
            }
            block_order.append(bn)
        g = block_data[bn][slot]
        g["cnt"] += r["count_per_ha"]
        g["tim"] += r["timber_m3_per_ha"]
        g["fuel"] += r["firewood_m3_per_ha"]
        g["tot"] += r["total_volume_m3_per_ha"]

    def _dash(val):
        return "—" if val == 0 else round(val, 2)

    result = []
    for bn in block_order:
        for grp_key, np_label in np_groups:
            g = block_data[bn][grp_key]
            if g["cnt"] == 0 and g["tim"] == 0 and g["fuel"] == 0 and g["tot"] == 0:
                continue
            result.append(
                {
                    "वन खण्ड": bn,
                    "ब्यास समूह": np_label,
                    "संख्या /हे.": _dash(g["cnt"]),
                    "काठ (घ.मी. /हे.)": _dash(g["tim"]),
                    "दाउरा (घ.मी. /हे.)": _dash(g["fuel"]),
                    "जम्मा (घ.मी. /हे.)": _dash(g["tot"]),
                }
            )

    # Grand total, area-weighted (D11/P6). Was weighted by sample-plot count,
    # which answered a different question than the column claimed.
    grand, skipped = _area_weighted_grand_total(
        block_data, block_order, ("ag", "mt"), block_areas,
        denominator_blocks=[b.block_name for b in blocks],
    )
    if skipped:
        logger.warning(
            "[op] CFMG harvest grand total: %d block(s) have no effective area and "
            "are excluded from the total: %s",
            len(skipped),
            skipped,
        )
    if any(any(v for v in g.values()) for g in grand.values()):
        for grp_key, np_label in np_groups:
            g = grand[grp_key]
            result.append(
                {
                    "वन खण्ड": "कुल जम्मा (भारित)",
                    "ब्यास समूह": np_label,
                    "संख्या /हे.": _dash(g["cnt"]),
                    "काठ (घ.मी. /हे.)": _dash(g["tim"]),
                    "दाउरा (घ.मी. /हे.)": _dash(g["fuel"]),
                    "जम्मा (घ.मी. /हे.)": _dash(g["tot"]),
                }
            )

    return result


# The four measures an OP grand total is taken over, in the local vocabulary the
# formatters already use (`cnt`/`tim`/`fuel`/`tot`). Named once so the two
# weighting sites cannot drift on a spelling.
_OP_GT_MEASURES = ("cnt", "tim", "fuel", "tot")


def _weighted_mean(
    values: Dict[str, float],
    weights: Dict[str, float],
    denominator_blocks: Optional[List[str]] = None,
) -> float:
    """The one weighted mean in this module (D11), over whatever is handed to it.

    `denominator_blocks` exists because getting it wrong is not a rounding
    matter. The numerator only sees blocks that hold something, but a
    forest-wide rate must divide by **every** block in scope: a compartment with
    no stems of a class still occupies hectares, and leaving those out of the
    denominator divides a forest rate by less than the forest. Blocks that are in
    the denominator but have no value simply contribute nothing, which is the
    correct treatment of a zero.

    Returns 0.0 when the denominator has no positive weight, so a caller can
    treat 0 as "nothing to average" rather than dividing by zero.
    """
    denominator = denominator_blocks if denominator_blocks is not None else list(values)
    total = sum(float(weights.get(bn) or 0.0) for bn in denominator)
    if total <= 0:
        return 0.0
    return sum(
        float(values.get(bn) or 0.0) * float(weights.get(bn) or 0.0) for bn in denominator
    ) / total


def _sum_and_mean(terms: Iterable[Tuple[float, float]]) -> Tuple[float, float]:
    """Sum of `value * weight`, and that sum divided by the total weight.

    The two-number return is deliberate: MAI and AAH are **annual volumes for the
    forest** (m3/year), and the per-hectare figure printed in the report is only a
    rate for comparing blocks. Returning both keeps the absolute next to the rate
    instead of leaving the absolute to be reconstructed by multiplying again --
    which is how a per-hectare number ends up in a plan as if it were a quota.

    Weighted rather than summed because the terms are per-hectare rates: an
    unweighted sum of 21 rates has no units anyone can name.
    """
    total = 0.0
    weight = 0.0
    for value, w in terms:
        total += value * w
        weight += w
    return total, (total / weight if weight > 0 else 0.0)


def _area_weighted_grand_total(
    block_data: Dict[str, Dict[str, Dict[str, float]]],
    block_order: List[str],
    slots: Sequence[str],
    block_areas: Dict[str, float],
    denominator_blocks: Optional[List[str]] = None,
) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
    """Area-weighted mean of the per-hectare values (plan D11, P6).

    Replaces the sample-plot weighting these tables used before. The two are
    different questions, and the old one was not what the column said it was:
    weighting per-hectare figures by how many plots a block happened to have
    gives a *sampling-intensity* mean, not a forest mean. On the owner's forest
    plot density varies 13-fold (C-3-SC3 at 1.30 plots/ha against C-6 at 0.09),
    so the intensively-sampled compartments carried up to 14 times the weight per
    hectare of the rest, and the "grand total" moved accordingly.

    `denominator_blocks` is separate from `block_order` on purpose, and getting
    that wrong is not a rounding matter -- it inflated a figure by 12%. The
    numerator only sees blocks that hold stems of the group in question, but the
    denominator must be **every** block in the table. A compartment with no mature
    stems still occupies hectares, and those hectares belong in the mean: leaving
    them out divides a forest-wide rate by less than the forest. On the owner's
    forest, `mature_np` over 17 blocks of the 21 read 87.32 m3/ha against the
    correct 78.16 over all 21.

    Returns the per-slot means and the blocks skipped for want of an area, so the
    caller can say which they were rather than quietly dropping them. When no
    block has an area the means come back as zeros and the caller emits no total:
    a missing grand total is visible to whoever reads the report, and a
    plot-weighted one wearing an area-weighted label would not be.
    """
    grand: Dict[str, Dict[str, float]] = {
        slot: {m: 0.0 for m in _OP_GT_MEASURES} for slot in slots
    }
    denominator = denominator_blocks if denominator_blocks is not None else block_order
    total_area = sum(float(block_areas.get(bn) or 0.0) for bn in denominator)
    skipped = [bn for bn in denominator if float(block_areas.get(bn) or 0.0) <= 0]
    if total_area <= 0:
        return grand, skipped

    for slot in slots:
        for m in _OP_GT_MEASURES:
            # `block_areas` is passed straight through as the weight mapping. An
            # earlier version of this built a `weights` dict scoped to
            # `block_order`, which quietly re-broke the denominator bug this
            # function exists to fix: a block in the denominator but absent from
            # `block_order` then had no weight and dropped out of the mean too.
            # `_weighted_mean` treats a missing key as 0, which is the right
            # default for a block that has no value -- and only for that.
            grand[slot][m] = _weighted_mean(
                {bn: block_data[bn][slot][m] for bn in block_order},
                block_areas,
                denominator,
            )
    return grand, skipped


def _fetch_dbh_class_breakdown_single_np(
    db: Session,
    fi_calc_id: str,
    blocks: List[Any],
    group_key: str,
    np_label: str,
    block_areas: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Shared helper: one CFMG harvest group per-block per-hectare summary, Nepali.

    `group_key` is a neutral `harvest_groups` key, not a set of class names. It
    used to be the latter -- a literal set of three display class names -- which
    was a fourth copy of the class list, in the display form
    `_fetch_dbh_class_breakdown` happens to emit for Excel-pivot parity. It was
    correct today and would have broken silently the day a class was renamed or
    CFMG moved a boundary, with nothing to say so. The classes are now resolved
    through the registry, so this table follows the database rather than
    restating it.

    (The class names are deliberately not written out even here. A list left in
    a docstring reads as documentation and becomes the thing the next reader
    trusts, and `test_no_dbh_class_label_is_retyped_outside_the_mapping` fails on
    exactly that.)
    """
    per_block_rows = _fetch_dbh_class_breakdown(db, fi_calc_id, None)

    group_of_class = harvest_groups.class_to_group()

    block_data: Dict[str, dict] = {}
    block_order: List[str] = []
    for r in per_block_rows:
        key = harvest_groups.resolve_class_key(r["dbh_class"])
        if key is None or group_of_class.get(key) != group_key:
            continue
        bn = r["block_name"]
        if bn not in block_data:
            block_data[bn] = {"cnt": 0, "tim": 0, "fuel": 0, "tot": 0}
            block_order.append(bn)
        g = block_data[bn]
        g["cnt"] += r["count_per_ha"]
        g["tim"] += r["timber_m3_per_ha"]
        g["fuel"] += r["fuelwood_m3_per_ha"]
        g["tot"] += r["total_volume_m3_per_ha"]

    def _dash(val):
        return "—" if val == 0 else round(val, 2)

    result = []
    for bn in block_order:
        g = block_data[bn]
        result.append(
            {
                "वन खण्ड": bn,
                "संख्या /हे.": _dash(g["cnt"]),
                "काठ (घ.मी. /हे.)": _dash(g["tim"]),
                "दाउरा (घ.मी. /हे.)": _dash(g["fuel"]),
                "जम्मा (घ.मी. /हे.)": _dash(g["tot"]),
            }
        )

    # Grand total, area-weighted (D11/P6) -- the single-group form of the same
    # calculation the two-group table does. It goes through the same helper
    # rather than a second copy, so the two tables cannot drift apart; the flat
    # per-block shape is wrapped into the one-slot shape the helper takes.
    grand, skipped = _area_weighted_grand_total(
        {bn: {"g": block_data[bn]} for bn in block_order},
        block_order,
        ("g",),
        block_areas,
        # Every block in the table, not only those holding stems of this group.
        denominator_blocks=[b.block_name for b in blocks],
    )
    if skipped:
        logger.warning(
            "[op] CFMG single-group grand total: %d block(s) have no effective "
            "area and are excluded from the total: %s",
            len(skipped),
            skipped,
        )
    if any(any(v for v in g.values()) for g in grand.values()):
        result.append(
            {
                "वन खण्ड": "कुल जम्मा (भारित)",
                "संख्या /हे.": _dash(grand["g"]["cnt"]),
                "काठ (घ.मी. /हे.)": _dash(grand["g"]["tim"]),
                "दाउरा (घ.मी. /हे.)": _dash(grand["g"]["fuel"]),
                "जम्मा (घ.मी. /हे.)": _dash(grand["g"]["tot"]),
            }
        )

    return result


def _fetch_dbh_class_breakdown_advance_np(
    db: Session,
    fi_calc_id: str,
    blocks: List[Any],
    block_areas: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Advance Growth (एड्भान्स ग्रोथ — DBH 10-40 cm) per-block per-hectare, Nepali."""
    return _fetch_dbh_class_breakdown_single_np(
        db,
        fi_calc_id,
        blocks,
        harvest_groups.ADVANCE_GROWTH,
        "एड्भान्स ग्रोथ (१०-४० से.मी.)",
        block_areas,
    )


def _fetch_dbh_class_breakdown_mature_np(
    db: Session,
    fi_calc_id: str,
    blocks: List[Any],
    block_areas: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Mature Tree (परिपक्व रूख — DBH >40 cm) per-block per-hectare, Nepali."""
    return _fetch_dbh_class_breakdown_single_np(
        db,
        fi_calc_id,
        blocks,
        harvest_groups.MATURE_TREE,
        "परिपक्व रूख (>४० से.मी.)",
        block_areas,
    )


# business: CFMG — block effective area excludes private land (sub-areas)
def _fetch_block_effective_areas(db: Session, calculation_id: str) -> Dict[str, float]:
    """Fetch net effective forest cover area per block using GIS-based computation.

    Uses calculate_block_area_details() — the same function as the
    block-area-detail endpoint — to subtract excluded sub-areas (private land,
    protected areas) from block geometry and recompute tree cover on the
    effective geometry.  Matches the Total Inventory tab exactly.
    """
    from app.services.tree_cover_analysis import calculate_block_area_details

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.result_data:
        return {}
    rd = calc.result_data
    # The unit set the analysis ran on (leaf view: FS-1a.10) - blocks OR compartments, whichever the forest uses.
    blocks = PolygonSource.for_result_data(rd).get_polygons()
    sub_areas = rd.get("sub_areas", [])  # calculate_block_area_details keeps the zones and the river bank (protection), drops fire lines
    if not blocks:
        return {}

    details = calculate_block_area_details(db, blocks, sub_areas)
    return {d["block_name"]: round(d["effective_area_ha"], 2) for d in details}


def _fetch_block_protected_areas(db: Session, calculation_id: str) -> Dict[str, float]:
    """Protected sub-area extent per block/compartment, in ha.

    Same GIS basis as :func:`_fetch_block_effective_areas` — the protected
    portion is what ``effective_area_ha`` subtracts. Used to scale the
    protection-stratum growing stock (m³/ha) to an absolute total.
    """
    from app.services.tree_cover_analysis import calculate_block_area_details

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.result_data:
        return {}
    rd = calc.result_data
    # The unit set the analysis ran on (leaf view: FS-1a.10) - blocks OR compartments, whichever the forest uses.
    blocks = PolygonSource.for_result_data(rd).get_polygons()
    sub_areas = rd.get("sub_areas", [])  # calculate_block_area_details keeps the zones and the river bank (protection), drops fire lines
    if not blocks:
        return {}

    details = calculate_block_area_details(db, blocks, sub_areas)
    return {
        d["block_name"]: round(d.get("protected_area_ha", 0) or 0, 2) for d in details
    }


def _fetch_block_working_circle(db: Session, calculation_id: str) -> Dict[str, str]:
    """{unit block_name/name: 'production'|'protection'} from the reconciled units.

    P0 (PROTECTION_WORKING_CIRCLE_PLAN.md) writes ``working_circle`` into the
    ``result_data`` unit dicts. Empty when the forest has no units or none is a
    protection working circle. A missing value reads as ``'production'``.
    """
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    rd = (calc.result_data if calc else None) or {}
    if not isinstance(rd, dict):
        return {}
    units = rd.get("compartments") or rd.get("blocks") or []
    out: Dict[str, str] = {}
    for u in units:
        wc = u.get("working_circle") or "production"
        for key in (u.get("block_name"), u.get("name")):
            if key:
                out[str(key)] = wc
    return out


# business: CFMG §X.Y — species composition classification: dominant (>=20%), co-dominant (10-20%), associated (<10%) by volume share
def _compute_species_composition(
    species_block_data: List[Dict], base_species_data: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """Compute species composition analysis from block-level species growing stock.

    Classifies species into dominant (>=20%), co-dominant (10-20%), associated (<10%)
    based on total volume share. Also categorizes by growth rate from base species data.
    """
    species_vol: Dict[str, float] = {}
    for row in species_block_data:
        if row.get("block_name") == "Grand Total (Weighted)" or not row.get(
            "species_scientific"
        ):
            continue
        sci = row["species_scientific"]
        loc = row.get("species_local", "") or ""
        key = f"{sci} ({loc})" if loc else sci
        species_vol[key] = species_vol.get(key, 0) + float(
            row.get("total_volume_m3_per_ha", 0)
        )

    if not species_vol:
        return {}

    total = sum(species_vol.values())
    if total <= 0:
        return {}

    pct = {k: round(v / total * 100, 1) for k, v in species_vol.items()}
    sorted_species = sorted(pct.items(), key=lambda x: x[1], reverse=True)

    dominant = [s for s, p in sorted_species if p >= 20.0]
    co_dominant = [s for s, p in sorted_species if 10.0 <= p < 20.0]
    associated = [s for s, p in sorted_species if p < 10.0]

    # business: CFMG — growth rate from base species registry: fast/high, moderate/medium, slow/low
    fast_growing: List[str] = []
    moderate_growing: List[str] = []
    slow_growing: List[str] = []

    if base_species_data:
        for sp in base_species_data:
            sci = sp.get("scientific_name", "")
            loc = sp.get("local_name", "") or sp.get("nepali_name", "") or ""
            key = f"{sci} ({loc})" if loc else sci
            rate = (sp.get("growth_rate") or "").lower()
            if rate in ("fast", "high"):
                fast_growing.append(key)
            elif rate in ("moderate", "medium"):
                moderate_growing.append(key)
            elif rate in ("slow", "low"):
                slow_growing.append(key)

    return {
        "fi_species_composition": pct,
        "fi_dominant_species": dominant,
        "fi_co_dominant_species": co_dominant,
        "fi_associated_species": associated,
        "fi_fast_growing_species": fast_growing,
        "fi_moderate_growing_species": moderate_growing,
        "fi_slow_growing_species": slow_growing,
        # For block-species volume bar chart: sorted list of (name, pct)
        "fi_species_volume_by_block": sorted_species,
    }


# business: CFMG §X.Y — field inventory data for OP document growing stock section
# NOTE: uses stem_volume/branch_volume (raw), NOT net_volume/firewood_m3 (quality-adjusted)
def _species_stage_data(db: Session, fi_calc_id: Any, block_areas: Dict[str, float]) -> Dict[str, Any]:
    """Species x stage per-ha tables/charts; {} (and a log line) when the breakdown cannot be built."""
    try:
        from app.services.field_inventory_mgmt_data import _get_species_breakdown
        from app.services.operational_plan.species_stage_tables import build_species_stage_data

        return build_species_stage_data(_get_species_breakdown(db, fi_calc_id), block_areas)
    except Exception:
        logger.exception("species x stage tables could not be built for field inventory %s", fi_calc_id)
        return {}


def _species_regulation_data(db: Session, fi_calc_id: Any, block_areas: Dict[str, float]) -> Dict[str, Any]:
    """Regulation-category (codes 1-21, Terai/Hill other) per-ha tables; {} when they cannot be built."""
    try:
        from app.core.regulation_species import region_for_field_inventory
        from app.services.field_inventory_mgmt_data import _get_species_breakdown
        from app.services.operational_plan.species_regulation_tables import build_all_variants

        # fi_reg_* = 21 named + Other (Terai/Hill); fi_regc_* = classified species only, its own placeholders
        return build_all_variants(
            _get_species_breakdown(db, fi_calc_id), block_areas, region_for_field_inventory(db, fi_calc_id)
        )
    except Exception:
        logger.exception("regulation species tables could not be built for field inventory %s", fi_calc_id)
        return {}


def get_field_inventory_data(
    db: Session, calculation_id: str, base_species_data: Optional[Dict] = None
) -> Dict[str, Any]:
    """Collect field inventory data (blocks, species, volumes) for the OP document growing stock section."""
    from app.models.field_inventory import (
        FieldInventoryCalculation,
        FieldInventoryBlockSummary,
    )

    fi_calc = (
        db.query(FieldInventoryCalculation)
        .filter(FieldInventoryCalculation.calculation_id == calculation_id)
        .first()
    )
    if not fi_calc:
        return {"available": False}

    blocks = (
        db.query(FieldInventoryBlockSummary)
        .filter(FieldInventoryBlockSummary.field_inventory_calculation_id == fi_calc.id)
        .all()
    )

    # Block effective areas for weighted grand total and total inventory computation
    block_areas = _fetch_block_effective_areas(db, calculation_id)
    protected_areas = _fetch_block_protected_areas(db, calculation_id)

    # Species-level block growing stock (with weighted totals)
    species_block_data = _fetch_species_block_breakdown(db, fi_calc.id, block_areas)

    if blocks:
        # PROTECTION_WORKING_CIRCLE_PLAN.md P1 — a protection working-circle unit
        # keeps a full summary (growing stock, condition) but is out of MAI/AAH
        # and out of the production weighted grand total.
        _wc = _fetch_block_working_circle(db, calculation_id)

        def _is_protection(b) -> bool:
            return _wc.get(b.block_name, "production") == "protection"

        production_blocks = [b for b in blocks if not _is_protection(b)]
        protection_blocks = [b for b in blocks if _is_protection(b)]

        # Weighting / grand total are over the PRODUCTION units only.
        _weight_blocks = production_blocks or blocks
        # Area, not sample-plot count (D11/P6b). Plot density varies up to 14-fold
        # across this forest, so plot-weighting made the pole-dense, intensively
        # sampled compartments carry far more per-hectare weight than the rest --
        # visible as the pole figures rising ~4-5% and the tree figures falling
        # ~5-6% under the change, with total growing stock almost unchanged. The
        # protection exclusion is untouched and still deliberate.
        _weight_area = {
            b.block_name: float(block_areas.get(b.block_name) or 0.0)
            for b in _weight_blocks
        }
        _denominator_blocks = [b.block_name for b in _weight_blocks]
        total_weight = sum(_weight_area.values()) if _weight_area else 0


        # ── Helper: row builder for per-block dict ──
        def _block_row(b, area):
            is_prot = _is_protection(b)
            pt = float(b.pole_timber_m3_per_ha or 0)
            pf = float(b.pole_firewood_m3_per_ha or 0)
            tt = float(b.tree_timber_m3_per_ha or 0)
            tf = float(b.tree_firewood_m3_per_ha or 0)
            gs = float(b.total_growing_stock_m3_per_ha or 0)
            cond = b.forest_condition or "Moderate"
            # business: CFMG — MAI = growing_stock * mai_pct / 100; AAH = MAI * forest_condition_multiplier
            # A protection unit contributes 0 to yield regulation.
            mai_pct = 0.0 if is_prot else float(b.mai_percent or 0)
            aah_pct = 0.0 if is_prot else AAH_MULTIPLIER.get(cond, 60.0)
            mai_val = gs * mai_pct / 100.0
            aah_val = mai_val * aah_pct / 100.0
            return {
                "block_name": b.block_name,
                "working_circle": "protection" if is_prot else "production",
                "total_sample_plots": b.total_sample_plots or 0,
                "regeneration_per_ha": b.regeneration_per_ha or 0,
                "sapling_per_ha": b.sapling_per_ha or 0,
                "pole_per_ha": b.pole_per_ha or 0,
                "tree_per_ha": b.tree_per_ha or 0,
                "pole_timber_m3_per_ha": round(pt, 2),
                "pole_firewood_m3_per_ha": round(pf, 2),
                "pole_total_m3_per_ha": round(pt + pf, 2),
                "tree_timber_m3_per_ha": round(tt, 2),
                "tree_firewood_m3_per_ha": round(tf, 2),
                "tree_total_m3_per_ha": round(tt + tf, 2),
                "total_volume_m3_per_ha": round(pt + pf + tt + tf, 2),
                "total_growing_stock_m3_per_ha": round(gs, 2),
                # Protection stratum — growing stock only, NOT in MAI/AAH.
                "protected_growing_stock_m3_per_ha": round(
                    float(b.protected_growing_stock_m3_per_ha or 0), 2
                ),
                "protected_sample_plots": b.protected_sample_plots or 0,
                "satellite_volume_m3_per_ha": round(
                    float(b.satellite_volume_m3_per_ha or 0), 2
                ),
                "basal_area_m2_per_ha": round(float(b.basal_area_m2_per_ha or 0), 2),
                "regeneration_condition": b.regeneration_condition or "",
                "forest_condition": cond,
                "mai_percent": round(mai_pct, 2),
                "aah_multiplier_percent": round(aah_pct, 1),
                "mai_total_m3_per_ha": round(mai_val, 2),
                "aah_total_m3_per_ha": round(aah_val, 2),
                "weighted_wood_density": round(float(b.weighted_wood_density or 0), 3),
                "agb_t_per_ha": round(float(b.agb_t_per_ha or 0), 2),
                "bgb_t_per_ha": round(float(b.bgb_t_per_ha or 0), 2),
                "total_biomass_t_per_ha": round(
                    float(b.total_biomass_t_per_ha or 0), 2
                ),
                "carbon_stock_tc_per_ha": round(
                    float(b.carbon_stock_tc_per_ha or 0), 2
                ),
                "co2_equivalent_tco2_per_ha": round(
                    float(b.co2_equivalent_tco2_per_ha or 0), 2
                ),
            }

        block_rows = [_block_row(b, block_areas.get(b.block_name, 0)) for b in blocks]

        # ── Protection stratum — growing stock only, absent from MAI / AAH ──
        # Two sources: (a) protected plots embedded in a production block (#20
        # columns) and (b) every plot of a protection working-circle UNIT (P1).
        _prot_sources: list[tuple] = []
        for b in production_blocks:
            n = int(b.protected_sample_plots or 0)
            if n > 0:
                _prot_sources.append(
                    (b.block_name, n, float(b.protected_growing_stock_m3_per_ha or 0))
                )
        for b in protection_blocks:
            _prot_sources.append(
                (
                    b.block_name,
                    int(b.total_sample_plots or 0),
                    float(b.total_growing_stock_m3_per_ha or 0),
                )
            )

        _prot_plots_total = sum(n for _, n, _ in _prot_sources)
        # Area-weighted like everything else (D11/P6b). This one was plot-weighted
        # too and would have stayed that way indefinitely, because a forest with no
        # protection stratum never exercises it -- which is exactly the case on the
        # owner's forest. A defect that only shows up on someone else's data is a
        # defect that stays.
        _prot_area = {
            name: float(block_areas.get(name) or 0.0) for name, _, _ in _prot_sources
        }
        _prot_gs_weighted = _weighted_mean(
            {name: gs for name, _, gs in _prot_sources},
            _prot_area,
            list(_prot_area),
        )
        if _prot_gs_weighted == 0.0 and _prot_plots_total > 0:
            # **Falls back to plot weighting, on purpose, and says so.**
            #
            # The production row above does *not* fall back -- it emits no grand
            # total at all when no area is known, because a missing row is visible
            # in a report. This field is different: it is a single scalar that the
            # report template reads whether or not anyone is looking, and turning
            # it into 0.0 because the blocks happen to carry no geometry would
            # report "no protection stratum growing stock" for a forest that has
            # some. A wrong zero is worse than an approximation.
            #
            # So the old weighting survives as a documented fallback, reachable
            # only when *no* protection source has an area, and it logs. The
            # asymmetry with the row above is deliberate and this comment is the
            # reason for it.
            logger.warning(
                "[op] protection growing stock: no effective area available for any "
                "protection source (%s); falling back to plot-count weighting. The "
                "figure is an approximation, not a forest mean.",
                [name for name, _, _ in _prot_sources],
            )
            _prot_gs_weighted = (
                sum(gs * n for _, n, gs in _prot_sources) / _prot_plots_total
                if _prot_plots_total > 0
                else 0.0
            )
        protected_stratum_table = [
            {
                "block_name": name,
                "protected_sample_plots": n,
                "protected_growing_stock_m3_per_ha": round(gs, 2),
            }
            for name, n, gs in _prot_sources
        ]
        if protected_stratum_table:
            protected_stratum_table.append(
                {
                    "block_name": "जम्मा (भारित)",
                    "protected_sample_plots": _prot_plots_total,
                    "protected_growing_stock_m3_per_ha": round(_prot_gs_weighted, 2),
                }
            )
        _has_protected_stratum = bool(_prot_sources)

        # Per-unit protection working-circle detail ({{fi_protection_units}}).
        fi_protection_units = [
            {
                "unit_name": b.block_name,
                "area_ha": round(block_areas.get(b.block_name, 0.0), 2),
                "growing_stock_m3_per_ha": round(
                    float(b.total_growing_stock_m3_per_ha or 0), 2
                ),
                "sample_plots": int(b.total_sample_plots or 0),
                "forest_condition": b.forest_condition or "",
            }
            for b in protection_blocks
        ]
        _protected_stratum_note = (
            "संरक्षित क्षेत्रको वन मौज्दात मात्र; वार्षिक स्वीकार्य कटानमा समावेश छैन। "
            "(Protection-stratum growing stock only — excluded from the Annual Allowable Harvest.)"
            if _has_protected_stratum
            else ""
        )

        # ── Grand total row (area-weighted; production only) ──
        def _wmean(key: str) -> float:
            """One figure, area-weighted over the production blocks (D11)."""
            return _weighted_mean(
                {
                    b.block_name: float(getattr(b, key, 0) or 0)
                    for b in _weight_blocks
                },
                _weight_area,
                _denominator_blocks,
            )

        if total_weight > 0:
            wpt = _wmean("pole_timber_m3_per_ha")
            wpf = _wmean("pole_firewood_m3_per_ha")
            wtt = _wmean("tree_timber_m3_per_ha")
            wtf = _wmean("tree_firewood_m3_per_ha")
            wgs = _wmean("total_growing_stock_m3_per_ha")
            wmai = _wmean("mai_percent")
            wcond = "—"

            # MAI and AAH are **products of two rates**, and this is the third distinct
            # error the row has carried. It averaged `growing_stock` and `mai_percent`
            # separately and then multiplied -- an average of products built from
            # averages. You cannot add 20% of 100 m3 in one block to 2% of 200 m3 in
            # another and get "22% of the average 150 m3"; the total is 20 + 4 = 24, not
            # 22. By Jensen the error is an *under*statement wherever growing stock and
            # MAI% rise together, which is the normal case (better forest, higher
            # allowance) -- so it cannot be relied on to be conservative either. On the
            # owner's forest it cost 13 m3/year, about 1%.
            #
            # AAH then compounded it: the per-block rows use that block's own forest
            # condition, but the total applied `AAH_MULTIPLIER["Moderate"]` to the
            # whole forest. On that forest 5 of 21 blocks are "Weak" (40%), so the flat
            # multiplier was 28 m3/year the other way. **The two errors partly
            # cancelled** -- AAH read 819 m3/year against a correct 799 -- which is
            # exactly why fixing only the product would have made it *worse*, 827.
            # Both are fixed together here for that reason.
            #
            # Each block's own area multiplies its own product, so a block contributes
            # in proportion to its hectares. Protection units are out of `_weight_blocks`
            # already, which is the existing deliberate exclusion.
            _mai_terms = [
                (
                    float(b.total_growing_stock_m3_per_ha or 0)
                    * float(b.mai_percent or 0)
                    / 100.0,
                    _weight_area[b.block_name],
                )
                for b in _weight_blocks
            ]
            _aah_terms = [
                (
                    float(b.total_growing_stock_m3_per_ha or 0)
                    * float(b.mai_percent or 0)
                    / 100.0
                    * AAH_MULTIPLIER.get(b.forest_condition or "Moderate", 60.0)
                    / 100.0,
                    _weight_area[b.block_name],
                )
                for b in _weight_blocks
            ]
            mai_abs, wmai_val = _sum_and_mean(_mai_terms)
            aah_abs, waah_val = _sum_and_mean(_aah_terms)

            grand = {
                "total_sample_plots": sum(
                    b.total_sample_plots or 0 for b in _weight_blocks
                ),
                "regeneration_per_ha": round(
                    _wmean("regeneration_per_ha")
                ),
                "sapling_per_ha": round(_wmean("sapling_per_ha")),
                "pole_per_ha": round(_wmean("pole_per_ha")),
                "tree_per_ha": round(_wmean("tree_per_ha")),
                "pole_timber_m3_per_ha": round(wpt, 2),
                "pole_firewood_m3_per_ha": round(wpf, 2),
                "pole_total_m3_per_ha": round(wpt + wpf, 2),
                "tree_timber_m3_per_ha": round(wtt, 2),
                "tree_firewood_m3_per_ha": round(wtf, 2),
                "tree_total_m3_per_ha": round(wtt + wtf, 2),
                "total_volume_m3_per_ha": round(wpt + wpf + wtt + wtf, 2),
                "total_growing_stock_m3_per_ha": round(wgs, 2),
                "protected_growing_stock_m3_per_ha": round(_prot_gs_weighted, 2),
                "protected_sample_plots": _prot_plots_total,
                "satellite_volume_m3_per_ha": round(
                    _wmean("satellite_volume_m3_per_ha"), 2
                ),
                "basal_area_m2_per_ha": round(
                    _wmean("basal_area_m2_per_ha"), 2
                ),
                "regeneration_condition": "—",
                "forest_condition": wcond,
                "mai_percent": round(wmai, 2),
                "aah_multiplier_percent": AAH_MULTIPLIER["Moderate"],
                "mai_total_m3_per_ha": round(wmai_val, 2),
                "aah_total_m3_per_ha": round(waah_val, 2),
                # The **absolute** annual volumes, which are the figures a working
                # plan actually quotes; the per-hectare ones above are for comparing
                # blocks. Nothing renders these yet -- they are carried so the
                # regulated number is not left to be reconstructed by multiplying
                # the rate by an area somewhere downstream.
                "mai_total_m3": round(mai_abs, 2),
                "aah_total_m3": round(aah_abs, 2),
                "weighted_wood_density": round(
                    _wmean("weighted_wood_density"), 3
                ),
                "agb_t_per_ha": round(_wmean("agb_t_per_ha"), 2),
                "bgb_t_per_ha": round(_wmean("bgb_t_per_ha"), 2),
                "total_biomass_t_per_ha": round(
                    _wmean("total_biomass_t_per_ha"), 2
                ),
                "carbon_stock_tc_per_ha": round(
                    _wmean("carbon_stock_tc_per_ha"), 2
                ),
                "co2_equivalent_tco2_per_ha": round(
                    _wmean("co2_equivalent_tco2_per_ha"), 2
                ),
            }
        else:
            grand = None

        block_summaries = block_rows + ([grand] if grand else [])

        # ── MAI table (per block) — production units only ──
        mai_table = []
        for br in block_rows:
            if br.get("working_circle") == "protection":
                continue
            mai_table.append(
                {
                    "block_name": br["block_name"],
                    "pole_per_ha": br["pole_per_ha"],
                    "tree_per_ha": br["tree_per_ha"],
                    "pole_timber_m3_per_ha": br["pole_timber_m3_per_ha"],
                    "pole_firewood_m3_per_ha": br["pole_firewood_m3_per_ha"],
                    "pole_total_m3_per_ha": br["pole_total_m3_per_ha"],
                    "tree_timber_m3_per_ha": br["tree_timber_m3_per_ha"],
                    "tree_firewood_m3_per_ha": br["tree_firewood_m3_per_ha"],
                    "tree_total_m3_per_ha": br["tree_total_m3_per_ha"],
                    "total_mai_m3_per_ha": br["mai_total_m3_per_ha"],
                }
            )
        # MAI grand total
        if grand:
            mai_table.append(
                {
                    "block_name": "Grand Total (Weighted)",
                    "pole_per_ha": grand["pole_per_ha"],
                    "tree_per_ha": grand["tree_per_ha"],
                    "pole_timber_m3_per_ha": grand["pole_timber_m3_per_ha"],
                    "pole_firewood_m3_per_ha": grand["pole_firewood_m3_per_ha"],
                    "pole_total_m3_per_ha": grand["pole_total_m3_per_ha"],
                    "tree_timber_m3_per_ha": grand["tree_timber_m3_per_ha"],
                    "tree_firewood_m3_per_ha": grand["tree_firewood_m3_per_ha"],
                    "tree_total_m3_per_ha": grand["tree_total_m3_per_ha"],
                    "total_mai_m3_per_ha": grand["mai_total_m3_per_ha"],
                }
            )

        # ── AAH table (per block) — production units only ──
        aah_table = []
        for br in block_rows:
            if br.get("working_circle") == "protection":
                continue
            cond = br["forest_condition"]
            aah_pct = AAH_MULTIPLIER.get(cond, 60.0)
            mai_val = br["mai_total_m3_per_ha"]
            aah_val = round(mai_val * aah_pct / 100.0, 2)
            aah_table.append(
                {
                    "block_name": br["block_name"],
                    "pole_per_ha": br["pole_per_ha"],
                    "tree_per_ha": br["tree_per_ha"],
                    "forest_condition": cond,
                    "aah_multiplier_percent": aah_pct,
                    "pole_timber_m3_per_ha": br["pole_timber_m3_per_ha"],
                    "pole_firewood_m3_per_ha": br["pole_firewood_m3_per_ha"],
                    "pole_total_m3_per_ha": br["pole_total_m3_per_ha"],
                    "tree_timber_m3_per_ha": br["tree_timber_m3_per_ha"],
                    "tree_firewood_m3_per_ha": br["tree_firewood_m3_per_ha"],
                    "tree_total_m3_per_ha": br["tree_total_m3_per_ha"],
                    "total_aah_m3_per_ha": aah_val,
                }
            )
        if grand:
            aah_table.append(
                {
                    "block_name": "Grand Total (Weighted)",
                    "pole_per_ha": grand["pole_per_ha"],
                    "tree_per_ha": grand["tree_per_ha"],
                    "forest_condition": "—",
                    "aah_multiplier_percent": AAH_MULTIPLIER["Moderate"],
                    "pole_timber_m3_per_ha": grand["pole_timber_m3_per_ha"],
                    "pole_firewood_m3_per_ha": grand["pole_firewood_m3_per_ha"],
                    "pole_total_m3_per_ha": grand["pole_total_m3_per_ha"],
                    "tree_timber_m3_per_ha": grand["tree_timber_m3_per_ha"],
                    "tree_firewood_m3_per_ha": grand["tree_firewood_m3_per_ha"],
                    "tree_total_m3_per_ha": grand["tree_total_m3_per_ha"],
                    "total_aah_m3_per_ha": grand["aah_total_m3_per_ha"],
                }
            )

        return {
            "available": True,
            "total_sample_plots": fi_calc.total_sample_plots or 0,
            "total_blocks": fi_calc.total_blocks or 0,
            "regeneration_area_sqm": float(
                fi_calc.regeneration_area_sqm or REGEN_PLOT_AREA_SQM
            ),
            "sapling_area_sqm": float(
                fi_calc.sapling_area_sqm or SAPLING_PLOT_AREA_SQM
            ),
            "pole_area_sqm": float(fi_calc.pole_area_sqm or POLE_PLOT_AREA_SQM),
            "tree_area_sqm": float(fi_calc.tree_area_sqm or TREE_PLOT_AREA_SQM),
            "fi_regeneration_per_ha": grand["regeneration_per_ha"] if grand else 0,
            "fi_sapling_per_ha": grand["sapling_per_ha"] if grand else 0,
            "fi_pole_per_ha": grand["pole_per_ha"] if grand else 0,
            "fi_tree_per_ha": grand["tree_per_ha"] if grand else 0,
            "fi_growing_stock_m3_per_ha": (
                grand["total_growing_stock_m3_per_ha"] if grand else 0
            ),
            # Protection stratum — reported separately, never in MAI/AAH.
            "fi_has_protected_stratum": _has_protected_stratum,
            "fi_protected_sample_plots": _prot_plots_total,
            "fi_protected_growing_stock_m3_per_ha": round(_prot_gs_weighted, 2),
            "fi_protected_stratum_note": _protected_stratum_note,
            "fi_protected_stratum_table": protected_stratum_table,
            "fi_protection_units": fi_protection_units,
            "fi_basal_area_m2_per_ha": grand["basal_area_m2_per_ha"] if grand else 0,
            "fi_regeneration_condition": blocks[0].regeneration_condition or "",
            "fi_forest_condition": blocks[0].forest_condition or "",
            "fi_mai_percent": grand["mai_percent"] if grand else 0,
            "fi_agb_t_per_ha": grand["agb_t_per_ha"] if grand else 0,
            "fi_bgb_t_per_ha": grand["bgb_t_per_ha"] if grand else 0,
            "fi_total_biomass_t_per_ha": (
                grand["total_biomass_t_per_ha"] if grand else 0
            ),
            "fi_carbon_stock_tc_per_ha": (
                grand["carbon_stock_tc_per_ha"] if grand else 0
            ),
            "fi_co2_equivalent_tco2_per_ha": (
                grand["co2_equivalent_tco2_per_ha"] if grand else 0
            ),
            "fi_weighted_wood_density": grand["weighted_wood_density"] if grand else 0,
            # ── Per-block detailed results (used by {{fi_block_summaries}}) ──
            "fi_block_summaries": block_summaries,
            # ── Block-wise species growing stock ──
            "fi_species_block_growing_stock": species_block_data,
            # ── Species composition analysis from field inventory ──
            **_compute_species_composition(
                species_block_data,
                base_species_data.get("species_list") if base_species_data else None,
            ),
            # ── Species x stage tables + chart data (Rambhadevi-style plan) ──
            **_species_stage_data(db, fi_calc.id, block_areas),
            # ── Same tables by regulation category (1-21 + Terai/Hill other) ──
            **_species_regulation_data(db, fi_calc.id, block_areas),
            # ── Unit-wise regeneration chart data (Fig 1) ──
            "fi_unit_regen_chart_data": [
                {
                    "label": b.block_name,
                    "regen_per_ha": round(b.regeneration_per_ha or 0),
                    "sapling_per_ha": round(b.sapling_per_ha or 0),
                }
                for b in blocks
            ],
            # ── Block-wise regeneration status ──
            "fi_block_regeneration_status": [
                {
                    "वन_खन्डको_नाम": b.block_name,
                    "विरूवा_प्रति_हेक्टर": round(b.regeneration_per_ha or 0),
                    "लाथ्रा_प्रति_हेक्टर": round(b.sapling_per_ha or 0),
                }
                for b in blocks
            ],
            # ── Block-wise DBH class growing stock (English) ──
            "fi_block_dbh_class_growing_stock": _fetch_dbh_class_breakdown(
                db, fi_calc.id, block_areas
            ),
            # ── Block-wise DBH class growing stock (Nepali) ──
            "fi_block_dbh_class_growing_stock_np": _fetch_dbh_class_breakdown_np(
                db, fi_calc.id, block_areas
            ),
            # ── Advance Growth (10-40 cm) & Mature Tree (>40 cm) — Nepali ──
            "fi_block_dbh_class_ag_np": _fetch_dbh_class_breakdown_ag_np(
                db, fi_calc.id, blocks, block_areas
            ),
            # ── Advance Growth only (एड्भान्स ग्रोथ — 10-40 cm) — Nepali ──
            "fi_block_dbh_class_advance_np": _fetch_dbh_class_breakdown_advance_np(
                db, fi_calc.id, blocks, block_areas
            ),
            # ── Mature Tree only (परिपक्व रूख — >40 cm) — Nepali ──
            "fi_block_dbh_class_mature_np": _fetch_dbh_class_breakdown_mature_np(
                db, fi_calc.id, blocks, block_areas
            ),
            # ── DBH class chart data (forest-wide grand total, pole+tree) ──
            "fi_dbh_class_chart_data": _prepare_dbh_class_chart_data(
                db, fi_calc.id, block_areas
            ),
            # ── वार्षिक वृद्धि तालिका / MAI table ──
            "fi_mai_table": mai_table,
            # ── वार्षिक स्वीकार्य कटान तालिका / AAH table ──
            "fi_aah_table": aah_table,
            # ── ब्लक अनुसार प्रति हेक्टर विरूवा, लाथ्रा, पोल तथा रूखको संख्या ──
            "fi_block_tree_count_per_ha": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "विरुवा_प्रति_हेक्टर": br["regeneration_per_ha"],
                    "लाथ्रा_प्रति_हेक्टर": br["sapling_per_ha"],
                    "खाँवा_प्रति_हेक्टर": br["pole_per_ha"],
                    "रूख_प्रति_हेक्टर": br["tree_per_ha"],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "विरुवा_प्रति_हेक्टर": grand["regeneration_per_ha"],
                        "लाथ्रा_प्रति_हेक्टर": grand["sapling_per_ha"],
                        "खाँवा_प्रति_हेक्टर": grand["pole_per_ha"],
                        "रूख_प्रति_हेक्टर": grand["tree_per_ha"],
                    }
                ]
                if grand
                else []
            ),
            # ── ब्लक अनुसार प्रति हेक्टर पोल (खाँवा) तथा रूखको काठ दाउराको परिणाम ──
            "fi_block_pole_tree_volume": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "खाँवा_काठ_घमी_प्रति_हे": br["pole_timber_m3_per_ha"],
                    "खाँवा_दाउरा_घमी_प्रति_हे": br["pole_firewood_m3_per_ha"],
                    "खाँवा_जम्मा_घमी_प्रति_हे": br["pole_total_m3_per_ha"],
                    "रूख_काठ_घमी_प्रति_हे": br["tree_timber_m3_per_ha"],
                    "रूख_दाउरा_घमी_प्रति_हे": br["tree_firewood_m3_per_ha"],
                    "रूख_जम्मा_घमी_प्रति_हे": br["tree_total_m3_per_ha"],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "खाँवा_काठ_घमी_प्रति_हे": grand["pole_timber_m3_per_ha"],
                        "खाँवा_दाउरा_घमी_प्रति_हे": grand["pole_firewood_m3_per_ha"],
                        "खाँवा_जम्मा_घमी_प्रति_हे": grand["pole_total_m3_per_ha"],
                        "रूख_काठ_घमी_प्रति_हे": grand["tree_timber_m3_per_ha"],
                        "रूख_दाउरा_घमी_प्रति_हे": grand["tree_firewood_m3_per_ha"],
                        "रूख_जम्मा_घमी_प्रति_हे": grand["tree_total_m3_per_ha"],
                    }
                ]
                if grand
                else []
            ),
            # ── वन ब्लक अनुसार काठ, दाउरा तथा जम्मा वृद्धि मौज्दात प्रति हेक्टर ──
            "fi_block_growing_stock": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "वृद्धि_मौज्दात_काठ_घमी_प्रति_हे": round(
                        float(br["pole_timber_m3_per_ha"] or 0)
                        + float(br["tree_timber_m3_per_ha"] or 0),
                        2,
                    ),
                    "वृद्धि_मौज्दात_दाउरा_घमी_प्रति_हे": round(
                        float(br["pole_firewood_m3_per_ha"] or 0)
                        + float(br["tree_firewood_m3_per_ha"] or 0),
                        2,
                    ),
                    "वृद्धि_मौज्दात_जम्मा_घमी_प्रति_हे": br["total_volume_m3_per_ha"],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "वृद्धि_मौज्दात_काठ_घमी_प्रति_हे": round(
                            float(grand["pole_timber_m3_per_ha"] or 0)
                            + float(grand["tree_timber_m3_per_ha"] or 0),
                            2,
                        ),
                        "वृद्धि_मौज्दात_दाउरा_घमी_प्रति_हे": round(
                            float(grand["pole_firewood_m3_per_ha"] or 0)
                            + float(grand["tree_firewood_m3_per_ha"] or 0),
                            2,
                        ),
                        "वृद्धि_मौज्दात_जम्मा_घमी_प्रति_हे": grand["total_volume_m3_per_ha"],
                    }
                ]
                if grand
                else []
            ),
            # ── ब्लक अनुसार प्रति हेक्टर वेसल एरीया ──
            "fi_block_basal_area": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "बेसल_एरिया_वर्गमी_प्रति_हे": br["basal_area_m2_per_ha"],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "बेसल_एरिया_वर्गमी_प्रति_हे": grand["basal_area_m2_per_ha"],
                    }
                ]
                if grand
                else []
            ),
            # ── NASA/ORNL/biomass_carbon_density/v1 को अधारमा प्रति हेक्टर ग्रोइङ्स्टक अनुमान ──
            "fi_block_satellite_volume": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "भू_उपग्रहिय_इमेजको_आधारमा_जम्मा_आयतन": br[
                        "satellite_volume_m3_per_ha"
                    ],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "भू_उपग्रहिय_इमेजको_आधारमा_जम्मा_आयतन": grand[
                            "satellite_volume_m3_per_ha"
                        ],
                    }
                ]
                if grand
                else []
            ),
            # ── ब्लक अनुसार पुनरोत्पादन तथा वनको अवस्था र वार्षिक वृद्धि निर्धारण ──
            "fi_block_condition_growth": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "पुनरोत्पादनको_अवस्था": br["regeneration_condition"],
                    "वनको_अवस्था": br["forest_condition"],
                    "औसत_वार्षिक_वृद्धि_प्रतिशत": br["mai_percent"],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "पुनरोत्पादनको_अवस्था": "—",
                        "वनको_अवस्था": "—",
                        "औसत_वार्षिक_वृद्धि_प्रतिशत": grand["mai_percent"],
                    }
                ]
                if grand
                else []
            ),
            # ── (IPCC/REDD+) अनुसारको वनश्रोत सर्भेक्षणको अधारमा बायोमास तथा कार्वनको अनुमान ──
            "fi_block_biomass_carbon": [
                {
                    "ब्लकको_नाम": br["block_name"],
                    "काठ_घनत्व_टन_प्रति_घमी": br["weighted_wood_density"],
                    "जमिन_माथिको_बायोमास_टन_प्रति_हे": br["agb_t_per_ha"],
                    "जमिन_मुनिको_बायोमास_टन_प्रति_हे": br["bgb_t_per_ha"],
                    "जम्मा_बायोमास_टन_प्रति_हे": br["total_biomass_t_per_ha"],
                    "कार्बन_टन_कार्बन_प्रति_हे": br["carbon_stock_tc_per_ha"],
                    "CO₂_समतुल्य_टन_CO₂_प्रति_हे": br["co2_equivalent_tco2_per_ha"],
                }
                for br in block_rows
            ]
            + (
                [
                    {
                        "ब्लकको_नाम": "जम्मा (भारित)",
                        "काठ_घनत्व_टन_प्रति_घमी": grand["weighted_wood_density"],
                        "जमिन_माथिको_बायोमास_टन_प्रति_हे": grand["agb_t_per_ha"],
                        "जमिन_मुनिको_बायोमास_टन_प्रति_हे": grand["bgb_t_per_ha"],
                        "जम्मा_बायोमास_टन_प्रति_हे": grand["total_biomass_t_per_ha"],
                        "कार्बन_टन_कार्बन_प्रति_हे": grand["carbon_stock_tc_per_ha"],
                        "CO₂_समतुल्य_टन_CO₂_प्रति_हे": grand["co2_equivalent_tco2_per_ha"],
                    }
                ]
                if grand
                else []
            ),
            "_block_areas_ha": block_areas,
            "_protected_areas_ha": protected_areas,
            "_working_circle": _wc,
            "_protection_unit_names": [b.block_name for b in protection_blocks],
        }

    return {
        "available": True,
        "total_sample_plots": 0,
        "total_blocks": 0,
        "_block_areas_ha": block_areas,
        "_protected_areas_ha": protected_areas,
        "_working_circle": {},
        "_protection_unit_names": [],
        "fi_species_composition": {},
        "fi_dominant_species": [],
        "fi_co_dominant_species": [],
        "fi_associated_species": [],
        "fi_fast_growing_species": [],
        "fi_moderate_growing_species": [],
        "fi_slow_growing_species": [],
        "fi_species_volume_by_block": [],
        "fi_has_protected_stratum": False,
        "fi_protected_sample_plots": 0,
        "fi_protected_growing_stock_m3_per_ha": 0,
        "fi_protected_stratum_note": "",
        "fi_protected_stratum_table": [],
        "fi_protection_units": [],
    }


# business: CFMG — total inventory aggregates all blocks for AAH calculation
def _compute_total_inventory(fi_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert per-hectare field inventory data to total inventory absolute values.

    Takes the output of get_field_inventory_data() (which must include _block_areas_ha),
    computes ti_ (total inventory) keys by multiplying per-hectare values by block area.
    """
    result: Dict[str, Any] = {}
    block_areas: Dict[str, float] = fi_data.get("_block_areas_ha", {})
    if not fi_data.get("available") or not block_areas:
        result["ti_available"] = False
        return result
    result["ti_available"] = True

    total_area = sum(block_areas.values())
    # PROTECTION_WORKING_CIRCLE_PLAN.md P1 — the per-ha figures are now weighted
    # over PRODUCTION units, so scale them by the production area; the protection
    # working circle is reported on its own and never in the AAH totals.
    _prot_names = set(fi_data.get("_protection_unit_names", []))
    production_area = sum(a for n, a in block_areas.items() if n not in _prot_names)
    protection_area = sum(a for n, a in block_areas.items() if n in _prot_names)
    result["ti_effective_area_ha"] = round(total_area, 4)  # whole forest, both circles
    result["ti_production_area_ha"] = round(production_area, 4)  # operable
    result["ti_protection_working_circle_area_ha"] = round(protection_area, 4)
    result["ti_total_blocks"] = fi_data.get("total_blocks", 0)
    result["ti_total_plots"] = fi_data.get("total_sample_plots", 0)

    # ── Scalar forest-wide totals (per-ha × total_area) ──
    _SCALAR_TI = [
        ("fi_regeneration_per_ha", "ti_total_regeneration", 0),
        ("fi_sapling_per_ha", "ti_total_sapling", 0),
        ("fi_pole_per_ha", "ti_total_pole", 0),
        ("fi_tree_per_ha", "ti_total_tree", 0),
        ("fi_growing_stock_m3_per_ha", "ti_total_growing_stock_m3", 2),
        ("fi_basal_area_m2_per_ha", "ti_total_basal_area_m2", 2),
        ("fi_agb_t_per_ha", "ti_total_agb_tonnes", 3),
        ("fi_bgb_t_per_ha", "ti_total_bgb_tonnes", 3),
        ("fi_total_biomass_t_per_ha", "ti_total_biomass_tonnes", 3),
        ("fi_carbon_stock_tc_per_ha", "ti_total_carbon_tc", 3),
        ("fi_co2_equivalent_tco2_per_ha", "ti_total_co2_tco2", 3),
    ]
    for fi_key, ti_key, prec in _SCALAR_TI:
        val = fi_data.get(fi_key, 0)
        if isinstance(val, (int, float)) and val:
            result[ti_key] = (
                round(val * production_area, prec)
                if prec
                else int(val * production_area)
            )
        else:
            result[ti_key] = 0

    # ── MAI / AAH forest-wide totals — production working circle only ──
    gs_per_ha = float(fi_data.get("fi_growing_stock_m3_per_ha", 0) or 0)
    mai_pct = float(fi_data.get("fi_mai_percent", 0) or 0)
    mai_per_ha = gs_per_ha * mai_pct / 100.0
    result["ti_total_mai_m3_per_year"] = round(mai_per_ha * production_area, 2)
    aah_per_ha = mai_per_ha * AAH_MULTIPLIER["Moderate"] / 100.0
    result["ti_total_aah_m3_per_year"] = round(aah_per_ha * production_area, 2)

    # ── Protection stratum absolute total (never in AAH) ──
    # = embedded protected sub-area extent  +  protection working-circle units.
    protected_areas: Dict[str, float] = fi_data.get("_protected_areas_ha", {})
    total_protected_area = sum(protected_areas.values()) + protection_area
    prot_gs_per_ha = float(fi_data.get("fi_protected_growing_stock_m3_per_ha", 0) or 0)
    result["ti_protected_area_ha"] = round(total_protected_area, 4)
    result["ti_protected_growing_stock_m3"] = round(
        prot_gs_per_ha * total_protected_area, 2
    )

    # ── Weighted wood density (density is independent of area) ──
    result["ti_weighted_wood_density"] = fi_data.get("fi_weighted_wood_density", 0)

    # ── Helper: build block-wise absolute row from per-ha row ──
    def _to_abs(per_ha_row: dict, area: float) -> dict:
        """Multiply all per-hectare numeric fields by area to get absolute values."""
        abs_row = dict(per_ha_row)
        _no_scale = (
            "total_sample_plots",
            "mai_percent",
            "aah_multiplier_percent",
            # protection-stratum figures are per PROTECTED area, not this
            # productive area — scaled into ti_protected_growing_stock_m3 below.
            "protected_sample_plots",
            "protected_growing_stock_m3_per_ha",
        )
        for k, v in per_ha_row.items():
            if isinstance(v, (int, float)) and k not in _no_scale:
                abs_row[k] = (
                    round(v * area, 2) if isinstance(v, float) else int(v * area)
                )
        return abs_row

    # ── Block-wise list variables ──
    block_summaries = fi_data.get("fi_block_summaries", [])
    ti_block_rows = []
    for br in block_summaries:
        bn = br.get("block_name", "")
        if bn == "Grand Total (Weighted)":
            continue
        area = block_areas.get(bn, 0)
        if area <= 0:
            continue
        ti_block_rows.append(_to_abs(br, area))

    if ti_block_rows:
        # ti_block_summaries — full block-wise absolute results (both circles)
        result["ti_block_summaries"] = ti_block_rows
        # ...but the Forest Total sums the PRODUCTION units only (P1).
        _prod_ti_rows = [
            r for r in ti_block_rows if r.get("working_circle") != "protection"
        ]

        # Forest-wide total row
        ft = {
            "block_name": "Forest Total",
            "total_sample_plots": sum(
                r.get("total_sample_plots", 0) for r in _prod_ti_rows
            ),
            "regeneration_per_ha": sum(
                r.get("regeneration_per_ha", 0) for r in _prod_ti_rows
            ),
            "sapling_per_ha": sum(r.get("sapling_per_ha", 0) for r in _prod_ti_rows),
            "pole_per_ha": sum(r.get("pole_per_ha", 0) for r in _prod_ti_rows),
            "tree_per_ha": sum(r.get("tree_per_ha", 0) for r in _prod_ti_rows),
            "pole_timber_m3_per_ha": round(
                sum(r.get("pole_timber_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "pole_firewood_m3_per_ha": round(
                sum(r.get("pole_firewood_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "pole_total_m3_per_ha": round(
                sum(r.get("pole_total_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "tree_timber_m3_per_ha": round(
                sum(r.get("tree_timber_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "tree_firewood_m3_per_ha": round(
                sum(r.get("tree_firewood_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "tree_total_m3_per_ha": round(
                sum(r.get("tree_total_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "total_volume_m3_per_ha": round(
                sum(r.get("total_volume_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "total_growing_stock_m3_per_ha": round(
                sum(r.get("total_growing_stock_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "satellite_volume_m3_per_ha": round(
                sum(r.get("satellite_volume_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "basal_area_m2_per_ha": round(
                sum(r.get("basal_area_m2_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "mai_total_m3_per_ha": round(
                sum(r.get("mai_total_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "aah_total_m3_per_ha": round(
                sum(r.get("aah_total_m3_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "mai_percent": round(
                sum(
                    r.get("mai_percent", 0) * r.get("total_growing_stock_m3_per_ha", 0)
                    for r in _prod_ti_rows
                )
                / max(
                    sum(
                        r.get("total_growing_stock_m3_per_ha", 0) for r in _prod_ti_rows
                    ),
                    1,
                ),
                2,
            ),
            "aah_multiplier_percent": round(
                sum(
                    r.get("aah_multiplier_percent", 60.0)
                    * r.get("total_growing_stock_m3_per_ha", 0)
                    for r in _prod_ti_rows
                )
                / max(
                    sum(
                        r.get("total_growing_stock_m3_per_ha", 0) for r in _prod_ti_rows
                    ),
                    1,
                ),
                1,
            ),
            "agb_t_per_ha": round(
                sum(r.get("agb_t_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "bgb_t_per_ha": round(
                sum(r.get("bgb_t_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "total_biomass_t_per_ha": round(
                sum(r.get("total_biomass_t_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "carbon_stock_tc_per_ha": round(
                sum(r.get("carbon_stock_tc_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "co2_equivalent_tco2_per_ha": round(
                sum(r.get("co2_equivalent_tco2_per_ha", 0) for r in _prod_ti_rows), 2
            ),
            "weighted_wood_density": round(
                sum(
                    r.get("weighted_wood_density", 0)
                    * r.get("total_growing_stock_m3_per_ha", 0)
                    for r in _prod_ti_rows
                )
                / max(
                    sum(
                        r.get("total_growing_stock_m3_per_ha", 0) for r in _prod_ti_rows
                    ),
                    1,
                ),
                3,
            ),
        }
        result["ti_block_summaries"].append(ft)

        # ── Nepali-keyed block-wise tables ──
        result["ti_block_tree_count_total"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "विरुवा_कुल": r.get("regeneration_per_ha", 0),
                "लाथ्रा_कुल": r.get("sapling_per_ha", 0),
                "खाँवा_कुल": r.get("pole_per_ha", 0),
                "रूख_कुल": r.get("tree_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "विरुवा_कुल": ft.get("regeneration_per_ha", 0),
                "लाथ्रा_कुल": ft.get("sapling_per_ha", 0),
                "खाँवा_कुल": ft.get("pole_per_ha", 0),
                "रूख_कुल": ft.get("tree_per_ha", 0),
            }
        ]

        result["ti_block_pole_tree_volume"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "खाँवा_काठ_कुल_घमी": r.get("pole_timber_m3_per_ha", 0),
                "खाँवा_दाउरा_कुल_घमी": r.get("pole_firewood_m3_per_ha", 0),
                "खाँवा_जम्मा_कुल_घमी": r.get("pole_total_m3_per_ha", 0),
                "रूख_काठ_कुल_घमी": r.get("tree_timber_m3_per_ha", 0),
                "रूख_दाउरा_कुल_घमी": r.get("tree_firewood_m3_per_ha", 0),
                "रूख_जम्मा_कुल_घमी": r.get("tree_total_m3_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "खाँवा_काठ_कुल_घमी": ft.get("pole_timber_m3_per_ha", 0),
                "खाँवा_दाउरा_कुल_घमी": ft.get("pole_firewood_m3_per_ha", 0),
                "खाँवा_जम्मा_कुल_घमी": ft.get("pole_total_m3_per_ha", 0),
                "रूख_काठ_कुल_घमी": ft.get("tree_timber_m3_per_ha", 0),
                "रूख_दाउरा_कुल_घमी": ft.get("tree_firewood_m3_per_ha", 0),
                "रूख_जम्मा_कुल_घमी": ft.get("tree_total_m3_per_ha", 0),
            }
        ]

        result["ti_block_growing_stock"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "वृद्धि_मौज्दात_काठ_कुल_घमी": round(
                    float(r.get("pole_timber_m3_per_ha", 0) or 0)
                    + float(r.get("tree_timber_m3_per_ha", 0) or 0),
                    2,
                ),
                "वृद्धि_मौज्दात_दाउरा_कुल_घमी": round(
                    float(r.get("pole_firewood_m3_per_ha", 0) or 0)
                    + float(r.get("tree_firewood_m3_per_ha", 0) or 0),
                    2,
                ),
                "वृद्धि_मौज्दात_जम्मा_कुल_घमी": r.get("total_volume_m3_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "वृद्धि_मौज्दात_काठ_कुल_घमी": round(
                    float(ft.get("pole_timber_m3_per_ha", 0) or 0)
                    + float(ft.get("tree_timber_m3_per_ha", 0) or 0),
                    2,
                ),
                "वृद्धि_मौज्दात_दाउरा_कुल_घमी": round(
                    float(ft.get("pole_firewood_m3_per_ha", 0) or 0)
                    + float(ft.get("tree_firewood_m3_per_ha", 0) or 0),
                    2,
                ),
                "वृद्धि_मौज्दात_जम्मा_कुल_घमी": ft.get("total_volume_m3_per_ha", 0),
            }
        ]

        result["ti_block_basal_area"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "बेसल_एरिया_कुल_वर्गमी": r.get("basal_area_m2_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "बेसल_एरिया_कुल_वर्गमी": ft.get("basal_area_m2_per_ha", 0),
            }
        ]

        result["ti_block_satellite_volume"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "भू_उपग्रहिय_इमेजको_आधारमा_कुल_आयतन": r.get(
                    "satellite_volume_m3_per_ha", 0
                ),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "भू_उपग्रहिय_इमेजको_आधारमा_कुल_आयतन": ft.get(
                    "satellite_volume_m3_per_ha", 0
                ),
            }
        ]

        result["ti_block_condition_growth"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "पुनरोत्पादनको_अवस्था": r.get("regeneration_condition", ""),
                "वनको_अवस्था": r.get("forest_condition", ""),
                "औसत_वार्षिक_वृद्धि_प्रतिशत": r.get("mai_percent", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "पुनरोत्पादनको_अवस्था": "—",
                "वनको_अवस्था": "—",
                "औसत_वार्षिक_वृद्धि_प्रतिशत": ft.get("mai_percent", 0),
            }
        ]

        result["ti_block_biomass_carbon"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "काठ_घनत्व_टन_प्रति_घमी": r.get("weighted_wood_density", 0),
                "जमिन_माथिको_बायोमास_कुल_टन": r.get("agb_t_per_ha", 0),
                "जमिन_मुनिको_बायोमास_कुल_टन": r.get("bgb_t_per_ha", 0),
                "जम्मा_बायोमास_कुल_टन": r.get("total_biomass_t_per_ha", 0),
                "कार्बन_कुल_टन_कार्बन": r.get("carbon_stock_tc_per_ha", 0),
                "CO₂_समतुल्य_कुल_टन_CO₂": r.get("co2_equivalent_tco2_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "काठ_घनत्व_टन_प्रति_घमी": ft.get("weighted_wood_density", 0),
                "जमिन_माथिको_बायोमास_कुल_टन": ft.get("agb_t_per_ha", 0),
                "जमिन_मुनिको_बायोमास_कुल_टन": ft.get("bgb_t_per_ha", 0),
                "जम्मा_बायोमास_कुल_टन": ft.get("total_biomass_t_per_ha", 0),
                "कार्बन_कुल_टन_कार्बन": ft.get("carbon_stock_tc_per_ha", 0),
                "CO₂_समतुल्य_कुल_टन_CO₂": ft.get("co2_equivalent_tco2_per_ha", 0),
            }
        ]

        # ── MAI table (absolute) ──
        result["ti_mai_table"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "खाँवा_संख्या": r.get("pole_per_ha", 0),
                "रूख_संख्या": r.get("tree_per_ha", 0),
                "खाँवा_काठ_कुल_घमी": r.get("pole_timber_m3_per_ha", 0),
                "खाँवा_दाउरा_कुल_घमी": r.get("pole_firewood_m3_per_ha", 0),
                "खाँवा_जम्मा_कुल_घमी": r.get("pole_total_m3_per_ha", 0),
                "रूख_काठ_कुल_घमी": r.get("tree_timber_m3_per_ha", 0),
                "रूख_दाउरा_कुल_घमी": r.get("tree_firewood_m3_per_ha", 0),
                "रूख_जम्मा_कुल_घमी": r.get("tree_total_m3_per_ha", 0),
                "कुल_MAI_घमी_प्रति_वर्ष": r.get("mai_total_m3_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "खाँवा_संख्या": ft.get("pole_per_ha", 0),
                "रूख_संख्या": ft.get("tree_per_ha", 0),
                "खाँवा_काठ_कुल_घमी": ft.get("pole_timber_m3_per_ha", 0),
                "खाँवा_दाउरा_कुल_घमी": ft.get("pole_firewood_m3_per_ha", 0),
                "खाँवा_जम्मा_कुल_घमी": ft.get("pole_total_m3_per_ha", 0),
                "रूख_काठ_कुल_घमी": ft.get("tree_timber_m3_per_ha", 0),
                "रूख_दाउरा_कुल_घमी": ft.get("tree_firewood_m3_per_ha", 0),
                "रूख_जम्मा_कुल_घमी": ft.get("tree_total_m3_per_ha", 0),
                "कुल_MAI_घमी_प्रति_वर्ष": ft.get("mai_total_m3_per_ha", 0),
            }
        ]

        # ── AAH table (absolute) ──
        result["ti_aah_table"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "खाँवा_संख्या": r.get("pole_per_ha", 0),
                "रूख_संख्या": r.get("tree_per_ha", 0),
                "वन_अवस्था": r.get("forest_condition", ""),
                "AAH_गुणक_प्रतिशत": r.get("aah_multiplier_percent", 60.0),
                "कुल_AAH_घमी_प्रति_वर्ष": r.get("aah_total_m3_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "खाँवा_संख्या": ft.get("pole_per_ha", 0),
                "रूख_संख्या": ft.get("tree_per_ha", 0),
                "वन_अवस्था": "—",
                "AAH_गुणक_प्रतिशत": AAH_MULTIPLIER["Moderate"],
                "कुल_AAH_घमी_प्रति_वर्ष": ft.get("aah_total_m3_per_ha", 0),
            }
        ]

        # ── Regeneration status (absolute) ──
        result["ti_block_regeneration_status"] = fi_data.get(
            "fi_block_regeneration_status", []
        )

    # ── Species block growing stock (absolute) ──
    species_data = fi_data.get("fi_species_block_growing_stock", [])
    ti_species_rows = []
    for sr in species_data:
        bn = sr.get("block_name", "")
        if bn == "Grand Total (Weighted)":
            continue
        area = block_areas.get(bn, 0)
        if area <= 0:
            continue
        ti_species_rows.append(
            {
                "block_name": bn,
                "species_scientific": sr.get("species_scientific", ""),
                "species_local": sr.get("species_local", ""),
                "count_total": int((sr.get("count_per_ha", 0) or 0) * area),
                "timber_m3_total": round(
                    (sr.get("timber_m3_per_ha", 0) or 0) * area, 2
                ),
                "fuelwood_m3_total": round(
                    (sr.get("fuelwood_m3_per_ha", 0) or 0) * area, 2
                ),
                "total_volume_m3_total": round(
                    (sr.get("total_volume_m3_per_ha", 0) or 0) * area, 2
                ),
            }
        )
    if ti_species_rows:
        result["ti_species_block_growing_stock"] = ti_species_rows

        # Species-level grand totals
        sp_agg: Dict = {}
        sp_order: list = []
        for sr in ti_species_rows:
            key = (sr["species_scientific"] or "") + "||" + (sr["species_local"] or "")
            if key not in sp_agg:
                sp_agg[key] = {
                    "sci": sr["species_scientific"],
                    "loc": sr["species_local"],
                    "cnt": 0,
                    "tim": 0.0,
                    "fuel": 0.0,
                    "tot": 0.0,
                }
                sp_order.append(key)
            sp_agg[key]["cnt"] += sr["count_total"]
            sp_agg[key]["tim"] += sr["timber_m3_total"]
            sp_agg[key]["fuel"] += sr["fuelwood_m3_total"]
            sp_agg[key]["tot"] += sr["total_volume_m3_total"]
        for key in sp_order:
            s = sp_agg[key]
            ti_species_rows.append(
                {
                    "block_name": "Grand Total",
                    "species_scientific": s["sci"],
                    "species_local": s["loc"],
                    "count_total": s["cnt"],
                    "timber_m3_total": round(s["tim"], 2),
                    "fuelwood_m3_total": round(s["fuel"], 2),
                    "total_volume_m3_total": round(s["tot"], 2),
                }
            )

    # ── Species volume by block (absolute) — sorted species list ──
    species_vol = fi_data.get("fi_species_volume_by_block", [])
    if species_vol:
        result["ti_species_volume_by_block"] = [
            {
                "species": name,
                "total_volume_m3": round(
                    pct / 100.0 * result.get("ti_total_growing_stock_m3", 0), 2
                ),
            }
            for name, pct in species_vol
        ]

    # ── Species composition (absolute numbers) ──
    comp_pct = fi_data.get("fi_species_composition", {})
    if comp_pct and result.get("ti_total_growing_stock_m3"):
        result["ti_species_composition_absolute"] = {
            name: round(pct / 100.0 * result["ti_total_growing_stock_m3"], 2)
            for name, pct in comp_pct.items()
        }
        result["ti_dominant_species_absolute"] = fi_data.get("fi_dominant_species", [])
        result["ti_co_dominant_species_absolute"] = fi_data.get(
            "fi_co_dominant_species", []
        )
        result["ti_associated_species_absolute"] = fi_data.get(
            "fi_associated_species", []
        )

    # ── Growth rate species totals (absolute volume) ──
    fast = fi_data.get("fi_fast_growing_species", [])
    moderate = fi_data.get("fi_moderate_growing_species", [])
    slow = fi_data.get("fi_slow_growing_species", [])
    if comp_pct and result.get("ti_total_growing_stock_m3"):
        result["ti_fast_growing_species_total"] = (
            round(
                sum(comp_pct.get(s, 0) for s in fast)
                / 100.0
                * result["ti_total_growing_stock_m3"],
                2,
            )
            if fast
            else 0
        )
        result["ti_moderate_growing_species_total"] = (
            round(
                sum(comp_pct.get(s, 0) for s in moderate)
                / 100.0
                * result["ti_total_growing_stock_m3"],
                2,
            )
            if moderate
            else 0
        )
        result["ti_slow_growing_species_total"] = (
            round(
                sum(comp_pct.get(s, 0) for s in slow)
                / 100.0
                * result["ti_total_growing_stock_m3"],
                2,
            )
            if slow
            else 0
        )

    # business: CFMG — chart data for village-friendly OP graphics (pie + bar)
    # NOTE: colors hardcoded for consistent legend across all reports
    block_names = [r["block_name"] for r in ti_block_rows]
    block_stocks = [r.get("total_growing_stock_m3_per_ha", 0) for r in ti_block_rows]
    block_mais = [r.get("mai_total_m3_per_ha", 0) for r in ti_block_rows]
    block_aahs = [r.get("aah_total_m3_per_ha", 0) for r in ti_block_rows]
    colors = [
        "#22c55e",
        "#3b82f6",
        "#eab308",
        "#f97316",
        "#a855f7",
        "#ec4899",
        "#14b8a6",
        "#f43f5e",
    ]

    result["ti_chart_block_stock_pie"] = {
        "type": "pie",
        "title_np": "ब्लक अनुसार कुल ग्रोइङ स्टक वितरण",
        "title_en": "Block-wise Total Growing Stock Distribution",
        "labels": block_names,
        "data": block_stocks,
        "backgroundColor": colors[: len(block_names)],
        "unit": "m³",
    }
    result["ti_chart_block_comparison_bar"] = {
        "type": "bar",
        "title_np": "ब्लक अनुसार ग्रोइङ स्टक, MAI तथा AAH तुलना",
        "title_en": "Block-wise Growing Stock, MAI & AAH Comparison",
        "labels": block_names,
        "datasets": [
            {
                "label": "ग्रोइङ स्टक (m³)",
                "data": block_stocks,
                "backgroundColor": "#22c55e",
            },
            {"label": "MAI (m³/yr)", "data": block_mais, "backgroundColor": "#a855f7"},
            {"label": "AAH (m³/yr)", "data": block_aahs, "backgroundColor": "#f59e0b"},
        ],
    }

    # ── DBH class stacked bar chart data ──
    dbh_data = fi_data.get("fi_dbh_class_chart_data", [])
    if dbh_data:
        dbh_labels = [d["label"] for d in dbh_data]
        dbh_volumes = [d["total_volume_m3_per_ha"] for d in dbh_data]
        result["ti_chart_dbh_class_bar"] = {
            "type": "bar",
            "title_np": "DBH वर्ग अनुसार प्रतिहेक्टर आयतन",
            "title_en": "DBH Class Volume per ha",
            "labels": dbh_labels,
            "datasets": [
                {
                    "label": "आयतन (m³/ha)",
                    "data": dbh_volumes,
                    "backgroundColor": "#22c55e",
                }
            ],
        }

    # ── T7: DBH क्लास अनुसार कुल मौज्दात (Absolute) ──
    dbh_raw = fi_data.get("fi_block_dbh_class_growing_stock", [])
    _DBH_NP_LABEL = DBH_CLASS_NP
    if dbh_raw and ti_block_rows:
        # Per-block DBH class absolute values
        dbh_abs_rows = []
        for r in dbh_raw:
            bn = r.get("block_name", "")
            area = block_areas.get(bn, 0)
            if area <= 0 or bn == "Grand Total (Weighted)":
                continue
            dbh_abs_rows.append(
                {
                    "ब्लकको_नाम": bn,
                    "DBH_क्लास": _DBH_NP_LABEL.get(r["dbh_class"], r["dbh_class"]),
                    "गणना": int(r["count_per_ha"] * area),
                    "काठ_घमी": round(r["timber_m3_per_ha"] * area, 2),
                    "दाउरा_घमी": round(r["fuelwood_m3_per_ha"] * area, 2),
                    "आयतन_घमी": round(r["total_volume_m3_per_ha"] * area, 2),
                }
            )

        # Forest-wide DBH class totals
        ft_dbh: dict = {}
        ft_dbh_order: list = []
        for r in dbh_abs_rows:
            cls = r["DBH_क्लास"]
            if cls not in ft_dbh:
                ft_dbh[cls] = {
                    "गणना": 0,
                    "काठ_घमी": 0.0,
                    "दाउरा_घमी": 0.0,
                    "आयतन_घमी": 0.0,
                }
                ft_dbh_order.append(cls)
            ft_dbh[cls]["गणना"] += r["गणना"]
            ft_dbh[cls]["काठ_घमी"] += r["काठ_घमी"]
            ft_dbh[cls]["दाउरा_घमी"] += r["दाउरा_घमी"]
            ft_dbh[cls]["आयतन_घमी"] += r["आयतन_घमी"]

        result["ti_dbh_class_totals_table"] = dbh_abs_rows + [
            {
                "ब्लकको_नाम": "जम्मा वन कुल",
                "DBH_क्लास": cls,
                "गणना": ft_dbh[cls]["गणना"],
                "काठ_घमी": round(ft_dbh[cls]["काठ_घमी"], 2),
                "दाउरा_घमी": round(ft_dbh[cls]["दाउरा_घमी"], 2),
                "आयतन_घमी": round(ft_dbh[cls]["आयतन_घमी"], 2),
            }
            for cls in ft_dbh_order
        ]

        # ── T8: DBH क्लास अनुसार कुल मौज्दात (प्रति हे.) ──
        dbh_perha_rows = []
        for r in dbh_raw:
            bn = r.get("block_name", "")
            if bn == "Grand Total (Weighted)":
                continue
            area = block_areas.get(bn, 0)
            if area <= 0:
                continue
            dbh_perha_rows.append(
                {
                    "ब्लकको_नाम": bn,
                    "DBH_क्लास": _DBH_NP_LABEL.get(r["dbh_class"], r["dbh_class"]),
                    "गणना_प्रति_हे": r["count_per_ha"],
                    "काठ_घमी_प्रति_हे": r["timber_m3_per_ha"],
                    "दाउरा_घमी_प्रति_हे": r["fuelwood_m3_per_ha"],
                    "आयतन_घमी_प्रति_हे": r["total_volume_m3_per_ha"],
                }
            )
        # Forest-wide per-ha
        ft_perha: dict = {}
        ft_ph_order: list = []
        for r in dbh_perha_rows:
            cls = r["DBH_क्लास"]
            if cls not in ft_perha:
                ft_perha[cls] = {
                    "गणना_प्रति_हे": 0.0,
                    "काठ_घमी_प्रति_हे": 0.0,
                    "दाउरा_घमी_प्रति_हे": 0.0,
                    "आयतन_घमी_प्रति_हे": 0.0,
                }
                ft_ph_order.append(cls)
            area = block_areas.get(r["ब्लकको_नाम"], 0)
            ft_perha[cls]["गणना_प्रति_हे"] += r["गणना_प्रति_हे"] * area
            ft_perha[cls]["काठ_घमी_प्रति_हे"] += r["काठ_घमी_प्रति_हे"] * area
            ft_perha[cls]["दाउरा_घमी_प्रति_हे"] += r["दाउरा_घमी_प्रति_हे"] * area
            ft_perha[cls]["आयतन_घमी_प्रति_हे"] += r["आयतन_घमी_प्रति_हे"] * area
        for cls in ft_ph_order:
            for k in ft_perha[cls]:
                ft_perha[cls][k] = (
                    round(ft_perha[cls][k] / total_area, 2) if total_area > 0 else 0
                )

        result["ti_dbh_class_perha_table"] = dbh_perha_rows + [
            {"ब्लकको_नाम": "जम्मा वन कुल/हे.", "DBH_क्लास": cls, **ft_perha[cls]}
            for cls in ft_ph_order
        ]

        # ── T5: प्रजाति अनुसार DBH क्लास मौज्दात (block+dbh class, without species dimension) ──
        if dbh_perha_rows:
            result["ti_species_dbh_class_table"] = dbh_perha_rows
            # T6: पुरै वन क्षेत्र — forest-wide species×DBH (without species breakdown)
            result["ti_forest_dbh_class_table"] = [
                {
                    "DBH_क्लास": cls,
                    "गणना_प्रति_हे": ft_perha[cls]["गणना_प्रति_हे"],
                    "काठ_घमी_प्रति_हे": ft_perha[cls]["काठ_घमी_प्रति_हे"],
                    "दाउरा_घमी_प्रति_हे": ft_perha[cls]["दाउरा_घमी_प्रति_हे"],
                    "आयतन_घमी_प्रति_हे": ft_perha[cls]["आयतन_घमी_प्रति_हे"],
                }
                for cls in ft_ph_order
            ]

        # ── T9: DBH क्लास अनुसार MAI ──
        _mai_pct = float(fi_data.get("fi_mai_percent", 0) or 0)
        _aah_mult = AAH_MULTIPLIER["Moderate"] / 100.0  # default AAH multiplier
        # Build per-ha lookup from dbh_perha_rows
        _perha_lookup = {}
        for r in dbh_perha_rows:
            _perha_lookup[(r["ब्लकको_नाम"], r["DBH_क्लास"])] = r["गणना_प्रति_हे"]
        dbh_mai_rows = []
        for r in dbh_abs_rows:
            bname = r["ब्लकको_नाम"]
            vol = r["आयतन_घमी"]
            count_abs = r["गणना"]
            count_per_ha = _perha_lookup.get((bname, r["DBH_क्लास"]), 0)
            dbh_mai_rows.append(
                {
                    "ब्लकको_नाम": bname,
                    "DBH_क्लास": r["DBH_क्लास"],
                    "गणना_प्रति_हे": count_per_ha,
                    "गणना": count_abs,
                    "आयतन_घमी": vol,
                    "MAI_घमी_प्रति_वर्ष": round(vol * _mai_pct / 100.0, 2),
                    "MAI_संख्या_प्रति_हे": round(count_per_ha * _mai_pct / 100.0, 2),
                }
            )
        # Forest-wide DBH MAI
        ft_mai = []
        for cls in ft_dbh_order:
            vol = ft_dbh[cls]["आयतन_घमी"]
            count_abs = ft_dbh[cls]["गणना"]
            count_per_ha = (
                round(ft_perha[cls]["गणना_प्रति_हे"], 2) if cls in ft_perha else 0
            )
            ft_mai.append(
                {
                    "DBH_क्लास": cls,
                    "गणना_प्रति_हे": count_per_ha,
                    "गणना": count_abs,
                    "आयतन_घमी": round(vol, 2),
                    "MAI_घमी_प्रति_वर्ष": round(vol * _mai_pct / 100.0, 2),
                    "MAI_संख्या_प्रति_हे": round(count_per_ha * _mai_pct / 100.0, 2),
                }
            )
        result["ti_dbh_mai_table"] = (
            dbh_mai_rows + [{"ब्लकको_नाम": "जम्मा वन कुल", **r} for r in ft_mai]
            if ft_mai
            else []
        )

        # ── T10: DBH क्लास अनुसार AAH ──
        dbh_aah_rows = []
        for r in dbh_abs_rows:
            bname = r["ब्लकको_नाम"]
            vol = r["आयतन_घमी"]
            count_abs = r["गणना"]
            count_per_ha = _perha_lookup.get((bname, r["DBH_क्लास"]), 0)
            mai_val = vol * _mai_pct / 100.0
            mai_trees = count_per_ha * _mai_pct / 100.0
            dbh_aah_rows.append(
                {
                    "ब्लकको_नाम": bname,
                    "DBH_क्लास": r["DBH_क्लास"],
                    "गणना_प्रति_हे": count_per_ha,
                    "गणना": count_abs,
                    "आयतन_घमी": vol,
                    "MAI_घमी_प्रति_वर्ष": round(mai_val, 2),
                    "MAI_संख्या_प्रति_हे": round(mai_trees, 2),
                    "AAH_घमी_प्रति_वर्ष": round(mai_val * _aah_mult, 2),
                    "AAH_संख्या_प्रति_हे": round(mai_trees * _aah_mult, 2),
                }
            )
        ft_aah = []
        for cls in ft_dbh_order:
            vol = ft_dbh[cls]["आयतन_घमी"]
            count_abs = ft_dbh[cls]["गणना"]
            count_per_ha = (
                round(ft_perha[cls]["गणना_प्रति_हे"], 2) if cls in ft_perha else 0
            )
            mai_val = vol * _mai_pct / 100.0
            mai_trees = count_per_ha * _mai_pct / 100.0
            ft_aah.append(
                {
                    "DBH_क्लास": cls,
                    "गणना_प्रति_हे": count_per_ha,
                    "गणना": count_abs,
                    "आयतन_घमी": round(vol, 2),
                    "MAI_घमी_प्रति_वर्ष": round(mai_val, 2),
                    "MAI_संख्या_प्रति_हे": round(mai_trees, 2),
                    "AAH_घमी_प्रति_वर्ष": round(mai_val * _aah_mult, 2),
                    "AAH_संख्या_प्रति_हे": round(mai_trees * _aah_mult, 2),
                }
            )
        result["ti_dbh_aah_table"] = (
            dbh_aah_rows + [{"ब्लकको_नाम": "जम्मा वन कुल", **r} for r in ft_aah]
            if ft_aah
            else []
        )

    # ── T11: प्रजाति संरचना (स्थानीय नाम) ──
    comp_abs = fi_data.get("ti_species_composition_absolute", {})
    if comp_abs:
        total_vol = sum(v for v in comp_abs.values() if isinstance(v, (int, float)))
        result["ti_species_composition_table"] = [
            {
                "प्रजातिको_नाम": sp,
                "कुल_आयतन_घमी": round(vol, 2),
                "प्रतिशत": round(vol / total_vol * 100, 2) if total_vol > 0 else 0,
            }
            for sp, vol in sorted(comp_abs.items(), key=lambda x: x[1], reverse=True)
        ]

    # ── T12: ब्लक अनुसार उत्पादनसिल संचिती ──
    if ti_block_rows:
        result["ti_block_productivity_table"] = [
            {
                "ब्लकको_नाम": r["block_name"],
                "क्षेत्रफल_हे": round(block_areas.get(r["block_name"], 0), 4),
                "जम्मा_मौज्दात_घमी": r.get("total_growing_stock_m3_per_ha", 0),
                "प्रति_हे_मौज्दात_घमी": round(
                    r.get("total_growing_stock_m3_per_ha", 0)
                    / max(block_areas.get(r["block_name"], 1), 0.01),
                    2,
                ),
                "MAI_घमी_प्रति_वर्ष": r.get("mai_total_m3_per_ha", 0),
                "AAH_घमी_प्रति_वर्ष": r.get("aah_total_m3_per_ha", 0),
            }
            for r in ti_block_rows
        ] + [
            {
                "ब्लकको_नाम": "जम्मा",
                "क्षेत्रफल_हे": round(total_area, 4),
                "जम्मा_मौज्दात_घमी": ft.get("total_growing_stock_m3_per_ha", 0),
                "प्रति_हे_मौज्दात_घमी": round(
                    ft.get("total_growing_stock_m3_per_ha", 0) / max(total_area, 0.01),
                    2,
                ),
                "MAI_घमी_प्रति_वर्ष": ft.get("mai_total_m3_per_ha", 0),
                "AAH_घमी_प्रति_वर्ष": ft.get("aah_total_m3_per_ha", 0),
            }
        ]

    # ── T13: आर्थिक मूल्याङ्कन ──
    # constraint: default rates in NPR — timber=2500, fuelwood=1000, carbon=3000 per unit
    _TIMBER_RATE = 2500
    _FUELWOOD_RATE = 1000
    _CARBON_RATE = 3000
    if ti_block_rows:
        econ_rows = []
        gt_timber_val = gt_fuel_val = gt_carbon_val = 0.0
        for r in ti_block_rows:
            bn = r["block_name"]
            area = block_areas.get(bn, 0)
            timber_vol = r.get("pole_timber_m3_per_ha", 0) + r.get(
                "tree_timber_m3_per_ha", 0
            )
            fuel_vol = r.get("pole_firewood_m3_per_ha", 0) + r.get(
                "tree_firewood_m3_per_ha", 0
            )
            co2 = r.get("co2_equivalent_tco2_per_ha", 0)
            t_val = round(timber_vol * _TIMBER_RATE, 2)
            f_val = round(fuel_vol * _FUELWOOD_RATE, 2)
            c_val = round(co2 * _CARBON_RATE, 2)
            econ_rows.append(
                {
                    "ब्लकको_नाम": bn,
                    "उत्पादनसिल_संचिती_घमी": r.get("total_growing_stock_m3_per_ha", 0),
                    "काठ_दर_रु": _TIMBER_RATE,
                    "काठ_मूल्य_रु": t_val,
                    "दाउरा_दर_रु": _FUELWOOD_RATE,
                    "दाउरा_मूल्य_रु": f_val,
                    "कार्बन_दर_रु": _CARBON_RATE,
                    "कार्बन_मूल्य_रु": c_val,
                    "जम्मा_मूल्य_रु": round(t_val + f_val + c_val, 2),
                }
            )
            gt_timber_val += t_val
            gt_fuel_val += f_val
            gt_carbon_val += c_val
        result["ti_economic_valuation_table"] = econ_rows + [
            {
                "ब्लकको_नाम": "जम्मा",
                "उत्पादनसिल_संचिती_घमी": round(
                    sum(
                        r.get("total_growing_stock_m3_per_ha", 0) for r in _prod_ti_rows
                    ),
                    2,
                ),
                "काठ_दर_रु": _TIMBER_RATE,
                "काठ_मूल्य_रु": round(gt_timber_val, 2),
                "दाउरा_दर_रु": _FUELWOOD_RATE,
                "दाउरा_मूल्य_रु": round(gt_fuel_val, 2),
                "कार्बन_दर_रु": _CARBON_RATE,
                "कार्बन_मूल्य_रु": round(gt_carbon_val, 2),
                "जम्मा_मूल्य_रु": round(gt_timber_val + gt_fuel_val + gt_carbon_val, 2),
            }
        ]

    # business: CFMG — sustainability index (SI) = AAH/growing_stock * 100; harvest pressure (HP) = AAH/MAI * 100
    # constraint: SI < 100 = sustainable harvest; SI >= 100 = overharvest risk
    if ti_block_rows:
        sus_rows = []
        for r in ti_block_rows:
            bn = r["block_name"]
            area = block_areas.get(bn, 0) or 1
            gs = r.get("total_growing_stock_m3_per_ha", 0)
            mai_val = r.get("mai_total_m3_per_ha", 0)
            aah_val = r.get("aah_total_m3_per_ha", 0)
            si = round((aah_val / gs * 100), 2) if gs > 0 else 0
            hp = round((aah_val / mai_val * 100), 1) if mai_val > 0 else 0
            gs_per_ha = round(gs / area, 2) if area > 0 else 0
            regen_cond = r.get("regeneration_condition", "—")
            forest_cond = r.get("forest_condition", "—")
            sus_rows.append(
                {
                    "ब्लकको_नाम": bn,
                    "दिगोपन_सूचकांक_SI_प्रतिशत": si,
                    "कटान_दबाव_HP_प्रतिशत": hp,
                    "उत्पादनसिल_संचिती_प्रति_हे_घमी": gs_per_ha,
                    "MAI_प्रतिशत": r.get("mai_percent", 0),
                    "AAH_घमी_प्रति_वर्ष": aah_val,
                    "पुनरोत्पादन_अवस्था": regen_cond,
                    "वन_अवस्था": forest_cond,
                }
            )

        if sus_rows:
            gs_t = sum(r.get("total_growing_stock_m3_per_ha", 0) for r in _prod_ti_rows)
            mai_t = sum(r.get("mai_total_m3_per_ha", 0) for r in _prod_ti_rows)
            aah_t = sum(r.get("aah_total_m3_per_ha", 0) for r in _prod_ti_rows)
            si_t = round((aah_t / gs_t * 100), 2) if gs_t > 0 else 0
            hp_t = round((aah_t / mai_t * 100), 1) if mai_t > 0 else 0
            gs_t_per_ha = round(gs_t / total_area, 2) if total_area > 0 else 0
            sus_rows.append(
                {
                    "ब्लकको_नाम": "जम्मा",
                    "दिगोपन_सूचकांक_SI_प्रतिशत": si_t,
                    "कटान_दबाव_HP_प्रतिशत": hp_t,
                    "उत्पादनसिल_संचिती_प्रति_हे_घमी": gs_t_per_ha,
                    "MAI_प्रतिशत": round(mai_t / gs_t * 100, 1) if gs_t > 0 else 0,
                    "AAH_घमी_प्रति_वर्ष": round(aah_t, 2),
                    "पुनरोत्पादन_अवस्था": "—",
                    "वन_अवस्था": "—",
                }
            )
            result["ti_sustainability_table"] = sus_rows

    return result


# ── Sub-Areas Detail ──

_CATEGORY_NP = {
    "protected": "संरक्षित",
    "private_land": "निजी जग्गा",
    "plantation": "वृक्षरोपण",
    "pro_poor": "विपन्न",
    "religious": "धार्मिक",
    "biodiversity": "जैविक विविधता",
    "tourist": "पर्यटक",
    "office": "कार्यालय",
    "agroforestry": "कृषि वन",
    "tree_strata": "रूख स्तर",
    "water_hole": "पानीको मुहान",
    "wildlife_corridor": "वन्यजन्तु करिडोर",
}


# why: landcover_1984 computed from vector polygons (same source as the map);
# grouped + summed in SQL (one row per polygon before -> % kept only the last
# polygon of each class), areas via ::geography so no UTM guessing.
def _enrich_landcover_1984_from_polygons(
    db: Session, calculation_id, result_data: dict
) -> None:
    """Compute landcover_1984 percentages (canonical classes) from the 1984
    vector polygons, clipped to the forest boundary."""
    from sqlalchemy import text as sql_text
    from ...models.calculation import Calculation as CalcModel
    from ...core.landcover_1984 import normalize_lc1984

    calc = db.query(CalcModel).filter(CalcModel.id == calculation_id).first()
    if not calc or not calc.boundary_geom:
        return

    from geoalchemy2.shape import to_shape

    boundary_wkt = to_shape(calc.boundary_geom).wkt

    rows = db.execute(
        sql_text(
            """
        WITH b AS (SELECT ST_Transform(ST_GeomFromText(:wkt, 4326), 4326) AS g)
        SELECT lc.landuse_yr1984 AS lc_type,
               SUM(ST_Area(ST_Intersection(lc.geom, b.g)::geography)) AS m2
        FROM landcover.landcover_1984 lc, b
        WHERE ST_Intersects(lc.geom, b.g)
        GROUP BY lc.landuse_yr1984
    """
        ),
        {"wkt": boundary_wkt},
    ).fetchall()
    if not rows:
        return

    by_canon: dict[str, float] = {}
    for r in rows:
        canon = normalize_lc1984(r.lc_type)
        if canon and (r.m2 or 0) > 0:
            by_canon[canon] = by_canon.get(canon, 0.0) + float(r.m2)

    total = sum(by_canon.values())
    if total <= 0:
        return

    pct_dict = {
        c: round(v / total * 100.0, 2)
        for c, v in sorted(by_canon.items(), key=lambda kv: kv[1], reverse=True)
    }
    dominant = next(iter(pct_dict), None)

    result_data["landcover_1984_percentages"] = pct_dict
    result_data["landcover_1984_dominant"] = dominant
    result_data["landcover_1984_area_ha"] = {
        c: round(v / 10000.0, 3) for c, v in by_canon.items()
    }
    logger.info(
        "OP_COLLECT: landcover_1984 enriched from polygons — dominant=%s, classes=%d, area=%.1f ha",
        dominant,
        len(pct_dict),
        total / 10000.0,
    )


# business: CFMG — sub-areas detail table for excluded/included areas in OP document
def _fetch_sub_areas_detail(db: Session, calculation_id: str) -> List[Dict[str, Any]]:
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.result_data:
        return []
    rd = calc.result_data

    sub_areas = real_sub_areas(rd.get("sub_areas", []))  # the zones; strips have their own tables
    blocks = rd.get("blocks", [])
    block_map = {}
    for b in blocks:
        bid = b.get("block_id") or b.get("blockId")
        if bid:
            block_map[str(bid)] = b.get("block_name") or b.get("blockName") or ""

    result = []
    for sa in sub_areas:
        cat_np = _CATEGORY_NP.get(sa.get("category", ""), sa.get("category", ""))
        bid = sa.get("blockId") or sa.get("block_id")
        block_name = block_map.get(str(bid), "—") if bid else "—"
        status = (
            "बहिष्कृत" if sa.get("isExcluded", sa.get("is_excluded", False)) else "समावेश"
        )
        result.append(
            {
                "उपक्षेत्रको_नाम": sa.get("name", ""),
                "प्रकार": cat_np,
                "क्षेत्रफल_हे": sa.get("area_hectares", 0),
                "सम्बन्धित_ब्लक": block_name,
                "स्थिति": status,
            }
        )

    return result


# business: Table 5 format — block-wise land cover distribution per CFMG template
def _fetch_block_area_detail_merged(
    db: Session, calculation_id: str
) -> List[Dict[str, Any]]:
    from app.services.tree_cover_analysis import calculate_block_area_details

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.result_data:
        return []
    rd = calc.result_data
    # The unit set the analysis ran on (leaf view: FS-1a.10) - blocks OR compartments, whichever the forest uses.
    blocks = PolygonSource.for_result_data(rd).get_polygons()
    sub_areas = rd.get("sub_areas", [])  # calculate_block_area_details keeps the zones and the river bank (protection), drops fire lines
    if not blocks:
        return []

    details = calculate_block_area_details(db, blocks, sub_areas)

    result = []
    grand = {
        "total_area_ha": 0.0,
        "tree_cover_area_ha": 0.0,
        "other_landcover_area_ha": 0.0,
        "protected_area_ha": 0.0,
        "private_land_area_ha": 0.0,
        "effective_area_ha": 0.0,
        "official_area_ha": 0.0,
    }
    for d in details:
        excluded = (d["protected_area_ha"] or 0) + (d["private_land_area_ha"] or 0)
        official = d["official_area_ha"] or 0
        effective = d["effective_area_ha"] or 0
        result.append(
            {
                "ब्लकको_नाम": d["block_name"],
                "कुल_क्षेत्रफल_हे": round(d["total_area_ha"], 4),
                "रूखले_ढाकेको_हे": round(d["tree_cover_area_ha"], 4),
                "अन्यले_ढाकेको_हे": round(d["other_landcover_area_ha"], 4),
                "संरक्षित_क्षेत्र_हे": round(d["protected_area_ha"], 4),
                "निजि_आवादी_हे": round(d["private_land_area_ha"], 4),
                "बनश्रोत_अप्रभावित_क्षेत्र_हे": round(excluded, 4),
                "हस्तान्तरीत_क्षेत्रफल": round(official, 4),
                "वन_श्रोत_प्रभावित_क्षेत्रफल": round(effective, 4),
            }
        )
        for k in grand:
            grand[k] += d.get(k, 0) or 0

    g_excluded = grand["protected_area_ha"] + grand["private_land_area_ha"]
    result.append(
        {
            "ब्लकको_नाम": "जम्मा",
            "कुल_क्षेत्रफल_हे": round(grand["total_area_ha"], 4),
            "रूखले_ढाकेको_हे": round(grand["tree_cover_area_ha"], 4),
            "अन्यले_ढाकेको_हे": round(grand["other_landcover_area_ha"], 4),
            "संरक्षित_क्षेत्र_हे": round(grand["protected_area_ha"], 4),
            "निजि_आवादी_हे": round(grand["private_land_area_ha"], 4),
            "बनश्रोत_अप्रभावित_क्षेत्र_हे": round(g_excluded, 4),
            "हस्तान्तरीत_क्षेत्रफल": round(grand["official_area_ha"], 4),
            "वन_श्रोत_प्रभावित_क्षेत्रफल": round(grand["effective_area_ha"], 4),
        }
    )

    return result


# ─────────────────────────────────────────────────────────
# Compartment data (5 tables, 3-state logic)
# ─────────────────────────────────────────────────────────

# business: CFMG — Nepali DBH class ranges for compartment-level classification
_DBH_CLASS_RANGES: List[tuple] = [
    ("१०-२० से.मी.", 10, 20),
    ("२०-३० से.मी.", 20, 30),
    ("३०-४० से.मी.", 30, 40),
    ("४०-५० से.मी.", 40, 50),
    ("५०-६० से.मी.", 50, 60),
    (">६० से.मी.", 60, 999),
]


def _classify_dbh_np(dia_cm: Optional[float]) -> Optional[str]:
    if dia_cm is None:
        return None
    for label, lo, hi in _DBH_CLASS_RANGES:
        if lo <= dia_cm < hi:
            return label
    return ">६० से.मी."


# business: CFMG §X.Y — compartment data for OP section 5
# NOTE: 3-state logic — (A) no compartments, (B) compartments/no trees, (C) full data with spatial tree-to-compartment assignment
def _fetch_compartment_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    from app.models.forest_block import ForestBlock
    from app.models.inventory import InventoryTree, InventoryCalculation
    from sqlalchemy import func as sa_func
    from collections import defaultdict

    cid = str(calculation_id)
    _N = "\u2014"  # em-dash for null cells

    # ── Step 1: Fetch all compartments/sub-compartments ──
    compartments = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == cid, ForestBlock.is_compartment == True)
        .order_by(
            ForestBlock.parent_block_id,
            ForestBlock.division_level,
            ForestBlock.display_order,
        )
        .all()
    )

    if not compartments:
        return {
            "compartment_message": "यस सामुदायिक वनमा कुनै पनि कम्पाृ्टमेन्ट "
            "वा सव कम्पाृ्टमेन्ट तयार गरिएको छैन",
            "compartment_summary": [],
            "compartment_detail": [],
            "compartment_species_composition": [],
            "compartment_area_breakdown": [],
            "compartment_dbh_distribution": [],
        }

    # Parent block name map
    parent_ids = [str(c.parent_block_id) for c in compartments if c.parent_block_id]
    parent_blocks = {}
    if parent_ids:
        from uuid import UUID

        for pb in (
            db.query(ForestBlock)
            .filter(ForestBlock.id.in_([UUID(p) for p in set(parent_ids)]))
            .all()
        ):
            parent_blocks[str(pb.id)] = pb.name

    # business: CFMG — 3-state compartment logic: (A) no compartments, (B) compartments no trees, (C) full data
    tree_count = (
        db.query(sa_func.count(InventoryTree.id))
        .select_from(InventoryTree)
        .join(
            InventoryCalculation,
            InventoryTree.inventory_calculation_id == InventoryCalculation.id,
        )
        .filter(InventoryCalculation.calculation_id == cid)
        .scalar()
        or 0
    )

    # ── Helper: build State B rows (identity + area only) ──
    def _state_b_rows():
        bgroup: Dict[str, dict] = {}
        for c in compartments:
            pid = str(c.parent_block_id) if c.parent_block_id else ""
            if pid not in bgroup:
                bgroup[pid] = {
                    "name": parent_blocks.get(pid, pid),
                    "comp": 0,
                    "sub": 0,
                    "area": 0.0,
                }
            bg = bgroup[pid]
            if c.division_level == DEPTH_TOP_COMPARTMENT:
                bg["comp"] += 1
            else:
                bg["sub"] += 1
            bg["area"] += c.area_hectares or 0

        summary = []
        for pid in sorted(bgroup):
            bg = bgroup[pid]
            summary.append(
                {
                    "ब्लकको_नाम": bg["name"],
                    "कम्पार्टमेन्ट_संख्या": bg["comp"],
                    "उपकम्पार्टमेन्ट_संख्या": bg["sub"],
                    "कम्पार्टमेन्ट_क्षेत्रफल_हे": round(bg["area"], 4),
                    "जम्मा_रूख_संख्या": _N,
                    "जम्मा_काठ_मात्रा_m3": _N,
                    "जम्मा_दाउरा_मात्रा_m3": _N,
                }
            )
        if len(summary) > 1:
            summary.append(
                {
                    "ब्लकको_नाम": "जम्मा",
                    "कम्पार्टमेन्ट_संख्या": sum(r["कम्पार्टमेन्ट_संख्या"] for r in summary),
                    "उपकम्पार्टमेन्ट_संख्या": sum(r["उपकम्पार्टमेन्ट_संख्या"] for r in summary),
                    "कम्पार्टमेन्ट_क्षेत्रफल_हे": round(
                        sum(r["कम्पार्टमेन्ट_क्षेत्रफल_हे"] for r in summary), 4
                    ),
                    "जम्मा_रूख_संख्या": _N,
                    "जम्मा_काठ_मात्रा_m3": _N,
                    "जम्मा_दाउरा_मात्रा_m3": _N,
                }
            )

        detail = []
        for c in compartments:
            pid = str(c.parent_block_id) if c.parent_block_id else ""
            detail.append(
                {
                    "ब्लकको_नाम": parent_blocks.get(pid, ""),
                    "कोड": c.compartment_code or "",
                    "नाम": c.name,
                    "स्तर": "कम्पार्टमेन्ट" if c.division_level == DEPTH_TOP_COMPARTMENT else "उप-कम्पार्टमेन्ट",
                    "क्षेत्रफल_हे": round(c.area_hectares or 0, 4),
                    "रूख_संख्या": _N,
                    "काठ_मात्रा_m3": _N,
                    "दाउरा_मात्रा_m3": _N,
                    "स्थिति": "लक" if c.is_locked else "खुला",
                }
            )

        comp_only = [c for c in compartments if c.division_level == DEPTH_TOP_COMPARTMENT]
        area_breakdown = []
        for c in comp_only:
            pid = str(c.parent_block_id) if c.parent_block_id else ""
            children = [
                sc for sc in compartments if str(sc.parent_block_id) == str(c.id)
            ]
            cnames = ", ".join(sc.name for sc in children)
            area_breakdown.append(
                {
                    "ब्लकको_नाम": parent_blocks.get(pid, ""),
                    "कम्पार्टमेन्ट": c.name,
                    "क्षेत्रफल_हे": round(c.area_hectares or 0, 4),
                    "उप_कम्पार्टमेन्ट_संख्या": len(children),
                    "उप_कम्पार्टमेन्टहरू": cnames if cnames else _N,
                }
            )

        return summary, detail, area_breakdown

    if tree_count == 0:
        s, d, a = _state_b_rows()
        return {
            "compartment_message": "",
            "compartment_summary": s,
            "compartment_detail": d,
            "compartment_species_composition": [],
            "compartment_area_breakdown": a,
            "compartment_dbh_distribution": [],
        }

    # ── State C: full data with spatial tree-to-compartment assignment ──
    sql = text(
        """
        WITH tree_comp AS (
            SELECT DISTINCT ON (t.id)
                t.id,
                t.species,
                t.local_name,
                t.stem_volume,
                t.branch_volume,
                t.dia_cm,
                t.block_id,
                comp.id AS compartment_id,
                comp.name AS compartment_name,
                comp.compartment_code,
                comp.division_level,
                comp.parent_block_id
            FROM inventory_trees t
            JOIN inventory_calculations ic ON t.inventory_calculation_id = ic.id
            LEFT JOIN forest_blocks comp ON
                comp.calculation_id = ic.calculation_id
                AND comp.is_compartment = TRUE
                AND ST_Within(t.location::geometry, comp.geometry)
            WHERE ic.calculation_id = :calc_id
            ORDER BY t.id, comp.division_level DESC NULLS LAST
        )
        SELECT
            tc.*,
            parent.name AS parent_block_name
        FROM tree_comp tc
        LEFT JOIN forest_blocks parent ON tc.parent_block_id = parent.id
    """
    )
    rows = db.execute(sql, {"calc_id": cid}).fetchall()

    # Group trees by compartment_id
    comp_trees: Dict[str, list] = defaultdict(list)
    unassigned: list = []
    for r in rows:
        d = {
            "species": r.species,
            "local_name": r.local_name or "",
            # H6.2: Numeric as of migration 060, so these arrive as Decimal.
            # Every other consumer in this file already wraps them in float();
            # these three were the exceptions.
            "stem_volume": float(r.stem_volume or 0),
            "branch_volume": float(r.branch_volume or 0),
            "dia_cm": float(r.dia_cm) if r.dia_cm is not None else None,
        }
        ccid = str(r.compartment_id) if r.compartment_id else None
        if ccid:
            comp_trees[ccid].append(d)
        else:
            unassigned.append(d)

    # ── Summary: group compartments by parent block ──
    bgroup: Dict[str, dict] = {}
    for c in compartments:
        pid = str(c.parent_block_id) if c.parent_block_id else ""
        if pid not in bgroup:
            bgroup[pid] = {
                "name": parent_blocks.get(pid, pid),
                "comp": 0,
                "sub": 0,
                "area": 0.0,
                "trees": 0,
                "timber": 0.0,
                "fuelwood": 0.0,
            }
        bg = bgroup[pid]
        if c.division_level == DEPTH_TOP_COMPARTMENT:
            bg["comp"] += 1
        else:
            bg["sub"] += 1
        bg["area"] += c.area_hectares or 0
        for t in comp_trees.get(str(c.id), []):
            bg["trees"] += 1
            bg["timber"] += t["stem_volume"]
            bg["fuelwood"] += t["branch_volume"]

    summary = []
    for pid in sorted(bgroup):
        bg = bgroup[pid]
        summary.append(
            {
                "ब्लकको_नाम": bg["name"],
                "कम्पार्टमेन्ट_संख्या": bg["comp"],
                "उपकम्पार्टमेन्ट_संख्या": bg["sub"],
                "कम्पार्टमेन्ट_क्षेत्रफल_हे": round(bg["area"], 4),
                "जम्मा_रूख_संख्या": bg["trees"],
                "जम्मा_काठ_मात्रा_m3": round(bg["timber"], 4),
                "जम्मा_दाउरा_मात्रा_m3": round(bg["fuelwood"], 4),
            }
        )
    if unassigned:
        ut = unassigned
        summary.append(
            {
                "ब्लकको_नाम": "कम्पार्टमेन्ट बाहिर",
                "कम्पार्टमेन्ट_संख्या": _N,
                "उपकम्पार्टमेन्ट_संख्या": _N,
                "कम्पार्टमेन्ट_क्षेत्रफल_हे": _N,
                "जम्मा_रूख_संख्या": len(ut),
                "जम्मा_काठ_मात्रा_m3": round(sum(t["stem_volume"] for t in ut), 4),
                "जम्मा_दाउरा_मात्रा_m3": round(sum(t["branch_volume"] for t in ut), 4),
            }
        )
    if len(summary) > 1:
        total_trees = sum(
            r["जम्मा_रूख_संख्या"]
            for r in summary
            if isinstance(r["जम्मा_रूख_संख्या"], (int, float))
        )
        total_timber = sum(
            r["जम्मा_काठ_मात्रा_m3"]
            for r in summary
            if isinstance(r["जम्मा_काठ_मात्रा_m3"], (int, float))
        )
        total_fuelwood = sum(
            r["जम्मा_दाउरा_मात्रा_m3"]
            for r in summary
            if isinstance(r["जम्मा_दाउरा_मात्रा_m3"], (int, float))
        )
        total_comp = sum(
            r["कम्पार्टमेन्ट_संख्या"] for r in summary if isinstance(r["कम्पार्टमेन्ट_संख्या"], int)
        )
        total_sub = sum(
            r["उपकम्पार्टमेन्ट_संख्या"]
            for r in summary
            if isinstance(r["उपकम्पार्टमेन्ट_संख्या"], int)
        )
        total_area = sum(
            r["कम्पार्टमेन्ट_क्षेत्रफल_हे"]
            for r in summary
            if isinstance(r["कम्पार्टमेन्ट_क्षेत्रफल_हे"], (int, float))
        )
        summary.insert(
            0,
            {
                "ब्लकको_नाम": "जम्मा",
                "कम्पार्टमेन्ट_संख्या": total_comp,
                "उपकम्पार्टमेन्ट_संख्या": total_sub,
                "कम्पार्टमेन्ट_क्षेत्रफल_हे": round(total_area, 4),
                "जम्मा_रूख_संख्या": total_trees,
                "जम्मा_काठ_मात्रा_m3": round(total_timber, 4),
                "जम्मा_दाउरा_मात्रा_m3": round(total_fuelwood, 4),
            },
        )

    # ── Detail: one row per compartment ──
    detail = []
    for c in compartments:
        pid = str(c.parent_block_id) if c.parent_block_id else ""
        ct = comp_trees.get(str(c.id), [])
        detail.append(
            {
                "ब्लकको_नाम": parent_blocks.get(pid, ""),
                "कोड": c.compartment_code or "",
                "नाम": c.name,
                "स्तर": "कम्पार्टमेन्ट" if c.division_level == DEPTH_TOP_COMPARTMENT else "उप-कम्पार्टमेन्ट",
                "क्षेत्रफल_हे": round(c.area_hectares or 0, 4),
                "रूख_संख्या": len(ct),
                "काठ_मात्रा_m3": round(sum(t["stem_volume"] for t in ct), 4),
                "दाउरा_मात्रा_m3": round(sum(t["branch_volume"] for t in ct), 4),
                "स्थिति": "लक" if c.is_locked else "खुला",
            }
        )
    if unassigned:
        detail.append(
            {
                "ब्लकको_नाम": "",
                "कोड": "",
                "नाम": "कम्पार्टमेन्ट बाहिर",
                "स्तर": _N,
                "क्षेत्रफल_हे": _N,
                "रूख_संख्या": len(unassigned),
                "काठ_मात्रा_m3": round(sum(t["stem_volume"] for t in unassigned), 4),
                "दाउरा_मात्रा_m3": round(sum(t["branch_volume"] for t in unassigned), 4),
                "स्थिति": _N,
            }
        )

    # ── Species composition ──
    sp_data = defaultdict(lambda: {"count": 0, "timber": 0.0, "fuelwood": 0.0})
    for ccid, trees in comp_trees.items():
        comp_obj = next((c for c in compartments if str(c.id) == ccid), None)
        cname = comp_obj.name if comp_obj else ccid
        pid = (
            str(comp_obj.parent_block_id)
            if comp_obj and comp_obj.parent_block_id
            else ""
        )
        bname = parent_blocks.get(pid, "")
        for t in trees:
            key = (bname, cname, t["species"], t["local_name"])
            sp_data[key]["count"] += 1
            sp_data[key]["timber"] += t["stem_volume"]
            sp_data[key]["fuelwood"] += t["branch_volume"]
    for t in unassigned:
        key = ("", "कम्पार्टमेन्ट बाहिर", t["species"], t["local_name"])
        sp_data[key]["count"] += 1
        sp_data[key]["timber"] += t["stem_volume"]
        sp_data[key]["fuelwood"] += t["branch_volume"]

    species_rows = []
    for (bname, cname, sci, loc), sd in sorted(sp_data.items()):
        species_rows.append(
            {
                "ब्लकको_नाम": bname,
                "कम्पार्टमेन्ट": cname,
                "प्रजाति_वैज्ञानिक": sci,
                "प्रजाति_स्थानीय": loc or _N,
                "रूख_संख्या": sd["count"],
                "काठ_मात्रा_m3": round(sd["timber"], 4),
                "दाउरा_मात्रा_m3": round(sd["fuelwood"], 4),
                "जम्मा_मात्रा_m3": round(sd["timber"] + sd["fuelwood"], 4),
            }
        )

    # ── DBH class distribution ──
    dbh_data = defaultdict(lambda: {"count": 0, "timber": 0.0, "fuelwood": 0.0})
    for ccid, trees in comp_trees.items():
        comp_obj = next((c for c in compartments if str(c.id) == ccid), None)
        cname = comp_obj.name if comp_obj else ccid
        pid = (
            str(comp_obj.parent_block_id)
            if comp_obj and comp_obj.parent_block_id
            else ""
        )
        bname = parent_blocks.get(pid, "")
        for t in trees:
            dlabel = _classify_dbh_np(t.get("dia_cm"))
            if dlabel:
                key = (bname, cname, dlabel)
                dbh_data[key]["count"] += 1
                dbh_data[key]["timber"] += t["stem_volume"]
                dbh_data[key]["fuelwood"] += t["branch_volume"]
    for t in unassigned:
        dlabel = _classify_dbh_np(t.get("dia_cm"))
        if dlabel:
            key = ("", "कम्पार्टमेन्ट बाहिर", dlabel)
            dbh_data[key]["count"] += 1
            dbh_data[key]["timber"] += t["stem_volume"]
            dbh_data[key]["fuelwood"] += t["branch_volume"]

    dbh_rows = []
    for (bname, cname, dlabel), dd in sorted(dbh_data.items()):
        dbh_rows.append(
            {
                "ब्लकको_नाम": bname,
                "कम्पार्टमेन्ट": cname,
                "डीबीएच_वर्ग": dlabel,
                "रूख_संख्या": dd["count"],
                "काठ_मात्रा_m3": round(dd["timber"], 4),
                "दाउरा_मात्रा_m3": round(dd["fuelwood"], 4),
            }
        )

    # ── Area breakdown ──
    comp_only = [c for c in compartments if c.division_level == DEPTH_TOP_COMPARTMENT]
    area_breakdown = []
    for c in comp_only:
        pid = str(c.parent_block_id) if c.parent_block_id else ""
        children = [sc for sc in compartments if str(sc.parent_block_id) == str(c.id)]
        cnames = ", ".join(sc.name for sc in children)
        area_breakdown.append(
            {
                "ब्लकको_नाम": parent_blocks.get(pid, ""),
                "कम्पार्टमेन्ट": c.name,
                "क्षेत्रफल_हे": round(c.area_hectares or 0, 4),
                "उप_कम्पार्टमेन्ट_संख्या": len(children),
                "उप_कम्पार्टमेन्टहरू": cnames if cnames else _N,
            }
        )

    return {
        "compartment_message": "",
        "compartment_summary": summary,
        "compartment_detail": detail,
        "compartment_species_composition": species_rows,
        "compartment_area_breakdown": area_breakdown,
        "compartment_dbh_distribution": dbh_rows,
    }


# business: CFMG §X.Y — yearly activity plan for OP section 6
def _collect_yearly_activities_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Collect 10-year plan data from yearly activities for OP document consumption.

    Returns structured dicts for year-wise summaries, activity×year matrix,
    program-wise breakdown, and chart data.
    """
    activities = (
        db.query(ProposedYearlyActivity)
        .filter(ProposedYearlyActivity.calculation_id == calculation_id)
        .all()
    )

    if not activities:
        return {"available": False}

    # Pre-fetch all PotentialActivity for name/program/unit lookups
    potential_ids = list(set(a.potential_activity_id for a in activities))
    potential_map = {}
    if potential_ids:
        for pa in (
            db.query(PotentialActivity)
            .filter(PotentialActivity.id.in_(potential_ids))
            .all()
        ):
            potential_map[pa.id] = pa

    # Pre-fetch all year details for all activities
    activity_ids = [a.id for a in activities]
    year_details = (
        db.query(ActivityYearDetail)
        .filter(ActivityYearDetail.proposed_activity_id.in_(activity_ids))
        .order_by(
            ActivityYearDetail.proposed_activity_id, ActivityYearDetail.year_number
        )
        .all()
    )

    # Index year details by proposed_activity_id
    yd_by_activity: Dict[UUID, Dict[int, ActivityYearDetail]] = {}
    for yd in year_details:
        pid = yd.proposed_activity_id
        if pid not in yd_by_activity:
            yd_by_activity[pid] = {}
        yd_by_activity[pid][yd.year_number] = yd

    plan_years = list(range(1, 11))

    # ── (A) ya_year_summary: one row per year ──
    year_summary = []
    cumulative_budget = 0.0
    for y in plan_years:
        year_count = 0
        year_qty = 0.0
        year_budget = 0.0
        for act in activities:
            yd = yd_by_activity.get(act.id, {}).get(y)
            qty = (
                float(yd.quantity)
                if yd and yd.quantity is not None
                else float(act.default_quantity or 0)
            )
            bgt = (
                float(yd.yearly_budget)
                if yd and yd.yearly_budget is not None
                else float(act.default_yearly_budget or 0)
            )
            if bgt > 0 or qty > 0:
                year_count += 1
            year_qty += qty
            year_budget += bgt
        cumulative_budget += year_budget
        year_summary.append(
            {
                "year": y,
                "activity_count": year_count,
                "total_quantity": round(year_qty, 2),
                "total_budget": round(year_budget, 2),
                "cumulative_budget": round(cumulative_budget, 2),
            }
        )

    # ── (B) ya_plan_matrix: one row per activity, columns per year ──
    plan_matrix = []
    for act in activities:
        pa = potential_map.get(act.potential_activity_id)
        row = {
            "activity_name": (
                pa.activities if pa else f"Activity {act.potential_activity_id}"
            ),
            "program": pa.progarms if pa else "",
            "unit": pa.unit if pa else "",
        }
        total_qty = 0.0
        total_bgt = 0.0
        for y in plan_years:
            yd = yd_by_activity.get(act.id, {}).get(y)
            qty = (
                float(yd.quantity)
                if yd and yd.quantity is not None
                else float(act.default_quantity or 0)
            )
            bgt = (
                float(yd.yearly_budget)
                if yd and yd.yearly_budget is not None
                else float(act.default_yearly_budget or 0)
            )
            row[f"year_{y}_qty"] = round(qty, 2)
            row[f"year_{y}_budget"] = round(bgt, 2)
            total_qty += qty
            total_bgt += bgt
        row["total_quantity"] = round(total_qty, 2)
        row["total_budget"] = round(total_bgt, 2)
        plan_matrix.append(row)

    # ── (C) ya_program_budget: grouped by program ──
    program_data: Dict[str, Dict] = {}
    for act in activities:
        pa = potential_map.get(act.potential_activity_id)
        prog = pa.progarms if pa else "Other"
        if prog not in program_data:
            program_data[prog] = {f"year_{y}_budget": 0.0 for y in plan_years}
            program_data[prog]["activity_count"] = 0
            program_data[prog]["total_budget"] = 0.0
        program_data[prog]["activity_count"] += 1
        for y in plan_years:
            yd = yd_by_activity.get(act.id, {}).get(y)
            bgt = (
                float(yd.yearly_budget)
                if yd and yd.yearly_budget is not None
                else float(act.default_yearly_budget or 0)
            )
            program_data[prog][f"year_{y}_budget"] += bgt
            program_data[prog]["total_budget"] += bgt
    program_budget = []
    for prog_name, pd in sorted(program_data.items()):
        row = {"program": prog_name}
        row.update(pd)
        row["total_budget"] = round(row["total_budget"], 2)
        for y in plan_years:
            row[f"year_{y}_budget"] = round(row[f"year_{y}_budget"], 2)
        program_budget.append(row)

    # ── (D) ya_total_budget_by_year: dict year→budget ──
    # keyed by the row's OWN year: this used `y` — the stale variable of the loop above, always 10 — so the dict held
    # one entry (year 10) instead of ten, in every plan document
    total_budget_by_year = {
        str(ys["year"]): round(ys["total_budget"], 2) for ys in year_summary
    }

    # ── (E) ya_total_ten_year_budget ──
    total_ten_year_budget = round(sum(ys["total_budget"] for ys in year_summary), 2)

    # ── (F) ya_program_pie_data: {program: total_budget} ──
    program_pie_data = {pb["program"]: pb["total_budget"] for pb in program_budget}

    # ── (G) ya_budget_year_trend: {year: budget} ──
    budget_year_trend = {str(ys["year"]): ys["total_budget"] for ys in year_summary}

    # ── (H) ya_activity_plan_detail: one row per activity matching CSV export ──
    sa_all = (
        db.query(ActivitySpatialAssignment)
        .filter(ActivitySpatialAssignment.proposed_activity_id.in_(activity_ids))
        .all()
    )
    df_all = (
        db.query(ActivityDrawnFeature)
        .filter(ActivityDrawnFeature.proposed_activity_id.in_(activity_ids))
        .all()
    )

    block_ids = set()
    for sa in sa_all:
        if sa.block_id:
            block_ids.add(sa.block_id)
    block_map: Dict[str, str] = {}
    if block_ids:
        for b in (
            db.query(ForestBlock).filter(ForestBlock.id.in_(list(block_ids))).all()
        ):
            block_map[str(b.id)] = b.name

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    sub_area_names: Dict[str, str] = {}
    if calc and calc.result_data and calc.result_data.get("sub_areas"):
        for sa_entry in calc.result_data["sub_areas"]:
            sa_id = str(sa_entry.get("id", ""))
            sa_name = sa_entry.get("name", "") or ""
            sub_area_names[sa_id] = sa_name

    sa_by_activity: Dict[UUID, list] = {}
    for sa in sa_all:
        sa_by_activity.setdefault(sa.proposed_activity_id, []).append(sa)
    df_by_activity: Dict[UUID, list] = {}
    for df in df_all:
        df_by_activity.setdefault(df.proposed_activity_id, []).append(df)

    activity_plan_detail = []
    for idx, act in enumerate(activities, start=1):
        pa = potential_map.get(act.potential_activity_id)
        activity_name = pa.activities if pa else f"Activity {act.potential_activity_id}"
        program_name = pa.progarms if pa else ""
        unit_name = pa.unit if pa else ""

        qty_parts: list[str] = []
        bgt_parts: list[str] = []
        total_bgt = 0.0
        for y in plan_years:
            yd = yd_by_activity.get(act.id, {}).get(y)
            qty = (
                float(yd.quantity)
                if yd and yd.quantity is not None
                else float(act.default_quantity or 0)
            )
            bgt = (
                float(yd.yearly_budget)
                if yd and yd.yearly_budget is not None
                else float(act.default_yearly_budget or 0)
            )
            if qty > 0:
                qty_parts.append(f"Y{y}:{qty:g}")
            if bgt > 0:
                bgt_parts.append(f"Y{y}:{bgt:g}")
            total_bgt += bgt

        assignments = sa_by_activity.get(act.id, [])
        if act.assign_to_all_blocks or any(
            s.assignment_type == "all_blocks" for s in assignments
        ):
            location_type = "all"
            location_details = "All Blocks"
        elif assignments:
            loc_names: list[str] = []
            has_block = False
            has_sub_area = False
            for s in assignments:
                if s.assignment_type == "block" and s.block_id:
                    has_block = True
                    loc_names.append(block_map.get(str(s.block_id), str(s.block_id)))
                elif s.assignment_type == "sub_area":
                    has_sub_area = True
                    nm = block_map.get(str(s.block_id), "")
                    if s.sub_area_id:
                        san = sub_area_names.get(str(s.sub_area_id), "")
                        if san:
                            nm = f"{nm} > {san}" if nm else san
                    loc_names.append(nm or str(s.sub_area_id))
            location_type = (
                "blocks" if has_block else "sub_areas" if has_sub_area else "none"
            )
            location_details = (
                ", ".join(loc_names) if loc_names else "No specific location"
            )
        else:
            location_type = "none"
            location_details = "No specific location"

        drawn_features_list = df_by_activity.get(act.id, [])
        feature_names = []
        for df in drawn_features_list:
            fn = (df.properties or {}).get("name", "") or (df.properties or {}).get(
                "label", ""
            )
            if fn:
                feature_names.append(fn)
        spatial_features = ", ".join(feature_names) if feature_names else "None"

        activity_plan_detail.append(
            {
                "s_no": idx,
                "activity": activity_name,
                "program": program_name,
                "unit": unit_name,
                "quantity_years": ", ".join(qty_parts) if qty_parts else "None",
                "budget_years": ", ".join(bgt_parts) if bgt_parts else "None",
                "total_budget": round(total_bgt, 2),
                "location_type": location_type,
                "location_details": location_details,
                "spatial_features": spatial_features,
            }
        )

    return {
        "available": True,
        "year_summary": year_summary,
        "plan_matrix": plan_matrix,
        "program_budget": program_budget,
        "total_budget_by_year": total_budget_by_year,
        "total_ten_year_budget": total_ten_year_budget,
        "program_pie_data": program_pie_data,
        "budget_year_trend": budget_year_trend,
        "activity_plan_detail": activity_plan_detail,
    }


# business: CFMG — sampling point locations for OP map appendix
# why: cached points_data preferred; fallback computes on-the-fly from WKT geometry
def _fetch_sampling_point_locations(
    db: Session, calculation_id: str
) -> List[Dict[str, Any]]:
    """Build per-point location table from sampling design data.

    Returns a list of dicts with Nepali keys as table headers.
    Uses cached points_data (from API) when available, falls back to on-the-fly.
    """
    from app.models.sampling import SamplingDesign
    from app.utils.number_format import format_devanagari, _ARABIC_TO_DEV
    from shapely import wkt as shapely_wkt

    designs = (
        db.query(SamplingDesign)
        .filter(
            SamplingDesign.calculation_id == calculation_id,
            SamplingDesign.points_geometry.isnot(None),
        )
        .all()
    )

    if not designs:
        return []

    design = designs[0]
    cached = design.points_data or {}
    cached_points = cached.get("points") if isinstance(cached, dict) else None

    # Use cached points_data when available (includes topographic context)
    if cached_points:
        from app.utils.geospatial import extract_elevation_at_point

        points_list = []
        for pt in cached_points:
            lon = pt.get("longitude")
            lat = pt.get("latitude")
            elevation_m = pt.get("elevation_m")
            topo_ctx = (
                pt.get("topographic_context") or pt.get("nearest_feature_name") or ""
            )
            dist = pt.get("distance_from_boundary")

            if lon is None or lat is None:
                continue

            lon_str = f"{lon:.7f}".translate(_ARABIC_TO_DEV)
            lat_str = f"{lat:.7f}".translate(_ARABIC_TO_DEV)
            elev_str = format_devanagari(int(elevation_m), 0) if elevation_m else "-"
            dist_str = format_devanagari(round(dist, 2), 2) if dist else "-"

            points_list.append(
                {
                    "नमुना_प्लट_नं": pt.get("plot_number", ""),
                    "ब्लकको_नाम": pt.get("block_name", ""),
                    "क्षेत्रको_किसिम": pt.get("zone_type", "productive"),
                    "देशान्तर": lon_str,
                    "अक्षांश": lat_str,
                    "उचाइ_मि": elev_str,
                    "ईपिएसजी_कोड": "EPSG:4326",
                    "नजिकको_प्राकृतिक_चिन्ह": topo_ctx,
                    "वन_सिमाना_देखिको_दुरी_मि": dist_str,
                }
            )
        return points_list

    # Fallback: compute from scratch
    from app.utils.geospatial import extract_elevation_at_point

    block_assignment = design.points_block_assignment or []

    result = db.execute(
        text(
            "SELECT ST_AsText(points_geometry) FROM public.sampling_designs WHERE id = :id"
        ),
        {"id": str(design.id)},
    ).first()
    if not result or not result[0]:
        return []

    multipoint = shapely_wkt.loads(result[0])

    from app.models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    boundary_wkt = None
    if calc:
        br = db.execute(
            text(
                "SELECT ST_AsText(boundary_geom) FROM public.calculations WHERE id = :id"
            ),
            {"id": calculation_id},
        ).first()
        if br:
            boundary_wkt = br[0]

    points_list = []
    for i, point in enumerate(multipoint.geoms):
        lon, lat = point.x, point.y

        block_info = next(
            (b for b in block_assignment if b.get("point_index") == i), None
        )
        block_name = (block_info or {}).get("block_name", "")
        zone_type = (block_info or {}).get("zone_type", "productive")

        elevation_m = extract_elevation_at_point(db, lon, lat)

        distance = None
        if boundary_wkt:
            try:
                boundary_geom = shapely_wkt.loads(boundary_wkt)
                distance = (
                    point.distance(boundary_geom.boundary) * METERS_PER_DEGREE_LAT
                )
            except Exception:
                logger.warning(
                    "distance-from-boundary unavailable - the field is left empty "
                    "for this point",
                    exc_info=True,
                )

        lon_str = f"{lon:.7f}".translate(_ARABIC_TO_DEV)
        lat_str = f"{lat:.7f}".translate(_ARABIC_TO_DEV)
        elev_str = format_devanagari(int(elevation_m), 0) if elevation_m else "-"
        dist_str = format_devanagari(round(distance, 2), 2) if distance else "-"

        points_list.append(
            {
                "नमुना_प्लट_नं": i + 1,
                "ब्लकको_नाम": block_name,
                "क्षेत्रको_किसिम": zone_type,
                "देशान्तर": lon_str,
                "अक्षांश": lat_str,
                "उचाइ_मि": elev_str,
                "ईपिएसजी_कोड": "EPSG:4326",
                "नजिकको_प्राकृतिक_चिन्ह": "",
                "वन_सिमाना_देखिको_दुरी_मि": dist_str,
            }
        )

    return points_list


# business: CFMG — fieldbook boundary traverse data for OP boundary section
def _fetch_fieldbook_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    from app.utils.number_format import format_devanagari as _fmt_d

    points = (
        db.query(Fieldbook)
        .filter(Fieldbook.calculation_id == calculation_id)
        .order_by(Fieldbook.point_number)
        .all()
    )

    if not points:
        return {"available": False, "total_points": 0}

    vertex_count = sum(1 for p in points if p.point_type == "vertex")
    interp_count = sum(1 for p in points if p.point_type == "interpolated")
    total = len(points)
    # The outer boundary length. Field books made before outer/internal existed have no class: fall back to
    # the old sum over the whole run.
    outer_pts = [p for p in points if p.boundary_class == "outer"]
    perimeter = (
        sum(float(p.distance_to_next or 0) for p in outer_pts)
        if outer_pts
        else sum(float(p.distance_to_next or 0) for p in points[:-1])
    )

    elev_vals = [float(p.elevation) for p in points if p.elevation is not None]
    avg_el = sum(elev_vals) / len(elev_vals) if elev_vals else None
    min_el = min(elev_vals) if elev_vals else None
    max_el = max(elev_vals) if elev_vals else None

    # Per-block summary
    block_map: Dict[str, dict] = {}
    for p in points:
        bn = p.block_name or "Unknown"
        if bn not in block_map:
            block_map[bn] = {
                "block_name": bn,
                "vertex": 0,
                "interpolated": 0,
                "total": 0,
                "perimeter_m": 0.0,
            }
        block_map[bn]["total"] += 1
        block_map[bn][p.point_type] = block_map[bn].get(p.point_type, 0) + 1
    # Compute per-block perimeter
    for i, p in enumerate(points[:-1]):
        bn = p.block_name or "Unknown"
        if bn in block_map:
            block_map[bn]["perimeter_m"] += float(p.distance_to_next or 0)
    block_rows = []
    for bn in sorted(block_map.keys()):
        b = block_map[bn]
        block_rows.append(
            {
                "ब्लकको_नाम": b["block_name"],
                "मुख्य_बिन्दु": b["vertex"],
                "अन्तरसम्मिलित": b["interpolated"],
                "जम्मा_बिन्दु": b["total"],
                "परिधि_मि": round(b["perimeter_m"], 2),
            }
        )

    # Per-point table with Nepali keys. Every value comes from the same canonical row the CSV / Excel / GeoJSON / GPX use
    # (services/fieldbook_record.py), so this printable table cannot disagree with them; it is the subset that fits a
    # page (no UTM / nearest-feature / verified columns), in Devanagari digits, with measurements to one decimal.
    from app.services.fieldbook_record import point_record
    from app.utils.number_format import _ARABIC_TO_DEV as _to_dev

    point_rows = []
    for p in points:
        rec = point_record(p)
        sub_area_str = "-"
        if rec["sub_area"]:
            sub_area_str = f"{rec['sub_area']} ({rec['sub_area_category']})" if rec["sub_area_category"] else rec["sub_area"]
        point_rows.append(
            {
                "बिन्दु_नं": rec["point"],
                "प्रकार": "V" if rec["type"] == "vertex" else "I",
                # one statement of what the point is and which units it separates (outer: A, B / internal: A, B)
                "कैफियत": rec["remarks"] or "",
                "उप-क्षेत्र": sub_area_str,
                "देशान्तर": f"{rec['longitude']:.7f}".translate(_to_dev),
                "अक्षांश": f"{rec['latitude']:.7f}".translate(_to_dev),
                "CRS": "EPSG:4326",
                "उचाइ_मि": _fmt_d(int(rec["elevation"]), 0) if rec["elevation"] is not None else "-",
                "अजिमुथ": f"{rec['azimuth']:.1f}" if rec["azimuth"] is not None else "-",
                "दुरी_मि": f"{rec['distance']:.1f}" if rec["distance"] is not None else "-",
            }
        )

    result = {
        "available": True,
        "total_points": total,
        "vertex_count": vertex_count,
        "interpolated_count": interp_count,
        "perimeter_m": round(perimeter, 2),
        "avg_elevation_m": round(avg_el, 1) if avg_el else None,
        "min_elevation_m": round(min_el, 1) if min_el else None,
        "max_elevation_m": round(max_el, 1) if max_el else None,
        "points": point_rows,
        "block_summary": block_rows,
    }
    return result


# ---- Dimension-mode-aware key injection ----
# After all section data is collected, we add mode-specific Nepali keys
# ("कम्पार्टमेन्टको नाम") alongside backward-compatible ("ब्लकको_नाम") keys.
# This avoids 65+ individual dict literal changes across this file.


def _add_dimension_section(result: dict, calc_uuid: UUID, db: Session) -> None:
    """Add 'dimension' section with mode-aware label variables.

    Call this before cache write so {{unit_label_np}} etc. resolve.
    """
    dim = get_forest_dimension(db, calc_uuid)
    result["dimension"] = {
        "unit_label_np": dimension_label(dim, nepali=True),
        "unit_label_en": dimension_label(dim, nepali=False),
        "unit_label_plural_np": dimension_label_plural(dim, nepali=True),
        "unit_label_plural_en": dimension_label_plural(dim, nepali=False),
        "unit_name_header_np": dimension_name_header_np(dim),
    }


# ---- RUSLE soil-loss (P3) ----
_SOIL_ASSUMPTIONS_NE = [
    "R: संशोधित फोर्नियर सूचकाङ्क (Arnoldus 1980) — वर्षा तीव्रता तथ्याङ्क नभएकोले।",
    "K: EPIC/Williams समीकरण; माटो तथ्याङ्क ~१३ हेक्टर MMU बहुभुजमा।",
    "LS: ढलान लम्बाइ स्थिर (प्रवाह सञ्चय बिना — v1)।",
    "RUSLE ले पाना तथा नाली क्षय मात्र आँकलन गर्छ — गल्ली/पहिरो/किनारा क्षय होइन।",
    "निरपेक्ष मान स्क्रिनिङ-स्तर (±५०–१००%); एकाइबिचको तुलना बलियो।",
]
_SOIL_ASSUMPTIONS_EN = [
    "R: Modified Fournier Index (Arnoldus 1980) — no rainfall-intensity data.",
    "K: EPIC/Williams equation; soil at ~13 ha MMU-polygon resolution.",
    "LS: constant slope length (no flow accumulation — v1).",
    "RUSLE estimates sheet & rill erosion only — not gully, landslide or bank.",
    "Absolute values are screening-grade (±50–100%); the per-unit ranking is robust.",
]


def get_soil_erosion_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """RUSLE annual soil-loss for the OP (S9). Never raises — a compute/raster
    failure yields ``{"soil_loss_available": False}`` + empty defaults so the OP
    still generates."""
    from app.services.operational_plan.soil_erosion_narration import all_narration

    empty = {
        "soil_loss_available": False,
        "soil_loss_by_unit": [],
        "soil_loss_hotspot_units": [],
        "soil_loss_assumptions": _SOIL_ASSUMPTIONS_NE,
        "soil_loss_assumptions_en": _SOIL_ASSUMPTIONS_EN,
        "soil_loss_has_user_group": False,
    }
    empty.update(all_narration(empty))
    try:
        import numpy as np

        from app.services.management_plan_docx import plan_map_service as pms
        from app.services.operational_plan import soil_erosion as se

        calc_uuid = (
            UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
        )
        res = se.compute_soil_loss(db, calc_uuid)
        g = res.grid
        breaks = list(res.params.severity_breaks)
        tol = float(res.params.tolerable_soil_loss)

        cf = se.aoi_summary(res, g.cf_mask)
        if cf["mean"] is None:
            return empty

        sel = g.cf_mask & np.isfinite(res.a)
        above = sel & (res.a > tol)
        pct_above = (
            round(
                100.0
                * float(g.cell_area_ha[above].sum())
                / float(g.cell_area_ha[sel].sum()),
                1,
            )
            if sel.any()
            else 0.0
        )

        cvs = {}
        for nm, arr in (("R", res.r), ("K", res.k), ("LS", res.ls), ("C", res.c)):
            v = arr[g.cf_mask & np.isfinite(arr)]
            if v.size and v.mean():
                cvs[nm] = float(v.std() / v.mean())
        dominant = max(cvs, key=cvs.get) if cvs else None

        units = pms._get_leaf_units_with_geometry(db, calc_uuid)
        by_unit = []
        for name, s in se.zonal_summary(res, units).items():
            if s["mean"] is None:
                continue
            pct_severe = sum(
                p for i, p in s["pct_by_severity"].items() if i >= len(breaks) - 1
            )
            by_unit.append(
                {
                    "एकाइ": name,
                    "औसत_क्षय_टन_हे_वर्ष": s["mean"],
                    "कुल_क्षय_टन_वर्ष": s["total_t_yr"],
                    "क्षेत्रफल_हे": s["area_ha"],
                    "गम्भीर_वर्ग_%": round(pct_severe, 1),
                }
            )
        hotspots = [
            r["एकाइ"]
            for r in sorted(by_unit, key=lambda r: r["औसत_क्षय_टन_हे_वर्ष"], reverse=True)
            if r["औसत_क्षय_टन_हे_वर्ष"] > tol
        ][:3]

        out = {
            "soil_loss_available": True,
            "soil_loss_mean_t_ha": cf["mean"],
            "soil_loss_total_t_yr": cf["total_t_yr"],
            "soil_loss_area_ha": cf["area_ha"],
            "soil_loss_tolerable": tol,
            "soil_loss_pct_above_tolerable": pct_above,
            "soil_loss_by_unit": by_unit,
            "soil_loss_hotspot_units": hotspots,
            "soil_loss_hotspot_units_str": " · ".join(hotspots) if hotspots else "—",
            "soil_loss_dominant_factor": dominant,
            "soil_loss_r_method": res.params.r_method,
            "soil_loss_customised": res.params.is_customised(),
            "soil_loss_severity_breaks": breaks,
            "soil_loss_assumptions": _SOIL_ASSUMPTIONS_NE,
            "soil_loss_assumptions_en": _SOIL_ASSUMPTIONS_EN,
            "soil_loss_params": res.params.model_dump(),
            "soil_loss_params_provenance": dict(res.params._provenance),
            "soil_loss_has_user_group": g.ug_mask is not None,
            "soil_loss_sdr_enabled": bool(res.params.sdr_enabled),
        }

        # P6c — sediment actually delivered to the stream network
        if res.delivered is not None:

            def _deliv(mask):
                sel = mask & np.isfinite(res.delivered)
                return round(float((res.delivered[sel] * g.cell_area_ha[sel]).sum()), 1)

            gross = out["soil_loss_total_t_yr"] or 0.0
            deliv_cf = _deliv(g.cf_mask)
            out["soil_loss_delivered_t_yr"] = deliv_cf
            out["soil_loss_basin_sdr"] = round(deliv_cf / gross, 3) if gross else None
            sv = res.sdr[g.cf_mask & np.isfinite(res.sdr)]
            out["soil_loss_sdr_mean"] = round(float(sv.mean()), 3) if sv.size else None

        if g.ug_mask is not None:
            ug = se.aoi_summary(res, g.ug_mask)
            ug_only = se.aoi_summary(res, g.ug_mask & ~g.cf_mask)
            out.update(
                {
                    "soil_loss_ug_mean_t_ha": ug["mean"],
                    "soil_loss_ug_total_t_yr": ug["total_t_yr"],
                    "soil_loss_ug_area_ha": ug["area_ha"],
                    "soil_loss_ug_minus_cf_mean_t_ha": ug_only["mean"],
                    "soil_loss_ug_minus_cf_total_t_yr": ug_only["total_t_yr"],
                    "soil_loss_ug_minus_cf_area_ha": ug_only["area_ha"],
                }
            )
            if res.delivered is not None:
                sel = g.ug_mask & np.isfinite(res.delivered)
                out["soil_loss_delivered_ug_t_yr"] = round(
                    float((res.delivered[sel] * g.cell_area_ha[sel]).sum()), 1
                )

            def _pct_above(mask):
                s = mask & np.isfinite(res.a)
                if not s.any():
                    return 0.0
                a2 = s & (res.a > tol)
                return round(
                    100.0
                    * float(g.cell_area_ha[a2].sum())
                    / float(g.cell_area_ha[s].sum()),
                    1,
                )

            out["soil_loss_aoi_comparison"] = [
                {
                    "क्षेत्र": lbl,
                    "क्षेत्रफल_हे": s["area_ha"],
                    "औसत_क्षय_टन_हे_वर्ष": s["mean"],
                    "कुल_क्षय_टन_वर्ष": s["total_t_yr"],
                    "सह्य_सीमाभन्दा_माथि_%": _pct_above(m),
                }
                for lbl, s, m in (
                    ("सामुदायिक वन", cf, g.cf_mask),
                    ("उपभोक्ता क्षेत्र (कुल)", ug, g.ug_mask),
                    ("वन बाहिरको बस्ती भूमि", ug_only, g.ug_mask & ~g.cf_mask),
                )
                if s["mean"] is not None
            ]

        out.update(all_narration(out))
        return out
    except Exception:  # noqa: BLE001 -- soil-loss must never break OP generation
        logger.warning(
            "OP_COLLECT: soil-erosion collection failed for %s",
            calculation_id,
            exc_info=True,
        )
        return empty


_HAZARD_ASSUMPTIONS_NE = [
    "पहिरो संवेदनशीलता (LSI): भारित बहु-मापदण्ड ओभरले — पहिरो सूची नभएकोले सापेक्ष, सम्भाव्यता होइन।",
    "स्थायित्व गुणांक (FS): अनन्त-ढलान मोडेल, मनसुनी संतृप्त परिदृश्य, अनुमानित रेगोलिथ गहिराइ।",
    "उच्च वर्ग क्षेत्र सामुदायिक वन उपभोक्ता समूहद्वारा स्थलगत प्रमाणीकरण गर्न सिफारिस।",
    "घरधुरी जोखिम: भौतिक प्रकोप × सामाजिक-आर्थिक संवेदनशीलता — टोल/घर नं. स्तरमा मात्र प्रस्तुत।",
]
_HAZARD_ASSUMPTIONS_EN = [
    "Landslide Susceptibility (LSI): a weighted multi-criteria overlay — relative, not a probability (no landslide inventory).",
    "Factor of Safety (FS): infinite-slope model under a saturated-monsoon scenario with an assumed regolith depth.",
    "The High+ class area should be field-verified by the CFUG.",
    "Household vulnerability: physical hazard × socio-economic sensitivity — reported at tole / house-number level only.",
]


def _hazard_vuln_narration(out: Dict[str, Any]) -> Dict[str, Any]:
    """P6's ``hazard_vuln_narration.all_narration`` when it exists; empty strings
    until then, so P5 data collection works before P6 lands."""
    try:
        from app.services.operational_plan.hazard_vuln_narration import all_narration

        return all_narration(out)
    except Exception:  # noqa: BLE001 -- P6 not built yet / narration must not break OP
        return {
            k: ""
            for k in (
                "hazard_methodology_narration",
                "hazard_methodology_narration_en",
                "hazard_findings_narration",
                "hazard_findings_narration_en",
                "hazard_prescription_narration",
                "hazard_prescription_narration_en",
            )
        }


def _plan_decision_choice(db: Session, calculation_id: str, key: str) -> Optional[str]:
    """What a person decided for a forest-wide plan question (Forest summary > Decisions needed), or ``None`` if not yet."""
    import uuid

    from app.models.forest_decision import ForestDecision

    calc_uuid = uuid.UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
    return (
        db.query(ForestDecision.choice)
        .filter(ForestDecision.calculation_id == calc_uuid, ForestDecision.key == key, ForestDecision.scope.is_(None))
        .scalar()
    )


def get_hazard_vuln_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Landslide hazard (LSI + FS) + household vulnerability for the OP (S9).
    Never raises — a compute failure yields ``{"hazard_vuln_available": False}``
    + empty defaults so the OP still generates. All numeric reductions are
    ``float()``-cast (no ``np.float64`` into JSONB)."""
    empty: Dict[str, Any] = {
        "hazard_vuln_available": False,
        "lsi_area_by_class": [],
        "lsi_by_unit": [],
        "fs_by_unit": [],
        "hazard_aoi_comparison": [],
        "hh_priority_table": [],
        "hh_settlement_rollup_table": [],
        "hh_driver_counts": [],
        "hazard_assumptions": _HAZARD_ASSUMPTIONS_NE,
        "hazard_assumptions_en": _HAZARD_ASSUMPTIONS_EN,
        "hazard_has_user_group": False,
        "fs_enabled": False,
        "hh_available": False,
        "hh_coord_source": "survey",
    }
    empty.update(_hazard_vuln_narration(empty))
    try:
        import numpy as np

        from app.services.management_plan_docx import plan_map_service as pms
        from app.services.operational_plan import landslide_susceptibility as lsm
        from app.services.operational_plan import slope_stability as ssm

        calc_uuid = (
            UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
        )
        lsi = lsm.compute_lsi(db, calc_uuid)
        g = lsi.grid
        lp = lsi.params.landslide
        nseen = lp.n_classes

        cf = lsm.aoi_summary(lsi, g.cf_mask)
        if cf["area_ha"] <= 0:
            return empty

        prone_ha = round(
            sum(v for i, v in cf["by_class_ha"].items() if i >= lp.prone_class_min - 1),
            2,
        )
        prone_pct = round(100.0 * prone_ha / cf["area_ha"], 1) if cf["area_ha"] else 0.0

        lsi_area_by_class = [
            {
                "वर्ग": lp.lsi_class_label(i, "ne"),
                "class_en": lp.lsi_class_label(i, "en"),
                "क्षेत्रफल_हे": round(float(cf["by_class_ha"].get(i, 0.0)), 2),
                "क्षेत्रफल_%": round(float(cf["by_class_pct"].get(i, 0.0)), 1),
            }
            for i in range(nseen)
        ]

        units = pms._get_leaf_units_with_geometry(db, calc_uuid)
        lsi_zonal = lsm.zonal_summary(lsi, units)
        lsi_by_unit = []
        for name, s in lsi_zonal.items():
            if s["area_ha"] <= 0:
                continue
            hi = sum(
                p for i, p in s["by_class_pct"].items() if i >= lp.prone_class_min - 1
            )
            lsi_by_unit.append(
                {
                    "एकाइ": name,
                    "क्षेत्रफल_हे": s["area_ha"],
                    "औसत_वर्ग": s.get("mean_class"),
                    "उच्च+_वर्ग_%": round(float(hi), 1),
                }
            )
        hi_units = [
            r["एकाइ"]
            for r in sorted(lsi_by_unit, key=lambda r: r["उच्च+_वर्ग_%"], reverse=True)
            if r["उच्च+_वर्ग_%"] > 0
        ][:3]

        out: Dict[str, Any] = {
            "hazard_vuln_available": True,
            "lsi_prone_area_ha": prone_ha,
            "lsi_prone_area_pct": prone_pct,
            "lsi_area_by_class": lsi_area_by_class,
            "lsi_by_unit": lsi_by_unit,
            "lsi_high_units_str": " · ".join(hi_units) if hi_units else "—",
            "lsi_class_method": lp.class_method,
            "lsi_consistency_ratio": round(float(lsi.consistency_ratio), 4),
            "lsi_customised": lsi.params.is_customised(),
            "hazard_assumptions": _HAZARD_ASSUMPTIONS_NE,
            "hazard_assumptions_en": _HAZARD_ASSUMPTIONS_EN,
            "hazard_has_user_group": g.ug_mask is not None,
            "hazard_vuln_params": lsi.params.model_dump(),
            "hazard_vuln_params_provenance": dict(lsi.params._provenance),
        }

        # ── Factor of Safety ──────────────────────────────────────────
        try:
            fs = ssm.compute_fs(db, calc_uuid)
            fp = fs.params.factor_of_safety
            if fp.enabled:
                fs_cf = ssm.aoi_summary(fs, g.cf_mask)
                out.update(
                    {
                        "fs_enabled": True,
                        "fs_unstable_area_ha": fs_cf["unstable_ha"],
                        "fs_unstable_pct": fs_cf["unstable_pct"],
                        "fs_marginal_area_ha": fs_cf["marginal_ha"],
                        "fs_marginal_pct": fs_cf["marginal_pct"],
                        "fs_scenario_note": fs.scenario.get("note_ne", ""),
                        "fs_scenario_note_en": fs.scenario.get("note_en", ""),
                        "fs_depth_mean_m": fs.scenario.get("depth_mean_m"),
                        "fs_by_unit": [
                            {
                                "एकाइ": name,
                                "क्षेत्रफल_हे": s["area_ha"],
                                "अस्थिर_हे": s["unstable_ha"],
                                "सीमान्त_हे": s["marginal_ha"],
                                "अस्थिर_%": s["unstable_pct"],
                            }
                            for name, s in ssm.zonal_summary(fs, units).items()
                            if s["area_ha"] > 0
                        ],
                    }
                )
            else:
                out["fs_enabled"] = False
        except Exception:  # noqa: BLE001 -- FS is optional
            logger.warning("OP_COLLECT: FS collection failed", exc_info=True)
            out["fs_enabled"] = False

        # ── household vulnerability ───────────────────────────────────
        try:
            from app.services.operational_plan import household_vulnerability as hvm

            hh = hvm.compute_household_vulnerability(db, calc_uuid)
            payload = hvm.op_payload(hh)
            s = payload["hh_vuln_summary"]
            out.update(
                {
                    "hh_available": bool(s.get("n_households")),
                    "hh_count": s.get("n_households", 0),
                    "hh_priority_count": s.get("n_priority", 0),
                    "hh_mean_score": s.get("mean_score"),
                    "hh_max_score": s.get("max_score"),
                    "hh_hazard_layer_informative": bool(
                        s.get("hazard_layer_informative")
                    ),
                    "hh_coord_source": s.get("coord_source", "survey"),
                    # "buildings": no household data, one stand-in per building footprint (exposure only)
                    "hh_basis": s.get("basis", "households"),
                    "hh_priority_table": [
                        {
                            "घर_नं": r["house_no"],
                            "टोल": r["tole"],
                            "जोखिम_अंक": r["score"],
                            "प्रमुख_कारक": r.get("dominant_driver_en"),
                        }
                        for r in payload["hh_priority_table"]
                    ],
                    "hh_settlement_rollup_table": [
                        {
                            "टोल": r["tole"],
                            "घरधुरी": r["n_households"],
                            "औसत_अंक": r["mean_score"],
                            "प्राथमिकता": r["n_priority"],
                            "दिशा": r.get("direction_from_forest"),
                        }
                        for r in payload["hh_settlement_rollup_table"]
                    ],
                    "hh_driver_counts": [
                        {"कारक": k, "घरधुरी": v}
                        for k, v in (s.get("driver_counts") or {}).items()
                    ],
                }
            )
        except Exception:  # noqa: BLE001 -- HH is optional
            logger.warning("OP_COLLECT: HH-vuln collection failed", exc_info=True)
            out["hh_available"] = False

        # ── CF vs UG vs UG−CF accounting ─────────────────────────────
        def _prone(summary):
            return round(
                sum(
                    v
                    for i, v in summary["by_class_ha"].items()
                    if i >= lp.prone_class_min - 1
                ),
                2,
            )

        rows = [("सामुदायिक वन", g.cf_mask, cf)]
        if g.ug_mask is not None:
            ug = lsm.aoi_summary(lsi, g.ug_mask)
            ug_only = lsm.aoi_summary(lsi, g.ug_mask & ~g.cf_mask)
            rows += [
                ("उपभोक्ता क्षेत्र (कुल)", g.ug_mask, ug),
                ("वन बाहिरको बस्ती भूमि", g.ug_mask & ~g.cf_mask, ug_only),
            ]
        out["hazard_aoi_comparison"] = [
            {
                "क्षेत्र": lbl,
                "क्षेत्रफल_हे": summ["area_ha"],
                "सापेक्ष_उच्च_हे": _prone(summ),
                "सापेक्ष_उच्च_%": (
                    round(100.0 * _prone(summ) / summ["area_ha"], 1)
                    if summ["area_ha"]
                    else 0.0
                ),
            }
            for lbl, _m, summ in rows
            if summ["area_ha"] > 0
        ]

        out["decision_landslide_method"] = _plan_decision_choice(db, calculation_id, "landslide_method")
        out.update(_hazard_vuln_narration(out))
        return out
    except Exception:  # noqa: BLE001 -- hazard/vuln must never break OP generation
        logger.warning(
            "OP_COLLECT: hazard-vuln collection failed for %s",
            calculation_id,
            exc_info=True,
        )
        return empty


def _cba_row_years(item) -> int:
    return max(0, int(item.year_to) - int(item.year_from) + 1)


def _cba_cost_total(item) -> float:
    return float(item.amount_per_year or 0) * _cba_row_years(item)


def _cba_benefit_total(item) -> float:
    apy = float(item.amount_per_year or 0)
    if apy == 0 and item.quantity is not None and item.unit_price is not None:
        apy = float(item.quantity) * float(item.unit_price)
    return apy * _cba_row_years(item)


def _cba_breakdown(items, key_fn, total_fn, key_label: str) -> List[Dict[str, Any]]:
    groups: Dict[str, float] = {}
    for it in items:
        k = key_fn(it) or "—"
        groups[k] = groups.get(k, 0.0) + total_fn(it)
    grand = sum(groups.values()) or 1.0
    return [
        {
            key_label: k,
            "कुल_रकम": round(v, 2),
            "प्रतिशत": round(v / grand * 100, 1),
        }
        for k, v in sorted(groups.items(), key=lambda kv: -kv[1])
    ]


def get_cost_benefit_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Cost-Benefit Analysis for the OP (Financial Analysis section). Reads the
    **base** scenario, its cached result **and its line items**. Never raises —
    a missing scenario yields ``{"cba_available": False}`` + empty tables so the
    OP still generates.

    Fixes the six rendering bugs recorded in ``cba_variable_maintance_detail_plan.md``:
    #1 ``Decimal('0.00')`` is falsy → every result field uses ``is not None``;
    #2 three *distinct* tables (indicator summary / cost-by-category /
       benefit-by-source), not the same scenario list three times;
    #5 the year-wise cash-flow table is flat — the nested ``cash_flow_data`` JSON
       is never surfaced in a cell;
    #6 the individual cost/benefit items are collected so the breakdown tables
       have data. (#3 number formatting is the renderer's job; #4 headers are
       Devanagari dict keys, so ``_add_list_table`` needs no ``NP_HEADERS`` map.)
    """
    from app.models.cost_benefit import (
        CBABenefitItem,
        CBACostItem,
        CostBenefitAnalysis,
    )

    empty: Dict[str, Any] = {
        "cba_available": False,
        "cba_discount_rate": None,
        "cba_time_horizon_years": None,
        "cba_base_npv": None,
        "cba_base_irr": None,
        "cba_base_bc_ratio": None,
        "cba_base_payback": None,
        "cba_summary_table": [],
        "cba_cash_flow_table": [],
        "cba_cost_breakdown": [],
        "cba_benefit_breakdown": [],
        "cba_verdict": "",
    }
    try:
        cid = (
            UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
        )
        base = (
            db.query(CostBenefitAnalysis)
            .filter(
                CostBenefitAnalysis.calculation_id == cid,
                CostBenefitAnalysis.is_base_scenario.is_(True),
            )
            .first()
        )
        if base is None:
            return empty

        # ND-6: the cached CBAResult can lag the line items (auto-populate
        # rewrites the items but never recomputes), which showed a zero NPV and
        # a missing B/C ratio in the plan. Refresh it when stale, then read it.
        from app.services.cost_benefit import result_sync

        r = result_sync.ensure_result_current(db, base)
        costs = db.query(CBACostItem).filter(CBACostItem.cba_id == base.id).all()
        benefits = (
            db.query(CBABenefitItem).filter(CBABenefitItem.cba_id == base.id).all()
        )

        def _f(v):
            return float(v) if v is not None else None  # bug #1

        npv = _f(r.npv) if r else None
        irr_frac = _f(r.irr) if r else None
        bcr = _f(r.benefit_cost_ratio) if r else None
        payback = _f(r.payback_period_years) if r else None
        cost_pv = _f(r.total_cost_pv) if r else None
        benefit_pv = _f(r.total_benefit_pv) if r else None
        cost_undisc = round(sum(_cba_cost_total(c) for c in costs), 2)
        benefit_undisc = round(sum(_cba_benefit_total(b) for b in benefits), 2)

        def _num(v, dp=2):
            return None if v is None else round(v, dp)

        summary_table = [
            {"सूचकांक": "खुद वर्तमान मूल्य (NPV)", "मान": _num(npv, 0)},
            {
                "सूचकांक": "आन्तरिक प्रतिफल दर (IRR %)",
                "मान": None if irr_frac is None else round(irr_frac * 100, 1),
            },
            {"सूचकांक": "लाभ-लागत अनुपात (B/C)", "मान": _num(bcr, 2)},
            {"सूचकांक": "भुक्तानी अवधि (वर्ष)", "मान": _num(payback, 1)},
            {"सूचकांक": "कुल लागत (वर्तमान मूल्य)", "मान": _num(cost_pv, 0)},
            {"सूचकांक": "कुल लाभ (वर्तमान मूल्य)", "मान": _num(benefit_pv, 0)},
            {"सूचकांक": "कुल लागत (अनविच्छेदित)", "मान": round(cost_undisc, 0)},
            {"सूचकांक": "कुल लाभ (अनविच्छेदित)", "मान": round(benefit_undisc, 0)},
        ]

        cf = list(r.cash_flow_data) if r and r.cash_flow_data else []
        cash_flow_table = [
            {
                "वर्ष": row.get("year"),
                "लागत": round(float(row.get("cost", 0) or 0), 0),
                "लाभ": round(float(row.get("benefit", 0) or 0), 0),
                "शुद्ध": round(float(row.get("net", 0) or 0), 0),
            }
            for row in cf
        ]

        verdict = (
            "यो योजना आर्थिक रूपले व्यवहार्य छ — NPV धनात्मक छ।"
            if npv is not None and npv > 0
            else "यस छुट दरमा NPV धनात्मक छैन; लागत/दर/अवधि पुनरावलोकन आवश्यक।"
        )

        return {
            "cba_available": True,
            "cba_scenario_name": base.name,
            "cba_discount_rate": float(base.discount_rate),
            "cba_time_horizon_years": int(base.time_horizon_years),
            "cba_base_npv": _num(npv, 0),
            "cba_base_irr": (None if irr_frac is None else round(irr_frac * 100, 1)),
            "cba_base_bc_ratio": _num(bcr, 2),
            "cba_base_payback": _num(payback, 1),
            "cba_summary_table": summary_table,
            "cba_cash_flow_table": cash_flow_table,
            "cba_cost_breakdown": _cba_breakdown(
                costs, lambda c: c.category, _cba_cost_total, "लागत_शीर्षक"
            ),
            "cba_benefit_breakdown": _cba_breakdown(
                benefits, lambda b: b.source, _cba_benefit_total, "लाभ_स्रोत"
            ),
            "cba_verdict": verdict,
        }
    except Exception:  # noqa: BLE001 -- CBA must never break OP generation
        logger.warning(
            "OP_COLLECT: cost-benefit collection failed for %s",
            calculation_id,
            exc_info=True,
        )
        return empty


_SFM_SLOPE_BAND_NE = {1: "< १९°", 2: "१९–३१°", 3: "३१–४५°", 4: "> ४५°"}
_SFM_METHOD_NE = {
    "selection_felling_cycle": "छनौट — कटान चक्र",
    "shelterwood_periodic_block": "आवरण — आवधिक खण्ड",
    "stem_count": "रुख संख्या नियमन",
    "area_coupe": "क्षेत्रफल / कुप",
}
_SFM_ORIENTATION_NE = {
    "Production": "उत्पादन",
    "Conservation": "संरक्षण",
    "Protection": "प्रतिरक्षा",
}
_SFM_SAMPLING_NOTE = (
    "दिगो वन व्यवस्थापन कार्यविधि, २०७९ को दफा १६ ले न्यूनतम नमुना तीव्रता तोक्छ — "
    "उत्पादन क्षेत्रमा २%, संरक्षण क्षेत्रमा १% र प्रतिरक्षा क्षेत्रमा ०.५%। "
    "तल दिइएको सुझाव मात्र हो; स्याम्पलिङ ट्याब नै आधिकारिक हुन्छ र तीव्रता बढाउन सकिन्छ।"
)


def get_sustainable_fm_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Sustainable Forest Management (दिगो वन व्यवस्थापन) classification for the
    OP — reads ``result_data['sfm']`` (built by the SFM tab / a nightly job; this
    collector never builds it). Never raises. When ``sfm`` is absent every key
    resolves to an empty-state sentence / ``[]`` so a placed ``३.१०`` node still
    renders a heading + one line rather than a blank.

    The growing-stock harvest figure is labelled *उत्पादन नियमन अनुसारको वार्षिक
    कटान परिमाण* and sits **beside** the MAI→AAH section — it never replaces it.
    """
    empty: Dict[str, Any] = {
        "sfm_available": False,
        "sfm_dominant_type_ne": "",
        "sfm_dominant_type_en": "",
        "sfm_total_annual_harvest_m3": None,
        "sfm_production_area_ha": None,
        "sfm_protection_area_ha": None,
        "sfm_plan_regime_note": "",
        "sfm_sampling_intensity_note": "",
        "sfm_felling_series_note": "",
        "sfm_methodology": "यस वनको दिगो वन व्यवस्थापन वर्गीकरण अझै बनाइएको छैन।",
        "sfm_findings": "दिगो वन व्यवस्थापन ट्याब खोलेपछि वर्गीकरण स्वतः बन्नेछ।",
        "sfm_prescription": "",
        "sfm_block_prescription_table": [],
        "sfm_type_area_table": [],
        "sfm_yield_table": [],
        "sfm_working_circle_table": [],
        "sfm_sampling_plan_table": [],
    }
    try:
        cid = (
            UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
        )
        calc = db.query(Calculation).filter(Calculation.id == cid).first()
        sfm = ((calc.result_data or {}).get("sfm") or {}) if calc else {}

        regime_note = ""
        try:
            from app.models.operational_plan import OperationalPlan

            op = (
                db.query(OperationalPlan)
                .filter(OperationalPlan.calculation_id == cid)
                .first()
            )
            regime = (op.plan_metadata or {}).get("template_regime") if op else None
            if regime == "sustainable_fmp":
                regime_note = (
                    "यो कार्ययोजना दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसार तयार गरिएको हो; "
                    "तसर्थ वार्षिक कटान परिमाण औसत वार्षिक वृद्धि (MAI) होइन, ≥ ४० से.मि. "
                    "व्यासका रुखको जम्मा मौज्दातबाट कटान श्रृंखला अनुसार निर्धारण गरिएको छ।"
                )
        except Exception:  # noqa: BLE001 -- regime note is optional
            regime_note = ""

        blocks = sfm.get("blocks") or []
        if not blocks:
            e = dict(empty)
            e["sfm_plan_regime_note"] = regime_note
            return e

        summ = sfm.get("forest_summary", {}) or {}
        series = sfm.get("felling_series", []) or []
        zone_by = sfm.get("zone_by_block", {}) or {}
        narr = sfm.get("narration") or sfm_narration.all_blocks(sfm)

        dom = summ.get("dominant_type_no")
        dom_block = next((b for b in blocks if b.get("effective_type_no") == dom), None)
        dom_card = (dom_block or {}).get("prescription") or {}

        def _band_ne(name: str) -> str:
            b = (zone_by.get(name) or {}).get("slope_band")
            return _SFM_SLOPE_BAND_NE.get(b, "—")

        prescription_table = [
            {
                "खण्ड": b.get("block_name"),
                "सि.नं.": b.get("effective_type_no"),
                "प्रणाली": ((b.get("prescription") or {}).get("system_ne")) or "—",
                "कटान चक्र (वर्ष)": (
                    (b.get("prescription") or {}).get("felling_cycle_years")
                    or (b.get("prescription") or {}).get("regeneration_period_years")
                ),
                "भिरालो वर्ग": _band_ne(b.get("block_name") or ""),
                "पुनरावलोकन": "आवश्यक" if b.get("needs_review") else "—",
            }
            for b in blocks
        ]

        type_area = summ.get("type_area_breakdown", {}) or {}
        total_area = sum(float(v or 0.0) for v in type_area.values()) or 1.0
        type_area_table = [
            {
                "सि.नं.": int(k),
                "क्षेत्रफल (हे.)": round(float(v or 0.0), 2),
                "प्रतिशत": round(100.0 * float(v or 0.0) / total_area, 1),
            }
            for k, v in sorted(type_area.items(), key=lambda kv: int(kv[0]))
        ]

        def _ncr(s: dict) -> str:
            parts = []
            if s.get("N") is not None:
                parts.append(f"N {s['N']}")
            if s.get("C") is not None:
                parts.append(f"C {s['C']}")
            if s.get("R") is not None:
                parts.append(f"R {s['R']}")
            return " · ".join(parts) or "—"

        yield_table = [
            {
                "कटान श्रृंखला (सि.नं.)": s.get("type_no"),
                "विधि": _SFM_METHOD_NE.get(s.get("method"), s.get("method") or "—"),
                "N / C / R": _ncr(s),
                "मौज्दात ≥४० (घन.मी.)": s.get("gs_ge40_m3"),
                "प्रतिशत": s.get("pct"),
                "वार्षिक कटान (घन.मी.)": s.get("annual_harvest_m3"),
            }
            for s in series
        ]

        wc_table = [
            {
                "खण्ड": b.get("block_name"),
                "अभिमुखीकरण": _SFM_ORIENTATION_NE.get(
                    b.get("orientation"), b.get("orientation") or "—"
                ),
                "कार्य वृत्त प्रस्ताव": (
                    ((b.get("working_circle_proposal") or {}).get("justification_ne"))
                    or "—"
                ),
            }
            for b in blocks
        ]

        sampling_table = [
            {
                "खण्ड": r.get("block_name"),
                "स्तर": {
                    "production": "उत्पादन",
                    "conservation": "संरक्षण",
                    "protection": "प्रतिरक्षा",
                }.get(r.get("stratum"), r.get("stratum") or "—"),
                "तीव्रता (%)": r.get("intensity_pct"),
                "प्लट संख्या": r.get("plots"),
            }
            for r in (summ.get("sampling_plan") or [])
        ]

        n_num_series = len(
            [s for s in series if s.get("annual_harvest_m3") is not None]
        )
        return {
            "sfm_available": True,
            "sfm_dominant_type_ne": dom_card.get("type_name_ne") or "",
            "sfm_dominant_type_en": dom_card.get("type_name_en") or "",
            "sfm_total_annual_harvest_m3": summ.get("total_annual_harvest_m3"),
            "sfm_production_area_ha": summ.get("production_area_ha"),
            "sfm_protection_area_ha": summ.get("protection_area_ha"),
            "sfm_plan_regime_note": regime_note,
            "sfm_sampling_intensity_note": _SFM_SAMPLING_NOTE,
            "sfm_felling_series_note": (
                f"जम्मा {len(series)} कटान श्रृंखला (एउटै वन प्रकारका खण्डहरूको समूह); "
                f"तीमध्ये {n_num_series} बाट संख्यात्मक वार्षिक कटान परिमाण प्राप्त भयो।"
            ),
            "sfm_methodology": (narr.get("methodology") or {}).get("ne") or "",
            "sfm_findings": (narr.get("findings") or {}).get("ne") or "",
            "sfm_prescription": (narr.get("prescription") or {}).get("ne") or "",
            "sfm_block_prescription_table": prescription_table,
            "sfm_type_area_table": type_area_table,
            "sfm_yield_table": yield_table,
            "sfm_working_circle_table": wc_table,
            "sfm_sampling_plan_table": sampling_table,
        }
    except Exception:  # noqa: BLE001 -- SFM must never break OP generation
        logger.warning(
            "OP_COLLECT: sustainable-fm collection failed for %s",
            calculation_id,
            exc_info=True,
        )
        return empty


_HAZARD_FULL_NARRATION_SECTIONS = (
    ("soil_erosion", "soil_loss_methodology_narration", "माटो क्षय — विधि"),
    ("soil_erosion", "soil_loss_findings_narration", "माटो क्षय — निष्कर्ष"),
    (
        "soil_erosion",
        "soil_loss_prescription_narration",
        "माटो क्षय — व्यवस्थापन दिशानिर्देश",
    ),
    ("hazard_vuln", "hazard_methodology_narration", "पहिरो र घरधुरी जोखिम — विधि"),
    ("hazard_vuln", "hazard_findings_narration", "पहिरो र घरधुरी जोखिम — निष्कर्ष"),
    (
        "hazard_vuln",
        "hazard_prescription_narration",
        "पहिरो र घरधुरी जोखिम — व्यवस्थापन दिशानिर्देश",
    ),
)


def _assemble_hazard_full_narration(soil: dict, hazard: dict) -> str:
    """The six Hazard & Erosion narration paragraphs, each under its heading —
    one drop-in ``{{hazard_erosion_full_narration}}`` for template designers.
    Empty when neither analysis has run."""
    blocks = {"soil_erosion": soil or {}, "hazard_vuln": hazard or {}}
    parts = []
    for block_key, narr_key, heading in _HAZARD_FULL_NARRATION_SECTIONS:
        text = (blocks.get(block_key, {}) or {}).get(narr_key) or ""
        if text.strip():
            parts.append(f"{heading}\n{text.strip()}")
    return "\n\n".join(parts)


# business: main entry point — collects ALL module data in dependency order
# why: caching via OP_DATA_CACHE_VERSION to avoid redundant DB queries
def read_op_data_cache(db: Session, calculation_id: str) -> Optional[Dict[str, Any]]:
    """The cached OP data for a forest, or ``None`` when there is none or it is out of date.

    Cache only: unlike ``collect_all_op_data`` this never collects (a miss costs seconds and may start a hazard
    computation), so a screen that must not compute can call it freely.
    """
    import uuid
    from app.models.op_data_cache import OpDataCache

    calc_uuid = uuid.UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
    cached = db.query(OpDataCache).filter(OpDataCache.calculation_id == calc_uuid).first()
    if not cached:
        return None
    data = dict(cached.data)
    if data.pop("_cache_version", None) != OP_DATA_CACHE_VERSION:
        return None
    return data


def collect_all_op_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Collect all module data for the OP document, using cache if available."""
    t_start = time.time()
    import uuid
    from app.models.op_data_cache import OpDataCache

    calc_uuid = (
        uuid.UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
    )
    cached = (
        db.query(OpDataCache).filter(OpDataCache.calculation_id == calc_uuid).first()
    )
    if cached:
        cached_data = dict(cached.data)
        # Invalidate if cache version doesn't match (schema/keys may have changed)
        if cached_data.pop("_cache_version", None) == OP_DATA_CACHE_VERSION:
            # ND-6: a stale CBA result would be frozen into the cached payload —
            # the items can be re-populated without the result being recomputed.
            from app.services.cost_benefit.result_sync import scenario_needs_recompute

            if not scenario_needs_recompute(db, calc_uuid):
                logger.info(
                    "OP_COLLECT: cache HIT for calc=%s (%.2fs)",
                    calculation_id,
                    time.time() - t_start,
                )
                return cached_data
            logger.info(
                "OP_COLLECT: cache HIT ignored for calc=%s — CBA result is stale",
                calculation_id,
            )

    logger.info(
        "OP_COLLECT: cache MISS for calc=%s — starting full collection", calculation_id
    )
    t0 = time.time()
    raw = _collect_all_data(db, calculation_id)
    logger.info("OP_COLLECT: _collect_all_data done in %.2fs", time.time() - t0)

    # Merge user_group_landcover into user_group so all UG vars resolve from one source
    if "user_group_landcover" in raw:
        buildings_available = raw.get("user_group", {}).get("available", False)
        ug_lc = raw.pop("user_group_landcover", {})
        raw.setdefault("user_group", {})
        raw["user_group"].update(ug_lc)
        # Preserve buildings availability — don't let missing landcover overwrite
        if buildings_available:
            raw["user_group"]["available"] = True

    t1 = time.time()
    fi_data = get_field_inventory_data(
        db, calculation_id, base_species_data=raw.get("species")
    )
    logger.info("OP_COLLECT: get_field_inventory_data done in %.2fs", time.time() - t1)
    raw["field_inventory"] = fi_data

    # Compute total inventory (absolute) from per-hectare field inventory data
    t2 = time.time()
    ti_data = _compute_total_inventory(fi_data)
    logger.info("OP_COLLECT: _compute_total_inventory done in %.2fs", time.time() - t2)
    raw["field_inventory"].update(ti_data)

    t2b = time.time()
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    raw["result_data"] = calc.result_data or {} if calc else {}

    # 1984 land use, read from the same vector polygons the map draws, so the variables, the narrative and the map agree.
    # The analysis stores only percentages (and only when it was run); this also gives the area per class.
    try:
        hist = raw.setdefault("raster_analysis", {}).setdefault("landcover_historical", {})
        fresh: dict = {}
        _enrich_landcover_1984_from_polygons(db, calculation_id, fresh)
        hist.update(fresh)
    except Exception:  # noqa: BLE001 -- the stored analysis values (if any) stay; logged so it is not silent
        logger.exception("OP_COLLECT: 1984 land-use enrichment failed for %s", calculation_id)

    raw["blocks"]["sub_areas_detail"] = _fetch_sub_areas_detail(db, calculation_id)
    raw["blocks"]["block_area_detail_merged"] = _fetch_block_area_detail_merged(
        db, calculation_id
    )
    # T1: Block area table — merge into field_inventory for ti_ variable resolution
    raw["field_inventory"]["ti_block_area_table"] = raw["blocks"][
        "block_area_detail_merged"
    ]

    raw["compartment"] = _fetch_compartment_data(db, calculation_id)

    # Yearly plan (10-year activities data)
    raw["yearly_plan"] = _collect_yearly_activities_data(db, calculation_id)

    # Fieldbook data — must be before section_generators so narration sees it
    raw["fieldbook"] = _fetch_fieldbook_data(db, calculation_id)

    # Tree mapping analysis data for sm_* variables
    t_sm = time.time()
    sm_data = get_tree_mapping_analysis_data(db, calculation_id)
    logger.info("OP_COLLECT: tree_mapping_analysis done in %.2fs", time.time() - t_sm)
    raw["tree_mapping_analysis"] = sm_data

    # RUSLE soil-loss (S9) — before section_generators so narration sees it
    t_se = time.time()
    raw["soil_erosion"] = get_soil_erosion_data(db, calculation_id)
    logger.info("OP_COLLECT: soil_erosion done in %.2fs", time.time() - t_se)

    # Landslide hazard + household vulnerability (S9) — before section_generators
    t_hv = time.time()
    raw["hazard_vuln"] = get_hazard_vuln_data(db, calculation_id)
    logger.info("OP_COLLECT: hazard_vuln done in %.2fs", time.time() - t_hv)

    # HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P2 — one drop-in variable holding the
    # whole Hazard & Erosion write-up (the 6 methodology/findings/prescription
    # paragraphs, each under a heading). Assembled here because the two source
    # blocks live in different collectors.
    raw["soil_erosion"]["hazard_erosion_full_narration"] = (
        _assemble_hazard_full_narration(
            raw.get("soil_erosion", {}), raw.get("hazard_vuln", {})
        )
    )

    # Cost-Benefit Analysis (Financial Analysis section)
    t_cba = time.time()
    raw["cost_benefit"] = get_cost_benefit_data(db, calculation_id)
    logger.info("OP_COLLECT: cost_benefit done in %.2fs", time.time() - t_cba)

    # Sustainable Forest Management (दिगो वन व्यवस्थापन) — read-only, § ३.१०
    t_sfm = time.time()
    raw["sustainable_fm"] = get_sustainable_fm_data(db, calculation_id)
    logger.info("OP_COLLECT: sustainable_fm done in %.2fs", time.time() - t_sfm)

    # NTFP inventory results (the optional NTFP page): {"available": False} unless field records exist
    try:
        from app.services.operational_plan.ntfp_inventory_op import get_ntfp_inventory_data

        raw["ntfp_inventory"] = get_ntfp_inventory_data(db, calculation_id)
    except Exception:  # noqa: BLE001 -- the optional table must never break the plan; logged
        logger.exception("OP_COLLECT: NTFP inventory results failed for %s", calculation_id)
        raw["ntfp_inventory"] = {"available": False}

    # business: CFMG — demand-supply analysis for OP sustainability section
    # why: demand/supply/deficit used for biodiversity reporting and harvest planning
    try:
        from app.services.demand_supply_service import (
            get_demand,
            get_community_forest_regular_supply,
            get_community_forest_aah_supply,
            get_private_supply,
        )

        calc_uuid = UUID(calculation_id)
        demand = get_demand(db, calc_uuid)
        cf_reg = get_community_forest_regular_supply(db, calc_uuid)
        cf_aah = get_community_forest_aah_supply(db, calc_uuid)
        cf_data = {
            "firewood_bhari": cf_reg.get("firewood_bhari", 0),
            "grass_bhari": cf_reg.get("grass_bhari", 0),
            "bedding_bhari": cf_reg.get("bedding_bhari", 0),
            "timber_cft": cf_aah.get("timber_cft", 0),
            "poles_count": cf_aah.get("poles_count", 0),
        }
        pvt = get_private_supply(db, calc_uuid)
        total_supply = {
            k: (cf_data.get(k, 0) or 0) + (pvt.get(k, 0) or 0)
            for k in (
                "firewood_bhari",
                "grass_bhari",
                "bedding_bhari",
                "timber_cft",
                "poles_count",
            )
        }
        deficit = {
            k: total_supply.get(k, 0) - (demand.get(k, 0) or 0)
            for k in (
                "firewood_bhari",
                "grass_bhari",
                "bedding_bhari",
                "timber_cft",
                "poles_count",
            )
        }
        raw["demand_supply"] = {
            "demand": demand,
            "supply_cf_regular": cf_reg,
            "supply_cf_aah": cf_aah,
            "supply_private": pvt,
            "total_supply": total_supply,
            "deficit": deficit,
        }
    except Exception as exc:
        logger.warning("OP_COLLECT: demand-supply collection failed: %s", exc)
        raw["demand_supply"] = {}

    # Derived scalars/tables for the Rambhadevi-style plan (stem lists, silviculture schedule, ...) -
    # before section_generators so narration could use them.
    from app.services.operational_plan.plan_extras import collect_plan_extras

    raw["plan_extras"] = collect_plan_extras(db, calculation_id, raw)

    t3 = time.time()
    raw["section_generators"] = collect_section_content(raw)
    logger.info(
        "OP_COLLECT: block+compartment+act+fieldbook+sections done in %.2fs",
        time.time() - t2b,
    )

    # Sampling: Nepali-keyed variants for inline table rendering
    sampling_data = raw.get("sampling", {})
    if sampling_data.get("available"):
        sampling_data["sampling_point_locations"] = _fetch_sampling_point_locations(
            db, calculation_id
        )

        # Transform blocks_info keys to Nepali for {{sampling_block_summary}}
        designs = sampling_data.get("designs", [])
        if designs:
            bi = designs[0].get("blocks_info") or []
            nepali_rows = []
            for b in bi:
                nepali_rows.append(
                    {
                        "ब्लकको_नाम": b.get("block_name", ""),
                        "क्षेत्रफल_हे": b.get("block_area_hectares", 0),
                        "पहुँचयुक्त_वन_हे": b.get("accessible_forest_area_ha", ""),
                        "संरक्षित": b.get("is_protected", ""),
                        "नमुना_प्लट_संख्या": b.get("samples_generated", 0),
                        "प्लट_दुरी_मि": b.get("grid_spacing_meters", ""),
                        "वास्तविक_इन्टेन्सिटी_प्रतिशत": b.get(
                            "actual_intensity_percent", ""
                        ),
                        "स्याम्पलिङ_विधि": b.get("sampling_method", ""),
                    }
                )
            sampling_data["sampling_block_summary"] = nepali_rows

    # Add dimension section with mode-aware label variables
    # Must be before cache write so {{unit_label_np}} resolves.
    _add_dimension_section(raw, calc_uuid, db)

    from app.models.op_data_cache import OpDataCache

    # Clean NaN values that can't be serialized to JSONB
    def _clean_nan(obj):
        if isinstance(obj, float) and math.isnan(obj):
            return None
        if isinstance(obj, dict):
            return {k: _clean_nan(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean_nan(v) for v in obj]
        return obj

    raw = _clean_nan(raw)

    existing = (
        db.query(OpDataCache).filter(OpDataCache.calculation_id == calc_uuid).first()
    )
    raw["_cache_version"] = OP_DATA_CACHE_VERSION
    if existing:
        existing.data = raw
        existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(OpDataCache(calculation_id=calc_uuid, data=raw))
    db.commit()
    logger.info(
        "OP_COLLECT: total=%.2fs calc=%s cache=%s",
        time.time() - t_start,
        calculation_id,
        "WRITTEN",
    )
    return raw


# ═══════════════════════════════════════════════════════════════════
# Tree Mapping Analysis — sm_* variables
# ═══════════════════════════════════════════════════════════════════


def _safe_hierarchy(val: Any) -> str:
    """Normalize hierarchy value: None, empty, whitespace → '-'"""
    if val is None:
        return "-"
    s = str(val).strip()
    return s if s else "-"


def unit_label_map(units: Any) -> Dict[str, str]:
    """Any name a unit has been known by -> the name the attribute table shows for it now (``ForestBlock.name``).

    A tree keeps a snapshot of the names of the units it fell in when it was assigned; after a merge, a rename or a re-division that
    snapshot can differ from the unit's current name (and some snapshots hold the label, others the auto-made name). The table of units is
    the truth, so every name is looked up there. ``units`` is any iterable of objects with ``name`` and ``block_name``.
    """
    canon: Dict[str, str] = {}
    for u in units:
        name = (getattr(u, "name", None) or "").strip()
        if name:
            canon[name] = name
    for u in units:
        name = (getattr(u, "name", None) or "").strip()
        label = (getattr(u, "block_name", None) or "").strip()
        if name and label and label not in canon:
            canon[label] = name
    return canon


_HIERARCHY_KEYS = ("block_name", "compartment", "sub_compartment")


_SNAPSHOT_NAMES_SQL = text(
    """
    SELECT DISTINCT n FROM (
        SELECT NULLIF(TRIM(extra_columns->>'compartment_name'), '') AS n
          FROM public.inventory_trees WHERE inventory_calculation_id = :inv AND jsonb_typeof(extra_columns) = 'object'
        UNION
        SELECT NULLIF(TRIM(extra_columns->>'parent_compartment_name'), '')
          FROM public.inventory_trees WHERE inventory_calculation_id = :inv AND jsonb_typeof(extra_columns) = 'object'
    ) x WHERE n IS NOT NULL
    """
)


def tree_unit_names_are_stale(db: Any, inventory_id: Any, canon: Dict[str, str], calculation_id: Any = None) -> bool:
    """Do the trees carry a unit name that no unit has any more?

    Each tree keeps a snapshot of the names of the units it fell in, written when it was assigned. Renaming a unit afterwards leaves the old
    name on its trees (a top compartment renamed "q" kept "बनस्खन्डी - Compartment 1" on 2,340 trees), and the analysis then showed a name
    that is nowhere in the attribute table. A name that is neither a unit's name nor a label it has had means the snapshot is out of date.
    """
    names = {r[0] for r in db.execute(_SNAPSHOT_NAMES_SQL, {"inv": str(inventory_id)}).fetchall()}
    if any(n not in canon for n in names):
        return True
    # a tree filed under a unit that has been divided, although a leaf unit contains it: the table lists leaf units, so the tree belongs there
    if calculation_id is not None:
        from app.services.forest_units.hierarchy import has_trees_filed_under_a_divided_unit

        return has_trees_filed_under_a_divided_unit(db, calculation_id, inventory_id)
    return False


def relabel_tree_analysis_units(result: Dict[str, Any], canon: Dict[str, str]) -> None:
    """Show every unit of the tree-mapping analysis by its own current name, exactly as the attribute table does.

    Rows carry ``block_name`` / ``compartment`` / ``sub_compartment`` copied from the trees: each is replaced by the unit's current name,
    and ``unit_name`` (the unit the row IS: its sub-compartment, else its compartment, else its block) is added for the screen. The
    remark breakdown is keyed ``"compartment|sub_compartment"``: its keys are renamed the same way so a row still finds its numbers.
    """

    def resolve(value: Any) -> Any:
        if isinstance(value, str) and value.strip() and value != "-":
            return canon.get(value.strip(), value)
        return value

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            if any(k in node for k in _HIERARCHY_KEYS):
                for k in _HIERARCHY_KEYS:
                    if k in node:
                        node[k] = resolve(node[k])
                own = "-"
                for k in ("sub_compartment", "compartment", "block_name"):
                    v = node.get(k)
                    if isinstance(v, str) and v.strip() and v != "-":
                        own = v
                        break
                node["unit_name"] = own
            for v in node.values():
                if isinstance(v, (list, dict)):
                    visit(v)

    for key, value in list(result.items()):
        if key == "sm_hierarchy_remark_breakdown" and isinstance(value, dict):
            renamed: Dict[str, Any] = {}
            for k, v in value.items():
                comp, _, sub = str(k).partition("|")
                renamed[f"{resolve(comp)}|{resolve(sub)}"] = v
            result[key] = renamed
        elif isinstance(value, (list, dict)):
            visit(value)


# business: CFMG — Shannon-Wiener diversity index for biodiversity reporting
def _compute_shannon_diversity(species_counts: Dict[str, int]) -> Dict[str, Any]:
    """Compute Shannon Index and Evenness from species counts."""
    total = sum(species_counts.values())
    if total == 0:
        return {"species_richness": 0, "shannon_index": 0.0, "evenness": 0.0}
    richness = len(species_counts)
    shannon = 0.0
    for count in species_counts.values():
        pi = count / total
        if pi > 0:
            shannon -= pi * math.log(pi)
    evenness = shannon / math.log(richness) if richness > 1 else 0.0
    return {
        "species_richness": richness,
        "shannon_index": round(shannon, 4),
        "evenness": round(evenness, 4),
    }


# business: CFMG §X.Y — tree mapping analysis (sm_* variables) for OP sections 7-9
def get_tree_mapping_analysis_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Collect tree mapping analysis data for sm_* variables.

    Returns a dict keyed by sm_* variable names containing all data
    needed for the Tree Mapping Analysis section.
    """
    from app.models.inventory import (
        InventoryCalculation,
        InventoryTree,
        TreeSpeciesCoefficient,
    )
    from app.models.forest_block import ForestBlock
    from app.services.carbon_calculator import calculate_all as carbon_calculate_all

    result: Dict[str, Any] = {}

    # Find inventory_calculation for this calculation_id
    calc_uuid = (
        UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
    )
    inv_calc = (
        db.query(InventoryCalculation)
        .filter(InventoryCalculation.calculation_id == calc_uuid)
        .first()
    )

    if not inv_calc:
        result["sm_available"] = False
        return result

    inv_id = inv_calc.id

    # Check if there are any trees
    tree_count = (
        db.query(InventoryTree)
        .filter(InventoryTree.inventory_calculation_id == inv_id)
        .count()
    )

    if tree_count == 0:
        result["sm_available"] = False
        return result

    result["sm_available"] = True

    # The names on the trees must be the names the units have now: when a unit was renamed (or merged) after the trees were assigned, assign
    # them again (a plain re-run of the spatial step the upload runs, which rewrites every tree's compartment names from the current units).
    try:
        _units_now = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc_uuid).all()
        if tree_unit_names_are_stale(db, inv_id, unit_label_map(_units_now), calc_uuid):
            from app.services.inventory import InventoryService

            InventoryService(db)._update_tree_spatial_relationships_sync(inv_id, calc_uuid)
            logger.info("tree analysis: refreshed the unit names on the trees of inventory %s (units were renamed)", inv_id)
    except Exception:  # noqa: BLE001 -- the refresh only keeps names current; the analysis still runs on what is stored
        db.rollback()
        logger.warning("tree analysis: could not refresh the unit names of inventory %s", inv_id, exc_info=True)

    # Load species coefficients for wood density lookup
    species_coeffs = {}
    for sc in (
        db.query(TreeSpeciesCoefficient)
        .filter(TreeSpeciesCoefficient.is_active == True)
        .all()
    ):
        species_coeffs[sc.scientific_name] = {
            "local_name": sc.local_name or "",
            "wood_density": sc.wood_density_gm_cm3 or 0.6,
        }

    # Load block areas
    block_areas: Dict[str, float] = {}
    from app.services.forest_units.model import DEPTH_TOP_BLOCK

    blocks = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc_uuid,
            ForestBlock.is_compartment == False,
            ForestBlock.division_level == DEPTH_TOP_BLOCK,
        )
        .all()
    )
    for b in blocks:
        area = b.area_hectares
        if area is None and b.area_sqm:
            area = b.area_sqm / SQM_PER_HA
        block_areas[b.name] = area or 0

    # A compartment forest has no plain blocks, so a row has no block area to divide by: use the
    # area of the compartment / sub-compartment the row IS (names are unique within a forest). The units
    # module owns "which units does this forest have": top-level compartments plus the leaves under them.
    from app.services.forest_units.model import Branch
    from app.services.forest_units.queries import View, units as _forest_units

    unit_areas: Dict[str, float] = {}
    for view in (View.TOP_LEVEL, View.LEAF):
        for u in _forest_units(db, calc_uuid, view, branch=Branch.COMPARTMENT):
            unit_areas[u.name] = u.area_ha or 0

    # ── Core hierarchy aggregation query ──────────────────────────
    # Uses division_level to correctly map:
    #   compartment = parent compartment name (level 1)
    #   sub_compartment = deepest block name (level 2) or '-' (level 1)
    #
    # FS-1c.4 (structure work): every division_level read below comes from
    # inventory_trees.extra_columns, a compartment-hierarchy SNAPSHOT written by
    # inventory._update_tree_spatial_relationships (its 'effective_level', 1 or
    # 2 - never a block's depth). Migration 094 only changes what a top-level
    # BLOCK's division_level column holds; it does not touch this snapshot or
    # the values inventory.py computes for it. The boundary is bound as
    # :snap_top_level (= _INV_SNAP_BOUNDARY = DEPTH_TOP_COMPARTMENT) so no bare
    # depth number appears next to the snapshot column (FS-1c.9, invariant I10).
    hierarchy_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.species, it.dia_cm, it.height_m, it.tree_volume, it.stem_volume,
                it.branch_volume, it.gross_volume, it.net_volume, it.firewood_m3, it.firewood_chatta
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            MAX(block_name)                                         AS block_name,
            COUNT(*)                                                 AS tree_count,
            AVG(dia_cm)                                              AS avg_dbh,
            AVG(height_m)                                            AS avg_height,
            SUM(COALESCE(tree_volume, 0))                            AS total_volume,
            SUM(COALESCE(stem_volume, 0))                            AS stem_volume,
            SUM(COALESCE(branch_volume, 0))                          AS branch_volume,
            SUM(COALESCE(gross_volume, 0))                           AS gross_volume,
            SUM(COALESCE(net_volume, 0))                             AS net_volume,
            SUM(COALESCE(firewood_m3, 0))                            AS firewood_m3,
            SUM(COALESCE(firewood_chatta, 0))                        AS firewood_chatta,
            MODE() WITHIN GROUP (ORDER BY species)                   AS dominant_species
        FROM h
        GROUP BY compartment, sub_compartment
        ORDER BY
            CASE WHEN compartment = '-' THEN 1 ELSE 0 END, compartment,
            CASE WHEN sub_compartment = '-' THEN 1 ELSE 0 END, sub_compartment
    """
    )
    rows = db.execute(hierarchy_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()

    # Count distinct blocks with tree data
    blocks_analyzed = len(set(r.block_name for r in rows if r.block_name != "-"))
    result["sm_total_blocks_analyzed"] = blocks_analyzed
    result["sm_total_trees_analyzed"] = tree_count

    # ── Section 1: Spatial Hierarchy Summary ──────────────────────
    hierarchy_summary = []
    # inventory_trees.block_name falls back to the forest / polygon-boundary name when a tree
    # matched no unit; that is not a block or compartment, so never show it in the hierarchy.
    _real_units = set(block_areas) | set(unit_areas)

    def _unit_or_dash(name):
        return name if name in _real_units else "-"

    for r in rows:
        block = _unit_or_dash(r.block_name)
        area = block_areas.get(block, 0) if block != "-" else 0
        if not area:
            own = r.sub_compartment if r.sub_compartment != "-" else r.compartment
            area = unit_areas.get(own, 0) if own != "-" else 0
        tree_count_r = r.tree_count
        trees_per_ha = round(tree_count_r / area, 2) if area > 0 else None
        vol = float(r.total_volume or 0)
        vol_per_ha = round(vol / area, 2) if area > 0 else None
        hierarchy_summary.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": block,
                "tree_count": tree_count_r,
                "area_ha": round(area, 2) if area > 0 else "-",
                "trees_per_ha": trees_per_ha if trees_per_ha else "-",
                "total_volume_m3": round(vol, 2),
                "volume_per_ha": vol_per_ha if vol_per_ha else "-",
                "dominant_species": _safe_hierarchy(r.dominant_species),
                "avg_dbh_cm": round(float(r.avg_dbh or 0), 1),
                "avg_height_m": round(float(r.avg_height or 0), 1),
            }
        )
    result["sm_hierarchy_summary"] = hierarchy_summary

    # ── Section 2: Species by Hierarchy ───────────────────────────
    species_hier_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.species,
                COALESCE(NULLIF(TRIM(it.local_name), ''), '')  AS local_name,
                it.dia_cm, it.tree_volume, it.stem_volume, it.firewood_m3, it.net_volume
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            MAX(block_name)                             AS block_name,
            species, local_name,
            COUNT(*)                                         AS tree_count,
            SUM(COALESCE(stem_volume, 0))                   AS timber_m3,
            SUM(COALESCE(firewood_m3, 0))                   AS firewood_m3,
            SUM(COALESCE(tree_volume, 0))                   AS gross_volume_m3,
            SUM(COALESCE(net_volume, 0))                    AS net_volume_m3,
            AVG(dia_cm)                                     AS avg_dbh_cm,
            ROUND((COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (
                PARTITION BY compartment, sub_compartment
            ))::numeric, 1)                                    AS hierarchy_percent,
            ROUND((SUM(COALESCE(tree_volume, 0)) * 100.0 / NULLIF(SUM(SUM(COALESCE(tree_volume, 0))) OVER (), 0))::numeric, 1) AS volume_percent
        FROM h
        GROUP BY compartment, sub_compartment, species, local_name
        ORDER BY
            CASE WHEN compartment = '-' THEN 1 ELSE 0 END, compartment,
            CASE WHEN sub_compartment = '-' THEN 1 ELSE 0 END, sub_compartment,
            tree_count DESC
    """
    )
    sp_rows = db.execute(species_hier_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    species_by_hierarchy = []
    for r in sp_rows:
        species_by_hierarchy.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": _safe_hierarchy(r.block_name),
                "species": r.species or "",
                "local_name": r.local_name or "",
                "tree_count": r.tree_count,
                "hierarchy_percent": float(r.hierarchy_percent or 0),
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "firewood_m3": round(float(r.firewood_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
                "net_volume_m3": round(float(r.net_volume_m3 or 0), 2),
                "volume_percent": float(r.volume_percent or 0),
                "avg_dbh_cm": round(float(r.avg_dbh_cm or 0), 1),
            }
        )
    result["sm_species_by_hierarchy"] = species_by_hierarchy

    # ── Section 2b: Species Diversity by Block ────────────────────
    diversity_sql = text(
        """
        WITH h AS (
            SELECT
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.species
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT block_name, species, COUNT(*) AS cnt
        FROM h
        GROUP BY block_name, species
    """
    )
    div_rows = db.execute(diversity_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    block_species: Dict[str, Dict[str, int]] = {}
    for r in div_rows:
        bn = _safe_hierarchy(r.block_name)
        block_species.setdefault(bn, {})[r.species] = r.cnt

    species_diversity = []
    total_carbon_tc = 0.0
    total_co2_tco2 = 0.0
    for bn, sp_counts in sorted(block_species.items()):
        div = _compute_shannon_diversity(sp_counts)
        species_diversity.append(
            {
                "block_name": bn,
                **div,
            }
        )
    result["sm_species_diversity"] = species_diversity

    # ── Section 3: DBH by Hierarchy ───────────────────────────────
    dbh_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.dbh_class, it.stem_volume, it.firewood_m3, it.tree_volume, it.net_volume
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            MAX(block_name)                             AS block_name,
            dbh_class,
            COUNT(*)                                         AS tree_count,
            SUM(COALESCE(stem_volume, 0))                   AS timber_m3,
            SUM(COALESCE(firewood_m3, 0))                   AS firewood_m3,
            SUM(COALESCE(tree_volume, 0))                   AS gross_volume_m3,
            SUM(COALESCE(net_volume, 0))                    AS net_volume_m3,
            ROUND((COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (
                PARTITION BY compartment, sub_compartment
            ))::numeric, 1)                                    AS hierarchy_percent
        FROM h
        GROUP BY compartment, sub_compartment, dbh_class
        ORDER BY
            CASE WHEN compartment = '-' THEN 1 ELSE 0 END, compartment,
            CASE WHEN sub_compartment = '-' THEN 1 ELSE 0 END, sub_compartment,
            dbh_class
    """
    )
    dbh_rows = db.execute(dbh_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    dbh_by_hierarchy = []
    for r in dbh_rows:
        dbh_by_hierarchy.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": _safe_hierarchy(r.block_name),
                "dbh_class": DBH_CLASS_NP.get(r.dbh_class, r.dbh_class or "-"),
                "tree_count": r.tree_count,
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "firewood_m3": round(float(r.firewood_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
                "net_volume_m3": round(float(r.net_volume_m3 or 0), 2),
                "hierarchy_percent": float(r.hierarchy_percent or 0),
            }
        )
    result["sm_dbh_by_hierarchy"] = dbh_by_hierarchy

    # ── Section 3.5: DBH × Species by Hierarchy ──────────────────
    dbh_sp_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.dbh_class, it.species,
                COALESCE(NULLIF(TRIM(it.local_name), ''), '')  AS local_name,
                it.stem_volume, it.firewood_m3, it.tree_volume, it.net_volume
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            MAX(block_name)                             AS block_name,
            dbh_class, species, local_name,
            COUNT(*)                                         AS tree_count,
            SUM(COALESCE(stem_volume, 0))                   AS timber_m3,
            SUM(COALESCE(firewood_m3, 0))                   AS firewood_m3,
            SUM(COALESCE(tree_volume, 0))                   AS gross_volume_m3,
            SUM(COALESCE(net_volume, 0))                    AS net_volume_m3,
            ROUND((COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (
                PARTITION BY compartment, sub_compartment
            ))::numeric, 1)                                    AS hierarchy_percent,
            ROUND((COUNT(*) * 100.0 / SUM(COUNT(*)) OVER ())::numeric, 1) AS dbh_species_percent
        FROM h
        GROUP BY compartment, sub_compartment, dbh_class, species, local_name
        ORDER BY
            CASE WHEN compartment = '-' THEN 1 ELSE 0 END, compartment,
            CASE WHEN sub_compartment = '-' THEN 1 ELSE 0 END, sub_compartment,
            dbh_class, tree_count DESC
    """
    )
    dbh_sp_rows = db.execute(dbh_sp_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    dbh_species_by_hierarchy = []
    for r in dbh_sp_rows:
        dbh_species_by_hierarchy.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": _safe_hierarchy(r.block_name),
                "dbh_class": DBH_CLASS_NP.get(r.dbh_class, r.dbh_class or "-"),
                "species": r.species or "",
                "local_name": r.local_name or "",
                "tree_count": r.tree_count,
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "firewood_m3": round(float(r.firewood_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
                "net_volume_m3": round(float(r.net_volume_m3 or 0), 2),
                "hierarchy_percent": float(r.hierarchy_percent or 0),
                "dbh_species_percent": float(r.dbh_species_percent or 0),
            }
        )
    result["sm_dbh_species_by_hierarchy"] = dbh_species_by_hierarchy

    # ── Section 4: Stand Type by Hierarchy ────────────────────────
    stand_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.stand_type
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            MAX(block_name)                             AS block_name,
            SUM(CASE WHEN stand_type = 'Regeneration' THEN 1 ELSE 0 END) AS regeneration,
            SUM(CASE WHEN stand_type = 'Sapling' THEN 1 ELSE 0 END)      AS sapling,
            SUM(CASE WHEN stand_type = 'Pole' THEN 1 ELSE 0 END)         AS pole,
            SUM(CASE WHEN stand_type = 'Tree' THEN 1 ELSE 0 END)         AS tree_count,
            COUNT(*) AS total
        FROM h
        GROUP BY compartment, sub_compartment
        ORDER BY
            CASE WHEN compartment = '-' THEN 1 ELSE 0 END, compartment,
            CASE WHEN sub_compartment = '-' THEN 1 ELSE 0 END, sub_compartment
    """
    )
    stand_rows = db.execute(stand_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    stand_type_by_hierarchy = []
    total_regen = 0
    total_all = 0
    for r in stand_rows:
        regen_pct = round(r.regeneration * 100.0 / r.total, 1) if r.total > 0 else 0
        if regen_pct > 20:
            status = "राम्रो"
        elif regen_pct >= 10:
            status = "मध्यम"
        else:
            status = "कमजोर"
        total_regen += r.regeneration
        total_all += r.total
        stand_type_by_hierarchy.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": _safe_hierarchy(r.block_name),
                "regeneration": r.regeneration,
                "sapling": r.sapling,
                "pole": r.pole,
                "tree": r.tree_count,
                "total": r.total,
                "regeneration_percent": regen_pct,
                "structure_status": status,
            }
        )
    result["sm_stand_type_by_hierarchy"] = stand_type_by_hierarchy

    # Overall structure status
    overall_regen_pct = (
        round(total_regen * 100.0 / total_all, 1) if total_all > 0 else 0
    )
    if overall_regen_pct > 20:
        overall_status = "राम्रो"
    elif overall_regen_pct >= 10:
        overall_status = "मध्यम"
    else:
        overall_status = "कमजोर"

    good_blocks = sum(
        1 for s in stand_type_by_hierarchy if s["structure_status"] == "राम्रो"
    )
    moderate_blocks = sum(
        1 for s in stand_type_by_hierarchy if s["structure_status"] == "मध्यम"
    )
    weak_blocks = sum(
        1 for s in stand_type_by_hierarchy if s["structure_status"] == "कमजोर"
    )

    result["sm_forest_structure_status"] = {
        "overall_status": overall_status,
        "overall_regeneration_percent": overall_regen_pct,
        "total_trees_analyzed": total_all,
        "blocks_analyzed": blocks_analyzed,
        "good_structure_blocks": good_blocks,
        "moderate_structure_blocks": moderate_blocks,
        "weak_structure_blocks": weak_blocks,
    }

    # business: CFMG — carbon stock estimation per IPCC/REDD+ guidelines
    # why: uses carbon_calculate_all with wood density weighted by species composition
    carbon_by_hierarchy = []
    for r in rows:
        bn = r.block_name
        gross_vol = float(r.gross_volume or 0)
        # Get weighted average wood density for this hierarchy group
        avg_density = 0.6  # default (t/m³, same as g/cm³)
        if bn and bn != "-":
            # Simple average of species densities in this hierarchy group
            block_trees_sql = text(
                """
                SELECT it.species, COUNT(*) as cnt
                FROM public.inventory_trees it
                WHERE it.inventory_calculation_id = :inv_id
                    AND (
                        (COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                         AND COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-') = :comp
                         AND '-' = :sub_comp)
                        OR
                        (COALESCE((it.extra_columns->>'division_level')::int, 0) > :snap_top_level
                         AND COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-') = :comp
                         AND COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-') = :sub_comp)
                    )
                    AND COALESCE(NULLIF(TRIM(it.block_name), ''), '-') = :block
                GROUP BY it.species
            """
            )
            sp_cnt = db.execute(
                block_trees_sql,
                {
                    "inv_id": inv_id,
                    "snap_top_level": _INV_SNAP_BOUNDARY,
                    "comp": _safe_hierarchy(r.compartment),
                    "sub_comp": _safe_hierarchy(r.sub_compartment),
                    "block": _safe_hierarchy(bn),
                },
            ).fetchall()
            total_trees_in_group = sum(s.cnt for s in sp_cnt)
            if total_trees_in_group > 0:
                weighted_density = 0.0
                for s in sp_cnt:
                    coeff = species_coeffs.get(s.species, {})
                    density = float(coeff.get("wood_density", 0.6))
                    weighted_density += density * s.cnt / total_trees_in_group
                avg_density = weighted_density

        carbon = carbon_calculate_all(
            gross_vol, avg_density
        )  # g/cm³ = t/m³, no conversion needed
        agb_t = carbon["agb_t_per_ha"]
        bgb_t = carbon["bgb_t_per_ha"]
        biomass_t = carbon["total_biomass_t_per_ha"]
        carbon_tc = carbon["carbon_stock_tc_per_ha"]
        co2_tco2 = carbon["co2_equivalent_tco2_per_ha"]

        total_carbon_tc += carbon_tc
        total_co2_tco2 += co2_tco2

        carbon_by_hierarchy.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": _safe_hierarchy(bn),
                "gross_volume_m3": round(gross_vol, 2),
                "wood_density": round(avg_density, 1),
                "agb_t": round(agb_t, 3),
                "bgb_t": round(bgb_t, 3),
                "biomass_t": round(biomass_t, 3),
                "carbon_tc": round(carbon_tc, 3),
                "co2_tco2": round(co2_tco2, 3),
            }
        )
    result["sm_carbon_by_hierarchy"] = carbon_by_hierarchy
    result["sm_total_carbon_tc"] = round(total_carbon_tc, 3)
    result["sm_total_co2_tco2"] = round(total_co2_tco2, 3)

    # ── Section 6: Volume by Hierarchy ────────────────────────────
    result["sm_volume_by_hierarchy"] = [
        {
            "sub_compartment": h["sub_compartment"],
            "compartment": h["compartment"],
            "block_name": h["block_name"],
            "stem_volume_m3": round(float(rows[idx].stem_volume or 0), 2),
            "branch_volume_m3": round(float(rows[idx].branch_volume or 0), 2),
            "total_volume_m3": h["total_volume_m3"],
            "net_volume_m3": round(float(rows[idx].net_volume or 0), 2),
            "firewood_m3": round(float(rows[idx].firewood_m3 or 0), 2),
            "firewood_chatta": round(float(rows[idx].firewood_chatta or 0), 2),
        }
        for idx, h in enumerate(hierarchy_summary)
    ]

    # Top species by volume
    vol_species_sql = text(
        """
        SELECT
            it.species,
            COALESCE(NULLIF(TRIM(it.local_name), ''), '') AS local_name,
            SUM(COALESCE(it.tree_volume, 0)) AS total_volume
        FROM public.inventory_trees it
        WHERE it.inventory_calculation_id = :inv_id
        GROUP BY it.species, it.local_name
        ORDER BY total_volume DESC
    """
    )
    vol_sp_rows = db.execute(vol_species_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    grand_total_vol = sum(float(r.total_volume or 0) for r in vol_sp_rows)
    top_species_by_volume = []
    for r in vol_sp_rows[:10]:
        vol = float(r.total_volume or 0)
        pct = round(vol * 100.0 / grand_total_vol, 1) if grand_total_vol > 0 else 0
        top_species_by_volume.append(
            {
                "species": r.species or "",
                "local_name": r.local_name or "",
                "total_volume_m3": round(vol, 2),
                "percent": pct,
            }
        )
    result["sm_top_species_by_volume"] = top_species_by_volume

    # ── Section 7: Mother Tree Coverage ───────────────────────────
    mother_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                COALESCE(NULLIF(TRIM(it.block_name), ''), '-') AS block_name,
                it.grid_cell_id, it.remark
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
                AND it.grid_cell_id IS NOT NULL
        )
        SELECT
            compartment, sub_compartment,
            MAX(block_name)                             AS block_name,
            COUNT(DISTINCT grid_cell_id) AS grid_cells,
            SUM(CASE WHEN remark = 'Mother Tree' THEN 1 ELSE 0 END) AS mother_trees,
            SUM(CASE WHEN remark = 'Felling Tree' THEN 1 ELSE 0 END) AS felling_trees
        FROM h
        GROUP BY compartment, sub_compartment
        ORDER BY
            CASE WHEN compartment = '-' THEN 1 ELSE 0 END, compartment,
            CASE WHEN sub_compartment = '-' THEN 1 ELSE 0 END, sub_compartment
    """
    )
    mother_rows = db.execute(mother_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()

    total_grid_cells = 0
    total_mother = 0
    mother_by_hierarchy = []
    for r in mother_rows:
        gc = r.grid_cells or 0
        mt = r.mother_trees or 0
        total_grid_cells += gc
        total_mother += mt
        mother_by_hierarchy.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "block_name": _unit_or_dash(r.block_name),
                "grid_cells": gc,
                "mother_trees": mt,
                "felling_trees": r.felling_trees or 0,
                "coverage_ratio": round(mt / gc, 2) if gc > 0 else 0,
            }
        )

    grid_spacing = inv_calc.grid_spacing_meters or 50
    coverage_pct = (
        round(total_mother * 100.0 / total_grid_cells, 1) if total_grid_cells > 0 else 0
    )

    result["sm_mother_tree_coverage"] = {
        "grid_spacing_m": grid_spacing,
        "total_grid_cells": total_grid_cells,
        "cells_with_mother": total_mother,
        "coverage_percent": coverage_pct,
    }
    result["sm_mother_tree_by_hierarchy"] = mother_by_hierarchy

    # ── Section 8: Species-wise Mother Tree & Felling Tree ─────────
    species_remark_sql = text(
        """
        WITH h AS (
            SELECT
                it.species,
                COALESCE(NULLIF(TRIM(it.local_name), ''), '') AS local_name,
                it.remark,
                it.stem_volume, it.tree_volume, it.dia_cm
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
                AND it.remark IN ('Mother Tree', 'Felling Tree')
        )
        SELECT
            species, local_name, remark,
            COUNT(*) AS tree_count,
            SUM(COALESCE(stem_volume, 0)) AS timber_m3,
            SUM(COALESCE(tree_volume, 0)) AS gross_volume_m3,
            AVG(dia_cm) AS avg_dbh_cm
        FROM h
        GROUP BY species, local_name, remark
        ORDER BY remark, tree_count DESC
    """
    )
    sr_rows = db.execute(species_remark_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()

    mother_by_species = []
    felling_by_species = []
    total_mother_trees = 0
    total_felling_trees = 0
    for r in sr_rows:
        entry = {
            "species": r.species or "",
            "local_name": r.local_name or "",
            "tree_count": r.tree_count,
            "timber_m3": round(float(r.timber_m3 or 0), 2),
            "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
            "avg_dbh_cm": round(float(r.avg_dbh_cm or 0), 1),
        }
        if r.remark == "Mother Tree":
            total_mother_trees += r.tree_count
            mother_by_species.append(entry)
        elif r.remark == "Felling Tree":
            total_felling_trees += r.tree_count
            felling_by_species.append(entry)

    # Add percent to each entry
    for entry in mother_by_species:
        entry["percent"] = (
            round(entry["tree_count"] * 100.0 / total_mother_trees, 1)
            if total_mother_trees > 0
            else 0
        )
    for entry in felling_by_species:
        entry["percent"] = (
            round(entry["tree_count"] * 100.0 / total_felling_trees, 1)
            if total_felling_trees > 0
            else 0
        )

    result["sm_mother_tree_by_species"] = mother_by_species
    result["sm_felling_tree_by_species"] = felling_by_species
    result["sm_mother_felling_summary"] = {
        "total_mother_trees": total_mother_trees,
        "total_felling_trees": total_felling_trees,
        "total_trees": total_mother_trees + total_felling_trees,
        "mother_percent": (
            round(
                total_mother_trees * 100.0 / (total_mother_trees + total_felling_trees),
                1,
            )
            if (total_mother_trees + total_felling_trees) > 0
            else 0
        ),
        "felling_percent": (
            round(
                total_felling_trees
                * 100.0
                / (total_mother_trees + total_felling_trees),
                1,
            )
            if (total_mother_trees + total_felling_trees) > 0
            else 0
        ),
    }

    # ── Section 9: Hierarchy + Remark breakdown (for table columns) ──
    hier_remark_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                it.remark
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            SUM(CASE WHEN remark = 'Mother Tree' THEN 1 ELSE 0 END) AS mother_trees,
            SUM(CASE WHEN remark = 'Felling Tree' THEN 1 ELSE 0 END) AS felling_trees,
            COUNT(*) AS total_trees
        FROM h
        GROUP BY compartment, sub_compartment
    """
    )
    hr_rows = db.execute(hier_remark_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    hier_remark_map = {}
    for r in hr_rows:
        key = f"{_safe_hierarchy(r.compartment)}|{_safe_hierarchy(r.sub_compartment)}"
        hier_remark_map[key] = {
            "mother_trees": r.mother_trees or 0,
            "felling_trees": r.felling_trees or 0,
        }
    result["sm_hierarchy_remark_breakdown"] = hier_remark_map

    # ── Section 10: Species + Hierarchy + Remark breakdown ─────────
    sp_hier_remark_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                it.species,
                COALESCE(NULLIF(TRIM(it.local_name), ''), '') AS local_name,
                it.remark, it.stem_volume, it.tree_volume, it.dia_cm
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            species, local_name, remark,
            COUNT(*) AS tree_count,
            SUM(COALESCE(stem_volume, 0)) AS timber_m3,
            SUM(COALESCE(tree_volume, 0)) AS gross_volume_m3,
            AVG(dia_cm) AS avg_dbh_cm
        FROM h
        GROUP BY compartment, sub_compartment, species, local_name, remark
        ORDER BY compartment, sub_compartment, tree_count DESC
    """
    )
    shr_rows = db.execute(sp_hier_remark_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    species_hier_remark = []
    for r in shr_rows:
        species_hier_remark.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "species": r.species or "",
                "local_name": r.local_name or "",
                "remark": r.remark or "",
                "tree_count": r.tree_count,
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
                "avg_dbh_cm": round(float(r.avg_dbh_cm or 0), 1),
            }
        )
    result["sm_species_hier_remark"] = species_hier_remark

    # ── Section 11: DBH + Hierarchy + Remark breakdown ─────────────
    dbh_hier_remark_sql = text(
        """
        WITH h AS (
            SELECT
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'parent_compartment_name'), ''), '-')
                END AS compartment,
                CASE
                    WHEN COALESCE((it.extra_columns->>'division_level')::int, 0) <= :snap_top_level
                    THEN '-'
                    ELSE COALESCE(NULLIF(TRIM(it.extra_columns->>'compartment_name'), ''), '-')
                END AS sub_compartment,
                it.dbh_class, it.remark, it.stem_volume, it.tree_volume
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
        )
        SELECT
            compartment, sub_compartment,
            dbh_class, remark,
            COUNT(*) AS tree_count,
            SUM(COALESCE(stem_volume, 0)) AS timber_m3,
            SUM(COALESCE(tree_volume, 0)) AS gross_volume_m3
        FROM h
        GROUP BY compartment, sub_compartment, dbh_class, remark
        ORDER BY compartment, sub_compartment, dbh_class
    """
    )
    dhr_rows = db.execute(dbh_hier_remark_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()
    dbh_hier_remark = []
    for r in dhr_rows:
        dbh_hier_remark.append(
            {
                "sub_compartment": _safe_hierarchy(r.sub_compartment),
                "compartment": _safe_hierarchy(r.compartment),
                "dbh_class": DBH_CLASS_NP.get(r.dbh_class, r.dbh_class or "-"),
                "remark": r.remark or "",
                "tree_count": r.tree_count,
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
            }
        )
    result["sm_dbh_hier_remark"] = dbh_hier_remark

    # business: CFMG — felling tree analysis; DBH >= 30 cm per felling criteria
    # constraint: only trees marked 'Felling Tree' with DBH >= 30 cm qualify for harvest
    felling_sql = text(
        """
        WITH h AS (
            SELECT
                it.dbh_class, it.species,
                COALESCE(NULLIF(TRIM(it.local_name), ''), '') AS local_name,
                it.stem_volume, it.branch_volume, it.tree_volume, it.net_volume,
                it.firewood_m3, it.firewood_chatta, it.dia_cm
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
                AND it.remark = 'Felling Tree'
                AND it.dia_cm >= 30
        )
        SELECT
            dbh_class,
            COUNT(*) AS tree_count,
            SUM(COALESCE(stem_volume, 0)) AS timber_m3,
            SUM(COALESCE(branch_volume, 0)) AS firewood_m3,
            SUM(COALESCE(tree_volume, 0)) AS gross_volume_m3,
            SUM(COALESCE(net_volume, 0)) AS net_volume_m3,
            SUM(COALESCE(firewood_m3, 0)) AS fuelwood_m3,
            SUM(COALESCE(firewood_chatta, 0)) AS fuelwood_chatta,
            AVG(dia_cm) AS avg_dbh_cm
        FROM h
        GROUP BY dbh_class
        ORDER BY
            CASE
                WHEN dbh_class ~ '^[0-9]' THEN CAST(REGEXP_REPLACE(dbh_class, '[^0-9].*', '', 'g') AS INTEGER)
                ELSE 9999
            END
    """
    )
    felling_dbh_rows = db.execute(felling_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()

    # Species breakdown for felling trees (DBH >= 30)
    felling_sp_sql = text(
        """
        WITH h AS (
            SELECT
                it.species,
                COALESCE(NULLIF(TRIM(it.local_name), ''), '') AS local_name,
                it.stem_volume, it.branch_volume, it.tree_volume, it.net_volume,
                it.firewood_m3, it.firewood_chatta, it.dia_cm
            FROM public.inventory_trees it
            WHERE it.inventory_calculation_id = :inv_id
                AND it.remark = 'Felling Tree'
                AND it.dia_cm >= 30
        )
        SELECT
            species, local_name,
            COUNT(*) AS tree_count,
            SUM(COALESCE(stem_volume, 0)) AS timber_m3,
            SUM(COALESCE(branch_volume, 0)) AS firewood_m3,
            SUM(COALESCE(tree_volume, 0)) AS gross_volume_m3,
            SUM(COALESCE(net_volume, 0)) AS net_volume_m3,
            AVG(dia_cm) AS avg_dbh_cm
        FROM h
        GROUP BY species, local_name
        ORDER BY tree_count DESC
    """
    )
    felling_sp_rows = db.execute(felling_sp_sql, {"inv_id": inv_id, "snap_top_level": _INV_SNAP_BOUNDARY}).fetchall()

    # Build felling DBH table
    felling_dbh_summary = []
    total_felling_eligible = 0
    total_timber = 0.0
    total_firewood = 0.0
    total_gross = 0.0
    total_net = 0.0
    total_fuelwood = 0.0
    total_chatta = 0.0
    for r in felling_dbh_rows:
        tc = r.tree_count or 0
        total_felling_eligible += tc
        total_timber += float(r.timber_m3 or 0)
        total_firewood += float(r.firewood_m3 or 0)
        total_gross += float(r.gross_volume_m3 or 0)
        total_net += float(r.net_volume_m3 or 0)
        total_fuelwood += float(r.fuelwood_m3 or 0)
        total_chatta += float(r.fuelwood_chatta or 0)
        felling_dbh_summary.append(
            {
                "dbh_class": DBH_CLASS_NP.get(r.dbh_class, r.dbh_class or "-"),
                "tree_count": tc,
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "firewood_m3": round(float(r.firewood_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
                "net_volume_m3": round(float(r.net_volume_m3 or 0), 2),
                "fuelwood_m3": round(float(r.fuelwood_m3 or 0), 2),
                "fuelwood_chatta": round(float(r.fuelwood_chatta or 0), 2),
                "avg_dbh_cm": round(float(r.avg_dbh_cm or 0), 1),
            }
        )
    for entry in felling_dbh_summary:
        entry["percent"] = (
            round(entry["tree_count"] * 100.0 / total_felling_eligible, 1)
            if total_felling_eligible > 0
            else 0
        )

    # Build felling species table
    felling_species_summary = []
    for r in felling_sp_rows:
        tc = r.tree_count or 0
        felling_species_summary.append(
            {
                "species": r.species or "",
                "local_name": r.local_name or "",
                "tree_count": tc,
                "timber_m3": round(float(r.timber_m3 or 0), 2),
                "firewood_m3": round(float(r.firewood_m3 or 0), 2),
                "gross_volume_m3": round(float(r.gross_volume_m3 or 0), 2),
                "net_volume_m3": round(float(r.net_volume_m3 or 0), 2),
                "avg_dbh_cm": round(float(r.avg_dbh_cm or 0), 1),
            }
        )
    for entry in felling_species_summary:
        entry["percent"] = (
            round(entry["tree_count"] * 100.0 / total_felling_eligible, 1)
            if total_felling_eligible > 0
            else 0
        )

    result["sm_felling_dbh_analysis"] = felling_dbh_summary
    result["sm_felling_species_analysis"] = felling_species_summary
    result["sm_felling_totals"] = {
        "tree_count": total_felling_eligible,
        "timber_m3": round(total_timber, 2),
        "firewood_m3": round(total_firewood, 2),
        "gross_volume_m3": round(total_gross, 2),
        "net_volume_m3": round(total_net, 2),
        "fuelwood_m3": round(total_fuelwood, 2),
        "fuelwood_chatta": round(total_chatta, 2),
    }

    # every unit by its own current name, as the attribute table shows it (before the legends below read the labels)
    relabel_tree_analysis_units(
        result,
        unit_label_map(db.query(ForestBlock).filter(ForestBlock.calculation_id == calc_uuid).all()),
    )

    # --- Legend data for chart symbolization ---
    from app.utils.number_format import format_devanagari as _fmt_num

    def _build_hierarchy_legend(data_rows):
        legend = []
        for i, r in enumerate(data_rows, 1):
            sub = (r.get("sub_compartment") or "-").strip()
            comp = (r.get("compartment") or "-").strip()
            label = sub if sub and sub != "-" else comp
            if not label or label == "-":
                label = "-"
            legend.append({"symbol": _fmt_num(i, 0), "label": label})
        return legend

    result["sm_mf_hierarchy_legend"] = _build_hierarchy_legend(
        result.get("sm_hierarchy_summary", [])
    )
    result["sm_stand_type_legend"] = _build_hierarchy_legend(
        result.get("sm_stand_type_by_hierarchy", [])
    )
    result["sm_carbon_legend"] = _build_hierarchy_legend(
        result.get("sm_carbon_by_hierarchy", [])
    )
    result["sm_volume_legend"] = _build_hierarchy_legend(
        result.get("sm_volume_by_hierarchy", [])
    )

    mother_sp = result.get("sm_mother_tree_by_species", [])
    felling_sp = result.get("sm_felling_tree_by_species", [])
    all_species = list(
        dict.fromkeys(
            [r.get("species", "") for r in mother_sp]
            + [r.get("species", "") for r in felling_sp]
        )
    )[:10]
    result["sm_mf_species_legend"] = [
        {"symbol": _fmt_num(i, 0), "label": sp} for i, sp in enumerate(all_species, 1)
    ]

    felling_sp_data = result.get("sm_felling_species_analysis", [])
    result["sm_felling_species_legend"] = [
        {"symbol": _fmt_num(i, 0), "label": r.get("species", "")}
        for i, r in enumerate(felling_sp_data[:10], 1)
    ]

    return result
