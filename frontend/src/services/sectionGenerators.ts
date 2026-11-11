/**
 * sectionGenerators — OP section content generators.
 *
 * Generates formatted Nepali/English text, tables, and chart data for
 * each section of the Operational Plan document. Reads classified data
 * (slope, aspect, canopy, health, etc.) and produces section narratives.
 */
import {
  SLOPE_CLASS_NP, SLOPE_COLORS,
  ASPECT_CLASS_NP, ASPECT_COLORS,
  HEALTH_CLASS_NP, HEALTH_COLORS,
  CANOPY_CLASS_NP, CANOPY_COLORS,
  LANDCOVER_CLASS_NP, LANDCOVER_COLORS,
  SOIL_TEXTURE_NP, SOIL_PH_NP, FERTILITY_NP, COMPACTION_NP,
  SPECIES_ROLE_NP, SPECIES_ROLE_COLORS, SPECIES_GROWTH_NP,
  IUCN_STATUS_NP, IUCN_STATUS_COLORS, BIODIVERSITY_SUB_CATEGORY_NP,
  FOREST_QUALITY_NP, FOREST_QUALITY_COLORS,
  toNepaliDigit,
} from '../constants/nepaliLabels';

export interface LegendItem {
  color: string;
  labelNp: string;
  labelEn: string;
  value?: number;
  range?: string;
}

export interface GraphicData {
  type: 'pie' | 'bar' | 'horizontal_bar' | 'stacked_bar' | 'none';
  data: { label: string; value: number; color: string }[];
}

export interface SectionContent {
  titleNp: string;
  titleEn: string;
  narrative: string;
  graphics: GraphicData;
  legend: LegendItem[];
  variables: string[];
  source: string;
}

export interface SectionGenerator {
  generatorFn: (data: any, extra?: Record<string, any>) => SectionContent | null;
  variables: string[];
}

function fmt(val: number | undefined | null, decimals = 2): string {
  if (val === undefined || val === null) return '—';
  return toNepaliDigit(val, decimals);
}

function pct(val: number | undefined | null): string {
  if (val === undefined || val === null) return '—';
  return toNepaliDigit(val, 1);
}

// ─── 1. Forest Summary ──────────────────────────────────────────
export function generateForestSummary(data: any): SectionContent {
  const area = fmt(data.area_hectares, 2);
  const blocks = data.total_blocks || data.blocks_count || 0;
  const elevation = fmt(data.elevation_mean_m, 0);
  const carbon = data.carbon_stock_mg?.toLocaleString() || '—';
  const health = HEALTH_CLASS_NP[data.forest_health_dominant] || data.forest_health_dominant || '—';

  const narrative = `यस वनको कुल क्षेत्रफल ${area} हेक्टर रहेको छ। यस वनमा ${blocks} वटा वन खण्डहरू रहेका छन्। वनको औसत उचाइ ${elevation} मिटर रहेको छ। कुल कार्बन भण्डार ${carbon} मेगाग्राम रहेको छ। वन स्वास्थ्य "${health}" अवस्थामा रहेको छ।`;

  const legend: LegendItem[] = [
    { color: '#059669', labelNp: 'रूख आवरण', labelEn: 'Tree Cover' },
    { color: '#eab308', labelNp: 'अन्य आवरण', labelEn: 'Other Cover' },
    { color: '#f97316', labelNp: 'संरक्षित', labelEn: 'Protected' },
    { color: '#ef4444', labelNp: 'निजि जग्गा', labelEn: 'Private Land' },
    { color: '#6b7280', labelNp: 'बहिष्कृत', labelEn: 'Excluded' },
  ];

  return {
    titleNp: 'वन सारांश',
    titleEn: 'Forest Summary',
    narrative,
    graphics: { type: 'none', data: [] },
    legend,
    variables: ['area_hectares', 'blocks_count', 'elevation_mean_m', 'carbon_stock_mg', 'forest_health_dominant'],
    source: 'calculation',
  };
}

// ─── 2. Slope Analysis ──────────────────────────────────────────
export function generateSlopeAnalysis(data: any): SectionContent {
  const dominant = SLOPE_CLASS_NP[data.slope_dominant_class] || data.slope_dominant_class || '—';
  const percentages = data.slope_percentages || {};
  const dominantPct = pct(percentages[data.slope_dominant_class]);

  const narrative = `यस वनको प्रमुख भिरालो "${dominant}" वर्ग रहेको छ, जसले कुल क्षेत्रफलको ${dominantPct}% ओगटेको छ। भिरालोको आधारमा जमिनलाई पाँच वर्गमा बाँडिएको छ: समतल (Flat), हल्का (Gentle), मध्यम (Moderate), भिरालो (Steep), र अति भिरालो (Very Steep)। हल्का भिरालो जमिनमा सजिलै नमुना प्लट राख्न सकिन्छ भने भिरालो र अति भिरालो जमिनमा नमुना सङ्कलन गर्न कठिनाई हुन्छ।`;

  const chartData = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    label: SLOPE_CLASS_NP[key] || key,
    value: val,
    color: SLOPE_COLORS[key] || '#888',
  }));

  const legend: LegendItem[] = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    color: SLOPE_COLORS[key] || '#888',
    labelNp: SLOPE_CLASS_NP[key] || key,
    labelEn: key,
    value: val,
  }));

  return {
    titleNp: 'भिरालो विश्लेषण',
    titleEn: 'Slope Analysis',
    narrative,
    graphics: { type: 'horizontal_bar', data: chartData },
    legend,
    variables: ['slope_dominant_class', 'slope_percentages'],
    source: 'raster',
  };
}

// ─── 3. Elevation Profile ───────────────────────────────────────
export function generateElevationProfile(data: any): SectionContent {
  const mean = fmt(data.elevation_mean_m, 0);
  const min = fmt(data.elevation_min_m, 0);
  const max = fmt(data.elevation_max_m, 0);
  const range = data.elevation_max_m && data.elevation_min_m
    ? fmt(data.elevation_max_m - data.elevation_min_m, 0) : '—';

  const narrative = `यस वनको औसत उचाइ ${mean} मिटर रहेको छ। न्यूनतम उचाइ ${min} मिटर र अधिकतम उचाइ ${max} मिटर रहेको छ। उचाइको फरक ${range} मिटर रहेको छ, जसले यस वनमा विविध वनस्पति तथा वातावरणीय अवस्था रहेको संकेत गर्दछ।`;

  return {
    titleNp: 'उचाइ विवरण',
    titleEn: 'Elevation Profile',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['elevation_min_m', 'elevation_max_m', 'elevation_mean_m'],
    source: 'raster',
  };
}

// ─── 4. Aspect Analysis ─────────────────────────────────────────
export function generateAspectAnalysis(data: any): SectionContent {
  const dominant = ASPECT_CLASS_NP[data.aspect_dominant] || data.aspect_dominant || '—';
  const percentages = data.aspect_percentages || {};

  const narrative = `यस वनको प्रमुख दिशा "${dominant}" रहेको छ। दिशा (Aspect) ले भिरालो कुन दिशातिर फर्केको छ भन्ने देखाउँदछ। दक्षिणतर्फ फर्केको भिरालोमा घाम बढी लाग्छ भने उत्तरतर्फ फर्केको भिरालोमा चिसो हुन्छ।`;

  const chartData = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    label: ASPECT_CLASS_NP[key] || key.toUpperCase(),
    value: val,
    color: ASPECT_COLORS[key] || '#888',
  }));

  const legend: LegendItem[] = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    color: ASPECT_COLORS[key] || '#888',
    labelNp: ASPECT_CLASS_NP[key] || key.toUpperCase(),
    labelEn: key,
    value: val,
  }));

  return {
    titleNp: 'दिशा विश्लेषण',
    titleEn: 'Aspect Analysis',
    narrative,
    graphics: { type: 'horizontal_bar', data: chartData },
    legend,
    variables: ['aspect_dominant', 'aspect_percentages'],
    source: 'raster',
  };
}

// ─── 5. Forest Health ───────────────────────────────────────────
export function generateForestHealth(data: any): SectionContent {
  const dominant = HEALTH_CLASS_NP[data.forest_health_dominant] || data.forest_health_dominant || '—';
  const percentages = data.forest_health_percentages || {};
  const dominantPct = pct(percentages[data.forest_health_dominant]);

  const narrative = `यस वनको समग्र स्वास्थ्य अवस्था "${dominant}" रहेको छ, जसले कुल क्षेत्रफलको ${dominantPct}% ओगटेको छ। वन स्वास्थ्यलाई NDVI (Normalized Difference Vegetation Index) को आधारमा पाँच वर्गमा विभाजन गरिएको छ:

• 🔴 तनावग्रस्त (Stressed) — अत्यन्त कमजोर, NDVI < 0.2
• 🟠 कमजोर (Poor) — कम हरियोपन, NDVI 0.2-0.4
• 🟡 मध्यम (Moderate) — सामान्य अवस्था, NDVI 0.4-0.6
• 🟢 स्वस्थ (Healthy) — राम्रो अवस्था, NDVI 0.6-0.8
• 🌿 उत्कृष्ट (Excellent) — अत्यन्त स्वस्थ, NDVI > 0.8`;

  const chartData = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    label: HEALTH_CLASS_NP[key] || key,
    value: val,
    color: HEALTH_COLORS[key] || '#888',
  }));

  const legend: LegendItem[] = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    color: HEALTH_COLORS[key] || '#888',
    labelNp: HEALTH_CLASS_NP[key] || key,
    labelEn: key,
    value: val,
  }));

  return {
    titleNp: 'वन स्वास्थ्य',
    titleEn: 'Forest Health',
    narrative,
    graphics: { type: 'pie', data: chartData },
    legend,
    variables: ['forest_health_dominant', 'forest_health_percentages'],
    source: 'raster',
  };
}

// ─── 6. Forest Type ─────────────────────────────────────────────
export function generateForestType(data: any): SectionContent {
  const dominant = data.forest_type_dominant || '—';
  const percentages = data.forest_type_percentages || {};

  const narrative = `यस वनको प्रमुख वन प्रकार "${dominant}" रहेको छ। नेपालको FRTC (Forest Resource and Training Centre) वर्गीकरण प्रणाली अनुसार यस वनमा विभिन्न प्रकारका वनहरू पाइन्छन्।`;

  const chartData = Object.entries(percentages).map(([key, val]: [string, any], i: number) => {
    const colors = ['#059669', '#10b981', '#34d399', '#6ee7b7', '#a7f3d0', '#047857', '#065f46', '#064e3b'];
    return { label: key, value: val, color: colors[i % colors.length] };
  });

  const legend: LegendItem[] = Object.entries(percentages).map(([key, val]: [string, any], i: number) => {
    const colors = ['#059669', '#10b981', '#34d399', '#6ee7b7', '#a7f3d0', '#047857', '#065f46', '#064e3b'];
    return { color: colors[i % colors.length], labelNp: key, labelEn: key, value: val };
  });

  return {
    titleNp: 'वन प्रकार',
    titleEn: 'Forest Type',
    narrative,
    graphics: { type: 'bar', data: chartData },
    legend,
    variables: ['forest_type_dominant', 'forest_type_percentages'],
    source: 'raster',
  };
}

// ─── 7. Potential Species (from forest type associations) ────────
export function generatePotentialSpecies(data: any): SectionContent | null {
  const species = data.potential_species;
  if (!species || !Array.isArray(species) || species.length === 0) return null;

  const total = species.length;

  const roleCounts: Record<string, number> = {};
  const forestTypeCounts: Record<string, number> = {};
  const byRole: Record<string, string[]> = {};
  const byForestType: Record<string, string[]> = {};

  species.forEach((s: any) => {
    const role = s.role || 'Associate';
    const name = s.local_name || s.scientific_name;
    roleCounts[role] = (roleCounts[role] || 0) + 1;
    if (!byRole[role]) byRole[role] = [];
    byRole[role].push(name);

    if (s.forest_types && Array.isArray(s.forest_types)) {
      s.forest_types.forEach((ft: string) => {
        forestTypeCounts[ft] = (forestTypeCounts[ft] || 0) + 1;
        if (!byForestType[ft]) byForestType[ft] = [];
        if (!byForestType[ft].includes(name)) byForestType[ft].push(name);
      });
    }
  });

  const ftEntries = Object.entries(forestTypeCounts).sort(([, a], [, b]) => b - a);

  const ftSummary = ftEntries
    .map(([ft, c]) => `• ${ft}: ${c} प्रजातिहरू`)
    .join('\n');

  const roleOrder = ['Dominant', 'Co-dominant', 'Associate', 'Occasional', 'Rare'];
  const roleLabels: Record<string, string> = {
    Dominant: 'प्रमुख प्रजाती',
    'Co-dominant': 'सह-प्रमुख प्रजाती',
    Associate: 'सहयोगी प्रजाती',
    Occasional: 'विरलै हुने प्रजाती',
    Rare: 'दुर्लभ प्रजाती',
  };

  const roleSpeciesList = roleOrder
    .filter(r => byRole[r] && byRole[r].length > 0)
    .map(r => `• ${roleLabels[r]}: ${byRole[r].join(', ')}`)
    .join('\n');

  const narrative = `यस वनको वन प्रकार अनुसार जम्मा ${fmt(total, 0)} प्रजातिका रूखहरू सम्भावित रूपमा पाउन सकिन्छ। यस क्षेत्रमा वृक्षारोपण गर्न सकिने प्रजाती छनोट गर्दा यि प्रजातीलाइ प्राथमिकता दिन सकिन्छ।\n\nवन प्रकार अनुसार:\n${ftSummary}\n\nभूमिका अनुसार प्रजातिहरू:\n${roleSpeciesList}`;

  return {
    titleNp: 'सम्भावित प्रजातिहरू',
    titleEn: 'Potential Species',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['potential_species', 'species_count'],
    source: 'species',
  };
}

// ─── 8. Actual Species (from field inventory) ────────────────────
export function generateActualSpecies(data: any, extra?: Record<string, any>): SectionContent | null {
  const breakdown = extra?.fieldInventoryBreakdown;
  if (!breakdown || !Array.isArray(breakdown) || breakdown.length === 0) return null;

  // Aggregate counts per species per stand type (raw counts from plots, not per-ha)
  const perSpecies: Record<string, {
    local: string;
    saplingCount: number;
    poleCount: number;
    treeCount: number;
  }> = {};

  breakdown.forEach((row: any) => {
    const key = row.species_scientific;
    const local = row.species_local || key;

    if (!perSpecies[key]) {
      perSpecies[key] = { local, saplingCount: 0, poleCount: 0, treeCount: 0 };
    }
    const s = perSpecies[key];
    // Use per_ha values as proportional counts (they share the same per-ha scaling within each stand type)
    s.saplingCount += row.sapling_per_ha || 0;
    s.poleCount += row.pole_per_ha || 0;
    s.treeCount += row.tree_per_ha || 0;
  });

  // Separate by stand type, compute within-stand-type percentages
  type SpeciesEntry = { local: string; count: number; pct: number };
  const byStandType: Record<string, SpeciesEntry[]> = { sapling: [], pole: [], tree: [] };
  let totalOverallCount = 0;

  Object.entries(perSpecies).forEach(([, s]) => {
    totalOverallCount += s.saplingCount + s.poleCount + s.treeCount;
    if (s.saplingCount > 0) byStandType.sapling.push({ local: s.local, count: s.saplingCount, pct: 0 });
    if (s.poleCount > 0) byStandType.pole.push({ local: s.local, count: s.poleCount, pct: 0 });
    if (s.treeCount > 0) byStandType.tree.push({ local: s.local, count: s.treeCount, pct: 0 });
  });

  // Compute within-stand-type percentages
  ['sapling', 'pole', 'tree'].forEach((st) => {
    const entries = byStandType[st];
    const total = entries.reduce((s, e) => s + e.count, 0);
    if (total > 0) {
      entries.forEach(e => e.pct = Math.round((e.count / total) * 1000) / 10);
    }
    entries.sort((a, b) => b.count - a.count);
  });

  const totalSpecies = Object.keys(perSpecies).length;

  // Build narrative with per-stand-type composition
  const fmtPct = (v: number) => toNepaliDigit(v, 1);
  const narrativeParts: string[] = [
    `यस वनको स्थलगत सर्वेक्षणबाट जम्मा ${fmt(totalSpecies, 0)} प्रजातिका रूखहरू फेला परेका छन्।`,
  ];

  if (byStandType.sapling.length > 0) {
    const list = byStandType.sapling.map(s => `• ${s.local}: ${fmtPct(s.pct)}%`).join('\n');
    narrativeParts.push(`\nस्याप्लिङमा प्रजातिहरूको अनुपात:\n${list}`);
  }
  if (byStandType.pole.length > 0) {
    const list = byStandType.pole.map(s => `• ${s.local}: ${fmtPct(s.pct)}%`).join('\n');
    narrativeParts.push(`\nपोलमा प्रजातिहरूको अनुपात:\n${list}`);
  }
  if (byStandType.tree.length > 0) {
    const list = byStandType.tree.map(s => `• ${s.local}: ${fmtPct(s.pct)}%`).join('\n');
    narrativeParts.push(`\nरूखमा प्रजातिहरूको अनुपात:\n${list}`);
  }

  // Chart: pie chart of overall species composition by total count
  const allEntries = Object.values(perSpecies)
    .map(s => ({ local: s.local, count: s.saplingCount + s.poleCount + s.treeCount }))
    .filter(s => s.count > 0)
    .sort((a, b) => b.count - a.count);

  const chartColors = ['#059669', '#0d9488', '#0284c7', '#7c3aed', '#db2777', '#dc2626', '#ea580c', '#d97706', '#65a30d', '#14b8a6', '#6366f1', '#ec4899'];
  const chartData = allEntries.map((s, i) => ({
    label: s.local,
    value: Math.round(s.count * 100) / 100,
    color: chartColors[i % chartColors.length],
  }));

  const legend = allEntries.map((s, i) => ({
    color: chartColors[i % chartColors.length],
    labelNp: s.local,
    labelEn: '',
    value: s.count,
  }));

  return {
    titleNp: 'वन श्रोत बाट देखिएका काठ जातका प्रजातिहरू',
    titleEn: 'Actual Species (Field Inventory)',
    narrative: narrativeParts.join(''),
    graphics: { type: 'pie', data: chartData },
    legend,
    variables: [],
    source: 'field_inventory',
  };
}

// ─── 9. Biodiversity ─────────────────────────────────────────────
export function generateBiodiversity(data: any, extra?: Record<string, any>): SectionContent | null {
  const bioData = extra?.biodiversityData;
  if (!bioData || !bioData.species || !Array.isArray(bioData.species) || bioData.species.length === 0) return null;

  const species = bioData.species;

  // Group by sub_category
  const subCatCounts: Record<string, number> = {};
  const subCatSpecies: Record<string, { np: string; en: string; scientific: string; iucn: string }[]> = {};

  // Group by IUCN status
  const iucnCounts: Record<string, number> = {};

  // Separate vegetation vs animal
  let vegCount = 0;
  let animalCount = 0;

  species.forEach((rec: any) => {
    const s = rec.species;
    if (!s) return;
    const cat = s.sub_category || 'other';
    const nameNp = s.nepali_name || s.english_name || '—';

    subCatCounts[cat] = (subCatCounts[cat] || 0) + 1;
    if (!subCatSpecies[cat]) subCatSpecies[cat] = [];
    subCatSpecies[cat].push({ np: nameNp, en: s.english_name || '', scientific: s.scientific_name || '', iucn: s.iucn_status || '' });

    const iucn = s.iucn_status || 'DD';
    iucnCounts[iucn] = (iucnCounts[iucn] || 0) + 1;

    if (s.category === 'vegetation') vegCount++;
    else animalCount++;
  });

  const totalSpecies = species.length;

  // Separate species lists for vegetation and animal
  const vegSpecies: { np: string; en: string; subCat: string; iucn: string }[] = [];
  const animalSpecies: { np: string; en: string; subCat: string; iucn: string }[] = [];

  species.forEach((rec: any) => {
    const s = rec.species;
    if (!s) return;
    const entry = {
      np: s.nepali_name || s.english_name || '—',
      en: s.english_name || '',
      subCat: BIODIVERSITY_SUB_CATEGORY_NP[s.sub_category] || s.sub_category || 'अन्य',
      iucn: IUCN_STATUS_NP[s.iucn_status] || s.iucn_status || '—',
    };
    if (s.category === 'vegetation') vegSpecies.push(entry);
    else animalSpecies.push(entry);
  });

  // Build narrative
  const catEntries = Object.entries(subCatCounts).sort(([, a], [, b]) => b - a);
  const catList = catEntries
    .map(([cat, count]) => `• ${BIODIVERSITY_SUB_CATEGORY_NP[cat] || cat}: ${fmt(count, 0)}`)
    .join('\n');

  const iucnOrder = ['CR', 'EN', 'VU', 'NT', 'LC', 'DD'];
  const iucnList = iucnOrder
    .filter(ic => iucnCounts[ic])
    .map(ic => `• ${IUCN_STATUS_NP[ic] || ic}: ${fmt(iucnCounts[ic], 0)}`)
    .join('\n');

  const vegSpeciesList = vegSpecies
    .map(s => `• ${s.np} (${s.subCat}, ${s.iucn})`)
    .join('\n');

  const animalSpeciesList = animalSpecies
    .map(s => `• ${s.np} (${s.subCat}, ${s.iucn})`)
    .join('\n');

  const narrativeParts: string[] = [
    `यस वनको जैविक विविधता अन्तर्गत जम्मा ${fmt(totalSpecies, 0)} प्रजातिहरू पाइन्छन्। वनस्पति प्रजाति ${fmt(vegCount, 0)} र जनावर प्रजाति ${fmt(animalCount, 0)} रहेका छन्।`,
    `\n\nप्रकार अनुसार:\n${catList}`,
    `\n\nसंरक्षण स्थिति अनुसार:\n${iucnList}`,
  ];

  if (vegSpecies.length > 0) {
    narrativeParts.push(`\n\nवनस्पति प्रजातिहरू:\n${vegSpeciesList}`);
  }
  if (animalSpecies.length > 0) {
    narrativeParts.push(`\n\nजनावर प्रजातिहरू:\n${animalSpeciesList}`);
  }

  const narrative = narrativeParts.join('');

  // Chart: pie chart of sub-category distribution
  const chartColors = ['#059669', '#10b981', '#34d399', '#6ee7b7', '#0d9488', '#0284c7', '#6366f1', '#7c3aed', '#db2777', '#dc2626', '#ea580c', '#d97706', '#ca8a04', '#65a30d'];
  const chartData = catEntries.map(([cat, count], i) => ({
    label: BIODIVERSITY_SUB_CATEGORY_NP[cat] || cat,
    value: count,
    color: chartColors[i % chartColors.length],
  }));

  const legend = catEntries.map(([cat, count], i) => ({
    color: chartColors[i % chartColors.length],
    labelNp: BIODIVERSITY_SUB_CATEGORY_NP[cat] || cat,
    labelEn: `${count} species`,
    value: count,
  }));

  return {
    titleNp: 'जैविक विविधता',
    titleEn: 'Biodiversity',
    narrative,
    graphics: { type: 'pie', data: chartData },
    legend,
    variables: ['bio_total_species', 'bio_vegetation_count', 'bio_animal_count'],
    source: 'biodiversity',
  };
}

const CANOPY_ORDER = ['non_forest', 'regeneration', 'pole_trees', 'tree'];

// ─── 7. Canopy Structure ────────────────────────────────────────
export function generateCanopyStructure(data: any): SectionContent {
  const dominant = CANOPY_CLASS_NP[data.canopy_dominant_class] || data.canopy_dominant_class || '—';
  const height = fmt(data.canopy_mean_m, 1);
  const percentages = data.canopy_percentages || {};

  const narrative = `यस वनको प्रमुख वन छत्र वर्ग "${dominant}" रहेको छ। वन छत्रको औसत उचाइ ${height} मिटर रहेको छ। वन छत्रले वनको संरचना र रूखको घनत्व देखाउँदछ।`;

  const entries = CANOPY_ORDER
    .filter(k => k in percentages)
    .map(key => ({
      key,
      label: CANOPY_CLASS_NP[key] || key.replace('_', ' '),
      value: percentages[key],
      color: CANOPY_COLORS[key] || '#888',
    }));

  const chartData = entries.map(({ key, label, value, color }) => ({ label, value, color }));

  const legend: LegendItem[] = entries.map(({ key, label, value, color }) => ({
    color,
    labelNp: label,
    labelEn: key,
    value,
  }));

  return {
    titleNp: 'वन छत्र',
    titleEn: 'Canopy Structure',
    narrative,
    graphics: { type: 'horizontal_bar', data: chartData },
    legend,
    variables: ['canopy_dominant_class', 'canopy_percentages', 'canopy_mean_m'],
    source: 'raster',
  };
}

// ─── 8. Biomass & Carbon ────────────────────────────────────────
export function generateBiomassCarbon(data: any): SectionContent {
  const agbTotal = data.agb_total_mg?.toLocaleString() || data.agb_total?.toLocaleString() || '—';
  const agbMean = fmt(data.agb_mean_mg_ha ?? data.agb_mean, 1);
  const carbon = data.carbon_stock_mg?.toLocaleString() || data.carbon_stock?.toLocaleString() || '—';

  const narrative = `यस वनको कुल वायवीय जैविक पदार्थ (Above Ground Biomass) ${agbTotal} मेगाग्राम रहेको छ। प्रतिहेक्टर औसत ${agbMean} मेगाग्राम रहेको छ। कुल कार्बन भण्डार (AGB को ५०%) ${carbon} मेगाग्राम रहेको छ। कार्बन भण्डारले वनले वातावरणमा रहेको कार्बनलाई कति मात्रामा सोसेर राखेको छ भन्ने देखाउँदछ।`;

  return {
    titleNp: 'वायवीय जैविक पदार्थ तथा कार्बन',
    titleEn: 'Biomass & Carbon',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['agb_mean', 'agb_total', 'carbon_stock'],
    source: 'raster',
  };
}

// ─── 9. Climate Conditions ──────────────────────────────────────
export function generateClimateConditions(data: any): SectionContent {
  const temp = fmt(data.temperature_mean_c, 1);
  const precip = fmt(data.precipitation_mean_mm, 0);

  const narrative = `यस वनको वार्षिक औसत तापक्रम ${temp}°C रहेको छ। वार्षिक औसत वर्षा ${precip} मिलिमिटर रहेको छ। यी मौसमी अवस्थाहरूले यस वनको वनस्पति, माटो र समग्र पारिस्थितिकी प्रणालीलाई प्रभाव पार्दछन्।`;

  return {
    titleNp: 'मौसम अवस्था',
    titleEn: 'Climate Conditions',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['temperature_mean_c', 'precipitation_mean_mm'],
    source: 'raster',
  };
}

// ─── 10. Land Cover ─────────────────────────────────────────────
export function generateLandCover(data: any): SectionContent {
  const dominant = LANDCOVER_CLASS_NP[data.landcover_dominant] || data.landcover_dominant || '—';
  const percentages = data.landcover_percentages || {};

  const narrative = `यस वनको प्रमुख भू-आवरण "${dominant}" रहेको छ। भू-आवरणले जमिनको प्रयोग र प्राकृतिक अवस्था देखाउँदछ। यस वनमा रूख आवरण (Tree Cover), झाडी (Shrubland), घाँसे मैदान (Grassland), खेती योग्य (Cropland), बस्ती (Built-up), पानी (Water) लगायत विभिन्न प्रकारका भू-आवरणहरू पाइन्छन्।`;

  const chartData = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    label: LANDCOVER_CLASS_NP[key] || key,
    value: val,
    color: LANDCOVER_COLORS[key] || '#888',
  }));

  const legend: LegendItem[] = Object.entries(percentages).map(([key, val]: [string, any]) => ({
    color: LANDCOVER_COLORS[key] || '#888',
    labelNp: LANDCOVER_CLASS_NP[key] || key,
    labelEn: key,
    value: val,
  }));

  return {
    titleNp: 'भू-आवरण',
    titleEn: 'Land Cover',
    narrative,
    graphics: { type: 'pie', data: chartData },
    legend,
    variables: ['landcover_dominant', 'landcover_percentages'],
    source: 'raster',
  };
}

// ─── 11. Forest Loss ────────────────────────────────────────────
export function generateForestLoss(data: any): SectionContent {
  const total = fmt(data.forest_loss_hectares, 2);
  const area = data.area_hectares;
  const pctVal = area ? ((data.forest_loss_hectares / area) * 100).toFixed(1) : '—';
  const byYear = data.forest_loss_by_year || {};

  const narrative = `सन् २००१ देखि २०२४ सम्म यस वनको कुल ${total} हेक्टर (${pctVal}%) क्षेत्रमा वन क्षति भएको छ। यो जानकारी Hansen Global Forest Change डाटाबाट प्राप्त गरिएको हो। वन क्षति मुख्यतया मानवीय क्रियाकलाप, आगलागी र प्राकृतिक कारणले हुने गर्दछ।`;

  const yearEntries = Object.entries(byYear)
    .filter(([, val]: [string, any]) => val > 0)
    .sort(([a], [b]) => parseInt(a) - parseInt(b));

  const chartData = yearEntries.map(([year, val]: [string, any]) => ({
    label: year,
    value: val,
    color: val > 1 ? '#ef4444' : '#f97316',
  }));

  const legend: LegendItem[] = [
    { color: '#FFD700', labelNp: '२००१-२००८', labelEn: 'Early Loss', range: 'पुरानो क्षति' },
    { color: '#FF8C00', labelNp: '२००९-२०१६', labelEn: 'Mid Loss', range: 'मध्यम अवधि' },
    { color: '#DC143C', labelNp: '२०१७-२०२४', labelEn: 'Recent Loss', range: 'भर्खरको क्षति' },
  ];

  return {
    titleNp: 'वन क्षति',
    titleEn: 'Forest Loss',
    narrative,
    graphics: { type: 'bar', data: chartData },
    legend,
    variables: ['forest_loss_hectares', 'forest_loss_by_year'],
    source: 'raster',
  };
}

// ─── 12. Fire Loss ──────────────────────────────────────────────
export function generateFireLoss(data: any): SectionContent {
  const total = fmt(data.fire_loss_hectares, 2);
  const area = data.area_hectares;
  const pctVal = area ? ((data.fire_loss_hectares / area) * 100).toFixed(1) : '—';

  const narrative = `सन् २००१ देखि २०२४ सम्म यस वनको कुल ${total} हेक्टर (${pctVal}%) क्षेत्र आगलागीबाट क्षतिग्रस्त भएको छ। आगलागी वनको लागि प्रमुख जोखिम हो, जसले वनस्पति, वन्यजन्तु र माटोको गुणस्तरमा गम्भीर असर पार्दछ।`;

  const byYear = data.fire_loss_by_year || {};
  const yearEntries = Object.entries(byYear)
    .filter(([, val]: [string, any]) => val > 0)
    .sort(([a], [b]) => parseInt(a) - parseInt(b));

  const chartData = yearEntries.map(([year, val]: [string, any]) => ({
    label: year,
    value: val,
    color: val > 1 ? '#dc2626' : '#f97316',
  }));

  const legend: LegendItem[] = [
    { color: '#FF8C00', labelNp: '२००१-२००८', labelEn: 'Old Burns', range: 'पुरानो आगलागी' },
    { color: '#FF4500', labelNp: '२००९-२०१६', labelEn: 'Mid Burns', range: 'मध्यम अवधि' },
    { color: '#8B0000', labelNp: '२०१७-२०२४', labelEn: 'Recent Burns', range: 'भर्खरको आगलागी' },
  ];

  return {
    titleNp: 'आगलागी क्षति',
    titleEn: 'Fire Loss',
    narrative,
    graphics: { type: 'bar', data: chartData },
    legend,
    variables: ['fire_loss_hectares', 'fire_loss_by_year'],
    source: 'raster',
  };
}

// ─── 13. Forest Quality (NASA 2020) ────────────────────────────
export function generateForestQuality(data: any): SectionContent | null {
  const pct = data.whole_nasa_forest_2020_percentages || data.nasa_forest_2020_percentages || null;
  const dominant = data.whole_nasa_forest_2020_dominant || data.nasa_forest_2020_dominant || null;
  if (!pct || Object.keys(pct).length === 0) return null;

  const entries = Object.entries(pct)
    .filter(([, v]: [string, any]) => v > 0)
    .sort(([, a]: [string, any], [, b]: [string, any]) => b - a);

  const dominantNp = dominant ? (FOREST_QUALITY_NP[dominant] || dominant) : '—';
  const primaryPct = pct['Primary Forest'] ?? 0;
  const oldSecPct = pct['Old Secondary Forest'] ?? 0;
  const youngSecPct = pct['Young Secondary Forest'] ?? 0;
  const primaryArea = data.area_hectares ? (data.area_hectares * primaryPct / 100) : null;

  const parts = entries.map(([key, val]: [string, any]) => {
    const np = FOREST_QUALITY_NP[key] || key;
    const desc =
      key.toLowerCase().includes('primary') ? 'पुरानो वन, सर्वाधिक कार्बन' :
      key.toLowerCase().includes('young') ? 'पुनरुत्थान हुँदै गरेको, कम कार्बन' :
      key.toLowerCase().includes('old') ? 'परिपक्क दोस्रो पुस्ताको वन, मध्यम कार्बन' : '';
    return { np, pct: val, desc };
  });

  const breakdown = parts.map(p => `${p.np} ${fmt(p.pct, 1)}% (${p.desc})`).join(', ');

  const areaNote = primaryArea
    ? `यस वनको करिब ${fmt(primaryArea, 2)} हेक्टर क्षेत्र प्राथमिक वनले ढाकेको छ, जुन कार्बन भण्डारणको दृष्टिले अत्यन्त महत्वपूर्ण छ।`
    : '';

  const narrative = `यस वनको प्रमुख वन गुणस्तर "${dominantNp}" रहेको छ। वन गुणस्तर वितरण यस प्रकार रहेको छ: ${breakdown}।

प्राथमिक वन (Primary Forest) पुरानो तथा अत्यधिक कार्बन भण्डार भएको वन हो। प्राथमिक वनले दोस्रो पुस्ताको वनको तुलनामा २ देखि ३ गुणा बढी कार्बन भण्डारण गर्न सक्दछ। पुरानो दोस्रो पुस्ताको वन (Old Secondary Forest) मा समेत मध्यम मात्रामा कार्बन रहेको हुन्छ भने कम उमेरको वन (Young Secondary Forest) पुनरुत्थान हुँदै गरेको अवस्थामा रहेको हुन्छ।

वन उपभोक्ता समूहहरूले वन संरक्षण गर्नुको प्रमुख कारण यसले प्रदान गर्ने पारिस्थितिक सेवा हो — कार्बन भण्डारण, जलवायु नियमन, जैविक विविधता संरक्षण, माटो संरक्षण, तथा स्थानीय जीविकोपार्जन। प्राथमिक वनको उपस्थितिले वन उपभोक्ता समूहलाई REDD+ कार्यक्रम तथा कार्बन व्यापारमा सहभागी हुन अतिरिक्त आर्थिक लाभको सम्भावना प्रदान गर्दछ। ${areaNote} यो तथ्यांक नासा (NASA/ORNL DAAC) ३० मिटर रिजोलुसनको २०२० सालको उपग्रह तथ्यांकमा आधारित छ।`;

  const chartData = entries.map(([key, val]: [string, any]) => ({
    label: FOREST_QUALITY_NP[key] || key,
    value: val,
    color: FOREST_QUALITY_COLORS[key] || '#999999',
  }));

  return {
    titleNp: 'वन गुणस्तर (नासा २०२०)',
    titleEn: 'Forest Quality (NASA 2020)',
    narrative,
    graphics: { type: 'pie', data: chartData },
    legend: [],
    variables: ['whole_nasa_forest_2020_percentages', 'whole_nasa_forest_2020_dominant'],
    source: 'raster',
  };
}

// ─── 14. Soil Analysis ──────────────────────────────────────────
export function generateSoilAnalysis(data: any): SectionContent | null {
  const texture = data.soil_texture || null;
  if (!texture) return null;

  const props = data.soil_properties || {};
  const interp = data.interpretations || {};
  const texInterp = interp.texture_interpretation || {};
  const phInterp = interp.ph_interpretation || {};
  const nInterp = interp.nitrogen_interpretation || {};
  const cInterp = interp.carbon_interpretation || {};

  const textureNp = SOIL_TEXTURE_NP[texture.toLowerCase()] || texture;
  const phVal = typeof props.ph_h2o === 'number' ? fmt(props.ph_h2o, 1) : phInterp.value ? fmt(phInterp.value, 1) : '—';
  const phCat = phInterp.category || '—';
  const fertility = FERTILITY_NP[data.fertility_class?.toLowerCase()] || data.fertility_class || '—';
  const fertScore = data.fertility_score ?? '—';
  const compaction = COMPACTION_NP[data.compaction_status?.toLowerCase().replace(/\s+/g, '_')] || data.compaction_status || '—';
  const carbonStock = typeof data.carbon_stock_t_ha === 'number' ? fmt(data.carbon_stock_t_ha, 1) : '—';
  const nitrogen = typeof props.nitrogen_cg_kg === 'number' ? fmt(props.nitrogen_cg_kg, 1) : '—';
  const cec = typeof props.cec_mmol_kg === 'number' ? fmt(props.cec_mmol_kg, 0) : '—';
  const bd = typeof props.bulk_density_cg_cm3 === 'number' ? fmt(props.bulk_density_cg_cm3, 0) : '—';

  const clayPct = props.clay_pct ?? 0;
  const sandPct = props.sand_pct ?? 0;
  const siltPct = props.silt_pct ?? 0;

  const narrative = `यस वनको माटोको बनावट "${textureNp}" रहेको छ। माटोको भौतिक संरचनामा माटोको कण (Clay) ${clayPct.toFixed(1)}%, बालुवा (Sand) ${sandPct.toFixed(1)}%, र ग्राबेल (Silt) ${siltPct.toFixed(1)}% रहेको छ। माटोको pH मान ${phVal} रहेको छ, जुन "${phCat}" कोटीमा पर्दछ। माटोको उर्वराशक्ति "${fertility}" (${fertScore}/100) रहेको छ। माटो जमावको अवस्था "${compaction}" रहेको छ। माटोको जैविक कार्बन भण्डार ${carbonStock} t/ha रहेको छ। माटोको नाइट्रोजन मात्रा ${nitrogen} cg/kg र क्याटायन आदानप्रदान क्षमता (CEC) ${cec} mmol/kg रहेको छ। माटोको गुणस्तरले वनको वृद्धि र स्वास्थ्यमा प्रत्यक्ष प्रभाव पार्दछ।`;

  const chartData = [
    { label: 'माटोको कण (Clay)', value: clayPct, color: '#8B4513' },
    { label: 'ग्राबेल (Silt)', value: siltPct, color: '#C4A882' },
    { label: 'बालुवा (Sand)', value: sandPct, color: '#D2B48C' },
  ];

  return {
    titleNp: 'माटो विश्लेषण',
    titleEn: 'Soil Analysis',
    narrative,
    graphics: { type: 'horizontal_bar', data: chartData },
    legend: [],
    variables: ['soil_texture', 'soil_properties', 'fertility_class', 'carbon_stock_t_ha', 'compaction_status'],
    source: 'raster',
  };
}

// ─── 14. Location & Context ─────────────────────────────────────
export function generateLocationContext(data: any): SectionContent {
  const province = data.whole_province || data.province || '—';
  const district = data.whole_district || data.district || '—';
  const municipality = data.whole_municipality || data.municipality || '—';
  const ward = data.whole_ward || data.ward || '—';
  const watershed = data.whole_watershed || data.watershed || '—';
  const river = data.whole_major_river_basin || data.major_river_basin || '—';

  const narrative = `यस वन ${province} प्रदेश, ${district} जिल्ला, ${municipality} - वडा नं. ${ward} मा अवस्थित छ। यो वन ${watershed} जलाधार र ${river} प्रमुख नदी बेसिन अन्तर्गत पर्दछ।`;

  return {
    titleNp: 'स्थान तथा सन्दर्भ',
    titleEn: 'Location & Context',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['province', 'district', 'municipality', 'ward', 'watershed', 'major_river_basin'],
    source: 'calculation',
  };
}

// ─── 15. Species Distribution ───────────────────────────────────
export function generateSpeciesDistribution(data: any): SectionContent {
  const total = data.total_species || data.potential_species?.length || 0;

  const narrative = `यस वनमा जम्मा ${total} प्रजातिका रूखहरू पाइन्छन्। यी प्रजातिहरू विभिन्न वन खण्डहरूमा फैलिएका छन्। तल प्रमुख प्रजातिहरूको सूची दिइएको छ।`;

  return {
    titleNp: 'वन प्रजाति',
    titleEn: 'Species Distribution',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['total_species', 'species_list', 'species_by_role', 'confirmed_species'],
    source: 'species',
  };
}

// ─── 16. Accessible Forest Area ─────────────────────────────────
export function generateAccessibleForest(accessibleData: any, totalArea?: number): SectionContent {
  const blocks = accessibleData?.blocks || [];
  let totalAccessible = 0, totalInaccessible = 0, totalNonForest = 0;

  blocks.forEach((b: any) => {
    totalAccessible += b.accessible_forest_area_ha || 0;
    totalInaccessible += b.inaccessible_steep_forest_ha || 0;
    totalNonForest += b.non_forest_area_ha || 0;
  });

  const total = totalArea || totalAccessible + totalInaccessible + totalNonForest;
  const accessPct = total > 0 ? ((totalAccessible / total) * 100).toFixed(1) : '०';
  const inaccessPct = total > 0 ? ((totalInaccessible / total) * 100).toFixed(1) : '०';
  const nonForestPct = total > 0 ? ((totalNonForest / total) * 100).toFixed(1) : '०';

  const narrative = `यस वनको कुल क्षेत्रफलमध्ये ${totalAccessible.toFixed(2)} हेक्टर (${accessPct}%) क्षेत्र नमुना प्लट राख्नको लागि पहुँचयोग्य रहेको छ। दुर्गम वन क्षेत्र ${totalInaccessible.toFixed(2)} हेक्टर (${inaccessPct}%) र वन नभएको क्षेत्र ${totalNonForest.toFixed(2)} हेक्टर (${nonForestPct}%) रहेको छ।`;

  const chartData = [
    { label: 'पहुँचयोग्य', value: totalAccessible, color: '#22c55e' },
    { label: 'दुर्गम', value: totalInaccessible, color: '#eab308' },
    { label: 'वन नभएको', value: totalNonForest, color: '#6b7280' },
  ];

  const legend: LegendItem[] = [
    { color: '#22c55e', labelNp: 'पहुँचयोग्य', labelEn: 'Accessible Forest' },
    { color: '#eab308', labelNp: 'दुर्गम', labelEn: 'Inaccessible Forest' },
    { color: '#6b7280', labelNp: 'वन नभएको', labelEn: 'Non-forest' },
  ];

  return {
    titleNp: 'पहुँचयोग्य वन क्षेत्र',
    titleEn: 'Accessible Forest Area',
    narrative,
    graphics: { type: 'stacked_bar', data: chartData },
    legend,
    variables: ['accessible_forest_area_ha', 'inaccessible_steep_forest_ha', 'non_forest_area_ha'],
    source: 'field_inventory',
  };
}

// ─── 21. Field Inventory Narration ────────────────────────────────
export function generateFieldInventoryNarration(data: any): SectionContent | null {
  const fi = data.field_inventory || {};
  const breakdown = fi.breakdown || fi;
  if (!breakdown.total_sample_plots) return null;

  const plots = toNepaliDigit(breakdown.total_sample_plots || 0, 0);
  const blocks = toNepaliDigit(breakdown.total_blocks || 0, 0);
  const regen = toNepaliDigit(breakdown.fi_regeneration_per_ha || 0, 0);
  const sapling = toNepaliDigit(breakdown.fi_sapling_per_ha || 0, 0);
  const pole = toNepaliDigit(breakdown.fi_pole_per_ha || 0, 0);
  const tree = toNepaliDigit(breakdown.fi_tree_per_ha || 0, 0);
  const gs = toNepaliDigit(breakdown.fi_growing_stock_m3_per_ha || 0, 2);
  const ba = toNepaliDigit(breakdown.fi_basal_area_m2_per_ha || 0, 2);
  const agb = toNepaliDigit(breakdown.fi_agb_t_per_ha || 0, 2);
  const bgb = toNepaliDigit(breakdown.fi_bgb_t_per_ha || 0, 2);
  const tb = toNepaliDigit(breakdown.fi_total_biomass_t_per_ha || 0, 2);
  const c = toNepaliDigit(breakdown.fi_carbon_stock_tc_per_ha || 0, 2);
  const co2 = toNepaliDigit(breakdown.fi_co2_equivalent_tco2_per_ha || 0, 2);
  const maiPct = toNepaliDigit(breakdown.fi_mai_percent || 0, 1);
  const den = toNepaliDigit(breakdown.fi_weighted_wood_density || 0, 3);
  const fc = breakdown.fi_forest_condition || '—';

  const narrative = `यस वनको कुल ${plots} वटा नमुना प्लटहरू (${blocks} वटा ब्लक) मा गरिएको क्षेत्र सर्वेक्षण अनुसार प्रति हेक्टर ${regen} वटा विरुवा, ${sapling} वटा लाथ्रा, ${pole} वटा खाँवा र ${tree} वटा रूख रहेको पाइयो। कुल वृद्धि मौज्दात ${gs} घनमिटर प्रति हेक्टर र बेसल एरिया ${ba} वर्गमिटर प्रति हेक्टर रहेको छ। प्रति हेक्टर जमिन माथिको बायोमास ${agb} टन र जमिन मुनिको बायोमास ${bgb} टन (जम्मा ${tb} टन) रहेको छ। कुल कार्बन भण्डार ${c} टन कार्बन प्रति हेक्टर र कार्बन डाइअक्साइड समतुल्य ${co2} टन प्रति हेक्टर रहेको छ। वनको अवस्था "${fc}" रहेको छ भने औसत वार्षिक वृद्धि ${maiPct}% र काठ घनत्व ${den} टन प्रति घनमिटर रहेको छ।`;

  return {
    titleNp: 'क्षेत्र सर्वेक्षण विवरण',
    titleEn: 'Field Inventory Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['field_inventory'],
    source: 'field_inventory',
  };
}

// ─── 22. Tree Mapping: Hierarchy Narration ──────────────────────
export function generateSmHierarchyNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const blocks = sm.sm_total_blocks_analyzed || 0;
  const trees = sm.sm_total_trees_analyzed || 0;
  const levels = (sm.sm_hierarchy_summary || []).length;
  if (!blocks || !trees) return null;
  const narrative = `रूख म्यापिङ विश्लेषण अनुसार कुल ${toNepaliDigit(blocks, 0)} वटा ब्लकमा ${toNepaliDigit(trees, 0)} वटा रूखहरू विश्लेषण गरिएको छ। यी रूखहरू ${toNepaliDigit(levels, 0)} वटा स्थानिक स्तर संयोजनहरूमा वितरित छन्। प्रत्येक स्तरमा उप-कम्पार्टमेन्ट, कम्पार्टमेन्ट, ब्लक र उप-क्षेत्र अनुसार रूख सङ्ख्या, आयतन, प्रमुख प्रजाति, औसत डीबीएच र उचाइ समावेश गरिएको छ।`;
  return {
    titleNp: 'स्थानिक स्तर रूख सारांश विवरण',
    titleEn: 'Hierarchy Summary Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 23. Tree Mapping: Species Composition Narration ────────────
export function generateSmSpeciesNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const sData = sm.sm_species_by_hierarchy || [];
  const dData = sm.sm_species_diversity || [];
  if (!sData.length) return null;
  const speciesSet = new Set(sData.map((r: any) => r.species).filter(Boolean));
  const spCount = speciesSet.size;
  const spCounts: Record<string, number> = {};
  sData.forEach((r: any) => { if (r.species) spCounts[r.species] = (spCounts[r.species] || 0) + (r.tree_count || 0); });
  const top = Object.entries(spCounts).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const topStr = top.map(([s, c]) => `${s} (${toNepaliDigit(c, 0)})`).join(', ');
  let divStr = '';
  if (dData.length) {
    const avgShannon = dData.reduce((s: number, r: any) => s + Number(r.shannon_index || 0), 0) / dData.length;
    divStr = ` श्यानन विविधता सूचकांक औसत ${toNepaliDigit(avgShannon, 2)} रहेको छ।`;
  }
  const narrative = `रूख म्यापिङमा जम्मा ${toNepaliDigit(spCount, 0)} प्रजातिहरू फेला परेका छन्। सबैभन्दा बढी पाइने प्रजातिहरू: ${topStr}।${divStr}`;
  return {
    titleNp: 'प्रजाति संरचना विवरण',
    titleEn: 'Species Composition Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 24. Tree Mapping: DBH Class Narration ──────────────────────
export function generateSmDbhNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const dData = sm.sm_dbh_by_hierarchy || [];
  if (!dData.length) return null;
  const total = dData.reduce((s: number, r: any) => s + Number(r.tree_count || 0), 0);
  const clsCounts: Record<string, number> = {};
  dData.forEach((r: any) => { if (r.dbh_class) clsCounts[r.dbh_class] = (clsCounts[r.dbh_class] || 0) + Number(r.tree_count || 0); });
  const top = Object.entries(clsCounts).sort((a, b) => b[1] - a[1])[0];
  const dominant = top ? `${top[0]} (${toNepaliDigit(top[1], 0)} रूख)` : '—';
  const narrative = `DBH वर्ग विश्लेषण अनुसार जम्मा ${toNepaliDigit(total, 0)} वटा रूखहरूको वर्गीकरण गरिएको छ। सबैभन्दा बढी रूख भएको DBH वर्ग: ${dominant}। प्रत्येक स्थानिक स्तरमा DBH वर्ग अनुसार रूख सङ्ख्या, काठ आयतन, दाउरा आयतन र स्तर प्रतिशत विवरण तालिकामा समावेश गरिएको छ।`;
  return {
    titleNp: 'DBH वर्ग विवरण',
    titleEn: 'DBH Class Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 25. Tree Mapping: Stand Type Narration ─────────────────────
export function generateSmStandTypeNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const stData = sm.sm_stand_type_by_hierarchy || [];
  const status = sm.sm_forest_structure_status || {};
  if (!stData.length) return null;
  const totalRegen = stData.reduce((s: number, r: any) => s + Number(r.regeneration || 0), 0);
  const totalSapling = stData.reduce((s: number, r: any) => s + Number(r.sapling || 0), 0);
  const totalPole = stData.reduce((s: number, r: any) => s + Number(r.pole || 0), 0);
  const totalTree = stData.reduce((s: number, r: any) => s + Number(r.tree || 0), 0);
  const grand = totalRegen + totalSapling + totalPole + totalTree;
  const regenPct = grand ? ((totalRegen / grand) * 100).toFixed(1) : '0';
  const overall = status.overall_status || '—';
  const narrative = `वन संरचना विश्लेषण अनुसार जम्मा ${toNepaliDigit(grand, 0)} वटा रूखहरूमध्ये पुनरुत्पादन ${toNepaliDigit(totalRegen, 0)} (${toNepaliDigit(Number(regenPct), 1)}%), लाथ्रा ${toNepaliDigit(totalSapling, 0)}, पोल ${toNepaliDigit(totalPole, 0)} र रूख ${toNepaliDigit(totalTree, 0)} वटा रहेको छ। समग्र वन संरचना अवस्था "${overall}" रहेको छ।`;
  return {
    titleNp: 'स्ट्यान्ड प्रकार विवरण',
    titleEn: 'Stand Type Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 26. Tree Mapping: Carbon Stock Narration ──────────────────
export function generateSmCarbonNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const cData = sm.sm_carbon_by_hierarchy || [];
  const tc = sm.sm_total_carbon_tc || 0;
  const tco2 = sm.sm_total_co2_tco2 || 0;
  if (!cData.length) return null;
  const totalAgb = cData.reduce((s: number, r: any) => s + Number(r.agb_t || 0), 0);
  const totalBgb = cData.reduce((s: number, r: any) => s + Number(r.bgb_t || 0), 0);
  const totalBio = cData.reduce((s: number, r: any) => s + Number(r.biomass_t || 0), 0);
  const narrative = `कार्बन मौज्दात विश्लेषण अनुसार कुल जमिन माथिको बायोमास (AGB) ${toNepaliDigit(totalAgb, 2)} टन र जमिन मुनिको बायोमास (BGB) ${toNepaliDigit(totalBgb, 2)} टन (जम्मा ${toNepaliDigit(totalBio, 2)} टन) रहेको छ। कुल कार्बन मौज्दात ${toNepaliDigit(tc, 3)} tC र कार्बन डाइअक्साइड समतुल्य ${toNepaliDigit(tco2, 3)} tCO₂ रहेको छ। प्रत्येक स्थानिक स्तरको कार्बन विवरण तालिकामा समावेश गरिएको छ।`;
  return {
    titleNp: 'कार्बन मौज्दात विवरण',
    titleEn: 'Carbon Stock Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 27. Tree Mapping: Volume Distribution Narration ────────────
export function generateSmVolumeNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const vData = sm.sm_volume_by_hierarchy || [];
  const topSp = sm.sm_top_species_by_volume || [];
  if (!vData.length) return null;
  const totalStem = vData.reduce((s: number, r: any) => s + Number(r.stem_volume_m3 || 0), 0);
  const totalBranch = vData.reduce((s: number, r: any) => s + Number(r.branch_volume_m3 || 0), 0);
  const totalVol = vData.reduce((s: number, r: any) => s + Number(r.total_volume_m3 || 0), 0);
  const totalNet = vData.reduce((s: number, r: any) => s + Number(r.net_volume_m3 || 0), 0);
  let topStr = '';
  if (topSp.length) {
    const topEntries = topSp.slice(0, 3);
    topStr = '। आयतन अनुसार शीर्ष प्रजातिहरू: ' + topEntries.map((r: any) => `${r.local_name || r.species} (${toNepaliDigit(Number(r.total_volume_m3 || 0), 2)} m³)`).join(', ');
  }
  const narrative = `आयतन वितरण विश्लेषण अनुसार जम्मा काण्ड आयतन ${toNepaliDigit(totalStem, 2)} m³, हाँगा आयतन ${toNepaliDigit(totalBranch, 2)} m³ र कुल आयतन ${toNepaliDigit(totalVol, 2)} m³ रहेको छ। नेट आयतन ${toNepaliDigit(totalNet, 2)} m³ रहेको छ।${topStr}`;
  return {
    titleNp: 'आयतन वितरण विवरण',
    titleEn: 'Volume Distribution Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 28. Tree Mapping: Mother Tree Coverage Narration ──────────
export function generateSmMotherTreeNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const coverage = sm.sm_mother_tree_coverage || {};
  const mtData = sm.sm_mother_tree_by_hierarchy || [];
  const summary = sm.sm_mother_felling_summary || {};
  if (!coverage && !mtData.length && !Object.keys(summary).length) return null;
  const grid = coverage.grid_spacing_m || '—';
  const totalCells = coverage.total_grid_cells || 0;
  const withMother = coverage.cells_with_mother || 0;
  const covPct = coverage.coverage_percent || 0;
  const totalMother = summary.total_mother_trees || mtData.reduce((s: number, r: any) => s + Number(r.mother_trees || 0), 0);
  const totalFelling = summary.total_felling_trees || mtData.reduce((s: number, r: any) => s + Number(r.felling_trees || 0), 0);
  const narrative = `माँउ रूख कभरेज विश्लेषण: ग्रिड दूरी ${grid} मि., कुल ग्रिड सेल ${toNepaliDigit(totalCells, 0)} मध्ये ${toNepaliDigit(withMother, 0)} सेलमा माँउ रूख रहेको छ (कभरेज ${toNepaliDigit(covPct, 1)}%)। जम्मा ${toNepaliDigit(totalMother, 0)} वटा माँउ रूख र ${toNepaliDigit(totalFelling, 0)} वटा कटानी रूख रहेको छ।`;
  return {
    titleNp: 'माँउ रूख कभरेज विवरण',
    titleEn: 'Mother Tree Coverage Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── 29. Tree Mapping: Felling Tree Analysis Narration ─────────
export function generateSmFellingNarration(data: any): SectionContent | null {
  const sm = data.tree_mapping_analysis || {};
  if (!sm.sm_available) return null;
  const totals = sm.sm_felling_totals || {};
  const fDbh = sm.sm_felling_dbh_analysis || [];
  const fSp = sm.sm_felling_species_analysis || [];
  if (!totals && !fDbh.length) return null;
  const totalTrees = totals.tree_count || fDbh.reduce((s: number, r: any) => s + Number(r.tree_count || 0), 0);
  const totalVol = totals.gross_volume_m3 || fDbh.reduce((s: number, r: any) => s + Number(r.gross_volume_m3 || 0), 0);
  const totalTimber = totals.timber_m3 || fDbh.reduce((s: number, r: any) => s + Number(r.timber_m3 || 0), 0);
  const totalFw = totals.firewood_m3 || fDbh.reduce((s: number, r: any) => s + Number(r.firewood_m3 || 0), 0);
  let topStr = '';
  if (fSp.length) {
    const top = [...fSp].sort((a: any, b: any) => Number(b.gross_volume_m3 || 0) - Number(a.gross_volume_m3 || 0)).slice(0, 3);
    topStr = '। प्रजाति अनुसार: ' + top.map((r: any) => `${r.local_name || r.species} ${toNepaliDigit(Number(r.gross_volume_m3 || 0), 2)} m³`).join(', ');
  }
  const narrative = `कटानी रूख विश्लेषण (≥३० से.मी. DBH): जम्मा ${toNepaliDigit(totalTrees, 0)} वटा कटानी रूखको कुल आयतन ${toNepaliDigit(totalVol, 2)} m³ (काठ ${toNepaliDigit(totalTimber, 2)} m³, दाउरा ${toNepaliDigit(totalFw, 2)} m³) रहेको छ।${topStr}`;
  return {
    titleNp: 'कटानी रूख विश्लेषण विवरण',
    titleEn: 'Felling Tree Analysis Narration',
    narrative,
    graphics: { type: 'none', data: [] },
    legend: [],
    variables: ['tree_mapping_analysis'],
    source: 'tree_mapping_analysis',
  };
}

// ─── REGISTRY ────────────────────────────────────────────────────
export const SECTION_GENERATORS: Record<string, SectionGenerator> = {
  forest_summary: {
    generatorFn: generateForestSummary,
    variables: ['area_hectares', 'blocks_count', 'elevation_mean_m', 'carbon_stock_mg', 'forest_health_dominant'],
  },
  slope_analysis: {
    generatorFn: generateSlopeAnalysis,
    variables: ['slope_dominant_class', 'slope_percentages'],
  },
  elevation_profile: {
    generatorFn: generateElevationProfile,
    variables: ['elevation_min_m', 'elevation_max_m', 'elevation_mean_m'],
  },
  aspect_analysis: {
    generatorFn: generateAspectAnalysis,
    variables: ['aspect_dominant', 'aspect_percentages'],
  },
  forest_health: {
    generatorFn: generateForestHealth,
    variables: ['forest_health_dominant', 'forest_health_percentages'],
  },
  forest_type: {
    generatorFn: generateForestType,
    variables: ['forest_type_dominant', 'forest_type_percentages'],
  },
  species_potential: {
    generatorFn: generatePotentialSpecies,
    variables: ['potential_species', 'species_count'],
  },
  actual_species: {
    generatorFn: generateActualSpecies,
    variables: [],
  },
  biodiversity: {
    generatorFn: generateBiodiversity,
    variables: [],
  },
  canopy_structure: {
    generatorFn: generateCanopyStructure,
    variables: ['canopy_dominant_class', 'canopy_percentages', 'canopy_mean_m'],
  },
  biomass_carbon: {
    generatorFn: generateBiomassCarbon,
    variables: ['agb_mean', 'agb_total', 'carbon_stock'],
  },
  climate_conditions: {
    generatorFn: generateClimateConditions,
    variables: ['temperature_mean_c', 'precipitation_mean_mm'],
  },
  land_cover: {
    generatorFn: generateLandCover,
    variables: ['landcover_dominant', 'landcover_percentages'],
  },
  forest_loss: {
    generatorFn: generateForestLoss,
    variables: ['forest_loss_hectares', 'forest_loss_by_year'],
  },
  fire_loss: {
    generatorFn: generateFireLoss,
    variables: ['fire_loss_hectares', 'fire_loss_by_year'],
  },
  forest_quality: {
    generatorFn: generateForestQuality,
    variables: ['whole_nasa_forest_2020_percentages', 'whole_nasa_forest_2020_dominant'],
  },
  soil_analysis: {
    generatorFn: generateSoilAnalysis,
    variables: ['soil_texture', 'soil_properties', 'fertility_class'],
  },
  location_context: {
    generatorFn: generateLocationContext,
    variables: ['province', 'district', 'municipality', 'ward', 'watershed', 'major_river_basin'],
  },
  species_distribution: {
    generatorFn: generateSpeciesDistribution,
    variables: ['total_species', 'species_list'],
  },
  accessible_forest: {
    generatorFn: (data: any) => generateAccessibleForest(data.accessible_forest || data, data.area_hectares),
    variables: ['accessible_forest'],
  },
  field_inventory_narration: {
    generatorFn: (data: any) => generateFieldInventoryNarration(data),
    variables: ['field_inventory'],
  },

  // Tree Mapping Analysis Narrations
  sm_hierarchy_narration: {
    generatorFn: (data: any) => generateSmHierarchyNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_species_narration: {
    generatorFn: (data: any) => generateSmSpeciesNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_dbh_narration: {
    generatorFn: (data: any) => generateSmDbhNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_stand_type_narration: {
    generatorFn: (data: any) => generateSmStandTypeNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_carbon_narration: {
    generatorFn: (data: any) => generateSmCarbonNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_volume_narration: {
    generatorFn: (data: any) => generateSmVolumeNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_mother_tree_narration: {
    generatorFn: (data: any) => generateSmMotherTreeNarration(data),
    variables: ['tree_mapping_analysis'],
  },
  sm_felling_narration: {
    generatorFn: (data: any) => generateSmFellingNarration(data),
    variables: ['tree_mapping_analysis'],
  },
};

export const SECTION_TITLES: { key: string; titleNp: string; titleEn: string; icon: string }[] = [
  { key: 'forest_summary', titleNp: 'वन सारांश', titleEn: 'Forest Summary', icon: '📊' },
  { key: 'slope_analysis', titleNp: 'भिरालो विश्लेषण', titleEn: 'Slope Analysis', icon: '⛰️' },
  { key: 'elevation_profile', titleNp: 'उचाइ विवरण', titleEn: 'Elevation Profile', icon: '🏔️' },
  { key: 'aspect_analysis', titleNp: 'दिशा विश्लेषण', titleEn: 'Aspect Analysis', icon: '🧭' },
  { key: 'forest_health', titleNp: 'वन स्वास्थ्य', titleEn: 'Forest Health', icon: '💚' },
  { key: 'forest_type', titleNp: 'वन प्रकार', titleEn: 'Forest Type', icon: '🌲' },
  { key: 'species_potential', titleNp: 'सम्भावित प्रजातिहरू', titleEn: 'Potential Species', icon: '🌱' },
  { key: 'actual_species', titleNp: 'वन श्रोत बाट देखिएका काठ जातका प्रजातिहरू', titleEn: 'Actual Species (Field)', icon: '📋' },
  { key: 'biodiversity', titleNp: 'जैविक विविधता', titleEn: 'Biodiversity', icon: '🦌' },
  { key: 'canopy_structure', titleNp: 'वन मुकुट', titleEn: 'Canopy Structure', icon: '🌿' },
  { key: 'biomass_carbon', titleNp: 'जैविक पदार्थ तथा कार्बन', titleEn: 'Biomass & Carbon', icon: '📦' },
  { key: 'climate_conditions', titleNp: 'मौसम अवस्था', titleEn: 'Climate Conditions', icon: '🌡️' },
  { key: 'land_cover', titleNp: 'भू-आवरण', titleEn: 'Land Cover', icon: '🗺️' },
  { key: 'forest_loss', titleNp: 'वन क्षति', titleEn: 'Forest Loss', icon: '🔥' },
  { key: 'fire_loss', titleNp: 'आगलागी क्षति', titleEn: 'Fire Loss', icon: '🔥' },
  { key: 'forest_quality', titleNp: 'वन गुणस्तर (नासा २०२०)', titleEn: 'Forest Quality (NASA 2020)', icon: '🛰️' },
  { key: 'soil_analysis', titleNp: 'माटो विश्लेषण', titleEn: 'Soil Analysis', icon: '🌍' },
  { key: 'location_context', titleNp: 'स्थान तथा सन्दर्भ', titleEn: 'Location & Context', icon: '📍' },
  { key: 'species_distribution', titleNp: 'वन प्रजाति', titleEn: 'Species Distribution', icon: '🌳' },
  { key: 'accessible_forest', titleNp: 'पहुँचयोग्य वन क्षेत्र', titleEn: 'Accessible Forest Area', icon: '🚶' },
  { key: 'field_inventory_narration', titleNp: 'क्षेत्र सर्वेक्षण विवरण', titleEn: 'Field Inventory Narration', icon: '📋' },

  // Tree Mapping Analysis Narrations
  { key: 'sm_hierarchy_narration', titleNp: 'स्थानिक स्तर रूख सारांश विवरण', titleEn: 'Hierarchy Summary Narration', icon: '📋' },
  { key: 'sm_species_narration', titleNp: 'प्रजाति संरचना विवरण', titleEn: 'Species Composition Narration', icon: '📋' },
  { key: 'sm_dbh_narration', titleNp: 'DBH वर्ग विवरण', titleEn: 'DBH Class Narration', icon: '📋' },
  { key: 'sm_stand_type_narration', titleNp: 'स्ट्यान्ड प्रकार विवरण', titleEn: 'Stand Type Narration', icon: '📋' },
  { key: 'sm_carbon_narration', titleNp: 'कार्बन मौज्दात विवरण', titleEn: 'Carbon Stock Narration', icon: '📋' },
  { key: 'sm_volume_narration', titleNp: 'आयतन वितरण विवरण', titleEn: 'Volume Distribution Narration', icon: '📋' },
  { key: 'sm_mother_tree_narration', titleNp: 'माँउ रूख कभरेज विवरण', titleEn: 'Mother Tree Coverage Narration', icon: '📋' },
  { key: 'sm_felling_narration', titleNp: 'कटानी रूख विश्लेषण विवरण', titleEn: 'Felling Tree Analysis Narration', icon: '📋' },
];
