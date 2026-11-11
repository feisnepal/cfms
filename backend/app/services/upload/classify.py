"""Content-based identification of a loose upload (UP-4.2a).

Today's frontend `classifyUpload.ts` reads only the **filename, workbook sheet
names and shapefile layer names** — it never opens the data. This module adds
the missing signals by reading the **first rows / geometry type** and matching
them against the fingerprints already declared in ``schema.py``:

* signal 1 — the file / layer / sheet **name** (``name_aliases``);
* signal 2 — the **column set** (``fingerprint_required`` + column ``aliases``);
* signal 3 — the **geometry type** (``geometry_types``).

It is pure: ``classify_upload`` scores and ranks; ``read_signals`` extracts the
columns / layer names / geometry type from raw bytes. The endpoint
``POST /uploads/classify`` joins the two.
"""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import schema
from .column_synonyms import COVERED_PURPOSES, schema_columns_present


# ── normalisation ────────────────────────────────────────────────────────
def _norm(s: Any) -> str:
    return "".join(ch for ch in str(s).lower().strip() if ch.isalnum())


def _norm_geom(gt: str) -> str:
    """Collapse MULTIxxx → xxx and uppercase, so LINESTRING == MULTILINESTRING."""
    g = str(gt).upper().strip()
    if g.startswith("MULTI"):
        g = g[5:]
    return g


def _household_columns_hit(columns) -> int:
    """How many header cells are the household template's own column names (Nepali or English). The schema's household fingerprint does not
    describe the real template, so this is the signal that identifies a household list; three hits is a household table."""
    from .column_synonyms import resolve_column

    # Coordinates and remarks appear in almost every table, so they say nothing about a household list; count the household-only columns.
    generic = {"latitude", "longitude", "remarks"}
    found = {m.canonical for c in (columns or []) for m in [resolve_column(c, "households")] if m}
    return len(found - generic)


# A boundary file is coordinates and little else. What rules a table OUT is any column that is about trees, plots, households or activities:
# a species, a diameter, a height, a plot or house number. Columns we do not know (a code, a label, a GPS field) do not rule it out.
_OTHER_DATA_HINTS = (
    "species", "dbh", "diam", "girth", "height", "volume", "biomass", "tree", "stem", "regen", "sapling", "pole", "stock", "count",
    "plot", "block", "compartment", "house", "hh", "ward", "caste", "surname", "family", "member", "gender", "income", "land",
    "activity", "year", "cost", "price", "quantity", "qty", "area",
)


def _is_vertex_table(columns, lat_col, lon_col) -> bool:
    """Coordinates and nothing that belongs to trees, plots, households or activities: the shape of a boundary-point file."""
    if not (lat_col and lon_col and columns):
        return False
    from .coordinates import CRS_COLUMN_NAMES

    # the declared coordinate system is not data about trees ("coordinate_system_epsg" even contains the letters "stem"), and station numbers are not either
    skip = {_norm(lat_col), _norm(lon_col)} | {_norm(n) for n in CRS_COLUMN_NAMES}
    others = [_norm(c) for c in columns if _norm(c) and _norm(c) not in skip]
    return not any(h in o for o in others for h in _OTHER_DATA_HINTS)


_STAND_MEASURE = re.compile(r"^(regen|regeneration|seedling|sapling|pole|tree)_?(species|sp|dbh|diameter|height|ht|class|count|sn)")


def _stand_measure_columns(columns) -> int:
    """How many columns are a stand-type measurement (regeneration / sapling / pole / tree species, dbh, height, class ...). A field inventory
    has them; a file that only says WHERE the sample plots are does not."""
    return sum(1 for c in (columns or []) if _STAND_MEASURE.match(str(c).strip().lower().replace(" ", "_").replace("-", "_")))


def _present_columns(purpose, col_set) -> set:
    """Canonical column names of ``purpose`` found in the header row (by the
    column's own name or any of its aliases)."""
    present = set()
    for col in purpose.columns:
        keys = {_norm(col.name), *(_norm(a) for a in col.aliases)}
        if keys & col_set:
            present.add(col.name)
    # a fingerprint column with no Column entry still counts when named exactly
    for c in purpose.fingerprint_required:
        if _norm(c) in col_set:
            present.add(c)
    return present


@dataclass
class Candidate:
    purpose_id: str
    score: float
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"purpose_id": self.purpose_id, "score": round(self.score, 3), "reasons": self.reasons}


@dataclass
class Classification:
    best: Optional[str]  # purpose id, or None
    candidates: List[Candidate]
    columns: List[str] = field(default_factory=list)
    layer_names: List[str] = field(default_factory=list)
    geometry_type: Optional[str] = None
    lat_col: Optional[str] = None
    lon_col: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "best": self.best,
            "candidates": [c.as_dict() for c in self.candidates],
            "columns": self.columns,
            "layer_names": self.layer_names,
            "geometry_type": self.geometry_type,
            "lat_col": self.lat_col,
            "lon_col": self.lon_col,
        }


def classify_upload(
    *,
    filename: Optional[str] = None,
    columns: Optional[List[str]] = None,
    layer_names: Optional[List[str]] = None,
    sheet_names: Optional[List[str]] = None,
    geometry_type: Optional[str] = None,
    lat_col: Optional[str] = None,
    lon_col: Optional[str] = None,
) -> Classification:
    """Score every purpose against the signals and rank them.

    Weights (deterministic, easy to reason about):

    1. a name / layer / sheet match on ``name_aliases`` / ``layer_name`` → **3**
    2. the full ``fingerprint_required`` column set → **2 + 0.1·n** (more specific
       wins); a partial match earns a fraction of **1**
    3. the geometry type is inside ``geometry_types`` → **+0.5**; excluded → **−0.5**
    """
    from_names: List[str] = []
    for nm in [filename, *(sheet_names or []), *(layer_names or [])]:
        if not nm:
            continue
        p = schema.by_layer_name(nm)
        if p is not None:
            from_names.append(p.id)

    col_set = {_norm(c) for c in (columns or [])}
    geom = _norm_geom(geometry_type) if geometry_type else None

    candidates: List[Candidate] = []
    for p in schema.ordered():
        score = 0.0
        reasons: List[str] = []

        if p.id in from_names:
            score += 3.0
            reasons.append("name")

        # canonical column names this purpose recognises in the header row
        # (directly, or by one of the column's aliases)
        present = _present_columns(p, col_set)
        if p.id in COVERED_PURPOSES:  # the shared resolver: Nepali spellings, stand x measure names, units in brackets
            present |= schema_columns_present(p.id, columns or [])

        fp = p.fingerprint_required
        if fp:
            matched = sum(1 for c in fp if c in present or _norm(c) in col_set)
            if matched == len(fp):
                score += 2.0 + 0.1 * len(fp)
                reasons.append("columns")
            elif matched >= 2 and col_set:  # one shared word such as 'name' says nothing: it must not pick a purpose
                score += round(matched / len(fp), 3)
                reasons.append("partial_columns")

        measures = _stand_measure_columns(columns)
        if p.id == "field_inventory" and measures >= 1 and any(
            k in col_set for k in ("plotnumber", "samplplotnumber", "sampleplotnumber", "plotno", "plot", "sampleplot", "sampleplotno", "spno")
        ):
            score += 3.0  # a plot number with stand-type species / dbh / height columns is a field inventory, whichever stand types it has
            reasons.append("field_inventory_columns")
        if p.id == "sample_plots" and measures >= 1:
            score -= 2.5  # sample-plot LOCATIONS carry no species, diameter or height
            reasons.append("has_measurements")

        if p.id == "households" and _household_columns_hit(columns) >= 3:
            score += 3.5  # outweighs a file NAME: a household table called 'boundary.csv' is still a household table
            reasons.append("household_columns")

        if geom and p.geometry_types:
            if any(_norm_geom(g) == geom for g in p.geometry_types):
                score += 0.5
                reasons.append("geometry")
            else:
                score -= 0.5
                reasons.append("geometry_mismatch")

        if score > 0:
            candidates.append(Candidate(p.id, score, reasons))

    # a table of coordinates with nothing else in it, and nothing else claiming it, is a list of boundary points
    if _is_vertex_table(columns, lat_col, lon_col) and not any(c.score >= 1.0 for c in candidates if c.purpose_id != "forest_boundary"):
        mine = next((c for c in candidates if c.purpose_id == "forest_boundary"), None)
        if mine is None:
            candidates.append(Candidate("forest_boundary", 2.0, ["vertex_table"]))
        else:
            mine.score += 2.0
            mine.reasons.append("vertex_table")

    candidates.sort(key=lambda c: (-c.score, c.purpose_id))
    # a best guess needs real evidence (a name, a column set) and a clear lead; geometry alone cannot tell a boundary from a block
    best = None
    if candidates:
        lead = candidates[0].score - (candidates[1].score if len(candidates) > 1 else 0.0)
        if candidates[0].score >= 2.0 or (candidates[0].score >= 1.0 and lead >= 0.5):  # a full column set / a name is proof; less needs a clear lead
            best = candidates[0].purpose_id
    return Classification(
        best=best,
        candidates=candidates,
        columns=list(columns or []),
        layer_names=list(layer_names or []),
        geometry_type=geometry_type,
        lat_col=lat_col,
        lon_col=lon_col,
    )


# ── signal extraction ────────────────────────────────────────────────────
def read_signals(content: bytes, filename: str) -> Dict[str, Any]:
    """Extract ``columns`` / ``layer_names`` / ``geometry_type`` from raw bytes.

    Never raises: an unreadable file yields an empty dict, so the endpoint still
    answers with the name-only signals the frontend already has.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if ext in ("csv", "xlsx", "xls"):
            return _tabular_signals(content, filename)
        if ext == "zip":
            return {"layer_names": _zip_layer_names(content)}
        if ext == "gpkg":
            return _gpkg_signals(content)
        if ext in ("geojson", "json"):
            return _geojson_signals(content)
        if ext in ("kml", "kmz"):
            return _kml_signals(content, ext)
        if ext == "gpx":
            return _gpx_signals(content)
    except Exception:  # noqa: BLE001 -- an unreadable file simply gives no content signals; the name-based guess still applies
        return {}
    return {}


def _tabular_signals(content: bytes, filename: str) -> Dict[str, Any]:
    from .csv_columns import read_csv_columns

    info = read_csv_columns(content, filename)
    return {
        "columns": info["columns"],
        "lat_col": info["lat_col"],
        "lon_col": info["lon_col"],
    }


def _zip_layer_names(content: bytes) -> List[str]:
    import io

    names: List[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for entry in zf.namelist():
            base = entry.rsplit("/", 1)[-1]
            if base.lower().endswith(".shp"):
                names.append(base[:-4])
    return names


def _gpkg_signals(content: bytes) -> Dict[str, Any]:
    import sqlite3

    with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
        tmp.write(content)
        path = tmp.name
    try:
        con = sqlite3.connect(path)
        try:
            layers = [r[0] for r in con.execute(
                "SELECT table_name FROM gpkg_contents ORDER BY table_name"
            )]
            columns: List[str] = []
            if layers:
                columns = [r[1] for r in con.execute(f'PRAGMA table_info("{layers[0]}")')]
            geom = _gpkg_geometry_type(con, layers)
        finally:
            con.close()
    finally:
        import os

        try:
            os.unlink(path)
        except OSError:
            pass
    out: Dict[str, Any] = {"layer_names": layers}
    if columns:
        out["columns"] = columns
    if geom:
        out["geometry_type"] = geom
    return out


def _gpkg_geometry_type(con, layers: List[str]) -> Optional[str]:
    if not layers:
        return None
    row = con.execute(
        "SELECT geometry_type_name FROM gpkg_geometry_columns WHERE table_name = ?",
        (layers[0],),
    ).fetchone()
    return _norm_geom(row[0]) if row and row[0] else None


def _geojson_signals(content: bytes) -> Dict[str, Any]:
    obj = json.loads(content.decode("utf-8", errors="replace"))
    features: List[dict] = []
    if isinstance(obj, dict):
        if obj.get("type") == "FeatureCollection":
            features = obj.get("features") or []
        elif obj.get("type") == "Feature":
            features = [obj]
    props: List[str] = []
    for f in features:
        for k in (f.get("properties") or {}):
            if k not in props:
                props.append(k)
    geom = None
    for f in features:
        g = (f.get("geometry") or {}).get("type")
        if g:
            geom = _norm_geom(g)
            break
    out: Dict[str, Any] = {"columns": props}
    if geom:
        out["geometry_type"] = geom
    return out


def _kml_signals(content: bytes, ext: str) -> Dict[str, Any]:
    if ext == "kmz":
        import io

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            kml = next((n for n in zf.namelist() if n.lower().endswith(".kml")), None)
            if not kml:
                return {}
            content = zf.read(kml)
    text = content.decode("utf-8", errors="replace")
    # first geometry tag wins — good enough for a hint
    geom = None
    for tag, gt in (("Point", "POINT"), ("LineString", "LINESTRING"), ("Polygon", "POLYGON")):
        if f"<{tag}" in text:
            geom = gt
            break
    props = re.findall(r'<Data\s+name="([^"]+)"', text)
    out: Dict[str, Any] = {"columns": props}
    if geom:
        out["geometry_type"] = geom
    return out


def _gpx_signals(content: bytes) -> Dict[str, Any]:
    text = content.decode("utf-8", errors="replace")
    if "<trk" in text or "<rte" in text:
        geom = "LINESTRING"
    elif "<wpt" in text:
        geom = "POINT"
    else:
        geom = None
    out: Dict[str, Any] = {}
    if geom:
        out["geometry_type"] = geom
    return out
