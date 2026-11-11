"""Map generation service for 10-year management plans.
# business: CFMG — management plan requires boundary + land cover maps

Generates high-quality matplotlib maps of forest boundaries, blocks,
land cover, elevation, slope, and other raster analysis layers for
embedding in management plan DOCX documents. Supports cached tile
rendering via contextily and the internal tile service.

Key function:
    generate_standard_map() — produces a map image for any layer type.

See also:
    .plan_chapter_builders — embeds maps in document chapters
    app.services.tile_service — cached tile rendering backend
"""

import io
import math
import os
import hashlib
import logging
from typing import Any, Optional, Tuple, List, Dict
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text
from shapely.geometry import Polygon as ShapelyPolygon, MultiPolygon, shape
from geoalchemy2.shape import to_shape

import matplotlib

matplotlib.use("Agg")  # why: Agg matplotlib backend for headless server
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
from PIL import Image as PILImage

from app.utils.map_grid import compute_snapped_grid

import contextily as cx

from ..tile_service import get_tile_service

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

MAP_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploads",
    "maps_cache",
)  # NOTE: MAP_CACHE_DIR under uploads/


def _map_cache_path(calculation_id: UUID, layer_name: str, dpi: int = None) -> str:
    if dpi is None:
        import sys

        dpi = sys.modules[__name__].DPI
    cid = str(calculation_id)
    sub = os.path.join(MAP_CACHE_DIR, cid)
    os.makedirs(sub, exist_ok=True)
    return os.path.join(sub, f"{layer_name}_dpi{dpi}.png")


def _map_cache_get(
    calculation_id: UUID, layer_name: str, dpi: int = None
) -> Optional[io.BytesIO]:
    if dpi is None:
        import sys

        dpi = sys.modules[__name__].DPI
    path = _map_cache_path(calculation_id, layer_name, dpi)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                buf = io.BytesIO(f.read())
            logger.info(f"Map cache HIT: {layer_name} for {calculation_id} dpi={dpi}")
            return buf
        except Exception as e:
            logger.warning(f"Map cache read failed: {e}")
    return None


def _map_cache_set(
    calculation_id: UUID, layer_name: str, buf: io.BytesIO, dpi: int = None
):
    if dpi is None:
        import sys

        dpi = sys.modules[__name__].DPI
    buf.seek(0, 2)
    size = buf.tell()
    if size < 5000:
        logger.warning(
            f"Map cache SKIPPED (too small: {size}B): {layer_name} for {calculation_id}"
        )
        buf.seek(0)
        return
    buf.seek(0)
    path = _map_cache_path(calculation_id, layer_name, dpi)
    try:
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        logger.info(
            f"Map cache SAVED ({size/1024:.0f}KB): {layer_name} -> {path} dpi={dpi}"
        )
    except Exception as e:
        logger.warning(f"Map cache write failed: {e}")


def clear_map_cache(
    calculation_id: Optional[UUID] = None, layer_name: Optional[str] = None
):
    """Clear cached map images for a calculation, layer, or all maps."""
    if calculation_id:
        sub = os.path.join(MAP_CACHE_DIR, str(calculation_id))
        if layer_name:
            import glob

            for p in glob.glob(os.path.join(sub, f"{layer_name}_dpi*.png")):
                os.remove(p)
                logger.info(f"Map cache CLEARED: {os.path.basename(p)}")
        elif os.path.isdir(sub):
            import shutil

            shutil.rmtree(sub)
            logger.info(f"Map cache CLEARED all for {calculation_id}")
    elif os.path.isdir(MAP_CACHE_DIR):
        import shutil

        for entry in os.listdir(MAP_CACHE_DIR):
            shutil.rmtree(os.path.join(MAP_CACHE_DIR, entry))
        logger.info("Map cache CLEARED all")


# Devanagari font resolution is centralised in app.core.fonts (bundled font →
# fc-match → matplotlib → Windows). See THEMATIC_MAP_VARIABLES_PLAN §3.8 / P0.
from app.core.fonts import (
    configure_matplotlib_devanagari,
    dev_font_prop,
    devanagari_font_path,
)

configure_matplotlib_devanagari()
_DEVANAGARI_FONT = devanagari_font_path()


def _dev_fontprop(size: int = 14):
    return dev_font_prop(size)


FIG_SIZE_MM = 150
FIG_SIZE_INCHES = (FIG_SIZE_MM / 25.4, FIG_SIZE_MM / 25.4)
TILE_SIZE = 256
DPI = 150  # constraint: A4 landscape, 300 DPI; default 150 for preview speed
RASTER_ALPHA = 0.55
BOUNDARY_FILL_ALPHA = 0.25
BLOCK_FILL_ALPHA = 0.20

BASEMAP_SOURCES = {
    "boundary": cx.providers.OpenStreetMap.Mapnik,
    "slope": cx.providers.OpenTopoMap,
    "aspect": cx.providers.OpenTopoMap,
    "dem": cx.providers.OpenTopoMap,
    "forest_type": cx.providers.OpenStreetMap.Mapnik,
    "landcover": cx.providers.OpenStreetMap.Mapnik,
    "landcover_1984": cx.providers.OpenStreetMap.Mapnik,
    "forest_health": cx.providers.OpenStreetMap.Mapnik,
    "canopy": cx.providers.OpenStreetMap.Mapnik,
    "biomass": cx.providers.OpenStreetMap.Mapnik,
    "soil_texture": cx.providers.OpenStreetMap.Mapnik,
    "sampling_plot": cx.providers.OpenStreetMap.Mapnik,
    "sampling_plot_topo": cx.providers.OpenTopoMap,
    "sampling_plot_satellite": cx.providers.Esri.WorldImagery,
    "boundary_satellite": cx.providers.Esri.WorldImagery,
    "fieldbook": cx.providers.OpenTopoMap,
    "usergroup": cx.providers.OpenTopoMap,
    "subarea": cx.providers.OpenTopoMap,
    "compartment": cx.providers.OpenStreetMap.Mapnik,
    "sub_compartment": cx.providers.OpenStreetMap.Mapnik,
    # §3.5.2 muted "light gray canvas" ground for choropleths/glyphs — quiet
    # roads/rivers/towns without fighting the data. Esri's is free + keyless
    # (CartoDB Positron now demands an API key).
    "canvas_light": cx.providers.Esri.WorldGrayCanvas,
    # thematic §3.5.2 keys. imagery = Esri satellite (used by the terrain
    # choropleths). hillshade/topo = OpenTopoMap (Esri WorldShadedRelief has
    # no tiles over lowland Nepal at these zooms) — kept for the sparse glyph /
    # vector terrain maps where a light topo ground reads best.
    "hillshade": cx.providers.OpenTopoMap,
    "imagery": cx.providers.Esri.WorldImagery,
    "topo": cx.providers.OpenTopoMap,
}

LAYER_LABELS = {
    "boundary": {"ne": "सिमाना नक्सा", "en": "Boundary Map"},
    "forest_type": {"ne": "वन प्रकार नक्सा", "en": "Forest Type Map"},
    "forest_health": {"ne": "वन स्वास्थ्य नक्सा", "en": "Forest Health Map"},
    "slope": {"ne": "भिरालो नक्सा", "en": "Slope Map"},
    "biomass": {"ne": "बायोमास नक्सा", "en": "Biomass Map"},
    "landcover": {"ne": "भू-आवरण नक्सा", "en": "Land Cover Map"},
    "landcover_1984": {"ne": "सन् १९८४ को भू-उपयोग नक्सा", "en": "Land Use Map (1984)"},
    "soil_texture": {"ne": "माटो बनावट नक्सा", "en": "Soil Texture Map"},
    "dem": {"ne": "उचाइ नक्सा", "en": "Elevation Map"},
    "aspect": {"ne": "दिशा नक्सा", "en": "Aspect Map"},
    "canopy": {"ne": "वन छाना नक्सा", "en": "Canopy Cover Map"},
    "boundary_satellite": {"ne": "सामुदायिक वनको अवस्थिति (उपग्रह तस्वीर)", "en": "Boundary on satellite imagery"},
    "sampling_plot": {"ne": "नमुना प्लट नक्सा", "en": "Sample Plot Map"},
    "sampling_plot_topo": {
        "ne": "स्थलाकृतिक नमुना प्लट नक्सा",
        "en": "Sample Plot Map (Topo)",
    },
    "sampling_plot_satellite": {
        "ne": "उपग्रह नमुना प्लट नक्सा",
        "en": "Sample Plot Map (Satellite)",
    },
    "fieldbook": {"ne": "फिल्डबुक बाटो नक्सा", "en": "Fieldbook Path Map"},
    "usergroup": {"ne": "उपयोगकर्ता समूह नक्सा", "en": "User Group Map"},
    "subarea": {"ne": "उप-क्षेत्र नक्सा", "en": "Sub-Area Map"},
    "compartment": {"ne": "कम्पार्टमेन्ट नक्सा", "en": "Compartment Map"},
    "sub_compartment": {"ne": "उप-कम्पार्टमेन्ट नक्सा", "en": "Sub-Compartment Map"},
}

_SAMPLING_PLOT_LAYERS = {
    "sampling_plot",
    "sampling_plot_topo",
    "sampling_plot_satellite",
}

BLOCK_COLORS = [
    "#2e7d32",
    "#1565c0",
    "#795548",
    "#f9a825",
    "#6a1b9a",
    "#00838f",
    "#e65100",
    "#c62828",
]

SUB_AREA_CATEGORIES = [
    {
        "value": "protected",
        "label": "संरक्षित क्षेत्र",
        "color": "#ef4444",
        "is_excluded": False,
    },
    {
        "value": "plantation",
        "label": "बृक्षारोपण क्षेत्र",
        "color": "#10b981",
        "is_excluded": False,
    },
    {
        "value": "pro-poor",
        "label": "गरिव तथा विपन्नको लागी",
        "color": "#f59e0b",
        "is_excluded": False,
    },
    {
        "value": "religious",
        "label": "धार्मीक क्षेत्र",
        "color": "#8b5cf6",
        "is_excluded": False,
    },
    {
        "value": "biodiversity",
        "label": "जैविक विविधता क्षेत्र",
        "color": "#06b6d4",
        "is_excluded": False,
    },
    {
        "value": "tourist",
        "label": "पर्यटन क्षेत्र",
        "color": "#ec4899",
        "is_excluded": False,
    },
    {
        "value": "office",
        "label": "कार्यालय परिसर",
        "color": "#6b7280",
        "is_excluded": False,
    },
    {
        "value": "private_land",
        "label": "निजि जग्गा (बहिस्कृत)",
        "color": "#dc2626",
        "is_excluded": True,
    },
    {
        "value": "agroforestry",
        "label": "कृषिवन क्षेत्र",
        "color": "#84cc17",
        "is_excluded": False,
    },
    {
        "value": "tree_strata",
        "label": "धेरै ठुला रूख भएको क्षेत्र",
        "color": "#15803d",
        "is_excluded": False,
    },
    {
        "value": "water_hole",
        "label": "पानी मूहान",
        "color": "#0ea5e9",
        "is_excluded": False,
    },
    {
        "value": "wildlife_corridor",
        "label": "जैविक मार्ग",
        "color": "#a855f7",
        "is_excluded": False,
    },
]


def _get_forest_bbox(
    db: Session, calculation_id: UUID
) -> Optional[Tuple[float, float, float, float]]:
    from ...models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.boundary_geom:
        return None
    geom = to_shape(calc.boundary_geom)
    return geom.bounds


def _get_forest_geometry(db: Session, calculation_id: UUID):
    from ...models.calculation import Calculation
    from geoalchemy2.shape import to_shape

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.boundary_geom:
        return None
    return to_shape(calc.boundary_geom)


def _get_blocks_with_geometry(db: Session, calculation_id: UUID) -> List[Dict]:
    from ...models.forest_block import ForestBlock
    from ..forest_units.model import DEPTH_SUB, DEPTH_TOP_BLOCK

    # Migration 094 puts top-level blocks AND top-level compartments at the same depth (1), so the
    # is_compartment guard - absent here before, when blocks were the only rows at depth 0 - is now required
    # (I10: never test depth without the branch).
    blocks = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.is_compartment.isnot(True),
            ForestBlock.division_level == DEPTH_TOP_BLOCK,
        )
        .order_by(ForestBlock.index)
        .all()
    )

    result = []
    for b in blocks:
        try:
            geom = to_shape(b.geometry)
            centroid = geom.centroid
            result.append(
                {
                    "name": b.name,
                    "geometry": geom,
                    "centroid": centroid,
                    "area_ha": b.area_hectares,
                }
            )
        except Exception as e:
            logger.warning(f"Could not parse geometry for block {b.name}: {e}")
    return result


def _get_compartments_with_geometry(db: Session, calculation_id: UUID) -> List[Dict]:
    from ...models.forest_block import ForestBlock
    from uuid import UUID as _UUID

    compartments = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.is_compartment == True,
        )
        .order_by(
            ForestBlock.parent_block_id,
            ForestBlock.division_level,
            ForestBlock.display_order,
        )
        .all()
    )

    if not compartments:
        return []

    parent_ids = set()
    for c in compartments:
        if c.parent_block_id:
            parent_ids.add(str(c.parent_block_id))
    parent_map = {}
    if parent_ids:
        for pb in (
            db.query(ForestBlock)
            .filter(ForestBlock.id.in_([_UUID(pid) for pid in parent_ids]))
            .all()
        ):
            parent_map[str(pb.id)] = pb.name

    result = []
    for c in compartments:
        try:
            geom = to_shape(c.geometry)
            centroid = geom.centroid
            pid = str(c.parent_block_id) if c.parent_block_id else ""
            result.append(
                {
                    "id": str(c.id),
                    "name": c.name or "",
                    "code": c.compartment_code or "",
                    "parent_block_id": pid,
                    "parent_block_name": parent_map.get(pid, ""),
                    "division_level": c.division_level or 1,
                    "geometry": geom,
                    "centroid": centroid,
                    "area_ha": c.area_hectares or 0,
                }
            )
        except Exception as e:
            logger.warning(f"Could not parse geometry for compartment {c.name}: {e}")
    return result


def _get_leaf_units_with_geometry(db: Session, calculation_id: UUID) -> List[Dict]:
    """The forest's analysis units with geometry: the LEAF view of ``forest_units`` (FS-1a.8) - every unit that
    is not divided further, whichever branch. Use this wherever a map or a zonal summary needs "the units of the
    forest"; the ``_get_blocks_`` / ``_get_compartments_with_geometry`` helpers above draw the hierarchy (block
    outlines, compartments with their parents) and are not a unit set."""
    from ..forest_units import queries as forest_unit_queries

    result = []
    for u in forest_unit_queries.units(
        db, calculation_id, forest_unit_queries.View.LEAF
    ):
        try:
            geom = u.shape
            result.append(
                {
                    "id": str(u.id),
                    "name": u.name or "",
                    "block_name": u.block_name,
                    "parent_id": str(u.parent_id) if u.parent_id else "",
                    "depth": u.depth,
                    "geometry": geom,
                    "centroid": geom.centroid,
                    "area_ha": u.area_ha,
                }
            )
        except (
            Exception
        ) as e:  # noqa: BLE001 -- one bad geometry must not drop the other units
            logger.warning(f"Could not parse geometry for unit {u.name}: {e}")
    return result


def _get_sub_areas_with_geometry(db: Session, calculation_id: UUID) -> List[Dict]:
    from ...models.calculation import Calculation
    from shapely.geometry import shape as shapely_shape

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.result_data:
        return []

    from ...core.sub_area_kinds import real_sub_areas

    raw_sub_areas = real_sub_areas(calc.result_data.get("sub_areas", []))  # the zones; a strip has its own map
    if not raw_sub_areas:
        return []

    result = []
    for sa in raw_sub_areas:
        try:
            geo_dict = sa.get("geometry")
            if not geo_dict:
                continue
            geom = shapely_shape(geo_dict)
            centroid = geom.centroid
            category = sa.get("category", "")
            name = sa.get("name", "")
            is_excluded = sa.get("is_excluded", sa.get("isExcluded", False))
            area_ha = sa.get("area_hectares", sa.get("area", 0))
            cat_info = next(
                (c for c in SUB_AREA_CATEGORIES if c["value"] == category), None
            )
            result.append(
                {
                    "name": name,
                    "category": category,
                    "geometry": geom,
                    "centroid": centroid,
                    "area_ha": area_ha,
                    "is_excluded": is_excluded,
                    "color": cat_info["color"] if cat_info else "#9e9e9e",
                    "label_np": cat_info["label"] if cat_info else category,
                }
            )
        except Exception as e:
            logger.warning(
                f"Could not parse geometry for sub-area '{sa.get('name', '')}': {e}"
            )
    return result


def _get_sample_plots(db: Session, calculation_id: UUID) -> List[Dict]:
    from ...models.sampling import SamplingDesign
    from shapely import wkt as shapely_wkt

    designs = (
        db.query(SamplingDesign)
        .filter(
            SamplingDesign.calculation_id == calculation_id,
            SamplingDesign.points_geometry.isnot(None),
        )
        .order_by(SamplingDesign.created_at)
        .all()
    )
    if not designs:
        return []

    design = designs[0]

    # Prefer cached points_data (has lon/lat, point_index, block_name)
    cached = design.points_data or {}
    cached_points = cached.get("points") if isinstance(cached, dict) else None
    if cached_points:
        plots = []
        for pt in cached_points:
            lon = pt.get("longitude") or pt.get("lon")
            lat = pt.get("latitude") or pt.get("lat")
            if lon is None or lat is None:
                continue
            plots.append(
                {
                    "lon": float(lon),
                    "lat": float(lat),
                    "label": str(pt.get("plot_number", pt.get("point_index", ""))),
                    "block_name": pt.get("block_name", ""),
                }
            )
        return plots

    # Fallback: extract from points_geometry MULTIPOINT
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
    plots = []
    for i, point in enumerate(multipoint.geoms):
        block_info = next(
            (b for b in block_assignment if b.get("point_index") == i), None
        )
        plots.append(
            {
                "lon": point.x,
                "lat": point.y,
                "label": str(i + 1),
                "block_name": (block_info or {}).get("block_name", ""),
            }
        )
    return plots


def _get_activity_features(
    db: Session,
    calculation_id: UUID,
    year: Optional[int] = None,
    kind: Optional[str] = None,
) -> List[Dict]:
    """Drawn point/line/polygon features from the operational plan's activities
    (THEMATIC_MAP_VARIABLES_PLAN §3.4B / P7).

    Each dict: ``{geometry (shapely), feature_type, kind (canonical), raw_kind,
    label, years (list[int]), activity_name}``. ``year`` keeps only features
    whose activity is planned that plan year (effective quantity or budget > 0,
    ``yearly_plan_rules``); ``kind`` keeps only that canonical kind.
    """
    try:
        from app.models.yearly_activities import (
            ActivityDrawnFeature,
            ActivityYearDetail,
            PotentialActivity,
            ProposedYearlyActivity,
        )
        from app.services.operational_plan.feature_kinds import resolve_feature_kind
        from app.services.yearly_plan_rules import planned_years
    except Exception:  # noqa: BLE001
        return []

    rows = (
        db.query(ActivityDrawnFeature, ProposedYearlyActivity, PotentialActivity)
        .join(
            ProposedYearlyActivity,
            ActivityDrawnFeature.proposed_activity_id == ProposedYearlyActivity.id,
        )
        .outerjoin(
            PotentialActivity,
            ProposedYearlyActivity.potential_activity_id == PotentialActivity.id,
        )
        .filter(
            ActivityDrawnFeature.calculation_id == calculation_id,
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .all()
    )

    line_ids = {pa.id for _f, pa, _p in rows}
    year_rows: Dict[Any, Dict[int, Any]] = {}
    if line_ids:
        for yd in db.query(ActivityYearDetail).filter(
            ActivityYearDetail.proposed_activity_id.in_(line_ids)
        ):
            year_rows.setdefault(yd.proposed_activity_id, {})[yd.year_number] = yd

    out: List[Dict] = []
    for feat, pa, pot in rows:
        # the years the activity is planned, by effective values (a real 0 / 0 year is not
        # planned) — ``year_numbers`` is no longer a source (YEARLY_ACTIVITIES plan F11)
        years = planned_years(
            pa.default_quantity, pa.default_yearly_budget, year_rows.get(pa.id, {})
        )
        if year is not None and year not in years:
            continue
        props = feat.properties or {}
        raw_kind = props.get("kind") or props.get("feature_kind") or ""
        canon = resolve_feature_kind(
            raw_kind, getattr(pot, "map_kind", None), feat.feature_type
        )
        if kind is not None and canon != kind:
            continue
        try:
            geom = to_shape(feat.geometry)
        except Exception:  # noqa: BLE001
            continue
        out.append(
            {
                "geometry": geom,
                "feature_type": feat.feature_type,
                "kind": canon,
                "raw_kind": raw_kind,
                "label": props.get("label") or props.get("name") or "",
                "years": years,
                "activity_name": (
                    getattr(pot, "activities", None)
                    or getattr(pot, "program", "")
                    or ""
                ),
            }
        )
    return out


def _get_usergroup_extent(db: Session, calculation_id: UUID):
    """Returns user group extent as Shapely polygon, or None."""
    from app.models.user_group import UserGroupExtent
    from geoalchemy2.shape import to_shape

    # P7f: the group is every polygon, so the map draws their UNION. This used
    # to take `.first()`, which drew one arbitrary polygon of a multi-polygon
    # group while the report still read as though the whole group were shown.
    from shapely.ops import unary_union
    shapes = [
        to_shape(row.extent_geometry)
        for row in db.query(UserGroupExtent)
        .filter(UserGroupExtent.calculation_id == calculation_id)
        .all()
        if row.extent_geometry is not None
    ]
    shapes = [s for s in shapes if s is not None and not s.is_empty]
    if not shapes:
        return None
    try:
        return shapes[0] if len(shapes) == 1 else unary_union(shapes)
    except Exception:
        logger.exception(
            "stored map extent unreadable - the map will fall back to a "
            "computed extent instead of the one that was saved"
        )
        return None


def _get_usergroup_settlements(db: Session, calculation_id: UUID) -> List[Dict]:
    """Returns [{name, lat, lon, building_count}] grouped by settlement."""
    from app.models.user_group import UserGroupExtent, UserGroupBuilding

    extent_ids = [
        r[0]
        for r in db.query(UserGroupExtent.id)
        .filter(UserGroupExtent.calculation_id == calculation_id)
        .all()
    ]
    if not extent_ids:
        return []
    # P7f: buildings are keyed to the polygon that CONTAINS them, so a group
    # made of several polygons has its settlements spread across several
    # `extent_id`s. This used to filter on the one extent `.first()` returned,
    # so a DOCX operational plan would silently omit every settlement outside
    # that single polygon - the worst kind of wrong, because the document still
    # reads as if the whole group were covered.
    rows = (
        db.query(UserGroupBuilding)
        .filter(
            UserGroupBuilding.extent_id.in_(extent_ids),
            UserGroupBuilding.buildings_geojson.isnot(None),
        )
        .order_by(UserGroupBuilding.settlement_name)
        .all()
    )
    seen = {}
    for r in rows:
        name = r.settlement_name or "Unknown"
        if name not in seen:
            geo = r.buildings_geojson or []
            ref_lat = geo[0].get("lat") if geo else None
            ref_lon = geo[0].get("lon") if geo else None
            seen[name] = {
                "name": name,
                "lat": ref_lat,
                "lon": ref_lon,
                "building_count": sum(
                    sum(1 for bg in (b.buildings_geojson or []))
                    for b in rows
                    if (b.settlement_name or "Unknown") == name
                ),
            }
    return list(seen.values())


def _get_usergroup_buildings(db: Session, calculation_id: UUID) -> List[Dict]:
    """Returns [{lat, lon, area}] flattened from all UserGroupBuilding records."""
    from app.models.user_group import UserGroupExtent, UserGroupBuilding

    extent = (
        db.query(UserGroupExtent)
        .filter(UserGroupExtent.calculation_id == calculation_id)
        .first()
    )
    if not extent:
        return []
    rows = (
        db.query(UserGroupBuilding)
        .filter(
            UserGroupBuilding.extent_id == extent.id,
            UserGroupBuilding.buildings_geojson.isnot(None),
        )
        .all()
    )
    points = []
    for r in rows:
        geo = r.buildings_geojson or []
        for g in geo:
            lat = g.get("lat")
            lon = g.get("lon")
            if lat is not None and lon is not None:
                points.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "area": g.get("area", 0),
                    }
                )
    return points


def _get_usergroup_rivers(
    db: Session, calculation_id: UUID, extent_wkt: str
) -> List[Dict]:
    """Returns [{name, geometry_wkt}] of rivers intersecting the extent."""
    sql = text(
        """
        SELECT "river name", ST_AsText(shape) as geometry_wkt
        FROM river.river84
        WHERE ST_Intersects(shape, ST_SetSRID(ST_GeomFromText(:wkt), 4326))
        LIMIT 200
    """
    )
    try:
        rows = db.execute(sql, {"wkt": extent_wkt}).fetchall()
        return [{"name": r[0] or "", "geometry": r[1]} for r in rows]
    except Exception:
        logger.exception(
            "topographic feature query failed - the plan map will be drawn "
            "with no ridges or rivers, looking exactly like a forest that has "
            "none"
        )
        return []


def _get_usergroup_poi(
    db: Session, calculation_id: UUID, extent_wkt: str, table: str
) -> List[Dict]:
    """Returns [{name, lon, lat}] from infrastructure.{table} intersecting extent.
    Uses COALESCE to handle tables without a 'name' column (e.g. health_facilities uses hf_type).
    """
    ALLOWED_POI_TABLES = {"education_facilities", "health_facilities"}
    if table not in ALLOWED_POI_TABLES:
        return []
    ALLOWED_POI_COLUMNS = {"name", "hf_type"}
    name_col = "name" if table == "education_facilities" else "hf_type"
    if name_col not in ALLOWED_POI_COLUMNS:
        return []
    sql = text(
        f"""
        SELECT COALESCE({name_col}, '') as name,
               ST_X(geom) as lon, ST_Y(geom) as lat
        FROM infrastructure.{table}
        WHERE geom IS NOT NULL
          AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromText(:wkt), 4326))
        LIMIT 100
    """
    )
    try:
        rows = db.execute(sql, {"wkt": extent_wkt}).fetchall()
        return [{"name": r[0] or "", "lon": r[1], "lat": r[2]} for r in rows]
    except Exception:
        logger.exception(
            "settlement query failed - the plan map will be drawn with no "
            "settlements, looking exactly like a forest that has none"
        )
        return []


_TILE_DISK_CACHE = os.path.join(MAP_CACHE_DIR, "..", "tile_cache")


def _fetch_tile(url: str) -> Optional[np.ndarray]:
    """Fetch one XYZ tile as an RGBA array. Tiles are immutable by URL, so a
    disk cache under ``uploads/tile_cache/`` makes every basemap render after
    the first one nearly free (adjacent forests share tiles)."""
    cache_path = os.path.join(
        _TILE_DISK_CACHE, hashlib.md5(url.encode()).hexdigest() + ".png"
    )
    try:
        if os.path.exists(cache_path):
            return np.array(PILImage.open(cache_path).convert("RGBA"))
    except Exception:  # noqa: BLE001 -- a corrupt cache file → refetch
        pass

    try:
        import urllib.request

        req = urllib.request.Request(
            url, headers={"User-Agent": "ForestManagement/1.0"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read()
        img = PILImage.open(io.BytesIO(data)).convert("RGBA")
        try:
            os.makedirs(_TILE_DISK_CACHE, exist_ok=True)
            img.save(cache_path)
        except Exception:  # noqa: BLE001 -- cache write is best-effort
            pass
        return np.array(img)
    except Exception:
        logger.warning(
            "basemap tile fetch failed for %s - the map will be drawn without "
            "its background imagery",
            url,
            exc_info=True,
        )
        return None


def _add_basemap(ax, layer_name: str, alpha: float = 0.6):
    # why: a basemap gives the forest geographic context (roads, rivers, towns)
    source = BASEMAP_SOURCES.get(layer_name, cx.providers.OpenStreetMap.Mapnik)
    url_template = source.get("url", "")
    if not url_template:
        ax.set_facecolor("#f0f0f0")
        return False
    # xyzservices providers carry {variant}/{r} placeholders and their own
    # subdomain list — fill those before the per-tile {s}/{z}/{x}/{y} swap.
    url_template = url_template.replace(
        "{variant}", str(source.get("variant", ""))
    ).replace("{r}", "")
    _subs = str(source.get("subdomains", "abc")) or "abc"

    try:
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        lon_span = x1 - x0
        zoom = _calc_zoom(lon_span, FIG_SIZE_INCHES[0], dpi=150)

        # Tile coordinates covering the viewport
        min_tx, max_ty = _latlon_to_tile(y1, x0, zoom)  # NW corner
        max_tx, min_ty = _latlon_to_tile(y0, x1, zoom)  # SE corner

        tx_start, tx_end = min(min_tx, max_tx), max(min_tx, max_tx)
        ty_start, ty_end = min(min_ty, max_ty), max(min_ty, max_ty)

        # Clamp to valid range
        max_tile = 2**zoom - 1
        tx_start = max(0, min(tx_start, max_tile))
        tx_end = max(0, min(tx_end, max_tile))
        ty_start = max(0, min(ty_start, max_tile))
        ty_end = max(0, min(ty_end, max_tile))

        n = 2.0**zoom

        def _url(tx, ty):
            return (
                url_template.replace("{s}", _subs[(tx + ty) % len(_subs)])
                .replace("{z}", str(zoom))
                .replace("{x}", str(tx))
                .replace("{y}", str(ty))
            )

        coords = [
            (tx, ty)
            for ty in range(ty_start, ty_end + 1)
            for tx in range(tx_start, tx_end + 1)
        ]
        # fetch the viewport's tiles in parallel — serial urllib was minutes
        from concurrent.futures import ThreadPoolExecutor

        _blank = np.full((256, 256, 4), [240, 240, 240, 255], dtype=np.uint8)
        with ThreadPoolExecutor(max_workers=8) as ex:
            fetched = list(ex.map(lambda c: _fetch_tile(_url(*c)), coords))
        by_coord = {
            c: (t if t is not None else _blank) for c, t in zip(coords, fetched)
        }

        rows = []
        for ty in range(ty_start, ty_end + 1):
            rows.append(
                np.hstack([by_coord[(tx, ty)] for tx in range(tx_start, tx_end + 1)])
            )

        if not rows:
            raise ValueError("No tiles fetched")

        tile_img = np.vstack(rows)

        # Compute extent in lon/lat
        extent_min_lon = tx_start / n * 360.0 - 180.0
        extent_max_lon = (tx_end + 1) / n * 360.0 - 180.0
        extent_max_lat = math.degrees(
            math.atan(math.sinh(math.pi * (1 - 2 * ty_start / n)))
        )
        extent_min_lat = math.degrees(
            math.atan(math.sinh(math.pi * (1 - 2 * (ty_end + 1) / n)))
        )

        ax.imshow(
            tile_img,
            extent=[extent_min_lon, extent_max_lon, extent_min_lat, extent_max_lat],
            alpha=alpha,
            zorder=1,
        )
        return True

    except Exception as e:
        logger.warning(f"Basemap unavailable for {layer_name}: {e}")
        ax.set_facecolor("#f0f0f0")
        return False


def _add_raster_overlay(
    ax, db: Session, calculation_id: UUID, layer_name: str, bbox, dpi: int
):
    # business: raster overlay at alpha=0.55 for land cover / elevation visibility
    from shapely.geometry import Polygon, MultiPolygon

    min_lon, min_lat, max_lon, max_lat = bbox
    lon_width = max_lon - min_lon

    try:
        tile_service = get_tile_service(db)
        calc_id_str = str(calculation_id)
        zoom = _calc_zoom(lon_width, FIG_SIZE_INCHES[0], dpi=dpi)

        center_lat = (min_lat + max_lat) / 2.0
        x_min, _ = _latlon_to_tile(center_lat, min_lon, zoom)
        x_max, _ = _latlon_to_tile(center_lat, max_lon, zoom)
        _, y_min_t = _latlon_to_tile(max_lat, min_lon, zoom)
        _, y_max_t = _latlon_to_tile(min_lat, min_lon, zoom)

        x_start = min(x_min, x_max)
        x_end = max(x_min, x_max)
        y_start = min(y_min_t, y_max_t)
        y_end = max(y_min_t, y_max_t)

        n = 2.0**zoom
        comp_min_lon = x_start / n * 360.0 - 180.0
        comp_max_lon = (x_end + 1) / n * 360.0 - 180.0
        comp_max_lat = math.degrees(
            math.atan(math.sinh(math.pi * (1 - 2 * y_start / n)))
        )
        comp_min_lat = math.degrees(
            math.atan(math.sinh(math.pi * (1 - 2 * (y_end + 1) / n)))
        )

        from concurrent.futures import ThreadPoolExecutor, as_completed

        tile_coords = [
            (tx, ty)
            for ty in range(y_start, y_end + 1)
            for tx in range(x_start, x_end + 1)
        ]
        tile_results = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_map = {}
            for tx, ty in tile_coords:
                future = executor.submit(
                    tile_service.get_tile,
                    calculation_id=calc_id_str,
                    layer_name=layer_name,
                    z=zoom,
                    x=tx,
                    y=ty,
                    alpha=255,
                )
                future_map[future] = (tx, ty)
            for future in as_completed(future_map):
                tx, ty = future_map[future]
                try:
                    tb = future.result()
                    tile_results[(tx, ty)] = np.array(
                        PILImage.open(io.BytesIO(tb)).convert("RGBA")
                    )
                except Exception:
                    report_dropped(
                        logger,
                        "basemap tile",
                        "it is drawn as a transparent square, leaving a blank patch",
                        context=(tx, ty),
                    )
                    tile_results[(tx, ty)] = np.zeros(
                        (TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8
                    )
        rows = []
        for ty in range(y_start, y_end + 1):
            row_tiles = [tile_results[(tx, ty)] for tx in range(x_start, x_end + 1)]
            rows.append(np.hstack(row_tiles))
        raster_img = np.vstack(rows) if len(rows) > 1 else rows[0]

        extent = [comp_min_lon, comp_max_lon, comp_min_lat, comp_max_lat]
        ax.imshow(raster_img, extent=extent, alpha=RASTER_ALPHA, zorder=2)
        return True

    except Exception as e:
        logger.error(
            f"Raster overlay failed for {layer_name} (calc={calculation_id}): {type(e).__name__}: {e}",
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            logger.warning(
                "rollback failed while recovering the map session - later queries "
                "in this map build will probably fail too",
                exc_info=True,
            )
        return False


def _add_block_polygons_with_labels(ax, blocks: List[Dict], show_labels: bool = True):
    for i, blk in enumerate(blocks):
        color = BLOCK_COLORS[i % len(BLOCK_COLORS)]

        geom = blk["geometry"]
        centroid = blk["centroid"]

        if isinstance(geom, ShapelyPolygon):
            xs, ys = geom.exterior.xy
            ax.plot(xs, ys, color=color, linewidth=2.0, zorder=3)
            for ring in geom.interiors:
                rx, ry = ring.xy
                ax.plot(rx, ry, color="#888", linewidth=0.8, linestyle="--", zorder=3)
        elif isinstance(geom, MultiPolygon):
            for part in geom.geoms:
                xs, ys = part.exterior.xy
                ax.plot(xs, ys, color=color, linewidth=2.0, zorder=3)
                for ring in part.interiors:
                    rx, ry = ring.xy
                    ax.plot(
                        rx, ry, color="#888", linewidth=0.8, linestyle="--", zorder=3
                    )

        if show_labels:
            ax.annotate(
                blk["name"],
                xy=(centroid.x, centroid.y),
                fontsize=10,
                fontweight="bold",
                ha="center",
                va="center",
                color="#1b5e20",
                fontproperties=_dev_fontprop(10),
                bbox=dict(
                    boxstyle="round,pad=0.25",
                    facecolor="white",
                    edgecolor="#1b5e20",
                    alpha=0.85,
                    linewidth=0.5,
                ),
                zorder=6,
            )


COMPARTMENT_COLORS = [
    "#2e7d32",
    "#1565c0",
    "#795548",
    "#f9a825",
    "#6a1b9a",
    "#00838f",
    "#e65100",
    "#c62828",
    "#283593",
    "#4e342e",
    "#558b2f",
    "#ad1457",
    "#00695c",
    "#3e2723",
    "#f57f17",
    "#1a237e",
]


def _add_compartment_polygons_with_labels(
    ax, compartments: List[Dict], show_sub_as_overlay: bool = True
) -> List[Dict]:
    parent_keys = sorted(
        set(c["parent_block_id"] for c in compartments if c["parent_block_id"])
    )
    parent_color_map = {
        pid: COMPARTMENT_COLORS[i % len(COMPARTMENT_COLORS)]
        for i, pid in enumerate(parent_keys)
    }

    from ..forest_units.model import DEPTH_SUB

    legend_items = []
    item_index = 0

    for c in compartments:
        geom = c["geometry"]
        pid = c["parent_block_id"]
        is_sub = c["division_level"] >= DEPTH_SUB
        color = parent_color_map.get(pid, "#757575")

        if is_sub and show_sub_as_overlay:
            # Compartment layer: skip sub-compartments (level >= 2)
            continue
        if not is_sub and not show_sub_as_overlay:
            # Sub-compartment layer: skip compartments (level 1)
            continue
        prominent = True

        item_index += 1
        label = c["code"] or c["name"]
        parent_name = c["parent_block_name"]

        if isinstance(geom, ShapelyPolygon):
            xs, ys = geom.exterior.xy
            if prominent:
                ax.fill(xs, ys, color=color, alpha=0.20, zorder=4)
                ax.plot(xs, ys, color=color, linewidth=2.0, zorder=4)
            else:
                ax.fill(xs, ys, color=color, alpha=0.12, zorder=4)
                ax.plot(xs, ys, color=color, linewidth=1.0, linestyle="--", zorder=4)
            for ring in geom.interiors:
                rx, ry = ring.xy
                ax.plot(rx, ry, color="#888", linewidth=0.6, linestyle="--", zorder=4)
        elif isinstance(geom, MultiPolygon):
            for part in geom.geoms:
                xs, ys = part.exterior.xy
                if prominent:
                    ax.fill(xs, ys, color=color, alpha=0.20, zorder=4)
                    ax.plot(xs, ys, color=color, linewidth=2.0, zorder=4)
                else:
                    ax.fill(xs, ys, color=color, alpha=0.12, zorder=4)
                    ax.plot(
                        xs, ys, color=color, linewidth=1.0, linestyle="--", zorder=4
                    )
                for ring in part.interiors:
                    rx, ry = ring.xy
                    ax.plot(
                        rx, ry, color="#888", linewidth=0.6, linestyle="--", zorder=4
                    )

        # Numbered circle marker instead of text annotation — avoids overlap
        num_color = "#1a1a1a"
        ax.scatter(
            c["centroid"].x,
            c["centroid"].y,
            s=100,
            marker="o",
            facecolors="white",
            edgecolors=num_color,
            linewidth=1.5,
            zorder=8,
        )
        ax.annotate(
            str(item_index),
            xy=(c["centroid"].x, c["centroid"].y),
            fontsize=7,
            fontweight="bold",
            ha="center",
            va="center",
            color=num_color,
            zorder=9,
        )

        legend_label = f"{label} ({parent_name})" if parent_name else label
        legend_items.append(
            {
                "number": item_index,
                "name": legend_label,
                "is_sub": is_sub,
                "color": color,
            }
        )

    return legend_items


def _add_sub_area_polygons_with_labels(ax, sub_areas: List[Dict]) -> List[Dict]:
    legend_items = []
    for i, sa in enumerate(sub_areas, 1):
        geom = sa["geometry"]
        color = sa["color"]
        is_excluded = sa["is_excluded"]

        fill_color = color if not is_excluded else "#fca5a5"
        line_style = "dashed" if is_excluded else "solid"
        line_color = "#dc2626" if is_excluded else color

        if isinstance(geom, ShapelyPolygon):
            xs, ys = geom.exterior.xy
            ax.fill(xs, ys, color=fill_color, alpha=0.25, zorder=4)
            ax.plot(
                xs, ys, color=line_color, linewidth=1.8, linestyle=line_style, zorder=4
            )
            for ring in geom.interiors:
                rx, ry = ring.xy
                ax.plot(rx, ry, color="#888", linewidth=0.6, linestyle="--", zorder=4)
        elif isinstance(geom, MultiPolygon):
            for part in geom.geoms:
                xs, ys = part.exterior.xy
                ax.fill(xs, ys, color=fill_color, alpha=0.25, zorder=4)
                ax.plot(
                    xs,
                    ys,
                    color=line_color,
                    linewidth=1.8,
                    linestyle=line_style,
                    zorder=4,
                )
                for ring in part.interiors:
                    rx, ry = ring.xy
                    ax.plot(
                        rx, ry, color="#888", linewidth=0.6, linestyle="--", zorder=4
                    )

        centroid = sa["centroid"]
        num_color = "#dc2626" if is_excluded else "#1a1a1a"
        ax.scatter(
            centroid.x,
            centroid.y,
            s=100,
            marker="o",
            facecolors="white",
            edgecolors=num_color,
            linewidth=1.5,
            zorder=8,
        )
        ax.annotate(
            str(i),
            xy=(centroid.x, centroid.y),
            fontsize=7,
            fontweight="bold",
            ha="center",
            va="center",
            color=num_color,
            zorder=9,
        )
        legend_items.append(
            {
                "number": i,
                "name": sa["name"],
                "category": sa.get("label_np", sa["category"]),
                "color": color,
                "is_excluded": is_excluded,
            }
        )
    return legend_items


def _add_sample_plots(ax, plots: List[Dict]):
    for pt in plots:
        ax.scatter(
            pt["lon"],
            pt["lat"],
            s=160,
            marker="o",
            facecolors="none",
            edgecolors="#ffd600",
            linewidth=2.0,
            zorder=7,
        )
        ax.annotate(
            pt["label"],
            xy=(pt["lon"], pt["lat"]),
            fontsize=8,
            fontweight="bold",
            color="#000000",
            ha="center",
            va="center",
            fontproperties=_dev_fontprop(8),
            zorder=8,
        )


def _add_fieldbook_features(ax, db: Session, calculation_id: UUID):
    from ...models.fieldbook import Fieldbook
    from shapely import wkt as shapely_wkt

    points = (
        db.query(Fieldbook)
        .filter(Fieldbook.calculation_id == calculation_id)
        .order_by(Fieldbook.point_number)
        .all()
    )
    if not points:
        return

    # Distinct colors per forest block
    block_names = sorted(set(p.block_name or "Unknown" for p in points))
    palette = [
        "#e6194b",
        "#3cb44b",
        "#ffe119",
        "#4363d8",
        "#f58231",
        "#911eb4",
        "#42d4f4",
        "#f032e6",
        "#bfef45",
        "#fabed4",
        "#469990",
        "#dcbeff",
        "#9A6324",
        "#800000",
        "#aaffc3",
    ]
    block_color = {bn: palette[i % len(palette)] for i, bn in enumerate(block_names)}

    # Plot points per block with block-specific colors
    for bn in block_names:
        blk = [p for p in points if (p.block_name or "Unknown") == bn]
        c = block_color[bn]
        # Vertex points: filled circles
        vv = [p for p in blk if p.point_type == "vertex"]
        if vv:
            ax.scatter(
                [float(p.longitude) for p in vv],
                [float(p.latitude) for p in vv],
                s=40,
                marker="o",
                color=c,
                edgecolors="#000000",
                linewidth=1.0,
                zorder=7,
                label=bn,
            )
        # Interpolated points: hollow circles
        ii = [p for p in blk if p.point_type == "interpolated"]
        if ii:
            ax.scatter(
                [float(p.longitude) for p in ii],
                [float(p.latitude) for p in ii],
                s=25,
                marker="o",
                facecolors="none",
                edgecolors=c,
                linewidth=1.5,
                zorder=7,
            )

    # Vertex-only labels with 8-direction collision avoidance
    _label_offsets = [
        (0, 6, "center", "bottom"),  # above (default)
        (6, 0, "left", "center"),  # right
        (-6, 0, "right", "center"),  # left
        (0, -6, "center", "top"),  # below
        (6, 6, "left", "bottom"),  # top-right
        (-6, 6, "right", "bottom"),  # top-left
        (6, -6, "left", "top"),  # bottom-right
        (-6, -6, "right", "top"),  # bottom-left
    ]
    fs_pt = 6
    cw_pt = 3.5
    lh_pt = fs_pt + 2
    pad_pt = 1.5
    dpi = ax.figure.dpi if hasattr(ax, "figure") else 100
    placed_bboxes = []
    for p in points:
        if p.point_type != "vertex":
            continue
        label = p.point_label or str(p.point_number)
        lon, lat = float(p.longitude), float(p.latitude)
        lw_pt = len(label) * cw_pt + pad_pt * 2
        anchor = ax.transData.transform((lon, lat))
        placed = False
        for dx_pt, dy_pt, ha, va in _label_offsets:
            ox = anchor[0] + dx_pt * dpi / 72
            oy = anchor[1] + dy_pt * dpi / 72
            w = lw_pt * dpi / 72
            h = lh_pt * dpi / 72
            if ha == "center":
                x0, x1 = ox - w / 2, ox + w / 2
            elif ha == "left":
                x0, x1 = ox, ox + w
            else:
                x0, x1 = ox - w, ox
            if va == "bottom":
                y0, y1 = oy, oy + h
            elif va == "center":
                y0, y1 = oy - h / 2, oy + h / 2
            else:
                y0, y1 = oy - h, oy
            collision = any(
                not (x1 <= bx0 or x0 >= bx1 or y1 <= by0 or y0 >= by1)
                for bx0, bx1, by0, by1 in placed_bboxes
            )
            if not collision:
                ax.annotate(
                    label,
                    xy=(lon, lat),
                    xytext=(dx_pt, dy_pt),
                    textcoords="offset points",
                    fontsize=fs_pt,
                    fontweight="bold",
                    color="#000000",
                    ha=ha,
                    va=va,
                    zorder=8,
                )
                placed_bboxes.append((x0, x1, y0, y1))
                placed = True
                break

    # Legend for block colors
    handles = [
        mpatches.Patch(facecolor=block_color[bn], edgecolor="black", label=bn)
        for bn in block_names
    ]
    if handles:
        ax.legend(
            handles=handles,
            loc="lower right",
            fontsize=7,
            title="Forest Block",
            title_fontsize=8,
            prop=_dev_fontprop(7),
        )


def _add_boundary_outline(ax, boundary_geom, color="#1b5e20", linewidth=2.5):
    if boundary_geom is None:
        return
    from shapely.geometry import Polygon, MultiPolygon

    def extract_polygons(geom):
        if isinstance(geom, Polygon):
            return [geom]
        elif isinstance(geom, MultiPolygon):
            return list(geom.geoms)
        elif hasattr(geom, "geoms"):
            result = []
            for g in geom.geoms:
                result.extend(extract_polygons(g))
            return result
        return []

    polys = extract_polygons(boundary_geom)
    for poly in polys:
        xs, ys = poly.exterior.xy
        ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=5)
        for ring in poly.interiors:
            rx, ry = ring.xy
            ax.plot(rx, ry, color="#888", linewidth=1, linestyle="--", zorder=5)


def _add_grid(ax, min_lon, max_lon, min_lat, max_lat):
    """Draw snapped coordinate grid. Returns (snapped_min_lon, snapped_max_lon, snapped_min_lat, snapped_max_lat)."""
    lon_lines, lon_labels, lon_start, lon_end = compute_snapped_grid(min_lon, max_lon)
    lat_lines, lat_labels, lat_start, lat_end = compute_snapped_grid(min_lat, max_lat)

    for lon in lon_lines:
        ax.axvline(
            lon, color="#888888", linewidth=0.3, linestyle="-", alpha=0.5, zorder=0
        )
    for lat in lat_lines:
        ax.axhline(
            lat, color="#888888", linewidth=0.3, linestyle="-", alpha=0.5, zorder=0
        )

    kw = dict(
        fontsize=7.5,
        color="#000000",
        alpha=1.0,
        # a lighter halo — linewidth=2 on 7pt text bled into the thin strokes of
        # "27." so a rotated y-label read like "2/45°"
        path_effects=[pe.withStroke(linewidth=1.4, foreground="white")],
    )
    # Corner de-collision: the top-edge (lon) labels and the left-edge (lat)
    # labels both land on the top-left corner, where a centre-anchored lon
    # label and a centre-anchored lat label overprint each other. Anchor the
    # end-most labels *into* the frame so they clear the corner and each other.
    for i, (lon, lab) in enumerate(zip(lon_lines, lon_labels)):
        ha = "left" if i == 0 else ("right" if i == len(lon_lines) - 1 else "center")
        ax.text(lon, lat_end, f"{lab}°", ha=ha, va="bottom", **kw)
        ax.plot(
            lon,
            lat_end,
            marker="+",
            color="#dc2626",
            markersize=6,
            markeredgewidth=1.5,
            zorder=15,
        )
    for i, (lat, lab) in enumerate(zip(lat_lines, lat_labels)):
        va = "top" if i == len(lat_lines) - 1 else ("bottom" if i == 0 else "center")
        ax.text(lon_start, lat, f"{lab}°", ha="right", va=va, rotation=90, **kw)
        ax.plot(
            lon_start,
            lat,
            marker="+",
            color="#dc2626",
            markersize=6,
            markeredgewidth=1.5,
            zorder=15,
        )

    return lon_start, lon_end, lat_start, lat_end


def _add_neatline(ax, min_lon, max_lon, min_lat, max_lat):
    """Draw a rectangular border (neat line) around the map data area."""
    lons = [min_lon, max_lon, max_lon, min_lon, min_lon]
    lats = [min_lat, min_lat, max_lat, max_lat, min_lat]
    ax.plot(lons, lats, color="#333333", linewidth=1.5, zorder=10)


def _add_north_arrow(ax):
    # North arrow pinned to the very top-right corner of the map frame:
    # arrowhead just inside the neat line, the "N" chip right below it.
    na_x = 0.975
    na_y = 0.985  # arrowhead
    ax.annotate(
        "N",
        xy=(na_x, na_y),
        xytext=(na_x, na_y - 0.075),
        xycoords="axes fraction",
        fontsize=13,
        fontweight="bold",
        ha="center",
        va="center",
        annotation_clip=False,
        zorder=16,
        arrowprops=dict(arrowstyle="->", color="#222222", lw=2.5),
        bbox=dict(
            boxstyle="round,pad=0.18", facecolor="white", edgecolor="#cccccc", alpha=0.9
        ),
    )


def _nice_scale_length(raw_m: float) -> float:
    """Round *raw_m* down to a 1/2/5 × 10ⁿ 'nice' number for a scale-bar segment."""
    if raw_m <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw_m))
    for step in (5, 2, 1):
        if step * mag <= raw_m:
            return step * mag
    return mag


def _add_scale_bar(ax, min_lon: float, max_lon: float, min_lat: float, max_lat: float):
    """Metric scale bar, bottom-left, in data coordinates.

    THEMATIC_MAP_VARIABLES_PLAN §3.5.6 / P5a — the frame had a north arrow but
    no scale bar. Distances use the mean-latitude metres-per-degree (display CRS
    is EPSG:4326; a true UTM render is a later task)."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    mid_lat = (y0 + y1) / 2.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(mid_lat))
    span_m = (x1 - x0) * m_per_deg_lon
    if span_m <= 0:
        return
    seg_m = _nice_scale_length(span_m * 0.28)  # aim for ~¼ of the map width
    seg_deg = seg_m / m_per_deg_lon
    bx = x0 + (x1 - x0) * 0.04
    by = y0 + (y1 - y0) * 0.04
    bh = (y1 - y0) * 0.010
    # two alternating segments (0–½–full)
    half = seg_deg / 2.0
    for i, fill in enumerate(("#222222", "#ffffff")):
        ax.add_patch(
            plt.Rectangle(
                (bx + i * half, by),
                half,
                bh,
                facecolor=fill,
                edgecolor="#222222",
                linewidth=0.6,
                zorder=13,
            )
        )
    unit = "km" if seg_m >= 1000 else "m"
    for tx, tv in ((bx, 0), (bx + half, seg_m / 2), (bx + seg_deg, seg_m)):
        tv_disp = tv / 1000.0 if seg_m >= 1000 else tv
        ax.text(
            tx,
            by + bh * 1.6,
            f"{tv_disp:g}",
            ha="center",
            va="bottom",
            fontsize=6,
            color="#222222",
            zorder=13,
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
        )
    ax.text(
        bx + seg_deg + (x1 - x0) * 0.01,
        by + bh * 0.5,
        unit,
        ha="left",
        va="center",
        fontsize=6,
        color="#222222",
        zorder=13,
        path_effects=[pe.withStroke(linewidth=2, foreground="white")],
    )


def _add_legend(ax, layer_name: str, dynamic_items: Optional[List] = None):
    legend_map = {
        "forest_type": [
            ((0 / 255, 100 / 255, 0 / 255, 0.85), "Shorea robusta"),
            ((154 / 255, 205 / 255, 50 / 255, 0.85), "Pinus wallichiana"),
            ((46 / 255, 139 / 255, 87 / 255, 0.85), "Abies spectabilis"),
            ((106 / 255, 90 / 255, 205 / 255, 0.85), "Rhododendron"),
            ((139 / 255, 69 / 255, 19 / 255, 0.85), "Tropical Riverine"),
            ((189 / 255, 189 / 255, 189 / 255, 0.85), "Other"),
        ],
        "forest_health": [
            ((220 / 255, 20 / 255, 60 / 255, 0.85), "Stressed"),
            ((255 / 255, 140 / 255, 0 / 255, 0.85), "Poor"),
            ((255 / 255, 215 / 255, 0 / 255, 0.85), "Moderate"),
            ((144 / 255, 238 / 255, 144 / 255, 0.85), "Healthy"),
            ((34 / 255, 139 / 255, 34 / 255, 0.85), "Excellent"),
        ],
        "slope": [
            ((46 / 255, 204 / 255, 113 / 255, 0.85), "Gentle (<19°)"),
            ((241 / 255, 196 / 255, 15 / 255, 0.85), "Moderate (19-31°)"),
            ((230 / 255, 126 / 255, 34 / 255, 0.85), "Steep (31-45°)"),
            ((231 / 255, 76 / 255, 60 / 255, 0.85), "Very Steep (>45°)"),
        ],
        "biomass": [
            ((220 / 255, 20 / 255, 60 / 255, 0.85), "Very Low (<50 Mg/ha)"),
            ((255 / 255, 215 / 255, 0 / 255, 0.85), "Low (50-100)"),
            ((144 / 255, 238 / 255, 144 / 255, 0.85), "Medium (100-200)"),
            ((34 / 255, 139 / 255, 34 / 255, 0.85), "High (200-300)"),
            ((30 / 255, 144 / 255, 255 / 255, 0.85), "Very High (>300)"),
        ],
        "landcover": [
            ((0 / 255, 100 / 255, 0 / 255, 0.85), "Tree Cover"),
            ((255 / 255, 187 / 255, 34 / 255, 0.85), "Shrubland"),
            ((255 / 255, 255 / 255, 76 / 255, 0.85), "Grassland"),
            ((240 / 255, 150 / 255, 255 / 255, 0.85), "Cropland"),
            ((250 / 255, 0 / 255, 0 / 255, 0.85), "Built-up"),
            ((0 / 255, 100 / 255, 200 / 255, 0.85), "Water"),
        ],
        "dem": [
            ((139 / 255, 69 / 255, 19 / 255, 0.85), "Low"),
            ((255 / 255, 165 / 255, 0 / 255, 0.85), "Medium-Low"),
            ((127 / 255, 255 / 255, 0 / 255, 0.85), "Medium-High"),
            ((135 / 255, 206 / 255, 235 / 255, 0.85), "High"),
        ],
        "aspect": [
            ((200 / 255, 200 / 255, 200 / 255, 0.85), "N"),
            ((150 / 255, 150 / 255, 150 / 255, 0.85), "E"),
            ((100 / 255, 100 / 255, 100 / 255, 0.85), "S"),
            ((50 / 255, 50 / 255, 50 / 255, 0.85), "W"),
        ],
        "soil_texture": [
            ((139 / 255, 69 / 255, 19 / 255, 0.85), "Loam"),
            ((205 / 255, 133 / 255, 63 / 255, 0.85), "Sandy Loam"),
            ((244 / 255, 164 / 255, 96 / 255, 0.85), "Silt Loam"),
            ((160 / 255, 82 / 255, 45 / 255, 0.85), "Clay Loam"),
        ],
        "sampling_plot": [
            ((46 / 255, 125 / 255, 50 / 255, 0.85), "Forest Block"),
            ((255 / 255, 87 / 255, 34 / 255, 0.85), "Sample Plot"),
        ],
        "usergroup": [
            ((27 / 255, 94 / 255, 32 / 255, 0.85), "Community Forest"),
            ((0 / 255, 0 / 255, 255 / 255, 0.85), "User Group Extent"),
            ((255 / 255, 0 / 255, 0 / 255, 0.70), "Buildings"),
            ((0 / 255, 102 / 255, 255 / 255, 0.80), "Rivers"),
            ((255 / 255, 140 / 255, 0 / 255, 0.85), "Settlements"),
            ((156 / 255, 39 / 255, 176 / 255, 0.85), "Education"),
            ((233 / 255, 30 / 255, 99 / 255, 0.85), "Health"),
        ],
        "compartment": [
            ((46 / 255, 125 / 255, 50 / 255, 0.85), "Compartment"),
            ((46 / 255, 125 / 255, 50 / 255, 0.55), "Sub-Compartment"),
        ],
        "sub_compartment": [
            ((46 / 255, 125 / 255, 50 / 255, 0.55), "Sub-Compartment"),
        ],
        "subarea": [
            ((239 / 255, 68 / 255, 68 / 255, 0.85), "संरक्षित / Protected"),
            ((16 / 255, 185 / 255, 129 / 255, 0.85), "बृक्षारोपण / Plantation"),
            ((245 / 255, 158 / 255, 11 / 255, 0.85), "गरिव विपन्न / Pro-Poor"),
            ((139 / 255, 92 / 255, 246 / 255, 0.85), "धार्मीक / Religious"),
            ((6 / 255, 182 / 255, 212 / 255, 0.85), "जैविक / Biodiversity"),
            ((236 / 255, 72 / 255, 153 / 255, 0.85), "पर्यटन / Tourist"),
            ((107 / 255, 114 / 255, 128 / 255, 0.85), "कार्यालय / Office"),
            ((220 / 255, 38 / 255, 38 / 255, 0.85), "निजि जग्गा / Private Land"),
            ((132 / 255, 204 / 255, 23 / 255, 0.85), "कृषिवन / Agroforestry"),
            ((21 / 255, 128 / 255, 61 / 255, 0.85), "ठुला रूख / Tree Strata"),
            ((14 / 255, 165 / 255, 233 / 255, 0.85), "पानी मूहान / Water Hole"),
            ((168 / 255, 85 / 255, 247 / 255, 0.85), "जैविक मार्ग / Wildlife Corridor"),
        ],
    }

    items = dynamic_items if dynamic_items is not None else legend_map.get(layer_name)
    if not items:
        return

    elements = [mpatches.Patch(color=c, label=l) for c, l in items]
    ncol = len(items) if len(items) <= 4 else (len(items) + 1) // 2
    ax.legend(
        handles=elements,
        loc="lower right",
        fontsize=7,
        title_fontsize=8,
        framealpha=0.85,
        edgecolor="#555555",
        fancybox=True,
        ncol=ncol,
        prop=_dev_fontprop(7),
    )


def _add_landcover_1984_polygons(
    ax, db: Session, calculation_id: UUID
) -> List[Tuple[str, str]]:
    """Draw the 1984 land-use polygons (``landcover.landcover_1984``) clipped to
    the forest boundary, filled by canonical class. Returns
    ``[(hex_colour, en_label), ...]`` for the legend, biggest class first."""
    from shapely import wkb as shapely_wkb
    from ...core.landcover_1984 import (
        normalize_lc1984,
        lc1984_color,
        lc1984_label,
    )

    boundary = _get_forest_geometry(db, calculation_id)
    if boundary is None:
        return []

    rows = db.execute(
        text(
            """
            WITH b AS (SELECT ST_GeomFromText(:wkt, 4326) AS g)
            SELECT lc.landuse_yr1984 AS cls,
                   ST_AsBinary(
                       ST_CollectionExtract(ST_Intersection(lc.geom, b.g), 3)
                   ) AS geom_wkb,
                   ST_Area(ST_Intersection(lc.geom, b.g)::geography) AS m2
            FROM landcover.landcover_1984 lc, b
            WHERE ST_Intersects(lc.geom, b.g)
            """
        ),
        {"wkt": boundary.wkt},
    ).fetchall()

    area_by_canon: Dict[str, float] = {}
    for r in rows:
        canon = normalize_lc1984(r.cls)
        if not canon or not r.geom_wkb:
            continue
        area_by_canon[canon] = area_by_canon.get(canon, 0.0) + float(r.m2 or 0)
        try:
            geom = shapely_wkb.loads(bytes(r.geom_wkb))
        except Exception:
            report_dropped(
                logger,
                "1984 land-use polygon",
                "it will be missing from the map",
                context=canon,
            )
            continue
        colour = lc1984_color(canon)
        parts = (
            [geom]
            if isinstance(geom, ShapelyPolygon)
            else list(getattr(geom, "geoms", []))
        )
        for part in parts:
            if not isinstance(part, ShapelyPolygon) or part.is_empty:
                continue
            xs, ys = part.exterior.xy
            ax.fill(xs, ys, color=colour, alpha=0.6, zorder=2, linewidth=0)
            ax.plot(xs, ys, color="#5d4037", linewidth=0.3, zorder=2)

    legend: List[Tuple[str, str]] = []
    for canon, _a in sorted(area_by_canon.items(), key=lambda kv: kv[1], reverse=True):
        legend.append((lc1984_color(canon), lc1984_label(canon, "en")))
    return legend


def generate_standard_map(
    db: Session,
    calculation_id: UUID,
    layer_name: str,
    forest_name: str = "",
    dpi: int = DPI,
    use_cache: bool = True,
) -> io.BytesIO:
    """
    Generate a standardized map following the protocol:
    - Basemap (OSM or Topo per layer)
    - Raster overlay at alpha=0.55
    - Block polygons with distinct colors + name labels on ALL maps
    - Boundary outline
    - Coordinate grid (5x5), neat line
    - North arrow, legend, title
    - Devanagari font with fallback verification

    Uses a persistent file cache — generated maps are saved once and reused.
    Call clear_map_cache() to force regeneration.

    Args:
        db: Database session
        calculation_id: Forest calculation UUID
        layer_name: One of BASEMAP_SOURCES keys
        forest_name: Forest name for title
        dpi: Output DPI (200 default)
        use_cache: If True, check/save persistent cache (default True)

    Returns:
        BytesIO containing PNG image
    """
    if use_cache:
        cached = _map_cache_get(calculation_id, layer_name, dpi)
        if cached:
            return cached

    try:
        buf = _generate_map_inner(db, calculation_id, layer_name, forest_name, dpi)
    except Exception as e:
        logger.error(f"Map generation failed for {layer_name}: {e}")
        try:
            db.rollback()
        except Exception:
            logger.warning(
                "rollback failed while recovering the map session - later queries "
                "in this map build will probably fail too",
                exc_info=True,
            )
        buf = io.BytesIO()
        px = int(FIG_SIZE_INCHES[0] * dpi)
        PILImage.new("RGB", (px, px), "white").save(buf, format="PNG")
        buf.seek(0)

    if use_cache:
        buf.seek(0)
        _map_cache_set(calculation_id, layer_name, buf, dpi)
    buf.seek(0)
    return buf


def _generate_map_inner(
    db: Session,
    calculation_id: UUID,
    layer_name: str,
    forest_name: str = "",
    dpi: int = DPI,
) -> io.BytesIO:
    bbox = _get_forest_bbox(db, calculation_id)
    if not bbox:
        buf = io.BytesIO()
        px = int(FIG_SIZE_INCHES[0] * dpi)
        PILImage.new("RGB", (px, px), "white").save(buf, format="PNG")
        buf.seek(0)
        return buf

    min_lon, min_lat, max_lon, max_lat = bbox
    lon_width = max_lon - min_lon
    lat_height = max_lat - min_lat

    # For usergroup, focus viewport on the user group extent instead of full forest
    if layer_name == "usergroup":
        ug_extent = _get_usergroup_extent(db, calculation_id)
        if ug_extent:
            ug_bounds = ug_extent.bounds
            min_lon, min_lat, max_lon, max_lat = ug_bounds
            lon_width = max_lon - min_lon
            lat_height = max_lat - min_lat

    # For compartment/sub_compartment, zoom to compartment extent (not full forest)
    if layer_name in ("compartment", "sub_compartment"):
        comps = _get_compartments_with_geometry(db, calculation_id)
        if comps:
            bounds = [
                c["geometry"].bounds for c in comps if hasattr(c["geometry"], "bounds")
            ]
            if bounds:
                min_lon = min(b[0] for b in bounds)
                min_lat = min(b[1] for b in bounds)
                max_lon = max(b[2] for b in bounds)
                max_lat = max(b[3] for b in bounds)
                # Add 5% padding
                pad_lon = (max_lon - min_lon) * 0.05
                pad_lat = (max_lat - min_lat) * 0.05
                min_lon -= pad_lon
                min_lat -= pad_lat
                max_lon += pad_lon
                max_lat += pad_lat
                lon_width = max_lon - min_lon
                lat_height = max_lat - min_lat

    # Fixed square figure (map content preserves aspect via set_aspect('equal'))
    A5_W_MM = 148
    A5_H_MM = 210
    fig_size_in = FIG_SIZE_MM / 25.4

    subarea_legend_items = []
    n_extra_lines = 0
    if layer_name == "subarea":
        subarea_legend_items = _get_sub_areas_with_geometry(db, calculation_id)
        n_extra_lines = len(subarea_legend_items)
    if layer_name in ("compartment", "sub_compartment"):
        comps = _get_compartments_with_geometry(db, calculation_id)
        n_extra_lines = len(comps)

    if layer_name in ("subarea", "compartment", "sub_compartment"):
        fig_width = A5_W_MM / 25.4
        fig_height = A5_H_MM / 25.4
    else:
        fig_width = fig_size_in
        fig_height = fig_size_in * (
            1.25 if n_extra_lines > 4 else 1.15 if n_extra_lines > 0 else 1.0
        )

    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)

    boundary_geom = _get_forest_geometry(db, calculation_id)

    # Compute snapped grid bounds (replaces 2% padding)
    from app.utils.map_grid import compute_snapped_grid

    _, _, slon_start, slon_end = compute_snapped_grid(min_lon, max_lon)
    _, _, slat_start, slat_end = compute_snapped_grid(min_lat, max_lat)
    ax.set_xlim(slon_start, slon_end)
    ax.set_ylim(slat_start, slat_end)
    ax.set_aspect("equal")

    # Dynamic margins (convert user's cm specs to figure fractions)
    _cm = 1 / 2.54
    _fw, _fh = fig.get_size_inches()
    _lr_margin = 0.0 * _cm
    _title_margin = 1.0 * _cm
    _title_h = (
        6 + 14 * 1.3 * 2 + 4
    ) / 72  # pad + font*linespacing*nlines + buffer (in)
    _legend_rows = (
        (n_extra_lines + 3) // 4
        if layer_name in ("subarea", "compartment", "sub_compartment")
        else n_extra_lines
    )
    _legend_h = (_legend_rows * 0.22 + 0.5) / _fh if n_extra_lines > 0 else 0.0
    fig.subplots_adjust(
        left=_lr_margin / _fw,
        right=1 - _lr_margin / _fw,
        top=1 - (_title_margin + _title_h) / _fh,
        bottom=_legend_h,
    )

    # 1. Basemap (boundary_satellite is the boundary drawing over imagery)
    _add_basemap(ax, layer_name, alpha=1.0 if layer_name == "boundary_satellite" else 0.6)

    _NO_RASTER_LAYERS = {
        "boundary",
        "boundary_satellite",
        "fieldbook",
        "usergroup",
        "subarea",
        "compartment",
        "sub_compartment",
        "landcover_1984",  # vector polygons, drawn below (not a raster)
    } | _SAMPLING_PLOT_LAYERS
    # 2. Raster overlay (skip for boundary, fieldbook, subarea, and sampling_plot layers)
    if layer_name not in _NO_RASTER_LAYERS:
        _add_raster_overlay(ax, db, calculation_id, layer_name, bbox, dpi)

    # 3. Block polygons with name labels — on EVERY map except usergroup and compartment layers
    if layer_name != "usergroup" and layer_name not in (
        "compartment",
        "sub_compartment",
    ):
        blocks = _get_blocks_with_geometry(db, calculation_id)
        if blocks:
            _add_block_polygons_with_labels(
                ax, blocks, show_labels=(layer_name != "subarea")
            )

    # 3a. Compartment / Sub-compartment polygons (numbered markers, no text labels — avoids overlap)
    compartment_numbered = []
    if layer_name in ("compartment", "sub_compartment"):
        comps = _get_compartments_with_geometry(db, calculation_id)
        if comps:
            show_as_overlay = layer_name == "compartment"
            compartment_numbered = _add_compartment_polygons_with_labels(
                ax, comps, show_sub_as_overlay=show_as_overlay
            )

    # 3b. Sub-area polygons (subarea layer only)
    subarea_numbered = []
    if layer_name == "subarea" and subarea_legend_items:
        subarea_numbered = _add_sub_area_polygons_with_labels(ax, subarea_legend_items)

    # 3d. 1984 land-use polygons (landcover_1984 layer only)
    lc1984_legend: List[Tuple[str, str]] = []
    if layer_name == "landcover_1984":
        lc1984_legend = _add_landcover_1984_polygons(ax, db, calculation_id)

    # 4. Sample plot points (for all sampling_plot layer variants)
    if layer_name in _SAMPLING_PLOT_LAYERS:
        plots = _get_sample_plots(db, calculation_id)
        if plots:
            _add_sample_plots(ax, plots)

    # 4b. Fieldbook features (fieldbook layer only)
    if layer_name == "fieldbook":
        _add_fieldbook_features(ax, db, calculation_id)

    # 4c. User Group features (usergroup layer only)
    if layer_name == "usergroup":
        usergroup_extent = _get_usergroup_extent(db, calculation_id)

        # Rivers — zorder=2
        if usergroup_extent:
            from shapely import wkt as shapely_wkt

            extent_wkt = usergroup_extent.wkt
            river_data = _get_usergroup_rivers(db, calculation_id, extent_wkt)
            for r in river_data:
                try:
                    geom = shapely_wkt.loads(r["geometry"])
                    ax.plot(*geom.xy, color="#0066ff", linewidth=2, alpha=0.8, zorder=2)
                except Exception:
                    report_dropped(
                        logger,
                        "topographic feature",
                        "it will be missing from the plan map",
                        context=r.get("name"),
                    )

        # Buildings — scatter, Option C (zorder=3)
        buildings = _get_usergroup_buildings(db, calculation_id)
        if buildings:
            lons = [b["lon"] for b in buildings]
            lats = [b["lat"] for b in buildings]
            ax.scatter(
                lons, lats, s=8, color="#ff0000", alpha=0.7, zorder=3, marker="o"
            )

        # Forest boundary (zorder=5)
        _add_boundary_outline(ax, boundary_geom)

        # User group extent polygon — blue dashed (zorder=5)
        if usergroup_extent:
            from shapely.geometry import Polygon as ShapelyPolygon
            from shapely.geometry import MultiPolygon as ShapelyMultiPolygon

            ug_polys = (
                [usergroup_extent]
                if isinstance(usergroup_extent, ShapelyPolygon)
                else list(usergroup_extent.geoms)
            )
            for ug_poly in ug_polys:
                xs, ys = ug_poly.exterior.xy
                ax.plot(xs, ys, color="#0000ff", linewidth=3, linestyle="--", zorder=5)

        # Settlement markers with labels (zorder=7)
        settlements = _get_usergroup_settlements(db, calculation_id)
        for s in settlements:
            if s["lat"] is not None and s["lon"] is not None:
                ax.plot(
                    s["lon"],
                    s["lat"],
                    marker="s",
                    color="#ff8c00",
                    markersize=6,
                    zorder=7,
                )
                ax.annotate(
                    s["name"],
                    xy=(s["lon"], s["lat"]),
                    fontsize=7,
                    fontweight="bold",
                    color="#000",
                    ha="left",
                    va="bottom",
                    fontproperties=_dev_fontprop(7),
                    bbox=dict(
                        boxstyle="round,pad=0.15",
                        facecolor="white",
                        edgecolor="#cccccc",
                        alpha=0.85,
                    ),
                    zorder=8,
                )

        # Education and Health POIs (zorder=7)
        if usergroup_extent:
            extent_wkt = usergroup_extent.wkt
            for table, color in [("education", "#9c27b0"), ("health", "#e91e63")]:
                pois = _get_usergroup_poi(db, calculation_id, extent_wkt, table)
                for p in pois:
                    ax.plot(
                        p["lon"],
                        p["lat"],
                        marker="D",
                        color=color,
                        markersize=5,
                        zorder=7,
                    )

    # 5. Boundary outline (already drawn inside usergroup block for that layer)
    if layer_name != "usergroup":
        _add_boundary_outline(ax, boundary_geom)

    # 6. Coordinate grid (snapped to clean round values)
    slon_start, slon_end, slat_start, slat_end = _add_grid(
        ax, min_lon, max_lon, min_lat, max_lat
    )

    # 6b. Neat line (border around the map, matching snapped bounds)
    _add_neatline(ax, slon_start, slon_end, slat_start, slat_end)

    # 7. Hide axis ticks
    ax.axis("off")

    # 8. Title (English only, no forest name prefix)
    label_info = LAYER_LABELS.get(layer_name, {})
    title_en = label_info.get("en", layer_name)
    ax.set_title(
        title_en,
        fontsize=14,
        fontweight="bold",
        pad=6,
        color="#1b5e20",
        fontproperties=_dev_fontprop(14),
    )

    # 9. North arrow + metric scale bar (P5a)
    _add_north_arrow(ax)
    _add_scale_bar(ax, min_lon, max_lon, min_lat, max_lat)

    # 10. Legend (below map, horizontal) — skip for layers with numbered lists
    if layer_name == "landcover_1984":
        _add_legend(ax, layer_name, dynamic_items=lc1984_legend)
    elif layer_name not in ("boundary", "boundary_satellite", "subarea", "sub_compartment", "compartment"):
        _add_legend(ax, layer_name)

    # 11. Figure sizing: no extra top margin for these layers
    _numbered_for_height = (
        subarea_legend_items
        if layer_name == "subarea"
        else (comps if layer_name in ("compartment", "sub_compartment") else [])
    )

    # 11. Numbered list renderer (shared by subarea / compartment / sub_compartment)
    _numbered_items = subarea_numbered or compartment_numbered

    # 12. Sub-area numbered list (below map) — 4 columns with wrapping
    if subarea_numbered:

        def _wrap_label(text, max_chars=20):
            if len(text) <= max_chars:
                return text
            break_at = text.rfind(" ", 0, max_chars)
            if break_at == -1:
                break_at = max_chars
            return text[:break_at] + "\n" + text[break_at:]

        n_cols = 4
        col_width = 0.16
        gap = 0.008
        total_w = n_cols * col_width + (n_cols - 1) * gap
        x_start = (1.0 - total_w) / 2
        lines_per_col = (len(subarea_numbered) + n_cols - 1) // n_cols
        for idx, item in enumerate(subarea_numbered):
            col = idx // lines_per_col
            row = idx % lines_per_col
            x_pos = x_start + col * (col_width + gap)
            line_height = _legend_h * 0.85 / max(lines_per_col, 1)
            y_pos = _legend_h * 0.9 - row * line_height
            marker_color = "#dc2626" if item["is_excluded"] else "#1a1a1a"
            fig.text(
                x_pos,
                y_pos,
                f"{item['number']}. {_wrap_label(item['name'])}",
                fontsize=7,
                color=marker_color,
                fontweight="bold",
                va="top",
                ha="left",
                fontproperties=_dev_fontprop(7),
            )

    # 13. Compartment / Sub-compartment numbered list (below map) — 4 columns
    if compartment_numbered:

        def _wrap_label(text, max_chars=24):
            if len(text) <= max_chars:
                return text
            break_at = text.rfind(" ", 0, max_chars)
            if break_at == -1:
                break_at = max_chars
            return text[:break_at] + "\n" + text[break_at:]

        n_cols = 4
        col_width = 0.16
        gap = 0.008
        total_w = n_cols * col_width + (n_cols - 1) * gap
        x_start = (1.0 - total_w) / 2
        lines_per_col = (len(compartment_numbered) + n_cols - 1) // n_cols
        for idx, item in enumerate(compartment_numbered):
            col = idx // lines_per_col
            row = idx % lines_per_col
            x_pos = x_start + col * (col_width + gap)
            line_height = _legend_h * 0.85 / max(lines_per_col, 1)
            y_pos = _legend_h * 0.9 - row * line_height
            fig.text(
                x_pos,
                y_pos,
                f"{item['number']}. {_wrap_label(item['name'])}",
                fontsize=7,
                color="#1a1a1a",
                fontweight="bold",
                va="top",
                ha="left",
                fontproperties=_dev_fontprop(7),
            )

    buf = io.BytesIO()
    # P2: cairo (HarfBuzz) shaping for Devanagari conjuncts; no-op → Agg if
    # mplcairo is absent, so the fallback output is byte-identical to before.
    from app.core.text_shaping import save_figure

    save_figure(fig, buf, format="PNG", dpi=dpi, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _latlon_to_tile(lat: float, lon: float, z: int) -> Tuple[int, int]:
    n = 2.0**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int(
        (
            1.0
            - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat)))
            / math.pi
        )
        / 2.0
        * n
    )
    return (x, y)


def _calc_zoom(lon_width_deg: float, target_inches: float, dpi: int = 200) -> int:
    target_pixels = target_inches * dpi
    target_pixels_80 = target_pixels * 0.80
    for z in range(5, 19):
        tw = 360.0 / (2.0**z)
        pw = TILE_SIZE * (lon_width_deg / tw)
        if pw >= target_pixels_80:
            return z
    return 15
