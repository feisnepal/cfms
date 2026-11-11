"""
Forest Committee Validation and Processing Service
"""
from typing import List, Dict, Tuple, Optional, Any
from sqlalchemy.orm import Session
from decimal import Decimal
import re


class ForestCommitteeValidation:
    """Validation and calculation service for forest user committees"""

    # Valid values for dropdowns
    VALID_GENDERS = ['महिला', 'पुरूष']
    VALID_POSITIONS = ['अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव', 'सदस्य']
    VALID_CASTE_CATEGORIES = ['जनजाती', 'आदिवासी', 'दलित', 'सिमान्तकृत', 'अन्य']

    # Key positions that must meet gender requirements
    KEY_POSITIONS_GROUP_1 = ['अध्यक्ष', 'कोषाध्यक्ष']  # At least one must be महिला
    KEY_POSITIONS_GROUP_2 = ['उपाध्यक्ष', 'सचिव']  # At least one must be महिला

    @classmethod
    def validate_mobile_number(cls, mobile: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Validate mobile number format
        Returns: (cleaned_mobile or None, error_message or None)
        """
        if mobile is None or mobile == '' or str(mobile).strip() == '':
            return None, None

        # Convert to string and clean
        mobile_str = str(mobile).strip()
        cleaned = mobile_str.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

        # Check if it's exactly 10 digits
        if not cleaned.isdigit():
            return None, "मोवाइल नंवर मात्र संख्यामा हुनुपर्छ (Mobile must contain only digits)"

        if len(cleaned) != 10:
            return None, f"मोवाइल नंवर ठीक १० अंकको हुनुपर्छ (Mobile must be exactly 10 digits, got {len(cleaned)})"

        return cleaned, None

    @classmethod
    def validate_main_committee_row(cls, row_data: dict, row_number: int) -> Tuple[dict, List[str], List[str]]:
        """
        Validate a single main committee row
        Returns: (cleaned_data, errors, warnings)
        """
        errors = []
        warnings = []
        cleaned_data = {}

        # Validate serial_no
        serial_no = row_data.get('serial_no')
        if serial_no is None or serial_no == '':
            errors.append("सि.नं. आवश्यक छ (Serial number is required)")
        else:
            try:
                serial_no = int(serial_no)
                if serial_no < 1 or serial_no > 15:
                    errors.append("सि.नं. १ देखि १५ को बीचमा हुनुपर्छ (Serial number must be between 1 and 15)")
                else:
                    cleaned_data['serial_no'] = serial_no
            except (ValueError, TypeError):
                errors.append("सि.नं. मान्य संख्या हुनुपर्छ (Serial number must be a valid number)")

        # Validate gender
        gender = row_data.get('gender')
        if not gender or str(gender).strip() == '':
            errors.append("लिङ्ग आवश्यक छ (Gender is required)")
        elif gender not in cls.VALID_GENDERS:
            errors.append(f"लिङ्ग '{', '.join(cls.VALID_GENDERS)}' मध्ये एक हुनुपर्छ (Gender must be one of: {', '.join(cls.VALID_GENDERS)})")
        else:
            cleaned_data['gender'] = gender

        # Validate position
        position = row_data.get('position')
        if not position or str(position).strip() == '':
            errors.append("पद आवश्यक छ (Position is required)")
        elif position not in cls.VALID_POSITIONS:
            errors.append(f"पद मान्य हुनुपर्छ (Position must be one of valid positions)")
        else:
            cleaned_data['position'] = position

        # Validate caste_category
        caste = row_data.get('caste_category')
        if not caste or str(caste).strip() == '':
            errors.append("जातिय वर्ग आवश्यक छ (Caste category is required)")
        elif caste not in cls.VALID_CASTE_CATEGORIES:
            errors.append(f"जातिय वर्ग मान्य हुनुपर्छ (Caste category must be one of valid categories)")
        else:
            cleaned_data['caste_category'] = caste

        # Validate name
        name = row_data.get('name')
        if not name or str(name).strip() == '':
            errors.append("नाम आवश्यक छ (Name is required)")
        else:
            cleaned_data['name'] = str(name).strip()

        # Validate address
        address = row_data.get('address')
        if not address or str(address).strip() == '':
            errors.append("ठेगाना आवश्यक छ (Address is required)")
        else:
            cleaned_data['address'] = str(address).strip()

        # Validate mobile (optional)
        mobile = row_data.get('mobile')
        if mobile and str(mobile).strip() != '':
            cleaned_mobile, mobile_error = cls.validate_mobile_number(mobile)
            if mobile_error:
                warnings.append(mobile_error)
            else:
                cleaned_data['mobile'] = cleaned_mobile
        else:
            cleaned_data['mobile'] = None

        return cleaned_data, errors, warnings

    @classmethod
    def validate_advisory_financial_row(cls, row_data: dict, row_number: int, max_serial: int = 10) -> Tuple[dict, List[str], List[str]]:
        """
        Validate a single advisory/financial committee row
        Returns: (cleaned_data, errors, warnings)
        """
        errors = []
        warnings = []
        cleaned_data = {}

        # Validate serial_no
        serial_no = row_data.get('serial_no')
        if serial_no is None or serial_no == '':
            errors.append("सि.नं. आवश्यक छ (Serial number is required)")
        else:
            try:
                serial_no = int(serial_no)
                if serial_no < 1 or serial_no > max_serial:
                    errors.append(f"सि.नं. १ देखि {max_serial} को बीचमा हुनुपर्छ (Serial number must be between 1 and {max_serial})")
                else:
                    cleaned_data['serial_no'] = serial_no
            except (ValueError, TypeError):
                errors.append("सि.नं. मान्य संख्या हुनुपर्छ (Serial number must be a valid number)")

        # Validate name
        name = row_data.get('name')
        if not name or str(name).strip() == '':
            errors.append("नाम आवश्यक छ (Name is required)")
        else:
            cleaned_data['name'] = str(name).strip()

        # Validate address
        address = row_data.get('address')
        if not address or str(address).strip() == '':
            errors.append("ठेगाना आवश्यक छ (Address is required)")
        else:
            cleaned_data['address'] = str(address).strip()

        # Validate mobile (optional)
        mobile = row_data.get('mobile')
        if mobile and str(mobile).strip() != '':
            cleaned_mobile, mobile_error = cls.validate_mobile_number(mobile)
            if mobile_error:
                warnings.append(mobile_error)
            else:
                cleaned_data['mobile'] = cleaned_mobile
        else:
            cleaned_data['mobile'] = None

        return cleaned_data, errors, warnings

    @classmethod
    def validate_committee_composition(cls, members: List[dict]) -> Tuple[bool, List[str]]:
        """
        Validate main committee composition rules:
        1. At least 50% महिला (women)
        2. At least one of {अध्यक्ष, कोषाध्यक्ष} must be महिला
        3. At least one of {उपाध्यक्ष, सचिव} must be महिला
        4. Each position (except सदस्य) should be unique

        Returns: (is_valid, warnings)
        Note: This returns warnings, not errors (flexible enforcement)
        """
        warnings = []

        if not members or len(members) == 0:
            return True, []

        # Count women
        total_members = len(members)
        women_count = sum(1 for m in members if m.get('gender') == 'महिला')
        women_percentage = (women_count / total_members * 100) if total_members > 0 else 0

        # Check 50% women rule
        if women_percentage < 50:
            warnings.append(
                f"⚠️ महिला प्रतिनिधित्व कम्तीमा ५०% हुनुपर्छ (Women representation must be at least 50%). "
                f"हालको: {women_count}/{total_members} ({women_percentage:.1f}%)"
            )

        # Check key position group 1 (अध्यक्ष or कोषाध्यक्ष must have at least one महिला)
        group1_women = any(
            m.get('position') in cls.KEY_POSITIONS_GROUP_1 and m.get('gender') == 'महिला'
            for m in members
        )
        if not group1_women:
            group1_filled = any(m.get('position') in cls.KEY_POSITIONS_GROUP_1 for m in members)
            if group1_filled:
                warnings.append(
                    "⚠️ अध्यक्ष वा कोषाध्यक्ष पदमध्ये कम्तीमा एक महिला हुनुपर्छ "
                    "(At least one of अध्यक्ष or कोषाध्यक्ष must be a woman)"
                )

        # Check key position group 2 (उपाध्यक्ष or सचिव must have at least one महिला)
        group2_women = any(
            m.get('position') in cls.KEY_POSITIONS_GROUP_2 and m.get('gender') == 'महिला'
            for m in members
        )
        if not group2_women:
            group2_filled = any(m.get('position') in cls.KEY_POSITIONS_GROUP_2 for m in members)
            if group2_filled:
                warnings.append(
                    "⚠️ उपाध्यक्ष वा सचिव पदमध्ये कम्तीमा एक महिला हुनुपर्छ "
                    "(At least one of उपाध्यक्ष or सचिव must be a woman)"
                )

        # Check position uniqueness (except सदस्य)
        position_counts = {}
        for member in members:
            position = member.get('position')
            if position and position != 'सदस्य':
                position_counts[position] = position_counts.get(position, 0) + 1

        for position, count in position_counts.items():
            if count > 1:
                warnings.append(f"⚠️ '{position}' पद {count} पटक दोहोरिएको छ (Position '{position}' is assigned {count} times)")

        return True, warnings

    @classmethod
    def calculate_committee_summary(cls, main_members: List[dict]) -> dict:
        """Calculate summary statistics for committee composition"""
        total = len(main_members)
        women = sum(1 for m in main_members if m.get('gender') == 'महिला')
        men = sum(1 for m in main_members if m.get('gender') == 'पुरूष')
        women_pct = (women / total * 100) if total > 0 else 0

        # Position assignments
        positions_filled = {}
        for member in main_members:
            position = member.get('position')
            name = member.get('name')
            if position and position != 'सदस्य':
                if position in positions_filled:
                    # Duplicate position
                    positions_filled[position] += f", {name}"
                else:
                    positions_filled[position] = name

        # Find unfilled positions
        all_positions = ['अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव']
        unfilled = [p for p in all_positions if p not in positions_filled]

        return {
            'total': total,
            'women': women,
            'men': men,
            'women_percentage': round(women_pct, 1),
            'meets_50_percent': women_pct >= 50,
            'positions_filled': positions_filled,
            'unfilled_positions': unfilled
        }

    @classmethod
    def parse_committee_sheet(cls, worksheet, header_map: dict, committee_type: str = 'main') -> Tuple[List[dict], List[dict]]:
        """
        Parse a committee worksheet from Excel

        Args:
            worksheet: openpyxl worksheet object
            header_map: mapping of Nepali headers to field names
            committee_type: 'main', 'advisory', or 'financial'

        Returns:
            (valid_records, validation_results)
        """
        valid_records = []
        validation_results = []

        # Find header row (should be row 1)
        headers = {}
        for col_idx, cell in enumerate(worksheet[1], start=1):
            if cell.value and str(cell.value).strip() in header_map:
                headers[col_idx] = header_map[str(cell.value).strip()]

        if not headers:
            return [], []

        # Process data rows (starting from row 3, skipping row 2 which is English headers)
        for row_idx, row in enumerate(worksheet.iter_rows(min_row=3, values_only=True), start=3):
            # Skip empty rows
            if all(cell is None or str(cell).strip() == '' for cell in row):
                continue

            # Extract data using header mapping
            row_data = {}
            for col_idx, value in enumerate(row, start=1):
                if col_idx in headers:
                    field_name = headers[col_idx]
                    row_data[field_name] = value

            # Validate the row
            if committee_type == 'main':
                cleaned_data, errors, warnings = cls.validate_main_committee_row(row_data, row_idx)
            else:
                cleaned_data, errors, warnings = cls.validate_advisory_financial_row(row_data, row_idx)

            # Add to validation results
            validation_result = {
                'row_number': row_idx,
                'is_valid': len(errors) == 0,
                'errors': errors,
                'warnings': warnings,
                'data': cleaned_data if len(errors) == 0 else None
            }
            validation_results.append(validation_result)

            # Add to valid records if no errors
            if len(errors) == 0:
                valid_records.append(cleaned_data)

        return valid_records, validation_results
