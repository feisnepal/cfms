/**
 * Analysis Presets for Community Forest Management System
 *
 * Defines preset combinations of analysis options to make it easier for users
 * to select common analysis configurations.
 */

export interface AnalysisOptions {
  [key: string]: boolean;
  // Master switches
  run_raster_analysis: boolean;

  // Raster analyses
  run_elevation: boolean;
  run_slope: boolean;
  run_aspect: boolean;
  run_canopy: boolean;
  run_biomass: boolean;
  run_forest_health: boolean;
  run_forest_type: boolean;
  run_landcover: boolean;
  run_forest_loss: boolean;
  run_forest_gain: boolean;
  run_fire_loss: boolean;
  run_temperature: boolean;
  run_precipitation: boolean;
  run_soil: boolean;

  // Vector analyses
  run_proximity: boolean;

  // Auto-generation
  auto_generate_fieldbook: boolean;
  auto_generate_sampling: boolean;
}

export interface MapOptions {
  [key: string]: boolean;
  generate_boundary_map: boolean;
  generate_topographic_map: boolean;
  generate_slope_map: boolean;
  generate_aspect_map: boolean;
  generate_forest_type_map: boolean;
  generate_canopy_height_map: boolean;
  generate_landcover_change_map: boolean;
  generate_soil_map: boolean;
  generate_forest_health_map: boolean;
}

export type PresetName = 'quick' | 'standard' | 'complete' | 'custom';

export interface AnalysisPreset {
  name: PresetName;
  label: string;
  description: string;
  estimatedTime: string;
  options: AnalysisOptions;
}

/**
 * Quick Preset - Essential analyses only
 * Estimated time: ~30 seconds
 * Use case: Quick overview, initial assessment
 */
export const QUICK_PRESET: AnalysisPreset = {
  name: 'quick',
  label: 'analysis.presetQuick',
  description: 'analysis.presetQuickDesc',
  estimatedTime: 'analysis.estimatedTimeQuick',
  options: {
    run_raster_analysis: true,
    run_elevation: true,
    run_slope: true,
    run_aspect: true,
    run_canopy: false,
    run_biomass: false,
    run_forest_health: false,
    run_forest_type: false,
    run_landcover: false,
    run_forest_loss: false,
    run_forest_gain: false,
    run_fire_loss: false,
    run_temperature: false,
    run_precipitation: false,
    run_soil: false,
    run_proximity: false,
    auto_generate_fieldbook: false,
    auto_generate_sampling: false,
  }
};

/**
 * Standard Preset - Most commonly used analyses
 * Estimated time: ~2 minutes
 * Use case: Regular forest assessments, CFOP preparation
 */
export const STANDARD_PRESET: AnalysisPreset = {
  name: 'standard',
  label: 'analysis.presetStandard',
  description: 'analysis.presetStandardDesc',
  estimatedTime: 'analysis.estimatedTimeStandard',
  options: {
    run_raster_analysis: true,
    run_elevation: true,
    run_slope: true,
    run_aspect: true,
    run_canopy: true,
    run_biomass: true,
    run_forest_health: true,
    run_forest_type: true,
    run_landcover: true,
    run_forest_loss: false,
    run_forest_gain: false,
    run_fire_loss: false,
    run_temperature: false,
    run_precipitation: false,
    run_soil: true,
    run_proximity: false,
    auto_generate_fieldbook: true,
    auto_generate_sampling: false,
  }
};

/**
 * Complete Preset - All available analyses
 * Estimated time: ~5 minutes
 * Use case: Comprehensive assessments, research, detailed CFOP
 */
export const COMPLETE_PRESET: AnalysisPreset = {
  name: 'complete',
  label: 'analysis.presetComplete',
  description: 'analysis.presetCompleteDesc',
  estimatedTime: 'analysis.estimatedTimeComplete',
  options: {
    run_raster_analysis: true,
    run_elevation: true,
    run_slope: true,
    run_aspect: true,
    run_canopy: true,
    run_biomass: true,
    run_forest_health: true,
    run_forest_type: true,
    run_landcover: true,
    run_forest_loss: true,
    run_forest_gain: true,
    run_fire_loss: true,
    run_temperature: true,
    run_precipitation: true,
    run_soil: true,
    run_proximity: true,
    auto_generate_fieldbook: true,
    auto_generate_sampling: true,
  }
};

/**
 * Custom Preset - User-defined selection
 * Allows manual selection of individual analyses
 */
export const CUSTOM_PRESET: AnalysisPreset = {
  name: 'custom',
  label: 'analysis.presetCustom',
  description: 'analysis.presetCustomDesc',
  estimatedTime: 'analysis.estimatedTimeCustom',
  options: {
    run_raster_analysis: true,
    run_elevation: true,
    run_slope: true,
    run_aspect: true,
    run_canopy: true,
    run_biomass: true,
    run_forest_health: true,
    run_forest_type: true,
    run_landcover: true,
    run_forest_loss: true,
    run_forest_gain: true,
    run_fire_loss: true,
    run_temperature: true,
    run_precipitation: true,
    run_soil: true,
    run_proximity: true,
    auto_generate_fieldbook: true,
    auto_generate_sampling: true,
  }
};

/**
 * All available presets
 */
export const ANALYSIS_PRESETS: AnalysisPreset[] = [
  QUICK_PRESET,
  STANDARD_PRESET,
  COMPLETE_PRESET,
  CUSTOM_PRESET,
];

/**
 * Get preset by name
 */
export function getPresetByName(name: PresetName): AnalysisPreset | undefined {
  return ANALYSIS_PRESETS.find(p => p.name === name);
}

/**
 * Default analysis options (all enabled for backward compatibility)
 */
export const DEFAULT_ANALYSIS_OPTIONS: AnalysisOptions = COMPLETE_PRESET.options;

/**
 * Default map options (all disabled for on-demand generation)
 */
export const DEFAULT_MAP_OPTIONS: MapOptions = {
  generate_boundary_map: false,
  generate_topographic_map: false,
  generate_slope_map: false,
  generate_aspect_map: false,
  generate_forest_type_map: false,
  generate_canopy_height_map: false,
  generate_landcover_change_map: false,
  generate_soil_map: false,
  generate_forest_health_map: false,
};

/**
 * Analysis option labels and descriptions for UI display
 * Values are i18n keys - use useT() hook to translate at render time.
 */
export const ANALYSIS_OPTION_INFO: Record<keyof Omit<AnalysisOptions, 'run_raster_analysis' | 'auto_generate_fieldbook' | 'auto_generate_sampling'>, {label: string, description: string, category: string}> = {
  run_elevation: {
    label: 'analysis.elevation',
    description: 'analysis.elevationDesc',
    category: 'analysis.categoryTerrain'
  },
  run_slope: {
    label: 'analysis.slope',
    description: 'analysis.slopeDesc',
    category: 'analysis.categoryTerrain'
  },
  run_aspect: {
    label: 'analysis.aspect',
    description: 'analysis.aspectDesc',
    category: 'analysis.categoryTerrain'
  },
  run_canopy: {
    label: 'analysis.canopy',
    description: 'analysis.canopyDesc',
    category: 'analysis.categoryForestStructure'
  },
  run_biomass: {
    label: 'analysis.biomass',
    description: 'analysis.biomassDesc',
    category: 'analysis.categoryForestStructure'
  },
  run_forest_health: {
    label: 'analysis.forestHealth',
    description: 'analysis.forestHealthDesc',
    category: 'analysis.categoryForestStructure'
  },
  run_forest_type: {
    label: 'analysis.forestType',
    description: 'analysis.forestTypeDesc',
    category: 'analysis.categoryClassification'
  },
  run_landcover: {
    label: 'analysis.landcover',
    description: 'analysis.landcoverDesc',
    category: 'analysis.categoryClassification'
  },
  run_forest_loss: {
    label: 'analysis.forestLoss',
    description: 'analysis.forestLossDesc',
    category: 'analysis.categoryChangeDetection'
  },
  run_forest_gain: {
    label: 'analysis.forestGain',
    description: 'analysis.forestGainDesc',
    category: 'analysis.categoryChangeDetection'
  },
  run_fire_loss: {
    label: 'analysis.fireLoss',
    description: 'analysis.fireLossDesc',
    category: 'analysis.categoryChangeDetection'
  },
  run_temperature: {
    label: 'analysis.temperature',
    description: 'analysis.temperatureDesc',
    category: 'analysis.categoryClimate'
  },
  run_precipitation: {
    label: 'analysis.precipitation',
    description: 'analysis.precipitationDesc',
    category: 'analysis.categoryClimate'
  },
  run_soil: {
    label: 'analysis.soil',
    description: 'analysis.soilDesc',
    category: 'analysis.categorySoil'
  },
  run_proximity: {
    label: 'analysis.proximity',
    description: 'analysis.proximityDesc',
    category: 'analysis.categoryVector'
  },
};

/**
 * Map type labels and descriptions for UI display
 */
export const MAP_TYPE_INFO: Record<keyof MapOptions, {label: string, description: string, implemented: boolean}> = {
  generate_boundary_map: {
    label: 'Boundary Map',
    description: 'Forest boundary with surrounding context',
    implemented: true
  },
  generate_topographic_map: {
    label: 'Topographic Map',
    description: 'Elevation contours and terrain visualization',
    implemented: false // TODO: Implement
  },
  generate_slope_map: {
    label: 'Slope Map',
    description: 'Slope classification (4 classes)',
    implemented: true
  },
  generate_aspect_map: {
    label: 'Aspect Map',
    description: 'Directional aspect distribution (8 directions)',
    implemented: true
  },
  generate_forest_type_map: {
    label: 'Forest Type Map',
    description: 'Species-based forest type classification',
    implemented: false // TODO: Implement
  },
  generate_canopy_height_map: {
    label: 'Canopy Height Map',
    description: 'Forest structure visualization (4 classes)',
    implemented: false // TODO: Implement
  },
  generate_landcover_change_map: {
    label: 'Land Cover Map',
    description: 'ESA WorldCover land cover classes',
    implemented: true
  },
  generate_soil_map: {
    label: 'Soil Map',
    description: 'Soil texture classification',
    implemented: false // TODO: Implement
  },
  generate_forest_health_map: {
    label: 'Forest Health Map',
    description: 'Forest health status visualization (5 classes)',
    implemented: false // TODO: Implement
  },
};
