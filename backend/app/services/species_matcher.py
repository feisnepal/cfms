"""
Species Matcher Service

Identifies tree species from various input formats:
- Numeric code (1, 2, 3, ...)
- Scientific name (Shorea robusta, Alnus nepalensis, etc.)
- Abbreviated codes (sho, rob, sho rob, sho/rob, aln nep, etc.)
- Nepali Unicode name (साल, उत्तिस, etc.)
- Nepali Romanized name (Sal, Uttis, etc.)
- Common English name (Khair, Utis, etc.)
"""
# business: CFMG §X.Y — species identification by scientific/local name
# why: fuzzy matching for field data where names may be misspelled
# constraint: minimum confidence threshold 0.6 for auto-match

import logging
import re
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class SpeciesData:
    """Represents a single species record"""

    def __init__(self, code: int, species: str, species_nepali_unicode: str,
                 name_nep: str, common_name: str):
        self.code = code
        self.species = species.strip()
        self.species_nepali_unicode = species_nepali_unicode.strip()
        self.name_nep = name_nep.strip()
        self.common_name = common_name.strip()

        # Parse scientific name parts for abbreviated matching
        self.genus = ""
        self.species_epithet = ""
        self._parse_scientific_name()

    def _parse_scientific_name(self):
        """Extract genus and species epithet from scientific name"""
        parts = self.species.split()
        if len(parts) >= 2:
            self.genus = parts[0]
            self.species_epithet = parts[1]
        elif len(parts) == 1:
            self.genus = parts[0]
            self.species_epithet = ""

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "code": self.code,
            "species": self.species,
            "species_nepali_unicode": self.species_nepali_unicode,
            "name_nep": self.name_nep,
            "common_name": self.common_name
        }

    def __repr__(self):
        return f"<Species {self.code}: {self.species} ({self.name_nep})>"


class SpeciesMatcher:
    """
    Species identification service

    Usage:
        matcher = SpeciesMatcher()
        species = matcher.identify("18")  # Returns Shorea robusta
        species = matcher.identify("साल")  # Returns Shorea robusta
        species = matcher.identify("Sal")  # Returns Shorea robusta
    """

    def __init__(self, species_file: Optional[str] = None):
        """
        Initialize species matcher

        Args:
            species_file: Path to species.txt file (default: auto-detect)
        """
        if species_file is None:
            # Auto-detect species file location
            base_path = Path(__file__).parent.parent.parent.parent
            species_file = base_path / "species.txt"

        self.species_file = Path(species_file)
        self.species_data: Dict[int, SpeciesData] = {}
        self._load_species_data()

    def _load_species_data(self):
        """Load species data from file"""
        try:
            with open(self.species_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Skip header line
            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue

                parts = line.split('\t')
                if len(parts) >= 5:
                    try:
                        code = int(parts[0])
                        species = SpeciesData(
                            code=code,
                            species=parts[1],
                            species_nepali_unicode=parts[2],
                            name_nep=parts[3],
                            common_name=parts[4]
                        )
                        self.species_data[code] = species
                    except (ValueError, IndexError) as e:
                        # Skip malformed lines
                        continue

            logger.info(f"Loaded {len(self.species_data)} species from {self.species_file}")

        except FileNotFoundError:
            logger.warning(f"Warning: Species file not found: {self.species_file}")
            self.species_data = {}
        except Exception as e:
            logger.error(f"Error loading species data: {e}")
            self.species_data = {}

    def _match_abbreviated_code(self, input_text: str) -> Optional[Dict]:
        """
        Match abbreviated scientific name codes

        Examples:
            "sho" -> Shorea robusta
            "rob" -> Shorea robusta
            "sho rob" -> Shorea robusta
            "sho/rob" -> Shorea robusta
            "aln" -> Alnus nepalensis
            "aln nep" -> Alnus nepalensis

        Args:
            input_text: Abbreviated code input

        Returns:
            Match result or None
        """
        if not input_text or len(input_text) < 3:
            return None

        input_lower = input_text.lower().strip()

        # Skip if input is clearly a full scientific name (will be handled by exact match)
        # Only process abbreviations (3-10 chars per word)
        if ' ' in input_lower:
            parts_check = input_lower.split()
            # If any part is longer than 10 chars, it's likely a full name, not abbreviation
            if any(len(p) > 10 for p in parts_check):
                return None

        # Normalize separators: space, slash, dash, underscore -> space
        normalized = re.sub(r'[/\-_]+', ' ', input_lower)
        parts = normalized.split()

        # Try to match patterns
        matches = []

        for species in self.species_data.values():
            genus_lower = species.genus.lower()
            epithet_lower = species.species_epithet.lower()

            confidence = 0.0
            match_type = None

            # Pattern 1: Single abbreviation matches genus start
            # "sho" -> "Shorea", "rob" -> "robusta"
            if len(parts) == 1:
                abbrev = parts[0]

                # Skip if abbreviation is too long (likely not an abbreviation)
                if len(abbrev) > 8:
                    continue

                # Check genus (higher priority)
                if genus_lower.startswith(abbrev) and len(abbrev) >= 3:
                    # Calculate confidence based on match length
                    # Give minimum 0.7 confidence for 3+ char genus matches
                    confidence = max(0.7, len(abbrev) / len(genus_lower))
                    match_type = "abbrev_genus"

                # Check species epithet
                elif epithet_lower and epithet_lower.startswith(abbrev) and len(abbrev) >= 3:
                    # Slightly lower confidence for epithet-only match
                    confidence = max(0.65, len(abbrev) / len(epithet_lower))
                    match_type = "abbrev_epithet"

            # Pattern 2: Two abbreviations match genus + epithet
            # "sho rob" -> "Shorea robusta"
            # "aln nep" -> "Alnus nepalensis"
            elif len(parts) == 2:
                abbrev1, abbrev2 = parts[0], parts[1]

                # Skip if abbreviations are too long
                if len(abbrev1) > 8 or len(abbrev2) > 8:
                    continue

                # Check genus + epithet
                if genus_lower.startswith(abbrev1) and epithet_lower.startswith(abbrev2):
                    # Higher confidence for matching both parts
                    conf1 = len(abbrev1) / len(genus_lower) if genus_lower else 0
                    conf2 = len(abbrev2) / len(epithet_lower) if epithet_lower else 0
                    confidence = max(0.8, (conf1 + conf2) / 2 + 0.25)  # Bonus for matching both
                    match_type = "abbrev_both"

                # Check epithet + genus (reversed)
                elif epithet_lower.startswith(abbrev1) and genus_lower.startswith(abbrev2):
                    conf1 = len(abbrev1) / len(epithet_lower) if epithet_lower else 0
                    conf2 = len(abbrev2) / len(genus_lower) if genus_lower else 0
                    confidence = max(0.75, (conf1 + conf2) / 2 + 0.2)  # Slightly lower for reversed
                    match_type = "abbrev_both_reversed"

            # Add to matches if confidence is reasonable
            if confidence > 0.5:
                matches.append({
                    "species": species,
                    "confidence": min(confidence, 1.0),  # Cap at 1.0
                    "match_type": match_type
                })

        # Return best match if found
        if matches:
            # Sort by confidence (highest first)
            matches.sort(key=lambda x: x["confidence"], reverse=True)
            best = matches[0]

            # Only return if confidence is reasonable
            if best["confidence"] >= 0.65:
                return {
                    "species": best["species"].to_dict(),
                    "match_type": "abbreviated",
                    "confidence": round(best["confidence"], 2),
                    "matched_field": best["match_type"]
                }

        return None

    def identify(self, input_text: str, min_confidence: float = 0.6) -> Optional[Dict]:
        """
        Identify species from input text

        Args:
            input_text: User input (code, name, etc.)
            min_confidence: Minimum confidence score (0-1) for fuzzy matches

        Returns:
            Dictionary with species data and match confidence, or None if no match
            {
                "species": {...},
                "match_type": "code|exact|fuzzy",
                "confidence": 0.0-1.0,
                "matched_field": "code|species|nepali|romanized|common"
            }
        """
        if not input_text:
            return None

        input_text = input_text.strip()

        # Strategy 1: Try numeric code
        if input_text.isdigit():
            code = int(input_text)
            if code in self.species_data:
                return {
                    "species": self.species_data[code].to_dict(),
                    "match_type": "code",
                    "confidence": 1.0,
                    "matched_field": "code"
                }

        # Strategy 2: Try abbreviated code matching (sho, rob, sho rob, sho/rob, etc.)
        abbrev_result = self._match_abbreviated_code(input_text)
        if abbrev_result:
            return abbrev_result

        # Strategy 3: Try exact matches (case-insensitive)
        input_lower = input_text.lower()

        for species in self.species_data.values():
            # Exact scientific name match
            if species.species.lower() == input_lower:
                return {
                    "species": species.to_dict(),
                    "match_type": "exact",
                    "confidence": 1.0,
                    "matched_field": "species"
                }

            # Exact Nepali Unicode match
            if species.species_nepali_unicode == input_text:
                return {
                    "species": species.to_dict(),
                    "match_type": "exact",
                    "confidence": 1.0,
                    "matched_field": "nepali_unicode"
                }

            # Exact romanized Nepali match
            if species.name_nep.lower() == input_lower:
                return {
                    "species": species.to_dict(),
                    "match_type": "exact",
                    "confidence": 1.0,
                    "matched_field": "nepali_romanized"
                }

            # Exact common name match
            if species.common_name.lower() == input_lower:
                return {
                    "species": species.to_dict(),
                    "match_type": "exact",
                    "confidence": 1.0,
                    "matched_field": "common_name"
                }

        # Strategy 3: Fuzzy matching for typos/variations
        best_match = None
        best_confidence = 0.0
        best_field = None

        for species in self.species_data.values():
            # Check scientific name
            conf = self._similarity(input_lower, species.species.lower())
            if conf > best_confidence:
                best_confidence = conf
                best_match = species
                best_field = "species"

            # Check romanized Nepali
            conf = self._similarity(input_lower, species.name_nep.lower())
            if conf > best_confidence:
                best_confidence = conf
                best_match = species
                best_field = "nepali_romanized"

            # Check common name
            conf = self._similarity(input_lower, species.common_name.lower())
            if conf > best_confidence:
                best_confidence = conf
                best_match = species
                best_field = "common_name"

        # Return fuzzy match if confidence is high enough
        if best_match and best_confidence >= min_confidence:
            return {
                "species": best_match.to_dict(),
                "match_type": "fuzzy",
                "confidence": round(best_confidence, 2),
                "matched_field": best_field
            }

        # No match found
        return None

    def identify_batch(self, input_list: List[str],
                      min_confidence: float = 0.6) -> List[Optional[Dict]]:
        """
        Identify multiple species at once

        Args:
            input_list: List of species names/codes
            min_confidence: Minimum confidence for fuzzy matches

        Returns:
            List of match results (same order as input)
        """
        results = []
        for input_text in input_list:
            result = self.identify(input_text, min_confidence)
            results.append(result)
        return results

    def suggest(self, partial_input: str, limit: int = 5) -> List[Dict]:
        """
        Get species suggestions for autocomplete

        Args:
            partial_input: Partial species name
            limit: Maximum number of suggestions

        Returns:
            List of species suggestions with confidence scores
        """
        if not partial_input:
            return []

        partial_lower = partial_input.lower()
        suggestions = []

        for species in self.species_data.values():
            # Check if any field starts with the input
            max_conf = 0.0
            matched_field = None

            if species.species.lower().startswith(partial_lower):
                max_conf = 1.0
                matched_field = "species"
            elif species.name_nep.lower().startswith(partial_lower):
                max_conf = 1.0
                matched_field = "nepali_romanized"
            elif species.common_name.lower().startswith(partial_lower):
                max_conf = 1.0
                matched_field = "common_name"
            else:
                # Fuzzy match
                conf_species = self._similarity(partial_lower, species.species.lower())
                conf_nep = self._similarity(partial_lower, species.name_nep.lower())
                conf_common = self._similarity(partial_lower, species.common_name.lower())

                max_conf = max(conf_species, conf_nep, conf_common)
                if max_conf == conf_species:
                    matched_field = "species"
                elif max_conf == conf_nep:
                    matched_field = "nepali_romanized"
                else:
                    matched_field = "common_name"

            if max_conf > 0.3:  # Lower threshold for suggestions
                suggestions.append({
                    "species": species.to_dict(),
                    "confidence": round(max_conf, 2),
                    "matched_field": matched_field
                })

        # Sort by confidence (highest first)
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)

        return suggestions[:limit]

    def _similarity(self, s1: str, s2: str) -> float:
        """
        Calculate similarity between two strings using SequenceMatcher

        Returns:
            Similarity score (0-1)
        """
        return SequenceMatcher(None, s1, s2).ratio()

    def get_all_species(self) -> List[Dict]:
        """Get all species in the database"""
        return [species.to_dict() for species in self.species_data.values()]

    def get_species_by_code(self, code: int) -> Optional[Dict]:
        """Get species by numeric code"""
        if code in self.species_data:
            return self.species_data[code].to_dict()
        return None

    def validate_species_column(self, values: List[str],
                               min_confidence: float = 0.6) -> Dict:
        """
        Validate a column of species data from uploaded CSV/Excel

        Args:
            values: List of species values from user upload
            min_confidence: Minimum confidence for matches

        Returns:
            Validation report with matched, unmatched, and suggestions
        """
        matched = []
        unmatched = []
        low_confidence = []

        for i, value in enumerate(values):
            if not value or str(value).strip() == "":
                unmatched.append({
                    "row": i + 1,
                    "input": value,
                    "reason": "Empty value"
                })
                continue

            result = self.identify(str(value), min_confidence)

            if result:
                if result["confidence"] >= 0.9:
                    matched.append({
                        "row": i + 1,
                        "input": value,
                        "species": result["species"],
                        "confidence": result["confidence"],
                        "match_type": result["match_type"]
                    })
                else:
                    # Low confidence match - needs user confirmation
                    low_confidence.append({
                        "row": i + 1,
                        "input": value,
                        "suggested_species": result["species"],
                        "confidence": result["confidence"],
                        "alternatives": self.suggest(str(value), limit=3)
                    })
            else:
                # No match found
                suggestions = self.suggest(str(value), limit=3)
                unmatched.append({
                    "row": i + 1,
                    "input": value,
                    "reason": "No match found",
                    "suggestions": suggestions
                })

        return {
            "total": len(values),
            "matched": len(matched),
            "unmatched": len(unmatched),
            "low_confidence": len(low_confidence),
            "matched_details": matched,
            "unmatched_details": unmatched,
            "low_confidence_details": low_confidence
        }


# Singleton instance
_species_matcher_instance = None


def get_species_matcher() -> SpeciesMatcher:
    """Get or create singleton species matcher instance"""
    global _species_matcher_instance
    if _species_matcher_instance is None:
        _species_matcher_instance = SpeciesMatcher()
    return _species_matcher_instance
