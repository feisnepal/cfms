"""Turn the plain-string errors the older file readers raise into the shared findings (UPLOAD_EXPERIENCE_PLAN.md, UP-2.3).

The boundary / user-group file engine raises ``ValueError("...")`` with English text. Rewriting every raise site is a larger job than UP-2 needs;
this one seam maps each KNOWN message to its finding and sends everything else to the generic "could not be read" finding (never the raw text).
``tests/test_upload_baseline_user_group.py`` drives a real wrong file for every pattern below, so a reworded message breaks a test instead of
silently falling back to the generic finding.
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.services.upload.findings import UploadFinding, finding

_ACCEPTED = ".shp (zipped), .kml, .kmz, .geojson, .gpkg, .gpx, .csv, .xlsx"


def user_group_findings(message: str, filename: Optional[str] = None) -> List[UploadFinding]:
    """The finding(s) for a user-group / boundary import failure whose text is ``message``."""
    m = message or ""
    low = m.lower()
    kw = {"file": filename}

    if "no headers" in low or "file is empty" in low:
        return [finding("file.empty", **kw)]
    if "lat/lon columns" in low or "must have lat" in low:
        found = re.search(r"Found:\s*(.+)$", m)
        return [finding("user_group.no_coordinates", found=(found.group(1).strip() if found else "?"), **kw)]
    if "not in nepal" in low:
        ext = re.search(r"extent is (.+?)\. Nepal is", m)
        return [finding("user_group.outside_nepal", found=(ext.group(1) if ext else "outside the country"), **kw)]
    if "collinear" in low or "too close together" in low or "at least 3 points" in low:
        return [finding("user_group.too_few_points", **kw)]
    if "no .shp" in low:
        return [finding("user_group.no_shapefile", **kw)]
    if "unsupported file format" in low:
        ext = re.search(r"format:\s*(\.\w+)", m)
        return [finding("file.wrong_type", found=(ext.group(1) if ext else "this type"), expected=_ACCEPTED, **kw)]
    if "not a zip file" in low or "badzip" in low or "bad magic" in low or "password" in low:
        return [finding("file.corrupt", expected="Excel (.xlsx) or zipped shapefile", **kw)]
    if "no usable geometry" in low or "produced no user-group polygon" in low or "empty geometry" in low:
        return [finding("user_group.no_geometry", **kw)]
    return [finding("file.unreadable", expected=_ACCEPTED, **kw)]
