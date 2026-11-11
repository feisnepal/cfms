"""
Species code validator - handles both numeric codes (1-23) and scientific names
Supports automatic fallback to Terai spp (22) or Hill spp (23) based on physiographic zone
"""
from typing import Dict, List, Tuple, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from .species_matcher import SpeciesMatcher


class SpeciesCodeValidator:
    """
    Validates species input - accepts both numeric codes (1-23) and scientific names
    Provides fallback species selection based on physiographic zone
    """

    def __init__(self, db: Session):
        """
        Initialize species code validator

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.species_matcher = SpeciesMatcher(db)
        self.species_by_code = self._load_species_by_code()
        self.species_name_to_code = self._load_species_name_to_code()

    def _load_species_by_code(self) -> Dict[int, Dict]:
        """
        Load all species indexed by species_code

        Returns:
            Dict mapping code to species info
        """
        query = text("""
            SELECT
                species_code,
                scientific_name,
                local_name,
                a, b, c, a1, b1, s, m, bg
            FROM public.tree_species_coefficients
            WHERE is_active = TRUE
              AND species_code IS NOT NULL
            ORDER BY species_code
        """)
        results = self.db.execute(query).fetchall()

        species_by_code = {}
        for row in results:
            species_by_code[row.species_code] = {
                'scientific_name': row.scientific_name,
                'local_name': row.local_name,
                'species_code': row.species_code,
                'coefficients': {
                    'a': row.a,
                    'b': row.b,
                    'c': row.c,
                    'a1': row.a1,
                    'b1': row.b1,
                    's': row.s,
                    'm': row.m,
                    'bg': row.bg
                }
            }

        return species_by_code

    def _load_species_name_to_code(self) -> Dict[str, int]:
        """
        Create mapping of scientific names to species codes

        Returns:
            Dict mapping scientific_name to species_code
        """
        name_to_code = {}
        for code, species_info in self.species_by_code.items():
            name_to_code[species_info['scientific_name'].lower()] = code
        return name_to_code

    def validate_species_value(
        self,
        value: any,
        physiographic_zone: Optional[str] = None
    ) -> Tuple[str, Optional[int], str, float, Optional[str]]:
        """
        Validate species - accepts numeric code (1-23) or scientific name
        Returns normalized species info with automatic fallback for unknown species

        Args:
            value: Species value (code or name)
            physiographic_zone: Dominant physiographic zone (for fallback)

        Returns:
            Tuple of:
            - scientific_name: Matched scientific name
            - species_code: Species code (1-23) or None
            - method: How it was matched ('code', 'exact', 'alias', 'fuzzy', 'fallback')
            - confidence: Match confidence (0.0-1.0)
            - warning_message: Optional warning message
        """
        if pd.isna(value) or value is None or str(value).strip() == '':
            return None, None, 'no_match', 0.0, 'Missing species value'

        if isinstance(value, float) and value.is_integer():
            value = int(value)  # Excel hands a typed 18 back as 18.0
        value_str = str(value).strip()

        # Step 1: Try parsing as numeric code
        if value_str.isdigit():
            code = int(value_str)
            if 1 <= code <= 23:
                if code in self.species_by_code:
                    species_info = self.species_by_code[code]
                    return (
                        species_info['scientific_name'],
                        code,
                        'code',
                        1.0,
                        None
                    )
                else:
                    # Code exists in range but not in database
                    warning = f"Species code {code} not found in database"
                    return None, None, 'no_match', 0.0, warning
            else:
                # Code outside valid range (1-23)
                warning = f"Invalid species code: {code}. Valid codes are 1-23"
                # Try fallback
                return self._get_fallback_species(
                    physiographic_zone,
                    f"Code {code} invalid, using fallback"
                )

        # Step 2: Try as scientific name using existing species matcher
        matched_name, confidence, method = self.species_matcher.match_species(value_str)

        if matched_name:
            # Found a match - look up its code
            species_code = self.species_name_to_code.get(matched_name.lower())
            return matched_name, species_code, method, confidence, None

        # Step 3: No match found - use fallback based on physiographic zone
        return self._get_fallback_species(
            physiographic_zone,
            f"Species '{value_str}' not recognized, using fallback"
        )

    def _get_fallback_species(
        self,
        physiographic_zone: Optional[str],
        reason: str
    ) -> Tuple[str, int, str, float, str]:
        """
        Get fallback species (Terai spp or Hill spp) based on physiographic zone

        Args:
            physiographic_zone: Dominant physiographic zone
            reason: Reason for fallback

        Returns:
            Tuple of (scientific_name, species_code, method, confidence, warning)
        """
        # Terai zones: Bhawar, Chure Hillslopes, Dun, Inner River Valley, Terai, Madhesh
        terai_zones = [
            'Bhawar',
            'Chure Hillslopes',
            'Dun',
            'Inner River Valley',
            'Terai',
            'Madhesh'
        ]

        # Hill zones: High Mountain, Mahabharat, Middle Mountain
        # (all other zones default to Hill spp)

        if physiographic_zone and physiographic_zone in terai_zones:
            # Use Terai spp (code 22)
            fallback_code = 22
            warning = f"{reason}. Using 'Terai spp' based on {physiographic_zone} zone"
        else:
            # Use Hill spp (code 23)
            fallback_code = 23
            zone_info = f" ({physiographic_zone})" if physiographic_zone else ""
            warning = f"{reason}. Using 'Hill spp' based on physiographic zone{zone_info}"

        fallback_species = self.species_by_code.get(fallback_code)
        if fallback_species:
            return (
                fallback_species['scientific_name'],
                fallback_code,
                'fallback',
                0.5,  # Low confidence for fallback
                warning
            )
        else:
            # Fallback species not in database (shouldn't happen)
            return (
                None,
                None,
                'no_match',
                0.0,
                f"Fallback species (code {fallback_code}) not found in database"
            )

    def get_species_info_by_code(self, code: int) -> Optional[Dict]:
        """
        Get full species information by code

        Args:
            code: Species code (1-23)

        Returns:
            Dict with species info or None
        """
        return self.species_by_code.get(code)

    def get_all_valid_codes(self) -> List[int]:
        """
        Get list of all valid species codes

        Returns:
            List of valid codes
        """
        return sorted(self.species_by_code.keys())

    def get_species_code_mapping_table(self) -> List[Dict]:
        """
        Get complete species code mapping table for documentation

        Returns:
            List of dicts with code, scientific_name, local_name
        """
        result = []
        for code in sorted(self.species_by_code.keys()):
            species = self.species_by_code[code]
            result.append({
                'code': code,
                'scientific_name': species['scientific_name'],
                'local_name': species['local_name']
            })
        return result
