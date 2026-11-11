"""
Species name fuzzy matching and normalization
Handles typos, local names, and variations in species identification
"""
from typing import Dict, List, Tuple, Optional
from fuzzywuzzy import fuzz, process
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text


class SpeciesMatcher:
    """Handles species name matching with fuzzy logic"""

    def __init__(self, db: Session, threshold: int = 85):
        """
        Initialize species matcher

        Args:
            db: Database session
            threshold: Minimum similarity score (0-100) for fuzzy matching
        """
        self.db = db
        self.threshold = threshold
        self.species_list = self._load_species()
        self.alias_map = self._build_alias_map()
        self.scientific_names = [s['scientific_name'] for s in self.species_list]

    def _load_species(self) -> List[Dict]:
        """Load all valid species from database"""
        query = text("""
            SELECT scientific_name, local_name, aliases
            FROM public.tree_species_coefficients
            WHERE is_active = TRUE
            ORDER BY scientific_name
        """)
        result = self.db.execute(query).fetchall()

        species_list = []
        for row in result:
            species_list.append({
                'scientific_name': row[0],
                'local_name': row[1],
                'aliases': row[2] if row[2] else []
            })

        return species_list

    def _build_alias_map(self) -> Dict[str, str]:
        """Create mapping of aliases to scientific names"""
        alias_map = {}

        for species in self.species_list:
            scientific = species['scientific_name']

            # Add local name
            if species['local_name']:
                alias_map[species['local_name'].lower()] = scientific

            # Add aliases
            if species['aliases']:
                for alias in species['aliases']:
                    if alias:  # Check not empty
                        alias_map[alias.lower()] = scientific

            # Add scientific name itself
            alias_map[scientific.lower()] = scientific

        # A local-name cell often lists several names ("Sal, Sakhu, Sakhuwa"): each one is a name of its own. A name shared by more than one
        # species is ambiguous and is left out, so "Sal" never silently picks the wrong tree.
        import re

        owners: Dict[str, set] = {}
        for species in self.species_list:
            for part in re.split(r"[,;/]", species['local_name'] or ''):
                part = ' '.join(part.split()).lower()
                if part:
                    owners.setdefault(part, set()).add(species['scientific_name'])
        for part, names in owners.items():
            if len(names) == 1 and part not in alias_map:
                alias_map[part] = next(iter(names))

        return alias_map

    def normalize_species_name(self, name: str) -> Optional[str]:
        """
        Normalize species name (trim, title case, etc)

        Args:
            name: Input species name

        Returns:
            Normalized name or None if invalid
        """
        if pd.isna(name) or not name:
            return None

        # Remove extra whitespace
        normalized = ' '.join(str(name).strip().split())

        # Convert to title case
        normalized = normalized.title()

        # Handle 'spp' vs 'spp.'
        normalized = normalized.replace('Spp.', 'spp')
        normalized = normalized.replace(' Spp', ' spp')

        return normalized

    def match_species(
        self,
        name: str,
        threshold: Optional[int] = None
    ) -> Tuple[Optional[str], float, str]:
        """
        Match species name using fuzzy matching

        Args:
            name: Input species name
            threshold: Override default threshold

        Returns:
            Tuple of (matched_name, confidence, method)
            - matched_name: Best match or None
            - confidence: Match score 0.0-1.0
            - method: 'exact', 'alias', 'fuzzy', or 'no_match'
        """
        if not name:
            return None, 0.0, 'no_match'

        # Use instance threshold if not provided
        if threshold is None:
            threshold = self.threshold

        # Step 1: Normalize input
        normalized = self.normalize_species_name(name)
        if not normalized:
            return None, 0.0, 'no_match'

        # Step 2: Exact match check (case-insensitive)
        for species_name in self.scientific_names:
            if normalized.lower() == species_name.lower():
                return species_name, 1.0, 'exact'

        # Step 3: Alias match check
        if normalized.lower() in self.alias_map:
            matched = self.alias_map[normalized.lower()]
            return matched, 1.0, 'alias'

        # Step 4: Fuzzy matching
        match_result = process.extractOne(
            normalized,
            self.scientific_names,
            scorer=fuzz.token_sort_ratio
        )

        if match_result:
            matched_name, score = match_result[0], match_result[1]
            confidence = score / 100.0

            if score >= threshold:
                return matched_name, confidence, 'fuzzy'

        # No match found
        return None, 0.0, 'no_match'

    def get_suggestions(self, name: str, top_n: int = 3) -> List[Dict]:
        """
        Get top N species suggestions for unmatched name

        Args:
            name: Input species name
            top_n: Number of suggestions to return

        Returns:
            List of suggestion dictionaries
        """
        normalized = self.normalize_species_name(name)
        if not normalized:
            return []

        matches = process.extract(
            normalized,
            self.scientific_names,
            scorer=fuzz.token_sort_ratio,
            limit=top_n
        )

        suggestions = []
        for match_name, score in matches:
            # Find local name
            local = next(
                (s['local_name'] for s in self.species_list
                 if s['scientific_name'] == match_name),
                None
            )
            suggestions.append({
                'scientific_name': match_name,
                'local_name': local,
                'similarity': score / 100.0
            })

        return suggestions

    def validate_all_species(
        self,
        species_column: pd.Series
    ) -> Dict[str, List]:
        """
        Validate all species names in a column

        Args:
            species_column: Pandas series with species names

        Returns:
            Dict with 'matched', 'fuzzy_matched', 'unmatched' lists
        """
        results = {
            'exact_matches': [],
            'fuzzy_matches': [],
            'unmatched': [],
            'corrections': {}
        }

        for idx, name in species_column.items():
            matched, confidence, method = self.match_species(name)

            if method == 'exact' or method == 'alias':
                results['exact_matches'].append(idx)
            elif method == 'fuzzy':
                results['fuzzy_matches'].append(idx)
                results['corrections'][idx] = {
                    'original': name,
                    'matched': matched,
                    'confidence': confidence
                }
            else:
                results['unmatched'].append(idx)

        return results
