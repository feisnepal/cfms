/**
 * TypeScript types for Household Information feature
 */

export interface HouseholdInfo {
  id: string;
  calculation_id: string;

  // Basic Info
  house_no: number;
  surname: string;
  household_head_male?: string;
  household_head_female?: string;
  address_tole?: string;
  latitude?: number;
  longitude?: number;

  // Population
  female_count: number;
  male_count: number;
  total_population: number;

  // Land & Occupation
  land_area?: number;
  land_unit?: 'ropani' | 'kaththa';
  forest_based_occupation: boolean;
  other_occupation: boolean;

  // Livestock
  cow_ox_count: number;
  buffalo_count: number;
  goat_sheep_count: number;

  // Forest Product Demands
  timber_demand_cft: number;
  pole_demand: number;
  firewood_demand_bhari?: number;
  grass_demand_bhari?: number;
  bedding_demand_bhari?: number;

  // Flags
  firewood_auto_calculated: boolean;
  grass_auto_calculated: boolean;
  bedding_auto_calculated: boolean;

  // Classification
  caste_classification_ne?: string;
  caste_classification_en?: string;
  caste_classification_manual: boolean;

  // Other Info
  other_group_membership?: boolean;
  prosperity_level: string;
  prosperity_auto_suggested: boolean;
  remarks?: string;

  // Metadata
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface HouseholdInfoCreate {
  house_no: number;
  surname: string;
  household_head_male?: string;
  household_head_female?: string;
  address_tole?: string;
  latitude?: number;
  longitude?: number;
  female_count: number;
  male_count: number;
  land_area?: number;
  land_unit?: 'ropani' | 'kaththa';
  forest_based_occupation: boolean;
  other_occupation: boolean;
  cow_ox_count: number;
  buffalo_count: number;
  goat_sheep_count: number;
  timber_demand_cft?: number;
  pole_demand?: number;
  firewood_demand_bhari?: number;
  grass_demand_bhari?: number;
  bedding_demand_bhari?: number;
  firewood_auto_calculated?: boolean;
  grass_auto_calculated?: boolean;
  bedding_auto_calculated?: boolean;
  caste_classification_ne?: string;
  caste_classification_en?: string;
  caste_classification_manual?: boolean;
  other_group_membership?: boolean;
  prosperity_level?: string;
  prosperity_auto_suggested?: boolean;
  remarks?: string;
}

export interface HouseholdInfoUpdate {
  house_no?: number;
  surname?: string;
  household_head_male?: string;
  household_head_female?: string;
  address_tole?: string;
  latitude?: number;
  longitude?: number;
  female_count?: number;
  male_count?: number;
  land_area?: number;
  land_unit?: 'ropani' | 'kaththa';
  forest_based_occupation?: boolean;
  other_occupation?: boolean;
  cow_ox_count?: number;
  buffalo_count?: number;
  goat_sheep_count?: number;
  timber_demand_cft?: number;
  pole_demand?: number;
  firewood_demand_bhari?: number;
  grass_demand_bhari?: number;
  bedding_demand_bhari?: number;
  firewood_auto_calculated?: boolean;
  grass_auto_calculated?: boolean;
  bedding_auto_calculated?: boolean;
  caste_classification_ne?: string;
  caste_classification_en?: string;
  caste_classification_manual?: boolean;
  other_group_membership?: boolean;
  prosperity_level?: string;
  prosperity_auto_suggested?: boolean;
  remarks?: string;
}

export interface HouseholdUploadValidation {
  row_number: number;
  is_valid: boolean;
  errors: string[];
  warnings: string[];
  data?: any;
}

export interface HouseholdUploadResponse {
  success: boolean;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  records_imported: number;
  records_updated: number;
  /** households removed by "replace the whole list" (owner decision D5) */
  records_removed?: number;
  validations: HouseholdUploadValidation[];
  /** problems grouped by cause with how to fix them (UP-2) */
  findings?: import('../lib/uploadFindings').UploadFinding[];
}

export interface HouseholdSummary {
  total_households: number;
  total_population: number;
  total_male: number;
  total_female: number;
  total_cow_ox: number;
  total_buffalo: number;
  total_goat_sheep: number;
  total_timber_demand_cft: number;
  total_pole_demand: number;
  total_firewood_demand_bhari: number;
  total_grass_demand_bhari: number;
  total_bedding_demand_bhari: number;
  avg_land_area?: number;
  caste_distribution: Record<string, number>;
  prosperity_distribution: Record<string, number>;
  forest_dependent_households: number;
}

export interface SurnameSuggestion {
  surname_ne: string;
  surname_en?: string;
  classification_ne: string;
  caste_ne: string;
}

export interface CasteClassification {
  id: number;
  classification_ne: string;
  caste_ne: string;
  surname_ne: string;
  classification_en?: string;
  caste_en?: string;
  surname_en?: string;
}

export interface TemplateDownloadOptions {
  land_unit: 'ropani' | 'kaththa';
  include_coordinates: boolean;
}
