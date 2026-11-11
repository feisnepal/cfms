"""A map layer as a GeoPackage: the features the workspace shows, written exactly as they are shown.

The workspace already holds a layer's features (the attribute table's rows, as GeoJSON in WGS 84). Exporting them from here, not from a
second query on the server, means the file always equals what the user sees: the same units, the same names, the same columns.

A GeoPackage layer has one kind of geometry, and a workspace layer can mix them (the Activity Features layer holds points, lines and
polygons), so features are grouped by kind and each kind is written as its own layer of the file ("<name>_points" ...). Single and Multi
geometries of one kind are written as the Multi type so QGIS sees one clean type.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.services import layer_gpkg_style as gstyle

logger = logging.getLogger(__name__)

# A layer larger than this is refused rather than building a file nobody can open comfortably in one request.
MAX_FEATURES = 250_000

_FAMILIES = {
    "Point": ("point", "points"),
    "MultiPoint": ("point", "points"),
    "LineString": ("line", "lines"),
    "MultiLineString": ("line", "lines"),
    "Polygon": ("polygon", "polygons"),
    "MultiPolygon": ("polygon", "polygons"),
}
# the names a GeoPackage keeps for itself
_RESERVED_COLUMNS = {"fid", "geom", "geometry"}


class NothingToExport(ValueError):
    """The layer has no feature with a geometry."""


class TooManyFeatures(ValueError):
    """The layer is larger than one request will carry."""


def _slug(text: str) -> str:
    """Letters, digits and combining marks of any script are kept; every run of anything else becomes one underscore.

    (The regular-expression word class does not count the vowel signs and the virama of Devanagari as word characters, so using it would
    turn "कम्पार्टमेन्ट" into "कम_प_र_टम_न_ट".)
    """
    kept = "".join(ch if (ch.isalnum() or ch == "_" or unicodedata.category(ch).startswith("M")) else "_" for ch in str(text))
    return re.sub("_+", "_", kept).strip("_")


def safe_layer_name(name: Optional[str], fallback: str = "layer") -> str:
    """A GeoPackage layer / table name: letters (any script), digits and underscores, never empty, never starting with a digit."""
    text = _slug(name or "")
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"{fallback}_{text}"
    return text[:60]


def _column_names(keys: Iterable[str]) -> Dict[str, str]:
    """Property key -> column name: made safe, never a reserved name, unique (a clash gets _2, _3 ...)."""
    out: Dict[str, str] = {}
    used: set = set()
    for key in keys:
        base = _slug(key) or "field"
        if base.lower() in _RESERVED_COLUMNS:
            base = f"{base}_"
        name, n = base, 1
        while name.lower() in used:
            n += 1
            name = f"{base}_{n}"
        used.add(name.lower())
        out[key] = name
    return out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _column_kind(values: List[Any]) -> str:
    """'int', 'float', 'bool' or 'text': the narrowest type every non-empty value of the column fits."""
    present = [v for v in values if v is not None and v != ""]
    if present and all(isinstance(v, bool) for v in present):
        return "bool"
    if present and all(_is_number(v) for v in present):
        return "int" if all(isinstance(v, int) or float(v).is_integer() for v in present) else "float"
    return "text"


def _as_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def group_features(features: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Features with a geometry, grouped by kind ('points' / 'lines' / 'polygons'); the rest are dropped."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for f in features:
        geom = (f or {}).get("geometry") or {}
        family = _FAMILIES.get(geom.get("type"))
        if family and geom.get("coordinates"):
            groups.setdefault(family[1], []).append(f)
    return groups


def build_geopackage(features: List[Dict[str, Any]], layer_name: str) -> bytes:
    """The GeoPackage (WGS 84) holding `features`. Raises NothingToExport / TooManyFeatures."""
    if len(features) > MAX_FEATURES:
        raise TooManyFeatures(f"{len(features)} features")
    groups = group_features(features)
    if not groups:
        raise NothingToExport("no feature has a geometry")

    import geopandas as gpd
    from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon, shape

    base = safe_layer_name(layer_name)
    handle, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(handle)
    try:
        os.remove(path)  # let the driver create the file
        first = True
        styles: List[Tuple[str, str]] = []
        for suffix in ("points", "lines", "polygons"):
            rows = groups.get(suffix)
            if not rows:
                continue
            keys: List[str] = []
            for f in rows:
                for k in (f.get("properties") or {}):
                    if k not in keys:
                        keys.append(k)
            names = _column_names(keys)
            kinds = {k: _column_kind([(f.get("properties") or {}).get(k) for f in rows]) for k in keys}

            records: List[Dict[str, Any]] = []
            geometries = []
            for f in rows:
                props = f.get("properties") or {}
                record: Dict[str, Any] = {}
                for k in keys:
                    v = props.get(k)
                    kind = kinds[k]
                    if kind == "text":
                        record[names[k]] = _as_text(v)
                    elif v is None or v == "":
                        record[names[k]] = None
                    elif kind == "bool":
                        record[names[k]] = int(bool(v))
                    elif kind == "int":
                        record[names[k]] = int(v)
                    else:
                        record[names[k]] = float(v)
                records.append(record)
                geom = shape(f["geometry"])
                if suffix == "points" and geom.geom_type == "Point":
                    geom = MultiPoint([geom])
                elif suffix == "lines" and geom.geom_type == "LineString":
                    geom = MultiLineString([geom])
                elif suffix == "polygons" and geom.geom_type == "Polygon":
                    geom = MultiPolygon([geom])
                geometries.append(geom)

            # The look the workspace drew each feature in: a style QGIS applies when the file is opened.
            symbols = [f.get("_symbol") for f in rows]
            name = base if len(groups) == 1 else f"{base}_{suffix}"
            if any(symbols):
                per_feature = gstyle.looks(symbols)
                first_sym = next((s for s in symbols if s), {})
                qml, reads_fields = gstyle.build_qml(suffix, per_feature, bool(first_sym.get("dashArray")), float(first_sym.get("radius", 6) or 6))
                if reads_fields:
                    taken = {n.lower() for n in names.values()}
                    for field, idx in ((gstyle.FILL_FIELD, 0), (gstyle.OUTLINE_FIELD, 1), (gstyle.WIDTH_FIELD, 2)):
                        col = field
                        while col.lower() in taken:
                            col += "_"
                        taken.add(col.lower())
                        if col != field:  # a property already uses the name: the style must read the renamed field
                            qml = qml.replace(f'value="{field}"', f'value="{col}"')
                        for record, look in zip(records, per_feature):
                            record[col] = look[idx]
                styles.append((name, qml))

            gdf = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")
            for k in keys:  # keep whole-number columns whole even when a row is empty
                if kinds[k] == "int":
                    gdf[names[k]] = gdf[names[k]].astype("Int64")
            gdf.to_file(path, driver="GPKG", layer=name, engine="pyogrio", mode="w" if first else "a")
            first = False
        gstyle.write_layer_styles(path, styles)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            logger.debug("layer gpkg export: temp file already gone: %s", path)


def describe(path: str) -> List[Tuple[str, str, int]]:
    """(layer name, geometry type, feature count) of every layer in a GeoPackage file. Used by the tests."""
    import pyogrio

    out = []
    for name, geometry_type in pyogrio.list_layers(path):
        out.append((str(name), str(geometry_type), int(pyogrio.read_info(path, layer=name)["features"])))
    return out
