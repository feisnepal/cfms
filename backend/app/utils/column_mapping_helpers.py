"""
Helper functions for column mapping preferences and operations
"""

from typing import Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from sqlalchemy.sql import func
from datetime import datetime, timezone
import uuid

from app.models.column_mapping_preference import ColumnMappingPreference
from app.utils.column_mapper import ColumnMapper


def get_user_column_preferences(
    db: Session,
    user_id: uuid.UUID
) -> Dict[str, str]:
    """
    Get user's saved column mapping preferences.

    Args:
        db: Database session
        user_id: UUID of the user

    Returns:
        Dictionary mapping original_column -> standard_column
        Example: {"Species Name": "species", "DBH": "dia_cm"}
    """
    preferences = db.query(ColumnMappingPreference).filter(
        ColumnMappingPreference.user_id == user_id
    ).order_by(ColumnMappingPreference.last_used_at.desc()).all()

    return {
        pref.original_column: pref.mapped_to
        for pref in preferences
    }


def save_user_column_preferences(
    db: Session,
    user_id: uuid.UUID,
    mapping: Dict[str, str]
) -> None:
    """
    Save or update user's column mapping preferences.

    If a preference already exists for a column, increment times_used
    and update last_used_at. Otherwise, create a new preference.

    Args:
        db: Database session
        user_id: UUID of the user
        mapping: Dictionary of {original_column: standard_column}
    """
    for original_col, standard_col in mapping.items():
        # Check if preference already exists
        existing = db.query(ColumnMappingPreference).filter(
            ColumnMappingPreference.user_id == user_id,
            ColumnMappingPreference.original_column == original_col
        ).first()

        if existing:
            # Update existing preference
            existing.mapped_to = standard_col
            existing.times_used = existing.times_used + 1
            existing.last_used_at = datetime.now(timezone.utc)
        else:
            # Create new preference
            new_pref = ColumnMappingPreference(
                user_id=user_id,
                original_column=original_col,
                mapped_to=standard_col,
                times_used=1,
                last_used_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc)
            )
            db.add(new_pref)

    db.commit()


def merge_auto_mapping_with_preferences(
    db: Session,
    user_id: uuid.UUID,
    csv_columns: list
) -> Dict:
    """
    Combine automatic column mapping with user's saved preferences.

    Priority order:
    1. User's saved preferences (100% confidence)
    2. Automatic fuzzy matching

    Args:
        db: Database session
        user_id: UUID of the user
        csv_columns: List of column names from uploaded CSV

    Returns:
        Mapping result dictionary with merged results
    """
    mapper = ColumnMapper()

    # Get automatic mapping
    auto_result = mapper.auto_map_columns(csv_columns)

    # Get user preferences
    user_prefs = get_user_column_preferences(db, user_id)

    # Merge: user preferences override auto-mapping
    # For each user preference, remove any existing mapping to the same standard column
    # to prevent duplicates (e.g., both "longitude" and "LONGITUDE" mapping to "LONGITUDE")
    for csv_col in csv_columns:
        if csv_col in user_prefs:
            std_col = user_prefs[csv_col]
            other_cols = [
                c for c, s in list(auto_result["mapped"].items())
                if s == std_col and c != csv_col
            ]
            for c in other_cols:
                del auto_result["mapped"][c]
                del auto_result["confidence"][c]
                if c not in auto_result["unmapped"]:
                    auto_result["unmapped"].append(c)

            auto_result["mapped"][csv_col] = std_col
            auto_result["confidence"][csv_col] = 100
            if csv_col in auto_result["unmapped"]:
                auto_result["unmapped"].remove(csv_col)

    # Recalculate missing required columns after merge
    auto_result["missing_required"] = mapper._check_missing_required(
        auto_result["mapped"]
    )

    # Duplicates should be empty after our clean-up above, but recalculate to be safe
    auto_result["duplicates"] = mapper._check_duplicates(
        auto_result["mapped"]
    )

    return auto_result


def validate_and_prepare_dataframe(df, mapping: Dict[str, str]):
    """
    Apply column mapping to pandas DataFrame and validate.

    Args:
        df: pandas DataFrame with original CSV columns
        mapping: Dictionary of {original_column: standard_column}

    Returns:
        Dictionary with:
        - df: DataFrame with renamed columns
        - renamed_columns: List of columns that were renamed
        - preserved_columns: List of columns kept as-is
        - errors: List of validation errors (if any)

    Raises:
        ValueError: If required columns are missing after mapping
    """
    mapper = ColumnMapper()

    # Validate the mapping first
    validation = mapper.validate_mapping(mapping)
    if not validation["valid"]:
        return {
            "success": False,
            "errors": validation["errors"],
            "warnings": validation.get("warnings", [])
        }

    # Apply mapping
    result = mapper.apply_mapping(df, mapping)

    # Check for required columns in the final DataFrame
    required_cols = ["species", "dia_cm", "height_m", "LONGITUDE", "LATITUDE"]
    missing_in_df = [col for col in required_cols if col not in result["df"].columns]

    if missing_in_df:
        return {
            "success": False,
            "errors": [f"Required columns missing in DataFrame: {', '.join(missing_in_df)}"],
            "warnings": validation.get("warnings", [])
        }

    return {
        "success": True,
        "df": result["df"],
        "renamed_columns": result["renamed_columns"],
        "preserved_columns": result["preserved_columns"],
        "errors": [],
        "warnings": validation.get("warnings", [])
    }
