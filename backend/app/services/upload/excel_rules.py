"""Excel validation generated from the ONE rule table (VALIDATION_TRACKER.md, step D).

The tree-model export used to carry hand-typed numbers (integer-only heights, class edges typed as 3.99 / 9.99 / 29.99, ranges only for the rows
present). Both workbooks - the tree-model export and the Forest Data Workbook - now ask this module, so what Excel stops at and what the server
refuses are the same numbers (``upload/rules.py``):

* **hard** limit  -> a *stop* validation on typing (``decimal between`` / ``whole``; a custom formula where the upper edge is exclusive, because a
  size class is half-open: a stem of exactly 30.0 cm is a tree) and a RED fill for a value that got in by pasting, which validation cannot catch;
* **soft** limit  -> an AMBER fill ("usual range, please confirm"), never a stop;
* **species**     -> AMBER when a DBH / height is above the species' own maximum (looked up in the hidden SPECIES_DATABASE sheet);
* the validated range runs well below the data, so rows a user adds later are checked too.

Pure openpyxl; no database access.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .rules import RULES, NumberRule, range_text

MIN_VALIDATED_ROWS = 5000  # validation / highlighting runs at least this far down, whatever the data holds

# Resource columns: limits used by the Excel export only so far (the server validator does not check them yet)
RESOURCE_LIMITS: Dict[str, tuple] = {
    "firewood_kg_per_100sqm_per_year": (0, 500),
    "grass_kg_per_100sqm_per_year": (0, 500),
    "bedding_material_kg_per_100sqm_per_year": (0, 500),
    "ntfp_kg_per_100sqm_per_year": (0, 100),
}

RED = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
AMBER = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
_STAND_NE = {"regeneration": "पुनरुत्पादन", "sapling": "लाथ्रा", "pole": "खाँवा", "tree": "रुख"}
_MEASURE_NE = {"dbh": "DBH", "height": "उचाइ", "count": "गणना"}
_MEASURE_EN = {"dbh": "DBH", "height": "height", "count": "count"}


def rule_key_for(column_name: str) -> Optional[str]:
    """``pole_dbh_cm`` -> ``pole_dbh``, ``tree_height_m`` -> ``tree_height``, ``regen_count`` -> ``regen_count``; None for a column with no rule."""
    n = str(column_name).strip().lower()
    for suffix in ("_cm", "_m"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    return n if n in RULES else None


def _name(rule: NumberRule) -> str:
    return f"{rule.stand.capitalize()} {_MEASURE_EN[rule.measure]}"


def _hard_message(rule: NumberRule) -> str:
    text = f"{_name(rule)} must be {range_text(rule)}."
    if rule.hard_max_exclusive:
        hi = rule.hard_bounds()[1]
        text += f" {hi:g} or more belongs to the next size class: enter it in that column."
    if rule.integer:
        text += " Whole numbers only."
    return text[:255]


def _prompt(rule: NumberRule) -> str:
    parts = [f"Allowed: {range_text(rule)}."]
    if rule.soft_min is not None or rule.soft_max is not None:
        usual = f"{rule.soft_min:g}-{rule.soft_max:g}" if rule.soft_min is not None and rule.soft_max is not None else (
            f"up to {rule.soft_max:g}" if rule.soft_max is not None else f"from {rule.soft_min:g}")
        parts.append(f"Usual: {usual} (amber if outside).")
    return " ".join(parts)[:255]


def hard_validation(rule: NumberRule, letter: str, first_row: int = 2, last_row: int = MIN_VALIDATED_ROWS) -> DataValidation:
    """The stop-on-typing validation for a column, over ``letter{first_row}:letter{last_row}``."""
    lo, hi = rule.hard_bounds()
    common = dict(allow_blank=True, showErrorMessage=True, errorStyle="stop", errorTitle="Not allowed", error=_hard_message(rule),
                  showInputMessage=True, promptTitle=_name(rule)[:32], prompt=_prompt(rule))
    cell = f"{letter}{first_row}"
    if rule.integer:
        dv = DataValidation(type="whole", operator="between", formula1=f"{lo:g}", formula2=f"{hi:g}", **common)
    elif rule.hard_max_exclusive:
        # "between" is inclusive at both ends; the upper edge of a class is not part of it
        dv = DataValidation(type="custom", formula1=f"AND(ISNUMBER({cell}),{cell}>={lo:g},{cell}<{hi:g})", **common)
    else:
        dv = DataValidation(type="decimal", operator="between", formula1=f"{lo:g}", formula2=f"{hi:g}", **common)
    dv.add(f"{letter}{first_row}:{letter}{last_row}")
    return dv


def _hard_violation_formula(rule: NumberRule, cell: str) -> str:
    lo, hi = rule.hard_bounds()
    upper = f"{cell}>={hi:g}" if rule.hard_max_exclusive else f"{cell}>{hi:g}"
    extra = f",{cell}<>INT({cell})" if rule.integer else ""
    return f"AND(ISNUMBER({cell}),OR({cell}<{lo:g},{upper}{extra}))"


def _soft_violation_formula(rule: NumberRule, cell: str) -> Optional[str]:
    conds: List[str] = []
    if rule.soft_min is not None:
        conds.append(f"{cell}<{rule.soft_min:g}")
    if rule.soft_max is not None:
        conds.append(f"{cell}>{rule.soft_max:g}")
    return f"AND(ISNUMBER({cell}),OR({','.join(conds)}))" if conds else None


def add_highlighting(ws, letter: str, rule: NumberRule, first_row: int = 2, last_row: int = MIN_VALIDATED_ROWS) -> None:
    """RED for a value outside the hard limits (typed validation cannot catch a pasted value), AMBER for one outside the usual range."""
    rng = f"{letter}{first_row}:{letter}{last_row}"
    cell = f"{letter}{first_row}"
    ws.conditional_formatting.add(rng, FormulaRule(formula=[_hard_violation_formula(rule, cell)], fill=RED, stopIfTrue=True))
    soft = _soft_violation_formula(rule, cell)
    if soft:
        ws.conditional_formatting.add(rng, FormulaRule(formula=[soft], fill=AMBER))


def apply_numeric_rules(ws, col_map: Dict[str, str], last_row: int, first_row: int = 2) -> List[str]:
    """Validation + highlighting for every column that has a rule (and the resource columns). ``col_map`` is ``{header: column letter}``."""
    done: List[str] = []
    for name, letter in col_map.items():
        key = rule_key_for(name)
        if key:
            rule = RULES[key]
            ws.add_data_validation(hard_validation(rule, letter, first_row, last_row))
            add_highlighting(ws, letter, rule, first_row, last_row)
            done.append(name)
        elif name in RESOURCE_LIMITS:
            lo, hi = RESOURCE_LIMITS[name]
            dv = DataValidation(type="decimal", operator="between", formula1=str(lo), formula2=str(hi), allow_blank=True, showErrorMessage=True,
                                errorStyle="stop", errorTitle="Not allowed", error=f"{name} must be between {lo} and {hi}.")
            dv.add(f"{letter}{first_row}:{letter}{last_row}")
            ws.add_data_validation(dv)
            done.append(name)
    return done


def add_species_caps(ws, col_map: Dict[str, str], last_row: int, species_rows: int, first_row: int = 2) -> List[str]:
    """AMBER when a pole / tree DBH or height is above its species' own maximum (the hidden SPECIES_DATABASE sheet: B name, E max DBH, F max height)."""
    done: List[str] = []
    for stand in ("pole", "tree"):
        sp = col_map.get(f"{stand}_species_scientific")
        if not sp:
            continue
        for measure, col_index in (("dbh", 4), ("height", 5)):  # VLOOKUP over B:F -> E is the 4th column, F the 5th
            letter = next((l for n, l in col_map.items() if rule_key_for(n) == f"{stand}_{measure}"), None)
            if not letter:
                continue
            cell, spcell = f"{letter}{first_row}", f"${sp}{first_row}"
            formula = (f"AND(ISNUMBER({cell}),LEN({spcell})>0,"
                       f"IFERROR({cell}>VLOOKUP({spcell},SPECIES_DATABASE!$B$2:$F${species_rows + 1},{col_index},FALSE),FALSE))")
            ws.conditional_formatting.add(f"{letter}{first_row}:{letter}{last_row}", FormulaRule(formula=[formula], fill=AMBER))
            done.append(f"{stand}_{measure}")
    return done


def write_guide_sheet(wb, dbh_classes: Optional[list] = None) -> None:
    """The VALIDATION_GUIDE sheet, generated from the same table so it can never disagree with the rules."""
    from app.core import constants as c

    ws = wb.create_sheet("VALIDATION_GUIDE")
    bold = Font(bold=True)
    rows: List[tuple] = [
        ("Field Data Validation Guide / क्षेत्र तथ्याङ्क जाँच निर्देशिका", ""),
        ("", ""),
        ("COLOURS / रङ", ""),
        ("Red cell", "Outside the allowed range (typing it is refused; a pasted value is shown red). Correct it. / अनुमति परिसर बाहिर: सच्याउनुहोस्।"),
        ("Amber cell", "Possible but unusual (outside the usual range, or above the species' own maximum). Check it; you may keep it. / असामान्य: जाँचेर राख्न सकिन्छ।"),
        ("Green / red species", "Green = species found in SPECIES_DATABASE, red = not found (check the spelling). / हरियो = सूचीमा छ, रातो = छैन।"),
        ("", ""),
        ("NUMERIC LIMITS / संख्यात्मक सीमा", ""),
        ("Column", "Allowed (red outside)  |  Usual (amber outside)"),
    ]
    for key, r in RULES.items():
        usual = ""
        if r.soft_min is not None and r.soft_max is not None:
            usual = f"{r.soft_min:g} to {r.soft_max:g}"
        elif r.soft_max is not None:
            usual = f"up to {r.soft_max:g}"
        suffix = {"dbh": "_dbh_cm", "height": "_height_m", "count": "_count"}[r.measure]
        stem = "regen" if r.stand == "regeneration" else r.stand
        rows.append((f"{stem}{suffix}  ({_STAND_NE[r.stand]} {_MEASURE_NE[r.measure]})", f"{range_text(r)}{'; whole numbers' if r.integer else ''}  |  {usual or '-'}"))
    for name, (lo, hi) in RESOURCE_LIMITS.items():
        rows.append((name, f"{lo} to {hi} kg/100 m2/year  |  -"))
    rows += [
        ("", ""),
        ("SIZE CLASSES / आकार वर्ग", "A class includes its lower edge and not its upper edge: 30.0 cm is a tree, 10.0 cm a pole."),
    ]
    if dbh_classes:
        for d in dbh_classes:
            upper = "and above" if d.get("upper") is None else f"to under {d['upper']:g} cm"
            rows.append((str(d.get("key", "")).capitalize(), f"{d['lower']:g} cm {upper}"))
    rows += [
        ("", ""),
        ("TREE CLASS (Nepal standard) / रुख वर्ग", ""),
        ("1 or I", f"Large trees: DBH at least {c.TREE_CLASS_2_DBH_MAX_CM:g} cm or height at least {c.TREE_CLASS_2_HEIGHT_MAX_M:g} m"),
        ("2 or II", f"Mid-large: DBH {c.TREE_CLASS_3_DBH_MAX_CM:g}-{c.TREE_CLASS_2_DBH_MAX_CM:g} cm, height {c.TREE_CLASS_3_HEIGHT_MAX_M:g}-{c.TREE_CLASS_2_HEIGHT_MAX_M:g} m"),
        ("3 or III", f"Mid-small: DBH {c.TREE_CLASS_4_DBH_MAX_CM:g}-{c.TREE_CLASS_3_DBH_MAX_CM:g} cm, height {c.TREE_CLASS_4_HEIGHT_MAX_M:g}-{c.TREE_CLASS_3_HEIGHT_MAX_M:g} m"),
        ("4 or IV", f"Small: DBH under {c.TREE_CLASS_4_DBH_MAX_CM:g} cm or height under {c.TREE_CLASS_4_HEIGHT_MAX_M:g} m"),
        ("A, B, C, D (or a-d)", "Alternative classification system"),
        ("", ""),
        ("OTHER", "Decimals are allowed in DBH and height. The checks run down to row %d, so rows you add are checked too. Leave cells blank when there is no data." % MIN_VALIDATED_ROWS),
        ("", "The same numbers are applied when the file is uploaded; a red value will be refused there."),
    ]
    for r in rows:
        ws.append(list(r))
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 100
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        if row[0].value and (str(row[0].value).isupper() or "/" in str(row[0].value) and not row[1].value):
            row[0].font = bold
    ws["A1"].font = Font(bold=True, size=14)


def apply_workbook_validations(ws, purpose, first_row: int = 2, last_row: int = MIN_VALIDATED_ROWS) -> List[str]:
    """Validation for one sheet of the Forest Data Workbook, from the schema.

    The field-inventory sheet takes the rule table (the same limits as the tree-model export and the server). Every other sheet takes the ranges and
    allowed values its schema columns declare - so the workbook, the upload validator and the classifier all read ONE description of a column.
    """
    from openpyxl.utils import get_column_letter

    done: List[str] = []
    for idx, col in enumerate(purpose.columns, start=1):
        letter = get_column_letter(idx)
        key = rule_key_for(col.name) if purpose.id == "field_inventory" else None
        if key:
            rule = RULES[key]
            ws.add_data_validation(hard_validation(rule, letter, first_row, last_row))
            add_highlighting(ws, letter, rule, first_row, last_row)
            done.append(col.name)
        elif col.enum:
            dv = DataValidation(type="list", formula1='"' + ",".join(col.enum) + '"', allow_blank=True, showErrorMessage=True, errorStyle="stop",
                                errorTitle="Not allowed", error=f"{col.name} must be one of: {', '.join(col.enum)}"[:255])
            dv.add(f"{letter}{first_row}:{letter}{last_row}")
            ws.add_data_validation(dv)
            done.append(col.name)
        elif col.minimum is not None or col.maximum is not None:
            lo = col.minimum if col.minimum is not None else -1e9
            hi = col.maximum if col.maximum is not None else 1e9
            kind = "whole" if col.dtype == "integer" else "decimal"
            shown = f"{col.minimum:g}" if col.minimum is not None else "any"
            dv = DataValidation(type=kind, operator="between", formula1=f"{lo:g}", formula2=f"{hi:g}", allow_blank=True, showErrorMessage=True,
                                errorStyle="stop", errorTitle="Not allowed",
                                error=f"{col.name} must be between {shown} and {'any' if col.maximum is None else format(col.maximum, 'g')}"
                                      f"{' (whole numbers)' if kind == 'whole' else ''}."[:255])
            dv.add(f"{letter}{first_row}:{letter}{last_row}")
            ws.add_data_validation(dv)
            done.append(col.name)
    return done
