"""Pydantic schemas for forest metadata forms.

Defines the input/output models for forest calculation metadata including
administrative location, registration details, fiscal year, and Nepali
date validation. Uses custom field validators for Nepali date formats.

See also:
    app.utils.nepali_date — validation helpers
    app.services.metadata.admin_location_service — location resolution
"""

from typing import Optional
from pydantic import BaseModel, field_validator, model_validator
import re

from app.utils.nepali_date import (
    is_valid_nepali_date,
    is_valid_nepali_fiscal_year,
    is_valid_nepali_year_only,
)
from app.utils.number_format import normalize_nepali_digits


class MetadataFormUserInputs(BaseModel):
    """User input fields for forest metadata form."""
    cf_registration_number: Optional[str] = None
    op_preparation_year: Optional[int] = None
    sn_number: Optional[str] = None
    province_guideline_year: Optional[int] = None

    province: Optional[str] = None
    forest_district: Optional[str] = None
    division: Optional[str] = None
    sub_division: Optional[str] = None
    sub_division_chief: Optional[str] = None
    forest_management_section_chief: Optional[str] = None
    division_forest_officer: Optional[str] = None
    forest_municipality: Optional[str] = None
    municipality_type: Optional[str] = None
    forest_municipality_type: Optional[str] = None
    forest_ward: Optional[str] = None

    cf_sn_number: Optional[int] = None
    constitution_approved_year: Optional[str] = None
    kabuliyatnama_date: Optional[str] = None
    user_group_reg_no: Optional[int] = None
    op_start_fy: Optional[str] = None
    op_end_fy: Optional[str] = None
    cf_code: Optional[str] = None

    cf_boundary_east: Optional[str] = None
    cf_boundary_south: Optional[str] = None
    cf_boundary_west: Optional[str] = None
    cf_boundary_north: Optional[str] = None

    physiography_zone: Optional[str] = None
    protected_area_status: Optional[str] = None
    cf_handover_date: Optional[str] = None

    ug_prepopulated: Optional[bool] = None
    ug_province: Optional[str] = None
    ug_district: Optional[str] = None
    ug_division: Optional[str] = None
    ug_sub_division: Optional[str] = None
    ug_municipality: Optional[str] = None
    ug_municipality_type: Optional[str] = None
    ug_ward: Optional[str] = None
    ug_settlement: Optional[str] = None

    ug_boundary_east: Optional[str] = None
    ug_boundary_south: Optional[str] = None
    ug_boundary_west: Optional[str] = None
    ug_boundary_north: Optional[str] = None

    technical_assistance_org: Optional[str] = None
    op_general_assembly_date: Optional[str] = None
    forest_type: Optional[str] = "प्राकृतिक"
    forest_abundance: Optional[str] = "रुख"
    forest_avg_age: Optional[int] = 80
    main_non_timber_fp: Optional[str] = None
    avg_crown_density_pct: Optional[int] = None

    plan_year_start: Optional[int] = None
    plan_year_end: Optional[int] = None
    plan_duration_years: Optional[int] = None
    user_group_name: Optional[str] = None
    user_group_code: Optional[str] = None
    registration_date: Optional[str] = None
    registration_office: Optional[str] = None
    cf_area_provided: Optional[float] = None
    cf_total_households: Optional[int] = None
    cf_total_population: Optional[int] = None
    vdc_ward: Optional[str] = None
    contact_person: Optional[str] = None
    contact_designation: Optional[str] = None
    contact_phone: Optional[str] = None
    ranger_name: Optional[str] = None
    ranger_phone: Optional[str] = None
    prepared_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    approved_by: Optional[str] = None
    plan_language: Optional[str] = "NP"

    # Rambhadevi-style plan front matter / silviculture parameters (RAMBHADEVI_SFM_RENEW_TEMPLATE_PLAN.md §4)
    cf_first_renewal_date: Optional[str] = None
    cf_history_note: Optional[str] = None
    silviculture_system: Optional[str] = None
    rotation_years: Optional[int] = None
    regeneration_period_years: Optional[int] = None
    mother_tree_spacing_m: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_all_digits(cls, data):
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    data[k] = normalize_nepali_digits(v)
        return data

    @field_validator("cf_registration_number")
    @classmethod
    def validate_cf_reg_no(cls, v):
        if v and not re.match(r"^\d{3}/\d{4}/\d{2}/\d{2}$", v):
            raise ValueError("CF_REG_INVALID: सामुदायिक वन द.नं. ढाँचा: ३२८/२०६६/०२/२०")
        return v

    @field_validator("op_preparation_year")
    @classmethod
    def validate_op_year(cls, v):
        if v is not None and not is_valid_nepali_year_only(v):
            raise ValueError("OP_YEAR_INVALID: कार्ययोजना तयारी वर्ष २०५०-२०९९ भित्र हुनुपर्छ")
        return v

    @field_validator("sn_number", "cf_code")
    @classmethod
    def validate_sn_format(cls, v):
        if v and not re.match(r"^[\w/]+$", v):
            raise ValueError("SN_FORMAT_INVALID: अल्फान्युमेरिक वा / मात्र हुनुपर्छ")
        return v

    @field_validator("province_guideline_year")
    @classmethod
    def validate_guideline_year(cls, v):
        if v is not None and not is_valid_nepali_year_only(v):
            raise ValueError("PROVINCE_YEAR_INVALID: प्रदेश कार्यविधि वर्ष २०५०-२०९९ भित्र हुनुपर्छ")
        return v

    @field_validator("op_start_fy", "op_end_fy")
    @classmethod
    def validate_fiscal_year(cls, v):
        if v and not is_valid_nepali_fiscal_year(v):
            raise ValueError("FISCAL_YEAR_INVALID: आर्थिक वर्ष ढाँचा: २०८१/२०८२")
        return v

    @field_validator("constitution_approved_year", "cf_handover_date", "op_general_assembly_date", "kabuliyatnama_date", "cf_first_renewal_date")
    @classmethod
    def validate_nepali_date(cls, v):
        if v and not is_valid_nepali_date(v):
            raise ValueError("DATE_FORMAT_INVALID: मिति ढाँचा: २०८१/०१/१५ (वर्ष/महिना/दिन)")
        return v

    @field_validator("forest_type")
    @classmethod
    def validate_forest_type(cls, v):
        if v and v not in ("प्राकृतिक", "वृक्षारोपण"):
            raise ValueError("FOREST_TYPE_INVALID: प्राकृतिक वा वृक्षारोपण मात्र")
        return v

    @field_validator("forest_abundance")
    @classmethod
    def validate_forest_abundance(cls, v):
        if v and v not in ("रुख", "खाँवा", "पुनरोत्पादन"):
            raise ValueError("ABUNDANCE_INVALID: रुख, खाँवा, वा पुनरोत्पादन मात्र")
        return v

    @field_validator("rotation_years", "regeneration_period_years", "mother_tree_spacing_m")
    @classmethod
    def validate_positive_silviculture(cls, v):
        if v is not None and v <= 0:
            raise ValueError("SILVICULTURE_PARAM_INVALID: मान शून्यभन्दा ठूलो हुनुपर्छ")
        return v

    @field_validator("forest_avg_age")
    @classmethod
    def validate_avg_age(cls, v):
        if v is not None and v < 0:
            raise ValueError("AVG_AGE_NEGATIVE: औषत उमेर ऋणात्मक हुन सक्दैन")
        return v

    @field_validator("avg_crown_density_pct")
    @classmethod
    def validate_crown_density(cls, v):
        if v is not None and (v < 0 or v > 100):
            raise ValueError("CROWN_DENSITY_RANGE: छत्र घनत्व ०-१०० प्रतिशत हुनुपर्छ")
        return v

    @field_validator("contact_phone", "ranger_phone")
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r"^\d{7,15}$", str(v)):
            raise ValueError("PHONE_FORMAT_INVALID: फोन नं. ७-१५ अंकको हुनुपर्छ")
        return v


class MetadataFormHybridOverrides(BaseModel):
    """Hybrid override fields for auto-computed values."""
    altitude_min_m: Optional[float] = None
    altitude_max_m: Optional[float] = None
    altitude_mean_m: Optional[float] = None
    dominant_slope: Optional[str] = None
    dominant_aspect: Optional[str] = None
    dominant_soil: Optional[str] = None
    crown_density_pct: Optional[int] = None
    trees_per_hectare: Optional[float] = None
    growing_stock_m3_per_ha: Optional[float] = None
    biomass_t_per_ha: Optional[float] = None
    carbon_stock_tc_per_ha: Optional[float] = None


class MetadataFormUpdate(BaseModel):
    """Combined update payload for metadata form."""
    user_inputs: MetadataFormUserInputs
    hybrid_overrides: Optional[MetadataFormHybridOverrides] = None