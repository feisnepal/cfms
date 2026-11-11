/**
 * The values "Run analysis" stores for each unit (`an_*`), with the SUBJECT each belongs to and its table header.
 *
 * One table drives both the attribute-table columns (layerRegistry) and the sub-views under "Raster analysis" (attributeThemes), so a
 * column and its group cannot drift apart. The long class-breakdown texts ("Forest 71.2%; Shrub 3%") sit in their own group so the
 * subject groups stay narrow: the dominant class is in the subject group, its breakdown is under "Class breakdowns".
 *
 * Regrouping is a one-line edit here (plus the group's name in the locale files). A value the analysis starts producing is NOT shown
 * until it is listed here (it is stored either way); the unit test compares this list with the keys the analysis produced when it was
 * written, and checks that every column belongs to exactly one group.
 */
export type AnalysisGroup = 'location' | 'geography' | 'terrain' | 'vegetation' | 'environment' | 'change' | 'breakdowns';

export const ANALYSIS_GROUPS: AnalysisGroup[] = ['location', 'geography', 'terrain', 'vegetation', 'environment', 'change', 'breakdowns'];

export interface AnalysisField {
  /** the stored key without its `an_` prefix */
  key: string;
  group: AnalysisGroup;
  /** table header, with its unit */
  label: string;
}

const f = (key: string, group: AnalysisGroup, label: string): AnalysisField => ({ key, group, label });

export const ANALYSIS_FIELDS: AnalysisField[] = [
  // Location & administration
  f('province', 'location', 'Province'), f('province_ne', 'location', 'Province (Nepali)'),
  f('district', 'location', 'District'),
  f('municipality', 'location', 'Municipality'), f('municipality_n', 'location', 'Municipality (Nepali)'),
  f('municipality_type', 'location', 'Municipality type'), f('municipality_type_nep', 'location', 'Municipality type (Nepali)'),
  f('ward', 'location', 'Ward'), f('ward_ne', 'location', 'Ward (Nepali)'),
  f('juridiction_ne', 'location', 'Jurisdiction (Nepali)'), f('major_river_basin', 'location', 'River basin'),
  // Geography & offices
  f('physiography_ne', 'geography', 'Physiography (Nepali)'),
  f('division_n', 'geography', 'Division office (Nepali)'), f('subdivis_n', 'geography', 'Sub-division office (Nepali)'),
  f('access_info', 'geography', 'Access'), f('watershed', 'geography', 'Watershed'),
  // Terrain
  f('elevation_min_m', 'terrain', 'Elevation, min (m)'), f('elevation_mean_m', 'terrain', 'Elevation, mean (m)'),
  f('elevation_max_m', 'terrain', 'Elevation, max (m)'),
  f('slope_dominant_class', 'terrain', 'Slope class, dominant'), f('slope_min_code', 'terrain', 'Slope, gentlest class'),
  f('slope_max_code', 'terrain', 'Slope, steepest class'),
  f('aspect_dominant', 'terrain', 'Aspect, dominant'),
  // Canopy, biomass & carbon
  f('canopy_dominant_class', 'vegetation', 'Canopy class, dominant'), f('canopy_min_m', 'vegetation', 'Canopy height, min (m)'),
  f('canopy_mean_m', 'vegetation', 'Canopy height, mean (m)'), f('canopy_max_m', 'vegetation', 'Canopy height, max (m)'),
  f('agb_mean_mg_ha', 'vegetation', 'Biomass, mean (Mg/ha)'), f('agb_max_mg_ha', 'vegetation', 'Biomass, max (Mg/ha)'),
  f('agb_total_mg', 'vegetation', 'Biomass, total (Mg)'),
  f('carbon_stock_mg', 'vegetation', 'Biomass carbon, total (Mg)'),
  // Environment: climate, soil, land cover & forest, potential species
  f('temperature_min_c', 'environment', 'Temperature, min (°C)'), f('temperature_mean_c', 'environment', 'Temperature, mean (°C)'),
  f('temperature_max_c', 'environment', 'Temperature, max (°C)'),
  f('min_temp_coldest_min_c', 'environment', 'Coldest-month minimum temperature, min (°C)'),
  f('min_temp_coldest_mean_c', 'environment', 'Coldest-month minimum temperature, mean (°C)'),
  f('min_temp_coldest_max_c', 'environment', 'Coldest-month minimum temperature, max (°C)'),
  f('precipitation_min_mm', 'environment', 'Precipitation, min (mm)'), f('precipitation_mean_mm', 'environment', 'Precipitation, mean (mm)'),
  f('precipitation_max_mm', 'environment', 'Precipitation, max (mm)'),
  f('soil_texture', 'environment', 'Soil texture'), f('carbon_stock_t_ha', 'environment', 'Soil carbon stock, 0–30 cm (t/ha)'), f('soil_texture_system', 'environment', 'Soil texture classification'),
  f('fertility_class', 'environment', 'Soil fertility class'), f('fertility_score', 'environment', 'Soil fertility score (80+ = high)'),
  f('compaction_status', 'environment', 'Soil compaction'), f('compaction_alert', 'environment', 'Soil compaction advice'),
  f('limiting_factors', 'environment', 'Soil limiting factors'),
  f('landcover_dominant', 'environment', 'Land cover, dominant'), f('forest_type_dominant', 'environment', 'Forest type, dominant'),
  f('forest_health_dominant', 'environment', 'Forest health, dominant'), f('nasa_forest_2020_dominant', 'environment', 'NASA forest 2020, dominant'),
  f('species_count', 'environment', 'Potential species (count)'),
  // Forest change & history
  f('forest_loss_hectares', 'change', 'Forest loss (ha)'), f('forest_loss_by_year', 'change', 'Forest loss by year'),
  f('forest_gain_hectares', 'change', 'Forest gain (ha)'), f('fire_loss_hectares', 'change', 'Fire loss (ha)'),
  f('landcover_1984_dominant', 'change', 'Land cover 1984, dominant'), f('hansen2000_dominant', 'change', 'Forest cover 2000 (Hansen), dominant'),
  // Class breakdowns (the long "class x% ; class y%" texts)
  f('slope_percentages', 'breakdowns', 'Slope classes (% area)'), f('aspect_percentages', 'breakdowns', 'Aspect (% area)'),
  f('canopy_percentages', 'breakdowns', 'Canopy classes (% area)'), f('landcover_percentages', 'breakdowns', 'Land cover (% area)'),
  f('forest_type_percentages', 'breakdowns', 'Forest types (% area)'), f('forest_health_percentages', 'breakdowns', 'Forest health (% area)'),
  f('nasa_forest_2020_percentages', 'breakdowns', 'NASA forest 2020 (% area)'),
  f('landcover_1984_percentages', 'breakdowns', 'Land cover 1984 (% area)'), f('hansen2000_percentages', 'breakdowns', 'Forest cover 2000 (Hansen, % area)'),
  f('physiography_percentages', 'breakdowns', 'Physiography (% area)'), f('geology_percentages', 'breakdowns', 'Geology (% area)'),
  f('ecoregion_percentages', 'breakdowns', 'Ecoregion (% area)'),
];

const GROUP_BY_KEY: Record<string, AnalysisGroup> = Object.fromEntries(ANALYSIS_FIELDS.map((x) => [`an_${x.key}`, x.group]));

/** The subject of an analysis column (`an_elevation_mean_m` -> `terrain`); anything unlisted falls under `geography`. */
export const analysisGroupOf = (columnKey: string): AnalysisGroup => GROUP_BY_KEY[columnKey] ?? 'geography';
