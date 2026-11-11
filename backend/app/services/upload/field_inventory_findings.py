"""Plain-language findings for a field inventory upload (UPLOAD_EXPERIENCE_PLAN.md, UP-2.3).

The validator's own errors stay as they are (other code reads them); this turns them into what the user sees: a coded finding per required
column that is missing, one for a file with no data rows, and ONE info line naming the stand types that are present, replacing the "Optional
column ... not found" warnings the validator emits for stand types a file simply does not have (a tree-only inventory used to show nine of them).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from app.services.upload.coordinates import coordinate_findings
from app.services.upload.findings import UploadFinding, finding
from app.services.upload.units import dbh_unit_findings, height_unit_findings

# the column-name prefix that tells a stand type is present in the file
_STAND_PREFIX = {"regeneration": "regen_", "sapling": "sapling_", "pole": "pole_", "tree": "tree_"}
_STAND_LABEL_EN = {"regeneration": "regeneration", "sapling": "sapling", "pole": "pole", "tree": "tree"}
_STAND_TYPE_IN_WARNING = re.compile(r"\(stand type:\s*(\w+)\)")


def stand_types_present(columns) -> List[str]:
    cols = [str(c).lower() for c in columns]
    return [st for st, prefix in _STAND_PREFIX.items() if any(c.startswith(prefix) for c in cols)]


def enrich_report(report: Dict[str, Any], df, filename: str | None = None, reference_bbox=None, preview=None, renamed=None, converted=None, extra=None) -> List[UploadFinding]:
    """Add ``findings`` (and bilingual error texts) to the validator's ``report`` in place; return the findings."""
    findings: List[UploadFinding] = list(extra or [])  # findings the caller already made (the coordinate system the user chose)
    errors: List[Dict[str, Any]] = report.setdefault("errors", [])
    warnings: List[Dict[str, Any]] = report.setdefault("warnings", [])
    summary: Dict[str, Any] = report.setdefault("summary", {})

    proposals = report.get("proposals") or []
    if proposals:  # which rows, and a repeatable replacement inside each column's own class - for the user to apply or to correct the file
        findings.append(finding("field_inventory.corrections_proposed", rows=sorted({p["row"] for p in proposals})[:50], count=len(proposals),
                                proposals=proposals[:200], auto_fix="replace_random_in_class", file=filename))
    if converted:  # a unit written in a header was applied to the numbers: say so, never silently
        findings.append(finding("field_inventory.units_converted", found="; ".join(f"{c} ({u}) × {f:g}" for c, u, f in converted), count=len(converted), file=filename))
    if renamed:  # columns we recognised under another name: say which, so the user can check we guessed right
        findings.append(finding("field_inventory.columns_renamed", found="; ".join(f"{a} → {b}" for a, b in renamed), count=len(renamed), file=filename))

    # a file with column names but no data rows is NOT ready for processing (the validator used to say it was)
    if len(df) == 0:
        f = finding("file.no_rows", file=filename)
        findings.append(f)
        errors.append({"severity": "error", "type": "no_rows", "message": f.title_en, "message_np": f.title_ne})
        summary.update(ready_for_processing=False, has_critical_errors=True)

    for e in errors:
        if e.get("type") == "missing_column":
            col = re.search(r"'([^']+)'", str(e.get("message", "")))
            f = finding("field_inventory.required_column_missing", found=col.group(1) if col else "?", file=filename)
            findings.append(f)
            e["message"], e["message_np"] = f"{f.title_en} {f.fix_en}", f"{f.title_ne} {f.fix_ne}"  # was "REQUIRED_COLUMN_MISSING: <Nepali>"

    # coordinates that are not degrees in Nepal: name the mistake (UTM metres, swapped columns) instead of 'verify coordinates, EPSG code...'
    lon_col = next((c for c in df.columns if str(c).lower() in ('longitude', 'lon', 'long')), None)
    lat_col = next((c for c in df.columns if str(c).lower() in ('latitude', 'lat')), None)
    if lon_col is not None and lat_col is not None:
        import pandas as _pd

        lon_s, lat_s = _pd.to_numeric(df[lon_col], errors='coerce'), _pd.to_numeric(df[lat_col], errors='coerce')
        coord = coordinate_findings(lon_s, lat_s, reference_bbox=reference_bbox, file=filename)
        findings.extend(coord)
        outside = any('outside the boundary' in str(e.get('message', '')) for e in errors)
        if (coord or outside) and preview is not None:
            report['preview'] = preview(lon_s, lat_s)  # the points against the forest, so the user sees where they land

    # a whole column of diameters in millimetres would make every volume ~100x too big: stop it, name it, say what to do
    dbh_cols = []
    for stand, label in (("regen", "seedling"), ("sapling", "sapling"), ("pole", "pole"), ("tree", "tree")):
        col = next((c for c in df.columns if str(c).lower() in (f"{stand}_dbh", f"{stand}_dbh_cm")), None)
        if col is not None:
            dbh_cols.append((f"{label} diameters", df[col]))
    for f in dbh_unit_findings(dbh_cols, filename):
        findings.append(f)
        errors.append({"severity": "error", "type": "dbh_unit", "message": f"{f.title_en} {f.fix_en}", "message_np": f"{f.title_ne} {f.fix_ne}"})
        summary.update(ready_for_processing=False, has_critical_errors=True)

    # heights that look like feet: a warning (we cannot be sure), never a block
    height_cols = []
    for stand, label in (("pole", "pole"), ("tree", "tree")):
        col = next((c for c in df.columns if str(c).lower() in (f"{stand}_height", f"{stand}_height_m")), None)
        if col is not None:
            height_cols.append((f"{label} heights", df[col]))
    findings.extend(height_unit_findings(height_cols, filename))

    # species names we could not match exactly: say what we read them as (or that we found nothing), instead of "N species may need review"
    pairs: List[str] = []
    for w in warnings:
        if str(w.get("type", "")).endswith("_species_validation"):
            for d in w.get("details") or []:
                orig = str(d.get("original", "")).strip()
                text = f"{orig} → {d.get('resolved')}" if d.get("method") == "fuzzy" and d.get("resolved") else f"{orig} (not in our list)"
                if text not in pairs:
                    pairs.append(text)
    if pairs:
        findings.append(finding("field_inventory.species_suggestion", found="; ".join(pairs[:6]) + (" …" if len(pairs) > 6 else ""), count=len(pairs), file=filename))
        warnings[:] = [w for w in warnings if not str(w.get("type", "")).endswith("_species_validation")]  # the finding replaces them

    present = stand_types_present(df.columns)
    kept = []
    for w in warnings:
        m = _STAND_TYPE_IN_WARNING.search(str(w.get("message", "")))
        if w.get("type") == "missing_optional_column" and m and m.group(1) not in present:
            continue  # the file has no columns for this stand type at all: nothing is "missing"
        kept.append(w)
    warnings[:] = kept
    if present:
        findings.append(finding("field_inventory.stand_types_found", found=", ".join(_STAND_LABEL_EN[s] for s in present), file=filename))

    summary["error_count"] = len(errors)
    summary["warning_count"] = len(warnings)
    report["findings"] = [f.to_dict() for f in findings]
    return findings
