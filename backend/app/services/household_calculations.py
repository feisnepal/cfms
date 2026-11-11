"""
Household Calculations Service
Handles automatic calculations for household forest product demands
"""
from decimal import Decimal
from typing import Optional, Dict, Tuple
from sqlalchemy.orm import Session

from ..models.caste_classification import CasteClassification


class HouseholdCalculations:
    """
    Service for calculating household forest product demands
    All calculations are on yearly basis
    """

    # Conversion constant: 1 भारी = 30 kg (Forest Regulation 2079)
    BHARI_TO_KG = Decimal('30')

    # Fodder consumption rates (kg/day)
    COW_OX_GRASS_KG_PER_DAY = Decimal('20')
    BUFFALO_GRASS_KG_PER_DAY = Decimal('30')
    GOAT_SHEEP_GRASS_KG_PER_DAY = Decimal('5')

    # Bedding material consumption rate (kg/day)
    CATTLE_BEDDING_KG_PER_DAY = Decimal('10')  # For cow/ox and buffalo

    # Firewood consumption rates (kg/year)
    PERSON_FIREWOOD_KG_PER_YEAR = Decimal('250')
    CATTLE_FIREWOOD_KG_PER_YEAR = Decimal('600')  # For cow/ox and buffalo

    # Days in year
    DAYS_PER_YEAR = Decimal('365')

    @classmethod
    def calculate_grass_demand(
        cls,
        cow_ox_count: int,
        buffalo_count: int,
        goat_sheep_count: int
    ) -> Decimal:
        """
        Calculate fodder (grass) demand in भारी/year

        Formula:
        Daily needs:
        - गाइ गोरू (cow/ox): 20 kg/day
        - भैसी राँगा (buffalo): 30 kg/day
        - बाख्रा भेडा (goat/sheep): 5 kg/day

        Total kg = (cow_ox × 20 × 365) + (buffalo × 30 × 365) + (goat_sheep × 5 × 365)
        Result in भारी = Total kg ÷ 30

        Args:
            cow_ox_count: Number of cows/oxen
            buffalo_count: Number of buffaloes
            goat_sheep_count: Number of goats/sheep

        Returns:
            Grass demand in भारी/year (rounded to 2 decimals)
        """
        daily_kg = (
            Decimal(cow_ox_count) * cls.COW_OX_GRASS_KG_PER_DAY +
            Decimal(buffalo_count) * cls.BUFFALO_GRASS_KG_PER_DAY +
            Decimal(goat_sheep_count) * cls.GOAT_SHEEP_GRASS_KG_PER_DAY
        )
        yearly_kg = daily_kg * cls.DAYS_PER_YEAR
        bhari = yearly_kg / cls.BHARI_TO_KG
        return round(bhari, 2)

    @classmethod
    def calculate_bedding_demand(
        cls,
        cow_ox_count: int,
        buffalo_count: int
    ) -> Decimal:
        """
        Calculate bedding material (सोत्तर) demand in भारी/year

        Formula:
        Only for: गाइ गोरू + भैसी राँगा
        Daily needs: 10 kg/day per cattle

        Total kg = (cow_ox + buffalo) × 10 × 365
        Result in भारी = Total kg ÷ 30

        Args:
            cow_ox_count: Number of cows/oxen
            buffalo_count: Number of buffaloes

        Returns:
            Bedding demand in भारी/year (rounded to 2 decimals)
        """
        total_cattle = Decimal(cow_ox_count + buffalo_count)
        daily_kg = total_cattle * cls.CATTLE_BEDDING_KG_PER_DAY
        yearly_kg = daily_kg * cls.DAYS_PER_YEAR
        bhari = yearly_kg / cls.BHARI_TO_KG
        return round(bhari, 2)

    @classmethod
    def calculate_firewood_demand(
        cls,
        female_count: int,
        male_count: int,
        cow_ox_count: int,
        buffalo_count: int
    ) -> Decimal:
        """
        Calculate firewood (दाउरा) demand in भारी/year

        Formula:
        Per person: 250 kg/year
        Per cattle (गाइ गोरू + भैसी राँगा): 600 kg/year

        Total population = female_count + male_count
        Total kg = (Total population × 250) + ((cow_ox + buffalo) × 600)
        Result in भारी = Total kg ÷ 30

        Args:
            female_count: Number of females
            male_count: Number of males
            cow_ox_count: Number of cows/oxen
            buffalo_count: Number of buffaloes

        Returns:
            Firewood demand in भारी/year (rounded to 2 decimals)
        """
        total_population = Decimal(female_count + male_count)
        total_cattle = Decimal(cow_ox_count + buffalo_count)

        person_kg = total_population * cls.PERSON_FIREWOOD_KG_PER_YEAR
        cattle_kg = total_cattle * cls.CATTLE_FIREWOOD_KG_PER_YEAR

        total_kg = person_kg + cattle_kg
        bhari = total_kg / cls.BHARI_TO_KG
        return round(bhari, 2)

    @staticmethod
    def lookup_caste_classification(
        surname: str,
        db: Session
    ) -> Optional[Dict[str, str]]:
        """
        Lookup caste classification by surname

        Args:
            surname: Surname (थर) to lookup
            db: Database session

        Returns:
            Dictionary with classification info or None if not found
            {
                "classification_ne": "जनजाती",
                "classification_en": "Janajati",
                "caste_ne": "मगर",
                "caste_en": "Magar"
            }
        """
        result = db.query(CasteClassification).filter(
            CasteClassification.surname_ne == surname
        ).first()

        if result:
            return {
                "classification_ne": result.classification_ne,
                "classification_en": result.classification_en,
                "caste_ne": result.caste_ne,
                "caste_en": result.caste_en
            }
        return None

    @staticmethod
    def suggest_prosperity_level(
        land_area: Optional[Decimal],
        land_unit: Optional[str],
        cow_ox_count: int,
        buffalo_count: int,
        goat_sheep_count: int
    ) -> str:
        """
        Auto-suggest prosperity level based on land holdings and livestock

        Categories:
        - सम्पन्न (Prosperous): Large land + significant livestock
        - मध्यम (Medium): Moderate land + some livestock
        - विपन्न (Poor): Small land + minimal livestock
        - अति विपन्न (Very Poor): Very small/no land + no livestock

        Args:
            land_area: Land area
            land_unit: Land unit (ropani/kaththa)
            cow_ox_count: Number of cows/oxen
            buffalo_count: Number of buffaloes
            goat_sheep_count: Number of goats/sheep

        Returns:
            Suggested prosperity level
        """
        # Convert land to ropani for comparison (1 ropani = 16 kaththa)
        land_in_ropani = Decimal('0')
        if land_area:
            if land_unit == 'kaththa':
                land_in_ropani = land_area / Decimal('16')
            else:
                land_in_ropani = land_area

        # Calculate livestock score (weighted)
        livestock_score = (
            cow_ox_count * 3 +  # Cows/oxen are more valuable
            buffalo_count * 3 +  # Buffaloes are more valuable
            goat_sheep_count * 1  # Goats/sheep less valuable
        )

        # Determine prosperity level
        if land_in_ropani >= Decimal('10') and livestock_score >= 10:
            return 'सम्पन्न'  # Prosperous
        elif land_in_ropani >= Decimal('5') or livestock_score >= 5:
            return 'मध्यम'  # Medium
        elif land_in_ropani >= Decimal('1') or livestock_score >= 2:
            return 'विपन्न'  # Poor
        else:
            return 'अति विपन्न'  # Very Poor

    @classmethod
    def calculate_all_demands(
        cls,
        female_count: int,
        male_count: int,
        cow_ox_count: int,
        buffalo_count: int,
        goat_sheep_count: int
    ) -> Dict[str, Decimal]:
        """
        Calculate all forest product demands at once

        Args:
            female_count: Number of females
            male_count: Number of males
            cow_ox_count: Number of cows/oxen
            buffalo_count: Number of buffaloes
            goat_sheep_count: Number of goats/sheep

        Returns:
            Dictionary with all calculated demands:
            {
                "firewood_bhari": Decimal,
                "grass_bhari": Decimal,
                "bedding_bhari": Decimal
            }
        """
        return {
            "firewood_bhari": cls.calculate_firewood_demand(
                female_count, male_count, cow_ox_count, buffalo_count
            ),
            "grass_bhari": cls.calculate_grass_demand(
                cow_ox_count, buffalo_count, goat_sheep_count
            ),
            "bedding_bhari": cls.calculate_bedding_demand(
                cow_ox_count, buffalo_count
            )
        }

    @classmethod
    def validate_and_calculate(
        cls,
        household_data: dict,
        db: Session
    ) -> Tuple[dict, list]:
        """
        Validate household data and perform automatic calculations

        Args:
            household_data: Dictionary with household fields
            db: Database session

        Returns:
            Tuple of (updated_data, warnings)
            - updated_data: Data with calculated fields
            - warnings: List of warning messages
        """
        warnings = []

        # Calculate demands if not manually set
        if household_data.get('firewood_auto_calculated', True):
            household_data['firewood_demand_bhari'] = cls.calculate_firewood_demand(
                household_data.get('female_count', 0),
                household_data.get('male_count', 0),
                household_data.get('cow_ox_count', 0),
                household_data.get('buffalo_count', 0)
            )

        if household_data.get('grass_auto_calculated', True):
            household_data['grass_demand_bhari'] = cls.calculate_grass_demand(
                household_data.get('cow_ox_count', 0),
                household_data.get('buffalo_count', 0),
                household_data.get('goat_sheep_count', 0)
            )

        if household_data.get('bedding_auto_calculated', True):
            household_data['bedding_demand_bhari'] = cls.calculate_bedding_demand(
                household_data.get('cow_ox_count', 0),
                household_data.get('buffalo_count', 0)
            )

        # Lookup caste classification if not manual
        if not household_data.get('caste_classification_manual', False):
            surname = household_data.get('surname')
            if surname:
                caste_info = cls.lookup_caste_classification(surname, db)
                if caste_info:
                    household_data['caste_classification_ne'] = caste_info['classification_ne']
                    household_data['caste_classification_en'] = caste_info['classification_en']
                else:
                    warnings.append(f"Surname '{surname}' not found in caste database")

        # Auto-suggest prosperity level if not manually set
        if household_data.get('prosperity_auto_suggested', True):
            household_data['prosperity_level'] = cls.suggest_prosperity_level(
                household_data.get('land_area'),
                household_data.get('land_unit'),
                household_data.get('cow_ox_count', 0),
                household_data.get('buffalo_count', 0),
                household_data.get('goat_sheep_count', 0)
            )

        return household_data, warnings
