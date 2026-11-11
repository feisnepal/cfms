/**
 * Nepali-language label maps for forest classification constants.
 *
 * Provides Nepali (Devanagari) translations for slope classes, aspect
 * directions, canopy cover, forest health, DBH classes, land cover
 * types, and forest type classifications used throughout the UI.
 */
export const SLOPE_CLASS_NP: Record<string, string> = {
  flat: 'समतल',
  gentle: 'हल्का',
  moderate: 'मध्यम',
  steep: 'भिरालो',
  very_steep: 'अति भिरालो',
};

export const SLOPE_COLORS: Record<string, string> = {
  flat: '#22c55e',
  gentle: '#84cc16',
  moderate: '#eab308',
  steep: '#f97316',
  very_steep: '#ef4444',
};

export const ASPECT_CLASS_NP: Record<string, string> = {
  flat: 'समतल',
  n: 'उत्तर',
  north: 'उत्तर',
  ne: 'उत्तर-पूर्व',
  northeast: 'उत्तर-पूर्व',
  e: 'पूर्व',
  east: 'पूर्व',
  se: 'दक्षिण-पूर्व',
  southeast: 'दक्षिण-पूर्व',
  s: 'दक्षिण',
  south: 'दक्षिण',
  sw: 'दक्षिण-पश्चिम',
  southwest: 'दक्षिण-पश्चिम',
  w: 'पश्चिम',
  west: 'पश्चिम',
  nw: 'उत्तर-पश्चिम',
  northwest: 'उत्तर-पश्चिम',
};

export const ASPECT_COLORS: Record<string, string> = {
  flat: '#CCCCCC',
  north: '#1A5490',
  northeast: '#3498DB',
  east: '#1ABC9C',
  southeast: '#F1C40F',
  south: '#E74C3C',
  southwest: '#E67E22',
  west: '#F39C12',
  northwest: '#9B59B6',
};

export const HEALTH_CLASS_NP: Record<string, string> = {
  stressed: 'तनावग्रस्त',
  poor: 'कमजोर',
  moderate: 'मध्यम',
  healthy: 'स्वस्थ',
  very_healthy: 'स्वस्थ',
  excellent: 'उत्कृष्ट',
};

export const HEALTH_COLORS: Record<string, string> = {
  stressed: '#DC143C',
  poor: '#FF8C00',
  moderate: '#FFD700',
  healthy: '#90EE90',
  excellent: '#228B22',
};

export const CANOPY_CLASS_NP: Record<string, string> = {
  non_forest: 'वन नभएको (१)',
  regeneration: 'पुनरुत्थान (२-५)',
  pole_trees: 'पोल वन (६-१५)',
  tree: 'रूख (>१५)',
  dense: 'गाढा',
  medium: 'मध्यम',
  sparse: 'पातलो',
};

export const CANOPY_COLORS: Record<string, string> = {
  tree: '#059669',
  pole_trees: '#10b981',
  regeneration: '#84cc16',
  non_forest: '#94a3b8',
  dense: '#059669',
  medium: '#10b981',
  sparse: '#84cc16',
};

export const LANDCOVER_CLASS_NP: Record<string, string> = {
  tree_cover: 'रूख आवरण',
  shrubland: 'झाडी',
  grassland: 'घाँसे मैदान',
  cropland: 'खेती योग्य',
  built_up: 'बस्ती',
  bare_sparse: 'खुल्ला/पथरिलो',
  bare: 'खुल्ला',
  snow_ice: 'हिउँ',
  water: 'पानी',
  wetland: 'सिमसार',
  mangroves: 'म्यान्ग्रुभ',
  moss_lichen: 'झ्याउ',
};

export const LANDCOVER_COLORS: Record<string, string> = {
  tree_cover: '#006400',
  shrubland: '#FFBB22',
  grassland: '#FFFF4C',
  cropland: '#F096FF',
  built_up: '#FA0000',
  bare_sparse: '#B4B4B4',
  bare: '#B4B4B4',
  snow_ice: '#F0F0F0',
  water: '#0064C8',
  wetland: '#0096A0',
  mangroves: '#00CF75',
  moss_lichen: '#FAE6A0',
};

export const SOIL_TEXTURE_NP: Record<string, string> = {
  sand: 'बलुवे',
  loamy_sand: 'बलुवे दोमट',
  'loamy sand': 'बलुवे दोमट',
  sandy_loam: 'बलौटे दोमट',
  'sandy loam': 'बलौटे दोमट',
  loam: 'दोमट (उपयुक्त)',
  silt_loam: 'ग्राबेले दोमट',
  'silt loam': 'ग्राबेले दोमट',
  silt: 'ग्राबेले',
  sandy_clay_loam: 'बलौटे चिल्लो दोमट',
  'sandy clay loam': 'बलौटे चिल्लो दोमट',
  clay_loam: 'चिल्लो दोमट',
  'clay loam': 'चिल्लो दोमट',
  silty_clay_loam: 'ग्राबेले चिल्लो दोमट',
  'silty clay loam': 'ग्राबेले चिल्लो दोमट',
  sandy_clay: 'बलौटे चिल्लो',
  'sandy clay': 'बलौटे चिल्लो',
  silty_clay: 'ग्राबेले चिल्लो',
  'silty clay': 'ग्राबेले चिल्लो',
  clay: 'चिल्लो माटो',
};

export const SOIL_PH_NP: Record<string, string> = {
  extremely_acidic: 'अति अम्लिय',
  strongly_acidic: 'कडा अम्लिय',
  slightly_acidic: 'हल्का अम्लिय',
  neutral: 'तटस्थ (उपयुक्त)',
  slightly_alkaline: 'हल्का क्षारिय',
  strongly_alkaline: 'कडा क्षारिय',
};

/**
 * Canonical soil-fertility bands, keyed on the tokens the backend producer actually
 * emits (`app/core/soil_fertility.py::FertilityClass`): high / good / moderate / low /
 * very_low, in descending score order.
 *
 * One concept had three vocabularies. The producer emits these lowercase tokens; the
 * analysis page compared against 'Very High' / 'High' / 'Medium' / 'Low', which none of
 * them match; and the export below was keyed `very_low` / `low` / `medium` / `high` /
 * `very_high`, which matches neither - it had no `good` or `moderate` at all, and its
 * `high` meant the second band where the producer's `high` is the top one, so exported
 * reports were a band out. Both surfaces now resolve through here, so a soil cannot be
 * coloured one band and labelled another.
 */
export interface FertilityBand {
  labelEn: string;
  labelNp: string;
  color: string;
  badgeClass: string;
}

export const FERTILITY_BANDS: Record<string, FertilityBand> = {
  high: {
    labelEn: 'Very High',
    labelNp: 'अति उच्च',
    color: '#22c55e',
    badgeClass: 'bg-green-100 text-green-800',
  },
  good: {
    labelEn: 'High',
    labelNp: 'उच्च',
    color: '#84cc16',
    badgeClass: 'bg-green-50 text-green-700',
  },
  moderate: {
    labelEn: 'Medium',
    labelNp: 'मध्यम',
    color: '#eab308',
    badgeClass: 'bg-yellow-100 text-yellow-800',
  },
  low: {
    labelEn: 'Low',
    labelNp: 'न्यून',
    color: '#f97316',
    badgeClass: 'bg-orange-100 text-orange-800',
  },
  very_low: {
    labelEn: 'Very Low',
    labelNp: 'अति न्यून',
    color: '#ef4444',
    badgeClass: 'bg-red-100 text-red-800',
  },
};

/** Shown for a class that is not one of the five bands. */
export const FERTILITY_UNKNOWN_BADGE = 'bg-gray-100 text-gray-700';

/**
 * Resolve a fertility class to its band, tolerating case, padding and separators.
 * Returns `undefined` rather than a default, so an unrecognised class is not silently
 * presented as the bottom band.
 */
export function resolveFertilityBand(value?: string | null): FertilityBand | undefined {
  if (value === null || value === undefined) return undefined;
  const key = String(value).trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (!key) return undefined;
  return FERTILITY_BANDS[key];
}

/**
 * Keyed on the producer's own tokens, and derived from FERTILITY_BANDS so the export
 * cannot drift away from the band the analysis page displays.
 */
export const FERTILITY_NP: Record<string, string> = Object.fromEntries(
  Object.entries(FERTILITY_BANDS).map(([token, band]) => [token, band.labelNp]),
);

export const COMPACTION_NP: Record<string, string> = {
  low: 'न्यून जमाव',
  not_compacted: 'जमाव नभएको',
  slight_compaction: 'हल्का जमाव',
  moderate_compaction: 'मध्यम जमाव',
  moderate: 'मध्यम',
  elevated: 'उच्च',
  high_risk: 'उच्च जोखिम',
};

export const FOREST_QUALITY_NP: Record<string, string> = {
  'Primary Forest': 'प्राथमिक वन (पुरानो वन)',
  'Primary Forest (Class 1)': 'प्राथमिक वन (पुरानो वन)',
  'Young Secondary Forest': 'कम उमेरको दोस्रो पुस्ताको वन',
  'Young Secondary Forest (Class 2)': 'कम उमेरको दोस्रो पुस्ताको वन',
  'Old Secondary Forest': 'पुरानो दोस्रो पुस्ताको वन',
  'Old Secondary Forest (Class 3)': 'पुरानो दोस्रो पुस्ताको वन',
};

export const FOREST_QUALITY_COLORS: Record<string, string> = {
  'Primary Forest': '#00FF00',
  'Primary Forest (Class 1)': '#00FF00',
  'Young Secondary Forest': '#FF0000',
  'Young Secondary Forest (Class 2)': '#FF0000',
  'Old Secondary Forest': '#6666FF',
  'Old Secondary Forest (Class 3)': '#6666FF',
};

export const RASTER_LAYER_NP: Record<string, string> = {
  slope: 'भिरालो',
  aspect: 'दिशा',
  dem: 'उचाइ',
  canopy: 'वनको माथिल्लो सतह उचाइ',
  biomass: 'वायवीय जैविक पदार्थ',
  temperature: 'तापक्रम',
  precipitation: 'वर्षा',
  forest_health: 'वन स्वास्थ्य',
  min_temp_coldest: 'न्यूनतम तापक्रम (जाडो महिना)',
  nasa_forest_2020: 'वन गुणस्तर (नासा)',
  forest_type: 'वन प्रकार',
  landcover: 'जमिनको आवरण',
  forest_loss: 'वन क्षति',
  forest_gain: 'वन लाभ',
  fire: 'आगलागी क्षति',
  soil_ph: 'माटोको पीएच',
  soil_texture: 'माटोको बनावट',
  soil_carbon: 'माटोको जैविक कार्बन',
  soil_fertility: 'माटो उर्वराशक्ति',
  soil_density: 'माटो जमाव',
};

export const SPECIES_ROLE_NP: Record<string, string> = {
  Dominant: 'प्रमुख',
  'Co-dominant': 'सह-प्रमुख',
  Associate: 'सहयोगी',
  Occasional: 'कहिलेकाहीँ',
  Rare: 'दुर्लभ',
};

export const SPECIES_ROLE_COLORS: Record<string, string> = {
  Dominant: '#059669',
  'Co-dominant': '#10b981',
  Associate: '#84cc16',
  Occasional: '#f59e0b',
  Rare: '#ef4444',
};

export const IUCN_STATUS_NP: Record<string, string> = {
  CR: 'अति संकटापन्न',
  EN: 'संकटापन्न',
  VU: 'असुरक्षित',
  NT: 'संकटासन्न',
  LC: 'सामान्य',
  DD: 'अपर्याप्त',
};

export const IUCN_STATUS_COLORS: Record<string, string> = {
  CR: '#dc2626',
  EN: '#ea580c',
  VU: '#d97706',
  NT: '#ca8a04',
  LC: '#16a34a',
  DD: '#6b7280',
};

export const BIODIVERSITY_SUB_CATEGORY_NP: Record<string, string> = {
  tree: 'रूख',
  shrub: 'झाडी',
  herb: 'जडिबुटी',
  grass: 'घाँस',
  mammal: 'स्तनधारी',
  bird: 'चरा',
  reptile: 'सरीसृप',
  amphibian: 'उभयचर',
  fish: 'माछा',
  insect: 'कीरा',
  invertebrate: 'अमेरुदण्डी',
  fungi: 'च्याउ',
  lichen: 'लाइकेन',
  moss: 'झ्याउ',
};

export const SPECIES_GROWTH_NP: Record<string, string> = {
  fast: 'द्रुत बृद्धि',
  high: 'द्रुत बृद्धि',
  medium: 'मध्यम बृद्धि',
  moderate: 'मध्यम बृद्धि',
  slow: 'सुस्त बृद्धि',
  low: 'सुस्त बृद्धि',
};

export function toNepaliDigit(num: number | string, decimals: number = 2): string {
  const nepaliDigits = ['०', '१', '२', '३', '४', '५', '६', '७', '८', '९'];
  const numStr = typeof num === 'number' ? num.toFixed(decimals) : String(num);
  return numStr.replace(/\d/g, d => nepaliDigits[parseInt(d)] || d);
}

export function getValueWithUnit(value: number | undefined | null, key: string): string {
  if (value === undefined || value === null) return '—';
  const unitMap: Record<string, string> = {
    area_hectares: 'हेक्टर',
    total_area_hectares: 'हेक्टर',
    effective_area_hectares: 'हेक्टर',
    excluded_area_hectares: 'हेक्टर',
    elevation_mean_m: 'मिटर',
    elevation_min_m: 'मिटर',
    elevation_max_m: 'मिटर',
    temperature_mean_c: '°C',
    temperature_min_c: '°C',
    temperature_max_c: '°C',
    precipitation_mean_mm: 'मिमि/वर्ष',
    carbon_stock: 'मेगाग्राम',
    carbon_stock_mg: 'मेगाग्राम',
    agb_mean: 'Mg/ha',
    agb_total: 'मेगाग्राम',
    agb_total_mg: 'मेगाग्राम',
    agb_mean_mg_ha: 'Mg/ha',
    forest_loss_hectares: 'हेक्टर',
    forest_gain_hectares: 'हेक्टर',
    fire_loss_hectares: 'हेक्टर',
    canopy_mean_m: 'मिटर',
    fi_growing_stock_m3_per_ha: 'm³/ha',
  };
  const unit = unitMap[key] || '';
  const formatted = typeof value === 'number' ? value.toLocaleString() : String(value);
  return `${formatted} ${unit}`.trim();
}
