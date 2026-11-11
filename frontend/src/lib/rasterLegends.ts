/**
 * rasterLegends — single source of truth for raster overlay legends.
 *
 * The backend catalog endpoint (`GET /api/calculations/{id}/raster-layers`) is the
 * SSOT for raster *metadata* (id/name/description/source/resolution/year). Legend
 * *rendering* is a frontend concern and lives here so both the Analysis tab
 * (RasterLayerControl) and the workspace (LegendPanel) share one implementation.
 */

export interface LegendItem {
  color: string;
  label: string;
  range?: string;
}

/** Metadata shape returned by the backend raster catalog (mirrors the API response). */
export interface RasterLayerMeta {
  id: string;
  name: string;
  description: string;
  source?: string;
  resolution?: string;
  year?: string;
  /** Tile route segment when the layer is not served from `/tiles/{id}` (e.g. `user-group-tiles`). */
  tilesPath?: string;
  /** Path segment that replaces `{id}` in the tile route (user-group tiles are keyed by `landcover`/`biomass`). */
  tileKey?: string;
  /** Extra query params appended to every tile request (e.g. `exclude_forest: 'true'`). */
  extraParams?: Record<string, string>;
}

/**
 * Static legends for layers whose classes are fixed (categorical rasters).
 * These match the tile color ramps in backend/app/services/tile_service.py.
 */
export const STATIC_LEGENDS: Record<string, LegendItem[]> = {
  aspect: [
    { color: '#CCCCCC', label: 'Flat' },
    { color: '#1A5490', label: 'North (N)' },
    { color: '#3498DB', label: 'Northeast (NE)' },
    { color: '#1ABC9C', label: 'East (E)' },
    { color: '#F1C40F', label: 'Southeast (SE)' },
    { color: '#E74C3C', label: 'South (S)' },
    { color: '#E67E22', label: 'Southwest (SW)' },
    { color: '#F39C12', label: 'West (W)' },
    { color: '#9B59B6', label: 'Northwest (NW)' },
  ],
  forest_health: [
    { color: '#DC143C', label: 'Stressed', range: 'NDVI < 0.2' },
    { color: '#FF8C00', label: 'Poor', range: 'NDVI 0.2-0.4' },
    { color: '#FFD700', label: 'Moderate', range: 'NDVI 0.4-0.6' },
    { color: '#90EE90', label: 'Healthy', range: 'NDVI 0.6-0.8' },
    { color: '#228B22', label: 'Excellent', range: 'NDVI > 0.8' },
  ],
  nasa_forest_2020: [
    { color: '#00FF00', label: 'Primary Forest', range: 'Class 1 - Old-growth, highest carbon' },
    { color: '#FF0000', label: 'Young Secondary', range: 'Class 2 - Regenerating, low carbon' },
    { color: '#6666FF', label: 'Old Secondary', range: 'Class 3 - Mature regrowth, medium carbon' },
  ],
  landcover: [
    { color: '#006400', label: 'Tree Cover', range: '10' },
    { color: '#FFBB22', label: 'Shrubland', range: '20' },
    { color: '#FFFF4C', label: 'Grassland', range: '30' },
    { color: '#F096FF', label: 'Cropland', range: '40' },
    { color: '#FA0000', label: 'Built-up', range: '50' },
    { color: '#B4B4B4', label: 'Bare/Sparse', range: '60' },
    { color: '#F0F0F0', label: 'Snow/Ice', range: '70' },
    { color: '#0064C8', label: 'Water', range: '80' },
    { color: '#0096A0', label: 'Wetland', range: '90' },
    { color: '#00CF75', label: 'Mangroves', range: '95' },
    { color: '#FAE6A0', label: 'Moss/Lichen', range: '100' },
  ],
  forest_loss: [
    { color: '#FFD700', label: '2001-2008', range: 'Early Loss' },
    { color: '#FF8C00', label: '2009-2016', range: 'Mid Loss' },
    { color: '#DC143C', label: '2017-2024', range: 'Recent Loss' },
  ],
  forest_gain: [
    { color: '#32CD32', label: 'Forest Regrowth', range: '2000-2012' },
  ],
  fire: [
    { color: '#FF8C00', label: '2001-2008', range: 'Old Burns' },
    { color: '#FF4500', label: '2009-2016', range: 'Mid Burns' },
    { color: '#8B0000', label: '2017-2024', range: 'Recent Burns - Priority' },
  ],
  soil_ph: [
    { color: '#DC143C', label: 'Extremely Acidic', range: '< 4.5' },
    { color: '#FF8C00', label: 'Strongly Acidic', range: '4.5-5.5' },
    { color: '#FFD700', label: 'Slightly Acidic', range: '5.5-6.5' },
    { color: '#228B22', label: 'Neutral (Optimal)', range: '6.5-7.5' },
    { color: '#4682B4', label: 'Slightly Alkaline', range: '7.5-8.5' },
    { color: '#9370DB', label: 'Strongly Alkaline', range: '> 8.5' },
  ],
  soil_texture: [
    { color: '#654321', label: 'Clay', range: 'Heavy' },
    { color: '#8B4513', label: 'Clay Loam', range: 'Moderate' },
    { color: '#A0522D', label: 'Loam (Optimal)', range: 'Balanced' },
    { color: '#D2B48C', label: 'Sandy', range: 'Light' },
  ],
  soil_carbon: [
    { color: '#DC143C', label: 'Very Low', range: '< 0.5%' },
    { color: '#FF8C00', label: 'Low', range: '0.5-1.0%' },
    { color: '#FFD700', label: 'Medium', range: '1.0-2.0%' },
    { color: '#90EE90', label: 'High', range: '2.0-3.0%' },
    { color: '#228B22', label: 'Very High (Forest)', range: '> 3.0%' },
  ],
  soil_fertility: [
    { color: '#DC143C', label: 'Very Low', range: '0-20' },
    { color: '#FF8C00', label: 'Low', range: '20-40' },
    { color: '#FFD700', label: 'Medium', range: '40-60' },
    { color: '#90EE90', label: 'High', range: '60-80' },
    { color: '#228B22', label: 'Very High', range: '80-100' },
  ],
  soil_density: [
    { color: '#228B22', label: 'Low (Good)', range: '< 1.2 g/cm³' },
    { color: '#FFD700', label: 'Moderate', range: '1.2-1.4 g/cm³' },
    { color: '#FF8C00', label: 'Elevated', range: '1.4-1.6 g/cm³' },
    { color: '#DC143C', label: 'High Risk', range: '> 1.6 g/cm³' },
  ],
};

/** Slope classes shared by the dynamic generator and the static fallback. */
export const SLOPE_CLASSES: LegendItem[] = [
  { color: '#2ECC71', label: 'Gentle', range: '<19°' },
  { color: '#F1C40F', label: 'Moderate', range: '19-31°' },
  { color: '#E67E22', label: 'Steep', range: '31-45°' },
  { color: '#E74C3C', label: 'Very Steep', range: '>45°' },
];

/** 26 FRTC forest-type classes with colors embedded directly. */
export const FOREST_TYPE_CLASSES: Array<{ name: string; color: string }> = [
  // Tropical Zone (1-5): Dark Green shades
  { name: 'Shorea robusta Forest', color: '#006400' },
  { name: 'Alnus nepalensis Forest', color: '#0B7A0B' },
  { name: 'Schima-Castanopsis Forest', color: '#118F11' },
  { name: 'Quercus semecarpifolia Forest', color: '#17A517' },
  { name: 'Larix/Abies spectabilis Forest', color: '#1DBB1D' },

  // Sub-tropical Zone (6-10): Yellow-Green shades
  { name: 'Pinus wallichiana-Tsuga dumosa Forest', color: '#9ACD32' },
  { name: 'Plantation (Pinus-Eucalyptus) Forest', color: '#A4D73C' },
  { name: 'Ficus-Other Tropical Riverine Forest', color: '#AEE146' },
  { name: 'Tropical Mixed Broadleaved Forest', color: '#B8EB50' },
  { name: 'Quercus-Pinus Forest', color: '#C2F55A' },

  // Temperate Zone (11-15): Blue-Green shades
  { name: 'Abies spectabilis Forest', color: '#2E8B57' },
  { name: 'Pinus roxburghii-Mixed Broadleaved Forest', color: '#349B61' },
  { name: 'Pinus wallichiana Forest', color: '#3AAB6B' },
  { name: 'Warm Temperate Mixed Broadleaved Forest', color: '#40BB75' },
  { name: 'Upper Temperate Quercus Forest', color: '#46CB7F' },

  // Sub-alpine Zone (16-20): Purple-Blue shades
  { name: 'Rhododendron arboreum Forest', color: '#6A5ACD' },
  { name: 'Temperate Rhododendron Mixed Broadleaved Forest', color: '#7565D4' },
  { name: 'Dalbergia sissoo-Senegelia catechu Forest', color: '#8070DB' },
  { name: 'Terminalia-Tropical Mixed Broadleaved Forest', color: '#8B7BE2' },
  { name: 'Temperate Mixed Broadleaved Forest', color: '#9686E9' },

  // Alpine Zone (21-25): Brown-Red shades
  { name: 'Tropical Deciduous Indigenous Riverine Forest', color: '#8B4513' },
  { name: 'Tropical Riverine Forest', color: '#9B5923' },
  { name: 'Lower Temperate Mixed robusta Forest', color: '#AB6D33' },
  { name: 'Pinus roxburghii-Shorea robusta Forest', color: '#BB8143' },
  { name: 'Lower Temperate Pinus roxburghii-Quercus Forest', color: '#CB9553' },

  // Special (26)
  { name: 'Data Not Available', color: '#BDBDBD' },
];

/**
 * Static fallbacks for continuous layers, shown when no analysis result is
 * available. These are the same classes the tile color ramps use, so the
 * legend always stays color-accurate.
 */
export const STATIC_FALLBACKS: Record<string, LegendItem[]> = {
  dem: [
    { color: '#8B4513', label: 'Low', range: '< 500m' },
    { color: '#FFA500', label: 'Medium', range: '500-1500m' },
    { color: '#7FFF00', label: 'High', range: '1500-3000m' },
    { color: '#87CEEB', label: 'Very High', range: '> 3000m' },
  ],
  canopy: [
    { color: '#DC143C', label: 'Sparse/Regeneration', range: '0-5m' },
    { color: '#FF8C00', label: 'Young Forest', range: '5-15m' },
    { color: '#90EE90', label: 'Mature Forest', range: '15-30m' },
    { color: '#228B22', label: 'Old Growth', range: '>30m' },
  ],
  temperature: [
    { color: '#0000FF', label: 'Very Cold', range: '< 0°C' },
    { color: '#00BFFF', label: 'Cold', range: '0-10°C' },
    { color: '#90EE90', label: 'Moderate', range: '10-20°C' },
    { color: '#FFD700', label: 'Warm', range: '20-25°C' },
    { color: '#FF4500', label: 'Hot', range: '> 25°C' },
  ],
  precipitation: [
    { color: '#8B4513', label: 'Very Dry', range: '< 500mm' },
    { color: '#D2B48C', label: 'Dry', range: '500-1000mm' },
    { color: '#90EE90', label: 'Moderate', range: '1000-2000mm' },
    { color: '#4169E1', label: 'Wet', range: '2000-3000mm' },
    { color: '#0000CD', label: 'Very Wet', range: '> 3000mm' },
  ],
  biomass: [
    { color: '#DC143C', label: 'Very Low', range: '0-50 Mg/ha' },
    { color: '#FFD700', label: 'Low', range: '50-100 Mg/ha' },
    { color: '#90EE90', label: 'Medium', range: '100-200 Mg/ha' },
    { color: '#228B22', label: 'High', range: '200-300 Mg/ha' },
    { color: '#1E90FF', label: 'Very High', range: '>300 Mg/ha' },
  ],
  slope: SLOPE_CLASSES,
  min_temp_coldest: [
    { color: '#0000CD', label: 'Extreme Cold', range: '< -10°C' },
    { color: '#4169E1', label: 'Very Cold', range: '-10 to 0°C' },
    { color: '#87CEEB', label: 'Cold', range: '0 to 5°C' },
    { color: '#90EE90', label: 'Cool', range: '5 to 10°C' },
    { color: '#FFD700', label: 'Mild', range: '10 to 15°C' },
    { color: '#FF8C00', label: 'Warm', range: '> 15°C' },
  ],
  forest_type: FOREST_TYPE_CLASSES.map(({ name, color }) => ({
    color,
    label: name.replace(' Forest', '').replace(' forest', ''),
  })),
};

// --- Dynamic legend generators (ported from RasterLayerControl) ---

/** Dynamic elevation legend based on actual min/max values. */
export function generateDynamicElevationLegend(minElev: number, maxElev: number): LegendItem[] {
  // Round to nearest 10 for cleaner values
  const min = Math.floor(minElev / 10) * 10;
  const max = Math.ceil(maxElev / 10) * 10;
  const range = max - min;
  const quarter = range / 4;

  if (range < 100) {
    return [
      { color: '#D2691E', label: 'Low', range: `${min.toFixed(0)}-${(min + quarter).toFixed(0)}m` },
      { color: '#FFA500', label: 'Medium-Low', range: `${(min + quarter).toFixed(0)}-${(min + 2 * quarter).toFixed(0)}m` },
      { color: '#90EE90', label: 'Medium-High', range: `${(min + 2 * quarter).toFixed(0)}-${(min + 3 * quarter).toFixed(0)}m` },
      { color: '#4682B4', label: 'High', range: `${(min + 3 * quarter).toFixed(0)}-${max.toFixed(0)}m` },
    ];
  }

  return [
    { color: '#8B4513', label: 'Low', range: `${min.toFixed(0)}-${(min + quarter).toFixed(0)}m` },
    { color: '#FFA500', label: 'Medium-Low', range: `${(min + quarter).toFixed(0)}-${(min + 2 * quarter).toFixed(0)}m` },
    { color: '#7FFF00', label: 'Medium-High', range: `${(min + 2 * quarter).toFixed(0)}-${(min + 3 * quarter).toFixed(0)}m` },
    { color: '#87CEEB', label: 'High', range: `${(min + 3 * quarter).toFixed(0)}-${max.toFixed(0)}m` },
  ];
}

/** Dynamic canopy legend — only classes overlapping the actual min/max height. */
export function generateDynamicCanopyLegend(minHeight: number, maxHeight: number): LegendItem[] {
  const ecologicalClasses = [
    { minH: 0, maxH: 5, color: '#DC143C', label: 'Sparse/Regeneration', range: '0-5m' },
    { minH: 5, maxH: 15, color: '#FF8C00', label: 'Young Forest', range: '5-15m' },
    { minH: 15, maxH: 30, color: '#90EE90', label: 'Mature Forest', range: '15-30m' },
    { minH: 30, maxH: 1000, color: '#228B22', label: 'Old Growth', range: '>30m' },
  ];

  const relevantClasses = ecologicalClasses.filter(cls => cls.maxH > minHeight && cls.minH < maxHeight);

  if (relevantClasses.length === 0) {
    const minVal = minHeight != null ? minHeight.toFixed(1) : 'N/A';
    const maxVal = maxHeight != null ? maxHeight.toFixed(1) : 'N/A';
    return [{ color: '#228B22', label: 'Forest Canopy', range: `${minVal}-${maxVal}m` }];
  }

  return relevantClasses.map(({ color, label, range }) => ({ color, label, range }));
}

/** Dynamic temperature legend — only classes overlapping the actual min/max. */
export function generateDynamicTemperatureLegend(minTemp: number, maxTemp: number): LegendItem[] {
  const temperatureClasses = [
    { minT: -100, maxT: 0, color: '#0000FF', label: 'Very Cold', range: '< 0°C' },
    { minT: 0, maxT: 10, color: '#00BFFF', label: 'Cold', range: '0-10°C' },
    { minT: 10, maxT: 20, color: '#90EE90', label: 'Moderate', range: '10-20°C' },
    { minT: 20, maxT: 25, color: '#FFD700', label: 'Warm', range: '20-25°C' },
    { minT: 25, maxT: 100, color: '#FF4500', label: 'Hot', range: '> 25°C' },
  ];

  const relevantClasses = temperatureClasses.filter(cls => cls.maxT > minTemp && cls.minT < maxTemp);

  if (relevantClasses.length === 0) {
    const minVal = minTemp != null ? minTemp.toFixed(1) : 'N/A';
    const maxVal = maxTemp != null ? maxTemp.toFixed(1) : 'N/A';
    return [{ color: '#90EE90', label: 'Temperature', range: `${minVal}-${maxVal}°C` }];
  }

  return relevantClasses.map(({ color, label, range }) => ({ color, label, range }));
}

/** Dynamic precipitation legend — only classes overlapping the actual min/max. */
export function generateDynamicPrecipitationLegend(minPrecip: number, maxPrecip: number): LegendItem[] {
  const precipClasses = [
    { minP: 0, maxP: 500, color: '#8B4513', label: 'Very Dry', range: '< 500mm' },
    { minP: 500, maxP: 1000, color: '#D2B48C', label: 'Dry', range: '500-1000mm' },
    { minP: 1000, maxP: 2000, color: '#90EE90', label: 'Moderate', range: '1000-2000mm' },
    { minP: 2000, maxP: 3000, color: '#4169E1', label: 'Wet', range: '2000-3000mm' },
    { minP: 3000, maxP: 10000, color: '#0000CD', label: 'Very Wet', range: '> 3000mm' },
  ];

  const relevantClasses = precipClasses.filter(cls => cls.maxP > minPrecip && cls.minP < maxPrecip);

  if (relevantClasses.length === 0) {
    const minVal = minPrecip != null ? minPrecip.toFixed(0) : 'N/A';
    const maxVal = maxPrecip != null ? maxPrecip.toFixed(0) : 'N/A';
    return [{ color: '#90EE90', label: 'Precipitation', range: `${minVal}-${maxVal}mm` }];
  }

  return relevantClasses.map(({ color, label, range }) => ({ color, label, range }));
}

/** Dynamic biomass legend — only classes overlapping the actual min/max. */
export function generateDynamicBiomassLegend(minBiomass: number, maxBiomass: number): LegendItem[] {
  const biomassClasses = [
    { minB: 0, maxB: 50, color: '#DC143C', label: 'Very Low', range: '0-50 Mg/ha' },
    { minB: 50, maxB: 100, color: '#FFD700', label: 'Low', range: '50-100 Mg/ha' },
    { minB: 100, maxB: 200, color: '#90EE90', label: 'Medium', range: '100-200 Mg/ha' },
    { minB: 200, maxB: 300, color: '#228B22', label: 'High', range: '200-300 Mg/ha' },
    { minB: 300, maxB: 10000, color: '#1E90FF', label: 'Very High', range: '>300 Mg/ha' },
  ];

  const relevantClasses = biomassClasses.filter(cls => cls.maxB > minBiomass && cls.minB < maxBiomass);

  if (relevantClasses.length === 0) {
    const minVal = minBiomass != null ? minBiomass.toFixed(0) : 'N/A';
    const maxVal = maxBiomass != null ? maxBiomass.toFixed(0) : 'N/A';
    return [{ color: '#90EE90', label: 'Biomass', range: `${minVal}-${maxVal} Mg/ha` }];
  }

  return relevantClasses.map(({ color, label, range }) => ({ color, label, range }));
}

/** Dynamic slope legend — only classes between min/max slope codes. */
export function generateDynamicSlopeLegend(minCode: number, maxCode: number): LegendItem[] {
  const relevantClasses = SLOPE_CLASSES.filter((_, idx) => idx + 1 >= minCode && idx + 1 <= maxCode);
  return relevantClasses.length > 0 ? relevantClasses : SLOPE_CLASSES;
}

/** Dynamic min-temperature (coldest month) legend — only classes overlapping actual min/max. */
export function generateDynamicMinTempColdestLegend(minTemp: number, maxTemp: number): LegendItem[] {
  const tempClasses = [
    { minT: -100, maxT: -10, color: '#0000CD', label: 'Extreme Cold', range: '< -10°C' },
    { minT: -10, maxT: 0, color: '#4169E1', label: 'Very Cold', range: '-10 to 0°C' },
    { minT: 0, maxT: 5, color: '#87CEEB', label: 'Cold', range: '0 to 5°C' },
    { minT: 5, maxT: 10, color: '#90EE90', label: 'Cool', range: '5 to 10°C' },
    { minT: 10, maxT: 15, color: '#FFD700', label: 'Mild', range: '10 to 15°C' },
    { minT: 15, maxT: 100, color: '#FF8C00', label: 'Warm', range: '> 15°C' },
  ];

  const relevantClasses = tempClasses.filter(cls => cls.maxT > minTemp && cls.minT < maxTemp);

  if (relevantClasses.length === 0) {
    const minVal = minTemp != null ? minTemp.toFixed(1) : 'N/A';
    const maxVal = maxTemp != null ? maxTemp.toFixed(1) : 'N/A';
    return [{ color: '#87CEEB', label: 'Min Temperature', range: `${minVal}-${maxVal}°C` }];
  }

  return relevantClasses.map(({ color, label, range }) => ({ color, label, range }));
}

/** Dynamic land cover legend — only classes present in the data, sorted by share desc. */
export function generateDynamicLandcoverLegend(landcoverPercentages: Record<string, number>): LegendItem[] {
  const landcoverColors: Record<string, string> = {
    'Tree cover': '#006400',
    'Shrubland': '#FFBB22',
    'Grassland': '#FFFF4C',
    'Cropland': '#F096FF',
    'Built-up': '#FA0000',
    'Bare/sparse vegetation': '#B4B4B4',
    'Snow and ice': '#F0F0F0',
    'Permanent water bodies': '#0064C8',
    'Herbaceous wetland': '#0096A0',
    'Mangroves': '#00CF75',
    'Moss and lichen': '#FAE6A0',
  };

  const landcoverCodes: Record<string, string> = {
    'Tree cover': '10',
    'Shrubland': '20',
    'Grassland': '30',
    'Cropland': '40',
    'Built-up': '50',
    'Bare/sparse vegetation': '60',
    'Snow and ice': '70',
    'Permanent water bodies': '80',
    'Herbaceous wetland': '90',
    'Mangroves': '95',
    'Moss and lichen': '100',
  };

  if (!landcoverPercentages || Object.keys(landcoverPercentages).length === 0) {
    return [];
  }

  return Object.entries(landcoverPercentages)
    .filter(([, percentage]) => percentage > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([className, percentage]) => ({
      color: landcoverColors[className] || '#808080',
      label: className,
      range: `${landcoverCodes[className] || '?'} (${percentage.toFixed(1)}%)`,
    }));
}

/** Dynamic NASA forest legend — classes present, colors embedded directly. */
export function generateDynamicNasaForestLegend(nasaPercentages: Record<string, number>): LegendItem[] {
  const nasaClasses = [
    {
      name: 'Primary Forest',
      color: '#00FF00',
      description: 'Class 1 - Old-growth, highest carbon',
      aliases: ['primary forest', 'Primary Forest', 'PRIMARY FOREST'],
    },
    {
      name: 'Young Secondary Forest',
      color: '#FF0000',
      description: 'Class 2 - Regenerating, low carbon',
      aliases: ['young secondary forest', 'Young Secondary Forest', 'YOUNG SECONDARY FOREST'],
    },
    {
      name: 'Old Secondary Forest',
      color: '#6666FF',
      description: 'Class 3 - Mature regrowth, medium carbon',
      aliases: ['old secondary forest', 'Old Secondary Forest', 'OLD SECONDARY FOREST'],
    },
  ];

  if (!nasaPercentages || Object.keys(nasaPercentages).length === 0) {
    return [];
  }

  const legendItems: LegendItem[] = [];

  for (const [className, percentage] of Object.entries(nasaPercentages)) {
    if (percentage > 0) {
      const matchedClass = nasaClasses.find(cls =>
        cls.aliases.some(alias => alias.toLowerCase() === className.toLowerCase()),
      );
      if (matchedClass) {
        legendItems.push({
          color: matchedClass.color,
          label: className,
          range: `${matchedClass.description} (${percentage.toFixed(1)}%)`,
        });
      }
    }
  }

  return legendItems.sort((a, b) => {
    const aPercent = parseFloat(a.range?.match(/\(([\d.]+)%\)/)?.[1] || '0');
    const bPercent = parseFloat(b.range?.match(/\(([\d.]+)%\)/)?.[1] || '0');
    return bPercent - aPercent;
  });
}

/** Dynamic aspect legend — only directions present, compass order. */
export function generateDynamicAspectLegend(aspectPercentages: Record<string, number>): LegendItem[] {
  const aspectColors: Record<string, string> = {
    Flat: '#CCCCCC',
    N: '#1A5490',
    NE: '#3498DB',
    E: '#1ABC9C',
    SE: '#F1C40F',
    S: '#E74C3C',
    SW: '#E67E22',
    W: '#F39C12',
    NW: '#9B59B6',
  };

  const aspectLabels: Record<string, string> = {
    Flat: 'Flat',
    N: 'North (N)',
    NE: 'Northeast (NE)',
    E: 'East (E)',
    SE: 'Southeast (SE)',
    S: 'South (S)',
    SW: 'Southwest (SW)',
    W: 'West (W)',
    NW: 'Northwest (NW)',
  };

  if (!aspectPercentages || Object.keys(aspectPercentages).length === 0) {
    return [];
  }

  const order = ['Flat', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

  return Object.entries(aspectPercentages)
    .filter(([, percentage]) => percentage > 0)
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([direction, percentage]) => ({
      color: aspectColors[direction] || '#808080',
      label: aspectLabels[direction] || direction,
      range: `${percentage.toFixed(1)}%`,
    }));
}

/** Dynamic forest health legend — classes present, sorted Stressed → Excellent. */
export function generateDynamicForestHealthLegend(healthPercentages: Record<string, number>): LegendItem[] {
  interface HealthClass {
    name: string;
    color: string;
    range: string;
    order: number;
    aliases: string[];
  }

  const healthClasses: HealthClass[] = [
    { name: 'Stressed', color: '#DC143C', range: 'NDVI < 0.2', order: 1, aliases: ['stressed', 'Stressed', 'STRESSED'] },
    { name: 'Poor', color: '#FF8C00', range: 'NDVI 0.2-0.4', order: 2, aliases: ['poor', 'Poor', 'POOR'] },
    { name: 'Moderate', color: '#FFD700', range: 'NDVI 0.4-0.6', order: 3, aliases: ['moderate', 'Moderate', 'MODERATE'] },
    { name: 'Healthy', color: '#90EE90', range: 'NDVI 0.6-0.8', order: 4, aliases: ['healthy', 'Healthy', 'HEALTHY'] },
    { name: 'Excellent', color: '#228B22', range: 'NDVI > 0.8', order: 5, aliases: ['excellent', 'Excellent', 'EXCELLENT'] },
  ];

  if (!healthPercentages || Object.keys(healthPercentages).length === 0) {
    return [];
  }

  const legendItems: Array<LegendItem & { order: number }> = [];

  for (const [healthClass, percentage] of Object.entries(healthPercentages)) {
    if (percentage > 0) {
      const matchedClass = healthClasses.find(cls =>
        cls.aliases.some(alias => alias.toLowerCase() === healthClass.toLowerCase()),
      );
      if (matchedClass) {
        legendItems.push({
          color: matchedClass.color,
          label: healthClass,
          range: `${matchedClass.range} (${percentage.toFixed(1)}%)`,
          order: matchedClass.order,
        });
      }
    }
  }

  return legendItems
    .sort((a, b) => a.order - b.order)
    .map(({ order, ...item }) => item);
}

/** Dynamic forest type legend — classes present, flexible name matching, sorted by share desc. */
export function generateDynamicForestTypeLegend(forestTypePercentages: Record<string, number>): LegendItem[] {
  if (!forestTypePercentages || Object.keys(forestTypePercentages).length === 0) {
    return [];
  }

  const shortLabel = (name: string) => name.replace(' Forest', '').replace(' forest', '');

  const legendItems: LegendItem[] = [];

  for (const [typeName, percentage] of Object.entries(forestTypePercentages)) {
    if (percentage <= 0) continue;

    let matchedClass = FOREST_TYPE_CLASSES.find(cls => cls.name.toLowerCase() === typeName.toLowerCase());

    if (!matchedClass) {
      const typeNameWithForest = typeName.endsWith(' Forest') || typeName.endsWith(' forest')
        ? typeName
        : `${typeName} Forest`;
      matchedClass = FOREST_TYPE_CLASSES.find(cls => cls.name.toLowerCase() === typeNameWithForest.toLowerCase());
    }

    if (!matchedClass) {
      const typeNameWithoutForest = typeName.replace(' Forest', '').replace(' forest', '');
      matchedClass = FOREST_TYPE_CLASSES.find(
        cls => shortLabel(cls.name).toLowerCase() === typeNameWithoutForest.toLowerCase(),
      );
    }

    if (!matchedClass) {
      const firstWord = typeName.split(/[\s\-/]+/)[0].toLowerCase();
      matchedClass = FOREST_TYPE_CLASSES.find(cls => cls.name.toLowerCase().startsWith(firstWord));
    }

    if (matchedClass) {
      legendItems.push({
        color: matchedClass.color,
        label: shortLabel(typeName),
        range: `${percentage.toFixed(1)}%`,
      });
    } else {
      // Deterministic fallback color from a palette for unmatched legacy names
      const fallbackPalette = [
        '#E6194B', '#3CB44B', '#FFE119', '#4363D8', '#F58231',
        '#911EB4', '#42D4F4', '#F032E6', '#BFEF45', '#469990',
        '#DCBEFF', '#9A6324', '#800000', '#A9A9A9', '#000075',
      ];
      const hash = typeName.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
      legendItems.push({
        color: fallbackPalette[hash % fallbackPalette.length],
        label: shortLabel(typeName),
        range: `${percentage.toFixed(1)}%`,
      });
    }
  }

  return legendItems.sort((a, b) => (parseFloat(b.range || '0')) - (parseFloat(a.range || '0')));
}

/** Dynamic fire loss legend — grouped into time periods with total hectares. */
export function generateDynamicFireLossLegend(fireByYear: Record<string, number>): LegendItem[] {
  if (!fireByYear || Object.keys(fireByYear).length === 0) {
    return [];
  }

  const periods = [
    { label: '2001-2008', color: '#FF8C00', years: Array.from({ length: 8 }, (_, i) => String(2001 + i)), hectares: 0 },
    { label: '2009-2016', color: '#FF4500', years: Array.from({ length: 8 }, (_, i) => String(2009 + i)), hectares: 0 },
    { label: '2017-2024', color: '#8B0000', years: Array.from({ length: 8 }, (_, i) => String(2017 + i)), hectares: 0 },
  ];

  for (const [year, hectares] of Object.entries(fireByYear)) {
    for (const period of periods) {
      if (period.years.includes(year)) {
        period.hectares += hectares;
      }
    }
  }

  return periods
    .filter(p => p.hectares > 0)
    .map(p => ({
      color: p.color,
      label: p.label,
      range: `${p.hectares.toFixed(2)} ha`,
    }));
}

/** Dynamic soil pH legend — only the active pH category. */
export function generateDynamicSoilPHLegend(soilData: Record<string, any> | null | undefined): LegendItem[] {
  const categories = [
    { color: '#DC143C', label: 'Extremely Acidic', range: '< 4.5', min: 0, max: 4.5 },
    { color: '#FF8C00', label: 'Strongly Acidic', range: '4.5-5.5', min: 4.5, max: 5.5 },
    { color: '#FFD700', label: 'Slightly Acidic', range: '5.5-6.5', min: 5.5, max: 6.5 },
    { color: '#228B22', label: 'Neutral (Optimal)', range: '6.5-7.5', min: 6.5, max: 7.5 },
    { color: '#4682B4', label: 'Slightly Alkaline', range: '7.5-8.5', min: 7.5, max: 8.5 },
    { color: '#9370DB', label: 'Strongly Alkaline', range: '> 8.5', min: 8.5, max: 14 },
  ];

  const phValue = soilData?.soil_properties?.ph_h2o;

  if (phValue === null || phValue === undefined) {
    return [];
  }

  const activeCategory = categories.find(c => phValue >= c.min && phValue < c.max);
  if (!activeCategory) return [];

  return [{ color: activeCategory.color, label: activeCategory.label, range: `${activeCategory.range} (pH ${phValue.toFixed(1)})` }];
}

/** Dynamic soil texture legend — only the active texture. */
export function generateDynamicSoilTextureLegend(soilData: Record<string, any> | null | undefined): LegendItem[] {
  const categories = [
    { color: '#654321', label: 'Clay', range: 'Heavy', keywords: ['clay'] },
    { color: '#8B4513', label: 'Clay Loam', range: 'Moderate', keywords: ['clay loam'] },
    { color: '#A0522D', label: 'Loam (Optimal)', range: 'Balanced', keywords: ['loam', 'silt loam', 'sandy loam'] },
    { color: '#D2B48C', label: 'Sandy', range: 'Light', keywords: ['sand', 'sandy'] },
  ];

  const texture = soilData?.soil_texture?.toLowerCase();
  if (!texture) return [];

  const activeCategory = categories.find(c => c.keywords.some(keyword => texture.includes(keyword)));
  if (!activeCategory) return [];

  return [{ color: activeCategory.color, label: activeCategory.label, range: `${activeCategory.range} (${texture})` }];
}

/** Dynamic soil carbon legend — only the active SOC category. */
export function generateDynamicSoilCarbonLegend(soilData: Record<string, any> | null | undefined): LegendItem[] {
  const categories = [
    { color: '#DC143C', label: 'Very Low', range: '< 0.5%', max: 0.5 },
    { color: '#FF8C00', label: 'Low', range: '0.5-1.0%', min: 0.5, max: 1.0 },
    { color: '#FFD700', label: 'Medium', range: '1.0-2.0%', min: 1.0, max: 2.0 },
    { color: '#90EE90', label: 'High', range: '2.0-3.0%', min: 2.0, max: 3.0 },
    { color: '#228B22', label: 'Very High (Forest)', range: '> 3.0%', min: 3.0 },
  ];

  const socValue = soilData?.soil_properties?.soc_dg_kg;
  if (socValue === null || socValue === undefined) return [];

  // 1 dg/kg = 0.1%
  const socPercent = socValue > 10 ? socValue / 10.0 : socValue;

  const activeCategory = categories.find(c => {
    if (c.max !== undefined && c.min !== undefined) return socPercent >= c.min && socPercent < c.max;
    if (c.max !== undefined) return socPercent < c.max;
    if (c.min !== undefined) return socPercent >= c.min;
    return false;
  });

  if (!activeCategory) return [];

  return [{ color: activeCategory.color, label: activeCategory.label, range: `${activeCategory.range} (${socPercent.toFixed(1)}% SOC)` }];
}

/** Dynamic soil fertility legend — only the active fertility category. */
export function generateDynamicSoilFertilityLegend(soilData: Record<string, any> | null | undefined): LegendItem[] {
  const categories = [
    { color: '#DC143C', label: 'Very Low', range: '0-20', min: 0, max: 20 },
    { color: '#FF8C00', label: 'Low', range: '20-40', min: 20, max: 40 },
    { color: '#FFD700', label: 'Medium', range: '40-60', min: 40, max: 60 },
    { color: '#90EE90', label: 'High', range: '60-80', min: 60, max: 80 },
    { color: '#228B22', label: 'Very High', range: '80-100', min: 80, max: 100 },
  ];

  const fertilityScore = soilData?.fertility_score;
  if (fertilityScore === null || fertilityScore === undefined) return [];

  const activeCategory = categories.find(c => fertilityScore >= c.min && fertilityScore <= c.max);
  if (!activeCategory) return [];

  return [{ color: activeCategory.color, label: activeCategory.label, range: `${activeCategory.range} (Score: ${fertilityScore})` }];
}

/** Dynamic soil density legend — only the active bulk-density category. */
export function generateDynamicSoilDensityLegend(soilData: Record<string, any> | null | undefined): LegendItem[] {
  const categories = [
    { color: '#228B22', label: 'Low (Good)', range: '< 1.2 g/cm³', max: 1.2 },
    { color: '#FFD700', label: 'Moderate', range: '1.2-1.4 g/cm³', min: 1.2, max: 1.4 },
    { color: '#FF8C00', label: 'Elevated', range: '1.4-1.6 g/cm³', min: 1.4, max: 1.6 },
    { color: '#DC143C', label: 'High Risk', range: '> 1.6 g/cm³', min: 1.6 },
  ];

  const bulkDensityCG = soilData?.soil_properties?.bulk_density_cg_cm3;
  if (bulkDensityCG === null || bulkDensityCG === undefined) return [];

  const bulkDensityG = bulkDensityCG / 100;

  const activeCategory = categories.find(c => {
    if (c.max !== undefined && c.min !== undefined) return bulkDensityG >= c.min && bulkDensityG < c.max;
    if (c.max !== undefined) return bulkDensityG < c.max;
    if (c.min !== undefined) return bulkDensityG >= c.min;
    return false;
  });

  if (!activeCategory) return [];

  return [{ color: activeCategory.color, label: activeCategory.label, range: `${activeCategory.range} (${bulkDensityG.toFixed(2)} g/cm³)` }];
}

// --- Resolver ---

function minMaxLegend(
  rd: Record<string, any> | null | undefined,
  minKey: string,
  maxKey: string,
  validate: (min: number, max: number) => boolean,
  generate: (min: number, max: number) => LegendItem[],
): LegendItem[] {
  const min = rd?.[minKey];
  const max = rd?.[maxKey];
  if (typeof min !== 'number' || typeof max !== 'number' || !validate(min, max)) return [];
  return generate(min, max);
}

function percentageLegend(
  rd: Record<string, any> | null | undefined,
  key: string,
  generate: (p: Record<string, number>) => LegendItem[],
): LegendItem[] {
  const p = rd?.[key];
  if (!p || typeof p !== 'object' || Object.keys(p).length === 0) return [];
  return generate(p as Record<string, number>);
}

const DYNAMIC_LEGEND_FNS: Record<string, (rd: Record<string, any>) => LegendItem[]> = {
  dem: rd => minMaxLegend(rd, 'elevation_min_m', 'elevation_max_m', (a, b) => a > -32000 && b > -32000, generateDynamicElevationLegend),
  canopy: rd => minMaxLegend(rd, 'canopy_min_m', 'canopy_max_m', (a, b) => a >= 0 && b >= 0, generateDynamicCanopyLegend),
  temperature: rd => minMaxLegend(rd, 'temperature_min_c', 'temperature_max_c', (a, b) => a > -100 && b < 100, generateDynamicTemperatureLegend),
  precipitation: rd => minMaxLegend(rd, 'precipitation_min_mm', 'precipitation_max_mm', (a, b) => a >= 0 && b >= 0, generateDynamicPrecipitationLegend),
  biomass: rd => minMaxLegend(rd, 'agb_min_mg_ha', 'agb_max_mg_ha', (a, b) => a >= 0 && b >= 0, generateDynamicBiomassLegend),
  slope: rd => minMaxLegend(rd, 'slope_min_code', 'slope_max_code', (a, b) => a >= 1 && a <= 4 && b >= 1 && b <= 4, generateDynamicSlopeLegend),
  min_temp_coldest: rd => minMaxLegend(rd, 'min_temp_coldest_min_c', 'min_temp_coldest_max_c', (a, b) => a > -100 && b < 100, generateDynamicMinTempColdestLegend),
  landcover: rd => percentageLegend(rd, 'landcover_percentages', generateDynamicLandcoverLegend),
  nasa_forest_2020: rd => {
    const key = rd?.whole_nasa_forest_2020_percentages ? 'whole_nasa_forest_2020_percentages' : 'nasa_forest_2020_percentages';
    return percentageLegend(rd, key, generateDynamicNasaForestLegend);
  },
  aspect: rd => percentageLegend(rd, 'aspect_percentages', generateDynamicAspectLegend),
  forest_health: rd => percentageLegend(rd, 'forest_health_percentages', generateDynamicForestHealthLegend),
  forest_type: rd => percentageLegend(rd, 'forest_type_percentages', generateDynamicForestTypeLegend),
  fire: rd => percentageLegend(rd, 'fire_loss_by_year', generateDynamicFireLossLegend),
};

/** Tile route for a raster overlay. The generic route is
 *  `/tiles/{id}`; catalog entries may override it (e.g. the user-group
 *  overlays: `user-group-tiles/{landcover|biomass}` + `exclude_forest=true`). */
export function buildRasterTileUrl(
  calcId: string,
  id: string,
  meta?: RasterLayerMeta | null,
  alpha?: number,
): string {
  const path = meta?.tilesPath ?? 'tiles';
  const tileKey = meta?.tileKey ?? id;
  const extra = meta?.extraParams ? `&${new URLSearchParams(meta.extraParams).toString()}` : '';
  return `/api/calculations/${calcId}/${path}/${tileKey}/{z}/{x}/{y}.png?alpha=${alpha ?? 255}${extra}`;
}

/**
 * Resolve the legend for a raster layer.
 *
 * - With analysis `resultData`, continuous layers get dynamic class breaks and
 *   percentage-based layers get only the classes actually present.
 * - Without `resultData` (e.g. the workspace LegendPanel, which does not load
 *   the calculation), a color-accurate static fallback is returned so the
 *   legend is always populated.
 */
export function resolveRasterLegend(id: string, resultData?: Record<string, any> | null): LegendItem[] {
  // User-group overlays reuse the host layer's classes/colours (land-cover and
  // biomass rasters from `user-group-tiles` have the same ramps as the global
  // ones served from `/tiles`).
  const resolved = LEGEND_ALIASES[id] ?? id;
  const dynamic = DYNAMIC_LEGEND_FNS[resolved];
  if (dynamic && resultData) {
    try {
      const items = dynamic(resultData);
      if (items && items.length > 0) return items;
    } catch {
      // Fall back to the static legend below.
    }
  }
  return STATIC_FALLBACKS[resolved] ?? STATIC_LEGENDS[resolved] ?? [];
}

const LEGEND_ALIASES: Record<string, string> = {
  ug_landcover: 'landcover',
  ug_biomass: 'biomass',
};
