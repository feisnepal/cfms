"""The reference-data layers of the map workspace: ready-made context (rivers, roads, administrative areas, settlements, buildings) shown round a forest.

One list, read by the workspace (``GET /calculations/{id}/reference-layers``) and open to the printed maps and the plan document, so a layer is declared once: where it
lives, how it is clipped and simplified, which attributes it carries, how it is drawn and where it comes from.

Every layer is READ-ONLY reference data in a shared schema of the database; a forest never edits it. Table and column names here are trusted constants written by us (they are
put into SQL as identifiers), never taken from a request.

``source`` and ``licence`` say what is known about where the data came from. Where the repository does not record it, ``licence`` is None and ``licence_note`` says it is not
confirmed: the page shows that plainly rather than guessing a licence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: how a layer is cut to the forest's neighbourhood
CLIP_POLYGON = "polygon"   # intersect with the box (made valid first), then simplify: a municipality can be hundreds of square kilometres
CLIP_LINE = "line"         # intersect with the box
CLIP_NONE = "none"         # take whole features that touch the box (points, small footprints)

DEFAULT_BUFFER_M = 2000.0
MAX_BUFFER_M = 10000.0
#: a layer is cut at this many features and the answer says so (buildings can be thousands round a village)
DEFAULT_MAX_FEATURES = 6000


@dataclass(frozen=True)
class ReferenceLayer:
    key: str
    label_en: str
    label_ne: str
    table: str                       # schema-qualified, quoted where it needs it
    geom_column: str                 # unquoted column name
    geometry: str                    # "line" | "polygon" | "point"
    clip: str
    #: property key -> SQL expression over the table alias ``t`` (quoted where the column name has a space)
    properties: Dict[str, str]
    #: SQL expression for the text shown on hover and as the popup title (None: the layer has no names)
    label_expr: Optional[str]
    style: Dict[str, object]
    source: str
    licence: Optional[str] = None
    licence_note: Optional[str] = None
    simplify_deg: float = 0.0        # tolerance in degrees (0.00001 is about 1 m); 0 = none
    max_features: int = DEFAULT_MAX_FEATURES
    group: str = "context"
    notes: List[str] = field(default_factory=list)


LAYERS: Tuple[ReferenceLayer, ...] = (
    ReferenceLayer(
        key="rivers", label_en="Rivers and streams", label_ne="नदी तथा खोला", table="river.river84", geom_column="shape", geometry="line", clip=CLIP_LINE,
        properties={"name": "NULLIF(btrim(t.\"river name\"), '')", "river_system": 't."sub river system name"', "length_m": "t.length_meter"},
        label_expr="NULLIF(btrim(t.\"river name\"), '')", style={"color": "#1e88e5", "weight": 1.6, "opacity": 0.9},
        source="River network (river84, WGS84), the national hydrology data held in this database", licence=None,
        licence_note="The licence of this dataset is not recorded: confirm it before the layer is exported or printed.",
    ),
    ReferenceLayer(
        key="roads", label_en="Roads and tracks", label_ne="सडक तथा बाटो", table="infrastructure.road", geom_column="geom", geometry="line", clip=CLIP_LINE,
        properties={"name": "COALESCE(NULLIF(t.name_ne, ''), NULLIF(t.name, ''), NULLIF(t.name_en, ''))", "class": "t.highway", "surface": "t.surface", "width": "t.width",
                    "osm_id": "t.osm_id"},
        label_expr="COALESCE(NULLIF(t.name_ne, ''), NULLIF(t.name, ''), NULLIF(t.name_en, ''))", style={"color": "#8d6e63", "weight": 1.4, "opacity": 0.95, "dashArray": "6 3"},
        source="OpenStreetMap contributors (all of Nepal), infrastructure.road", licence="ODbL 1.0",
        licence_note="Open Database Licence: the credit 'OpenStreetMap contributors' must be shown with any map that uses it.",
    ),
    ReferenceLayer(
        key="municipalities", label_en="Municipalities", label_ne="गाउँपालिका / नगरपालिका", table="admin.municipality", geom_column="geom", geometry="polygon", clip=CLIP_POLYGON,
        properties={"name": "t.gapa_napa", "type": "t.type_gn", "district": "t.district", "province": "t.province"},
        label_expr="t.gapa_napa", style={"color": "#7b1fa2", "weight": 2.2, "opacity": 0.9, "fillOpacity": 0.0}, simplify_deg=0.00005, max_features=50,
        source="Administrative boundaries of Nepal (admin.municipality)", licence=None,
        licence_note="The licence of this dataset is not recorded: confirm it before the layer is exported or printed.",
    ),
    ReferenceLayer(
        key="wards", label_en="Wards", label_ne="वडा", table="admin.ward", geom_column="geom", geometry="polygon", clip=CLIP_POLYGON,
        properties={"ward": "t.ward", "municipality": "t.municipality", "district": "t.district", "type": "t.palika_type"},
        label_expr="t.municipality || ' - ' || t.ward", style={"color": "#9575cd", "weight": 1.2, "opacity": 0.9, "fillOpacity": 0.0, "dashArray": "4 3"},
        simplify_deg=0.00003, max_features=200,
        source="Administrative boundaries of Nepal (admin.ward)", licence=None,
        licence_note="The licence of this dataset is not recorded: confirm it before the layer is exported or printed.",
    ),
    ReferenceLayer(
        key="protected_areas", label_en="Protected areas", label_ne="संरक्षित क्षेत्र", table='admin.protected_area', geom_column="geom", geometry="polygon", clip=CLIP_POLYGON,
        properties={"name": 't."protected area name"', "description": "t.description"},
        label_expr='t."protected area name"', style={"color": "#2e7d32", "weight": 2, "opacity": 0.9, "fillColor": "#66bb6a", "fillOpacity": 0.12, "dashArray": "8 4"},
        simplify_deg=0.00005, max_features=30,
        source="Protected areas of Nepal (admin.protected_area)", licence=None,
        licence_note="The licence of this dataset is not recorded: confirm it before the layer is exported or printed.",
    ),
    ReferenceLayer(
        key="settlements", label_en="Settlements", label_ne="बस्ती", table="admin.settlement", geom_column="shape", geometry="point", clip=CLIP_NONE,
        properties={"name": "t.vil_name", "elevation_m": "t.asl"},
        label_expr="NULLIF(t.vil_name, '')", style={"color": "#e65100", "fillColor": "#ff9800", "fillOpacity": 0.9, "radius": 4, "weight": 1},
        source="Settlement points of Nepal (admin.settlement)", licence=None,
        licence_note="The licence of this dataset is not recorded: confirm it before the layer is exported or printed.",
    ),
    ReferenceLayer(
        key="buildings", label_en="Buildings", label_ne="भवन", table="buildings.building", geom_column="shape", geometry="polygon", clip=CLIP_NONE,
        properties={"area_sqm": 't."area sqm"'}, label_expr=None,
        style={"color": "#5d4037", "weight": 0.6, "opacity": 0.9, "fillColor": "#8d6e63", "fillOpacity": 0.55}, max_features=8000,
        source="Building footprints of Nepal (buildings.building)", licence=None,
        licence_note="The licence of this dataset is not recorded: confirm it before the layer is exported or printed.",
    ),
)

BY_KEY: Dict[str, ReferenceLayer] = {l.key: l for l in LAYERS}


def get(key: str) -> Optional[ReferenceLayer]:
    return BY_KEY.get(key)
