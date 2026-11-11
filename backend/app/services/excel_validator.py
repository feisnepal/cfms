"""
Excel Validation Enhancement for Tree Model Export

Adds data validation rules to Excel export for field data editing.
- Numeric columns have strict range validation
- Species columns have dropdown suggestions with conditional formatting
- Users can enter custom values in species columns
# constraint: validates against CFMG column header templates

Author: Forest Management System
Date: February 23, 2026
"""

import logging
import re
from typing import Tuple

from ..core.dbh_classifier import DbhClassRegistry
from .upload.excel_rules import MIN_VALIDATED_ROWS, add_species_caps, apply_numeric_rules, write_guide_sheet
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter, column_index_from_string
from sqlalchemy.orm import Session
from sqlalchemy import text
import os

logger = logging.getLogger(__name__)


def species_known_formula(cell: str, last_row: int) -> str:
    """TRUE when ``cell`` holds a species code (1-23), a scientific name or any local name from the hidden SPECIES_DATABASE sheet."""
    return (f'OR(AND(ISNUMBER({cell}),{cell}>=1,{cell}<=23,{cell}=INT({cell})),ISNUMBER(MATCH({cell},SPECIES_DATABASE!$B$2:$B${last_row},0)),'
            f'ISNUMBER(MATCH("*, "&LOWER(TRIM({cell}))&",*",SPECIES_DATABASE!$H$2:$H${last_row},0)))')


def add_validation_to_excel(
    excel_filepath: str,
    db: Session
) -> Tuple[str, float]:
    """
    Enhance existing Excel export with data validation rules

    Adds:
    - SPECIES_DATABASE hidden sheet with all tree species
    - Data validation rules for numeric columns (strict)
    - List validation for species columns (dropdown suggestions)
    - Conditional formatting for species (valid=green, invalid=red)
    - VALIDATION_GUIDE sheet with instructions

    Args:
        excel_filepath: Path to existing Excel file
        db: Database session for querying species

    Returns:
        Tuple of (filepath, file_size_mb)
    """
    # Load existing workbook
    wb = load_workbook(excel_filepath)
    ws_data = wb['Data']

    # Step 1: Create SPECIES_DATABASE sheet (hidden, for validation reference)
    ws_species = wb.create_sheet("SPECIES_DATABASE")
    ws_species.sheet_state = 'hidden'

    # Query all active tree species
    query = text("""
        SELECT
            species_code,
            scientific_name,
            local_name,
            is_tree_species,
            max_dbh_cm,
            max_height_m,
            economic_value
        FROM tree_species_coefficients
        WHERE is_active = TRUE
        ORDER BY
            species_code NULLS LAST,
            scientific_name
    """)

    result = db.execute(query)
    species_list = result.fetchall()

    # Write species database headers with styling
    headers = ['species_code', 'scientific_name', 'local_name', 'is_tree_species',
               'max_dbh_cm', 'max_height_m', 'economic_value', 'names_key']
    ws_species.append(headers)

    # Style headers
    header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws_species[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    # Write species data
    for sp in species_list:
        ws_species.append([
            sp[0] or '',  # species_code
            sp[1] or '',  # scientific_name
            sp[2] or '',  # local_name
            'TRUE' if sp[3] else 'FALSE',  # is_tree_species
            sp[4] or 100,  # max_dbh_cm
            sp[5] or 30,  # max_height_m
            sp[6] or 'Moderate',  # economic_value
            # every name the species is known by, lower case, ", " between and around them: a typed "sal" is found by MATCH("*, sal,*", ...)
            ", " + ", ".join(dict.fromkeys(
                [(sp[1] or '').strip().lower()] + [n.strip().lower() for n in re.split(r"[,;/]", sp[2] or '') if n.strip()]
            )) + ", ",
        ])

    # Auto-adjust column widths in species sheet
    for column in ws_species.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                logger.debug(
                    "cell value could not be measured - column width falls back to "
                    "the default", exc_info=True,
                )
        ws_species.column_dimensions[column_letter].width = min(max_length + 2, 30)

    # Get column letters mapping
    col_map = {}
    for idx, cell in enumerate(ws_data[1], start=1):
        col_map[cell.value] = get_column_letter(idx)

    logger.info(f"[Excel Validator] Found columns: {list(col_map.keys())}")
    logger.info(f"[Excel Validator] Total columns: {len(col_map)}")
    # constraint: max 200 columns per sheet

    # Get max row
    max_row = ws_data.max_row

    # Guard: If no data rows (only header), add a note and skip validation
    if max_row < 2:
        logger.warning(f"WARNING: Excel file has only header row (max_row={max_row}). Adding empty row for validation.")
        # Add a single empty row for validation to work
        ws_data.append([None] * len(col_map))
        max_row = ws_data.max_row

    # ===== NUMERIC LIMITS: generated from the ONE rule table (upload/rules.py) =====
    # The numbers used to be typed in here (integer-only heights, class edges typed as 3.99 / 9.99 / 29.99, only the rows that existed).
    # Now Excel stops at the numbers the server refuses at, a pasted value is shown red, an unusual one amber, and rows added later are covered.
    last_row = max(max_row, MIN_VALIDATED_ROWS)
    numeric_done = apply_numeric_rules(ws_data, col_map, last_row)
    logger.info(f"[Excel Validator] Applied the rule table to {len(numeric_done)} columns: {numeric_done}")

    # pole_class and tree_class: list validation (1-4, A-D, a-d, i-iv, I-IV)
    class_values = "1,2,3,4,A,B,C,D,a,b,c,d,i,ii,iii,iv,I,II,III,IV"

    if 'pole_class' in col_map:
        dv_class = DataValidation(
            type='list',
            formula1=f'"{class_values}"',
            allow_blank=True,
            showErrorMessage=True,
            errorTitle='Invalid Class',
            error='Tree class must be one of: 1,2,3,4,A,B,C,D,a,b,c,d,i,ii,iii,iv,I,II,III,IV'
        )
        dv_class.add(f"{col_map['pole_class']}2:{col_map['pole_class']}{last_row}")
        ws_data.add_data_validation(dv_class)

    if 'tree_class' in col_map:
        dv_class = DataValidation(
            type='list',
            formula1=f'"{class_values}"',
            allow_blank=True,
            showErrorMessage=True,
            errorTitle='Invalid Class',
            error='Tree class must be one of: 1,2,3,4,A,B,C,D,a,b,c,d,i,ii,iii,iv,I,II,III,IV'
        )
        dv_class.add(f"{col_map['tree_class']}2:{col_map['tree_class']}{last_row}")
        ws_data.add_data_validation(dv_class)

    # ===== SPECIES VALIDATION - Conditional Formatting =====
    # Add conditional formatting for species columns (green for valid, red for invalid)
    
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    green_font = Font(color="006100")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    red_font = Font(color="9C0006")

    # Species columns to check (with conditional formatting)
    species_columns = [
        'regen_species_scientific',
        'sapling_species_scientific', 
        'pole_species_scientific',
        'tree_species_scientific'
    ]

    # Get number of species rows for range
    species_count = len(species_list)

    logger.info(f"[Excel Validator] Adding species conditional formatting for {len(species_columns)} columns")

    for species_col_name in species_columns:
        if species_col_name in col_map:
            col_letter = col_map[species_col_name]
            col_num = column_index_from_string(col_letter)
            
            # Use proper range string format for conditional formatting
            range_str = f"{col_letter}2:{col_letter}{last_row}"
            
            try:
                # A species is known when it is a code (1-23), a scientific name, or any local name (SPECIES_DATABASE: B scientific, H every name)
                known = species_known_formula(f"{col_letter}2", species_count + 1)
                green_rule = FormulaRule(formula=[known], fill=green_fill, font=green_font)
                ws_data.conditional_formatting.add(range_str, green_rule)
                red_rule = FormulaRule(formula=[f"AND(LEN({col_letter}2)>0,NOT({known}))"], fill=red_fill, font=red_font)
                ws_data.conditional_formatting.add(range_str, red_rule)
                # an unknown one is questioned, not refused ("keep it?"): the user may know a species the list does not
                dv_species = DataValidation(type="custom", formula1=f"OR(LEN({col_letter}2)=0,{known})", allow_blank=True, showErrorMessage=True,
                                            errorStyle="warning", errorTitle="Species not in the list",
                                            error="This is not a scientific name, local name or code (1-23) in the species list. Check the spelling. Keep it anyway?")
                dv_species.add(range_str)
                ws_data.add_data_validation(dv_species)
                
                logger.info(f"[Excel Validator] Added conditional formatting to {col_letter} ({species_col_name})")
                
            except Exception as e:
                logger.warning(f"[Excel Validator] Warning: Could not add conditional formatting to {species_col_name}: {e}")

    # a pole / tree DBH or height above its species' own maximum: amber (confirm), never a stop
    caps = add_species_caps(ws_data, col_map, last_row, species_count)
    logger.info(f"[Excel Validator] Species-maximum highlighting on {caps}")

    # ===== VALIDATION_GUIDE SHEET (generated from the same table) =====
    class_defs = [{"key": c.key, "lower": float(c.lower), "upper": None if c.upper is None else float(c.upper)} for c in DbhClassRegistry.get_system("validation")]
    write_guide_sheet(wb, class_defs)

    wb.save(excel_filepath)
    logger.info(f"[Excel Validator] Workbook saved successfully")

    # Calculate new file size
    file_size_mb = os.path.getsize(excel_filepath) / (1024 * 1024)

    logger.info(f"[Excel Validator] Validation enhancement completed successfully!")
    logger.info(f"[Excel Validator] File size: {file_size_mb:.2f} MB")
    logger.info(f"[Excel Validator] Data validations in workbook: {len(ws_data.data_validations.dataValidation)}")

    return excel_filepath, file_size_mb
