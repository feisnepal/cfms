"""Species given as a code, a local name or a scientific name in a field-inventory file (owner, 2026-10-13).

The template says "scientific name preferred; a local name or the species code is welcome". The measurement code looks coefficients up by scientific name,
so what the user typed is turned into the scientific name once, before anything else reads the file - at upload and again at processing, the same way.
A near-miss spelling is NOT rewritten here (the validator already reports those for review), and an unknown name is left as typed.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from .findings import UploadFinding, finding

SPECIES_KEYS = ("regen_species_scientific", "sapling_species_scientific", "pole_species_scientific", "tree_species_scientific")


def resolve_species_columns(db, df: pd.DataFrame, mapping: Dict[str, str], *, file=None) -> Tuple[pd.DataFrame, List[UploadFinding]]:
    """``(df, findings)``: code / local-name cells replaced by the scientific name; one info finding lists what was read as what."""
    from app.services.validators.species_code_validator import SpeciesCodeValidator

    columns = [c for c in ((mapping.get(k) if mapping.get(k) in df.columns else k) for k in SPECIES_KEYS) if c in df.columns]
    if not columns:
        return df, []
    validator = SpeciesCodeValidator(db)
    out = df.copy()
    done: Dict[str, str] = {}
    for column in columns:
        cache: Dict[object, object] = {}
        for index, value in out[column].items():
            if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
                continue
            if value not in cache:
                name, _code, method, _conf, _warn = validator.validate_species_value(value, None)
                cache[value] = name if method in ("code", "alias", "exact") and name else value
            resolved = cache[value]
            if resolved != value:
                if str(value).strip().lower() != str(resolved).lower():
                    done.setdefault(str(value), str(resolved))
                out.at[index, column] = resolved
    findings: List[UploadFinding] = []
    if done:
        shown = "; ".join(f"{a} → {b}" for a, b in list(done.items())[:8]) + (" …" if len(done) > 8 else "")
        findings.append(finding("field_inventory.species_resolved", count=len(done), found=shown, file=file))
    return out, findings
