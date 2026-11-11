"""A GeoPackage layer's symbology, written the way QGIS stores it: a `layer_styles` table holding a QGIS style (QML) marked as the default.

QGIS reads that table when it opens the file, so the layer appears in the colours, outline and size the workspace drew. When every feature
shares one look the style is plain (one fixed symbol). When looks differ (palette colours, a thematic map, a per-feature colour) the style
reads each feature's colour and outline width from three fields written beside the attributes (`symbol_fill`, `symbol_outline`,
`symbol_width`), so one layer keeps one editable symbol instead of hundreds of rules, and the colours remain visible in the table.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import quoteattr

# the symbol a family draws with, and the QGIS symbol-layer class
_KIND = {"polygons": ("fill", "SimpleFill"), "lines": ("line", "SimpleLine"), "points": ("marker", "SimpleMarker")}

FILL_FIELD, OUTLINE_FIELD, WIDTH_FIELD = "symbol_fill", "symbol_outline", "symbol_width"

_LAYER_STYLES_DDL = """
CREATE TABLE IF NOT EXISTS layer_styles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    f_table_catalog TEXT(256),
    f_table_schema TEXT(256),
    f_table_name TEXT(256),
    f_geometry_column TEXT(256),
    styleName TEXT(30),
    styleQML TEXT,
    styleSLD TEXT,
    useAsDefault BOOLEAN,
    description TEXT,
    owner TEXT(30),
    ui TEXT(30),
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def rgba(hex_colour: str, opacity: float) -> str:
    """'#rrggbb' + 0..1 opacity -> QGIS's 'r,g,b,a' (each 0-255)."""
    h = (hex_colour or "#3388ff").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    h = (h + "000000")[:6]
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    a = max(0, min(255, round(float(opacity) * 255)))
    return f"{r},{g},{b},{a}"


def _look(sym: Dict[str, Any]) -> Tuple[str, str, float]:
    """(fill 'r,g,b,a', outline 'r,g,b,a', width px) of one feature's symbol."""
    weight = float(sym.get("weight", 3) or 0)
    return (
        rgba(sym.get("fill"), sym.get("fillOpacity", 0.2)),
        rgba(sym.get("stroke"), sym.get("strokeOpacity", 1) if weight > 0 else 0),
        weight,
    )


def looks(symbols: List[Optional[Dict[str, Any]]]) -> List[Tuple[str, str, float]]:
    return [_look(s or {}) for s in symbols]


def is_uniform(per_feature: List[Tuple[str, str, float]]) -> bool:
    return len(set(per_feature)) <= 1


def _option(name: str, value: Any, kind: str = "QString") -> str:
    return f"<Option name={quoteattr(name)} type={quoteattr(kind)} value={quoteattr(str(value))}/>"


def _data_defined(mapping: Dict[str, str]) -> str:
    """QGIS 'data defined' overrides: {property: field name}. Empty mapping = none."""
    if not mapping:
        props = ""
    else:
        inner = "".join(
            f'<Option name={quoteattr(prop)} type="Map">'
            f'{_option("active", "true", "bool")}{_option("field", field)}{_option("type", 2, "int")}</Option>'
            for prop, field in mapping.items()
        )
        props = f'<Option name="properties" type="Map">{inner}</Option>'
    return f'<data_defined_properties><Option type="Map">{_option("name", "")}{props}{_option("type", "collection")}</Option></data_defined_properties>'


def _symbol_layer(family: str, first: Tuple[str, str, float], dash: bool, radius: float, overrides: Dict[str, str]) -> str:
    fill, outline, width = first
    dash_style = "dash" if dash else "solid"
    if family == "polygons":
        opts = [
            ("color", fill), ("style", "solid" if fill.split(",")[-1] != "0" else "no"), ("outline_color", outline),
            ("outline_style", dash_style if outline.split(",")[-1] != "0" else "no"), ("outline_width", width),
            ("outline_width_unit", "Pixel"), ("joinstyle", "bevel"), ("offset", "0,0"), ("offset_unit", "MM"),
        ]
        dd = {"fillColor": overrides.get(FILL_FIELD), "outlineColor": overrides.get(OUTLINE_FIELD), "outlineWidth": overrides.get(WIDTH_FIELD)}
    elif family == "lines":
        opts = [
            ("line_color", outline), ("line_style", dash_style), ("line_width", width), ("line_width_unit", "Pixel"),
            ("capstyle", "square"), ("joinstyle", "bevel"), ("offset", "0"), ("offset_unit", "MM"),
        ]
        dd = {"outlineColor": overrides.get(OUTLINE_FIELD), "outlineWidth": overrides.get(WIDTH_FIELD)}
    else:
        opts = [
            ("name", "circle"), ("color", fill), ("outline_color", outline), ("outline_style", "solid" if outline.split(",")[-1] != "0" else "no"),
            ("outline_width", width), ("outline_width_unit", "Pixel"), ("size", round(radius * 2, 2)), ("size_unit", "Pixel"),
            ("angle", 0), ("joinstyle", "bevel"), ("offset", "0,0"), ("offset_unit", "MM"),
        ]
        dd = {"fillColor": overrides.get(FILL_FIELD), "outlineColor": overrides.get(OUTLINE_FIELD)}
    body = "".join(_option(k, v) for k, v in opts)
    cls = _KIND[family][1]
    return (
        f'<layer class="{cls}" enabled="1" locked="0" pass="0"><Option type="Map">{body}</Option>'
        f'{_data_defined({k: v for k, v in dd.items() if v})}</layer>'
    )


def build_qml(family: str, per_feature: List[Tuple[str, str, float]], dash: bool = False, radius: float = 6.0) -> Tuple[str, bool]:
    """(QML text, whether the style reads the symbol_* fields). `family` is 'points' / 'lines' / 'polygons'."""
    uniform = is_uniform(per_feature)
    first = per_feature[0] if per_feature else ("51,136,255,51", "51,136,255,255", 3.0)
    overrides = {} if uniform else {FILL_FIELD: FILL_FIELD, OUTLINE_FIELD: OUTLINE_FIELD, WIDTH_FIELD: WIDTH_FIELD}
    kind = _KIND[family][0]
    qml = (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>"
        '<qgis version="3.28.0-Firenze" styleCategories="Symbology">'
        '<renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0" referencescale="-1">'
        f'<symbols><symbol type="{kind}" name="0" alpha="1" clip_to_extent="1" force_rhr="0">'
        f"{_data_defined({})}"
        f"{_symbol_layer(family, first, dash, radius, overrides)}"
        "</symbol></symbols><rotation/><sizescale/></renderer-v2>"
        "<blendMode>0</blendMode><featureBlendMode>0</featureBlendMode><layerOpacity>1</layerOpacity>"
        "</qgis>"
    )
    return qml, not uniform


def write_layer_styles(path: str, styles: List[Tuple[str, str]], geometry_column: str = "geom") -> None:
    """Add the `layer_styles` table to the GeoPackage at `path` with one default style per (layer name, QML)."""
    if not styles:
        return
    con = sqlite3.connect(path)
    try:
        con.execute(_LAYER_STYLES_DDL)
        for table, qml in styles:
            con.execute(
                "INSERT INTO layer_styles (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, styleName, styleQML, useAsDefault, description)"
                " VALUES ('', '', ?, ?, ?, ?, 1, ?)",
                (table, geometry_column, "workspace", qml, "Symbology exported from the workspace"),
            )
        con.commit()
    finally:
        con.close()
