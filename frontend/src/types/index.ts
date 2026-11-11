/** Shared TypeScript type and interface definitions for the entire app. */
export type Designation = 'forest_guard' | 'forester' | 'ranger' | 'office';
export type UserType = 'official' | 'student' | 'researcher' | 'organization';

export interface User {
  id: string;
  /** Null for an account made through Facebook that has not given one yet. */
  email: string | null;
  full_name: string;
  phone?: string;
  designation?: Designation | null;
  sub_division?: string | null;
  instagram_handle?: string | null;
  phone_verified_at?: string | null;
  email_verified_at?: string | null;
  /** False = limited tier: signed in, but no super admin has approved the account yet. */
  is_approved?: boolean;
  /** False until designation and sub-division are filled in (a Facebook account starts without them). */
  profile_complete?: boolean;
  /** Null for an account from before types existed. */
  user_type?: UserType | null;
  type_details?: Record<string, string> | null;
  /** 'read_only' = a student or researcher: may look, not change. access_expires_at ends it. */
  access_level?: 'full' | 'read_only';
  access_expires_at?: string | null;
  org_member_role?: 'owner' | 'member' | null;
  org_vouched_at?: string | null;
  organization_name?: string | null;
  organization_verified?: boolean;
  role: 'guest' | 'user' | 'org_admin' | 'super_admin' | 'template_designer';
  status: 'pending' | 'active' | 'suspended';
  organization_id?: string;
  created_at: string;
  last_login?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  phone: string;
  /** The code sent by SMS to `phone`. */
  phone_code: string;
  user_type: UserType;
  /** Official only. */
  designation?: Designation;
  sub_division?: string;
  /** Student / researcher / organization fields. */
  details?: Record<string, string>;
  /** At least one of the two social identities is required. */
  facebook_access_token?: string;
  instagram_handle?: string;
}

export interface TokenResponse {
  access_token: string;
  /** H2.5 / S1-05: rotated on every use — store the new one, discard the old. */
  refresh_token?: string;
  token_type: string;
  expires_in: number;
}

export interface CommunityForest {
  id: number;
  name: string;
  code: string;
  regime: string;
  area_hectares: number;
  geometry?: any;
  role?: string;
}

export interface MyForest extends CommunityForest {
  role: string;
}

export interface MyForestsResponse {
  forests: MyForest[];
  total_count: number;
  total_area_hectares: number;
}

export interface ApiError {
  detail: string;
}

export interface ForestBlock {
  block_index: number;
  block_name: string;
  area_sqm: number;
  area_hectares: number;
  geometry: any;
  centroid: {
    lon: number;
    lat: number;
  };

  // Extent (bounding box)
  extent?: {
    N: number;
    S: number;
    E: number;
    W: number;
  };

  // Analysis fields for each block
  elevation_min_m?: number;
  elevation_max_m?: number;
  elevation_mean_m?: number;
  slope_dominant_class?: string;
  slope_percentages?: Record<string, number>;
  aspect_dominant?: string;
  aspect_percentages?: Record<string, number>;
  canopy_dominant_class?: string;
  canopy_percentages?: Record<string, number>;
  canopy_mean_m?: number;
  agb_mean_mg_ha?: number;
  agb_total_mg?: number;
  carbon_stock_mg?: number;
  forest_health_dominant?: string;
  forest_health_percentages?: Record<string, number>;
  forest_type_dominant?: string;
  forest_type_percentages?: Record<string, number>;
  landcover_dominant?: string;
  landcover_percentages?: Record<string, number>;
  forest_loss_hectares?: number;
  forest_loss_by_year?: Record<string, number>;
  forest_gain_hectares?: number;
  fire_loss_hectares?: number;
  fire_loss_by_year?: Record<string, number>;
  temperature_mean_c?: number;
  temperature_min_c?: number;
  precipitation_mean_mm?: number;
  soil_texture?: string;
  soil_properties?: Record<string, any>;

  // Administrative Location
  province?: string;
  district?: string;
  municipality?: string;
  ward?: string;
  watershed?: string;
  major_river_basin?: string;

  // Geology
  geology_percentages?: Record<string, number>;

  // Access
  access_info?: string;

  // Nearby Features (within 100m)
  features_north?: string;
  features_east?: string;
  features_south?: string;
  features_west?: string;
}

export interface AnalysisResultData {
  area_sqm?: number;
  area_hectares?: number;
  utm_zone?: number;
  total_blocks?: number;
  blocks?: ForestBlock[];
  compartments?: ForestBlock[];

  // Elevation
  elevation_min_m?: number;
  elevation_max_m?: number;
  elevation_mean_m?: number;

  // Slope
  slope_dominant_class?: string;
  slope_percentages?: Record<string, number>;

  // Aspect
  aspect_dominant?: string;
  aspect_percentages?: Record<string, number>;

  // Canopy
  canopy_dominant_class?: string;
  canopy_percentages?: Record<string, number>;
  canopy_mean_m?: number;

  // Biomass
  agb_mean_mg_ha?: number;
  agb_total_mg?: number;
  carbon_stock_mg?: number;

  // Forest Health
  forest_health_dominant?: string;
  forest_health_percentages?: Record<string, number>;

  // Forest Type
  forest_type_dominant?: string;
  forest_type_percentages?: Record<string, number>;

  // Land Cover
  landcover_dominant?: string;
  landcover_percentages?: Record<string, number>;

  // Climate
  temperature_mean_c?: number;
  temperature_min_c?: number;
  precipitation_mean_mm?: number;

  // Extent (bounding box)
  whole_forest_extent?: {
    N: number;
    S: number;
    E: number;
    W: number;
  };

  // Forest Change
  forest_loss_hectares?: number;
  forest_gain_hectares?: number;
  forest_loss_by_year?: Record<string, number>;
  fire_loss_hectares?: number;
  fire_loss_by_year?: Record<string, number>;

  // Soil
  soil_texture?: string;
  soil_properties?: Record<string, any>;
  soil_ph_dominant?: string;

  // Proximity
  buildings_within_1km?: number;
  nearest_settlement?: string;
  nearest_road?: string;

  // Administrative (old fields - kept for backward compatibility)
  province?: string;
  municipality?: string;
  ward?: string;

  // Administrative Location (whole forest)
  whole_province?: string;
  whole_district?: string;
  whole_municipality?: string;
  whole_ward?: string;
  whole_watershed?: string;
  whole_major_river_basin?: string;

  // Geology (whole forest)
  whole_geology_percentages?: Record<string, number>;

  // Physiography (whole forest)
  whole_physiography_percentages?: Record<string, number>;

  // Ecoregion (whole forest)
  whole_ecoregion_percentages?: Record<string, number>;

  // NASA Forest 2020 (whole forest)
  whole_nasa_forest_2020_percentages?: Record<string, number>;
  whole_nasa_forest_2020_dominant?: string;

  // Access (whole forest)
  whole_access_info?: string;

  // Nearby Features (whole forest, within 100m)
  whole_features_north?: string;
  whole_features_east?: string;
  whole_features_south?: string;
  whole_features_west?: string;

  // Historical / classified layers (whole forest)
  landcover_1984_dominant?: string;
  landcover_1984_percentages?: Record<string, number>;
  hansen2000_dominant?: string;
  hansen2000_percentages?: Record<string, number>;

  // Soil / fertility
  soil_texture_system?: string;
  carbon_stock_t_ha?: number;
  fertility_class?: string;
  fertility_score?: number;
  limiting_factors?: string[];
  compaction_status?: string;
  compaction_alert?: string;

  // Potential species
  potential_species?: any[];
  species_count?: number;

  // Sub-areas (excluded/non-forest polygons)
  sub_areas?: SubArea[];
  sub_areas_count?: number;
  excluded_area_hectares?: number;
  effective_area_hectares?: number;

  // Processing
  processing_info?: {
    partitioned: boolean;
    partition_info: Record<string, any>;
  };

  // Map compositions (U04)
  mapCompositions?: Record<string, any>[];
  activeCompositionId?: string;

  // Thematic renderer specs (WORKSPACE_LAYER_STYLING_PLAN.md P4 / D8):
  // { [bareLayerId | `imported-<id>`]: RendererSpec }
  layer_renderers?: Record<string, unknown>;
}

export interface SubArea {
  id?: number | string;
  name?: string;
  category?: string;
  geometry?: any;
  area_hectares?: number;
  isExcluded?: boolean;
  is_excluded?: boolean;
  block_id?: string;
  block_name?: string;
  blockBreakdown?: any[];
  [key: string]: any;
}

export interface OperationalPlanSection {
  content?: string;
  title?: string;
  [key: string]: any;
}

export interface OperationalPlanResponse {
  id: string;
  calculation_id?: string;
  forest_name?: string;
  template_id?: string;
  custom_notes?: string;
  sections?: Record<string, OperationalPlanSection>;
  status?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: any;
}

export interface Calculation {
  id: string;
  user_id: string;
  uploaded_filename?: string | null;
  forest_name?: string;
  block_name?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  processing_time_seconds?: number;
  error_message?: string;
  created_at: string;
  updated_at?: string;
  completed_at?: string;
  is_draft?: boolean;
  // U01 map lifecycle (Draft → Submitted → Calculating → Completed → Locked).
  // The workspace header/actions read the store value driven from this field
  // (backfill for getCalculation responses that carry it; legacy responses
  // without it fall back to the `status`-based mapping in useCalculationContext).
  map_lifecycle_status?: string;
  // Structure lock (H-SUBMIT). Authoritative once the read path carries it —
  // useCalculationContext syncs it into the store so a locked map shows
  // disabled controls instead of 423-ing on every restructure.
  structure_locked?: boolean;
  structure_locked_at?: string | null;
  geometry?: any;
  result_data?: AnalysisResultData;
  // Name-first creation: draft_data.islands_count == 0 marks a boundary-less
  // draft (route to the workspace "Add Geometry" flow, not the island resume).
  draft_data?: any;
  // U08/U09 — unified shell feature flag
  unified_shell_enabled?: boolean;
}
