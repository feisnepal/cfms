#!/usr/bin/env node
/**
 * Generate i18n segment files for Phase 4c keys
 * This script creates JSON segment files for the 443 new keys
 */

const fs = require('fs');
const path = require('path');

// Read the list of keys
const keysFile = 'C:/Users/Rajkumar/AppData/Local/Temp/all_new_keys.txt';
const rawKeys = fs.readFileSync(keysFile, 'utf8').trim().split('\n').map(k => k.trim()).filter(k => k);

// Parse keys - they have format: "key   (src\\components\\File.tsx)"
const keys = rawKeys.map(k => {
  const idx = k.indexOf('   (src');
  return idx > 0 ? k.substring(0, idx) : k;
});

console.log('Parsed', keys.length, 'keys');

// Translation map for all keys
const translations = {
  // Sampling keys
  'sampling.forestAreaClassification': { en: 'Forest Area Classification', ne: 'वन क्षेत्र वर्गीकरण' },
  'sampling.details': { en: 'Details', ne: 'विवरणहरू' },
  'sampling.totalBoundaryArea': { en: 'Total Boundary Area', ne: 'कुल सीमा क्षेत्रफल' },
  'sampling.accessibleForestGreen': { en: 'Accessible Forest (Green)', ne: 'पहुँचयोग्य वन (हरियो)' },
  'sampling.ofTotal': { en: 'of Total', ne: 'कुलको' },
  'sampling.protectedForestRed': { en: 'Protected Forest (Red)', ne: 'संरक्षित वन (रातो)' },
  'sampling.nonForestArea': { en: 'Non-forest Area', ne: 'गैर-वन क्षेत्र' },
  'sampling.mapLegend': { en: 'Map Legend', ne: 'नक्सा संकेत' },
  'sampling.boundary': { en: 'Boundary', ne: 'सीमा' },
  'sampling.accessibleForestResourceEffective': { en: 'Accessible forest area for effective resource management', ne: 'प्रभावकारी स्रोत व्यवस्थापनका लागि पहुँचयोग्य वन क्षेत्र' },
  'sampling.protectedForestSteepSlopes': { en: 'Protected forest on steep slopes', ne: 'ढलान ढलाउँदा संरक्षित वन क्षेत्र' },
  'sampling.slopeFilteringNoteTitle': { en: 'Slope Filtering Note', ne: 'ढलान फिल्टर नोट' },
  'sampling.slopeFilteringNoteBody': { en: 'Slope filtering excludes steep areas that are unsafe for field crews. The percentage shows how much accessible forest remains after applying the slope limit.', ne: 'ढलान फिल्टरले फिल्ड टोलीका लागि असुरक्षित ढलाउँ क्षेत्रहरूलाई बिर्ता गर्दछ। प्रतिशतले ढलान सीमा लागू गर्दा कति पहुँचयोग्य वन बाँकी रहन्छ भन्ने देखाउँछ।' },
  'sampling.understandingClassificationTitle': { en: 'Understanding the Classification', ne: 'वर्गीकरण बुझ्नुहोस्' },
  'sampling.greenAreasAccessible': { en: 'Green areas = accessible forest where sample plots can be established', ne: 'हरियो क्षेत्रहरू = नमूना प्लट स्थापना गर्न सकिने पहुँचयोग्य वन' },
  'sampling.greenAreasSlopeApplied': { en: 'Green areas already have slope filtering applied if enabled', ne: 'सक्षम भएमा हरियो क्षेत्रहरूमा ढलान फिल्टर पहिले नै लागू भएको हुन्छ' },
  'sampling.greenAreasSamplePlots': { en: 'Sample plots are placed only in green areas', ne: 'नमूना प्लटहरू केवल हरियो क्षेत्रमा राखिन्छन्' },
  'sampling.redAreasProtected': { en: 'Red areas = protected forest on steep slopes (> threshold)', ne: 'रातो क्षेत्रहरू = ढलाउँ ढलानमा (> सीमा) संरक्षित वन' },
  'sampling.redAreasExplanation': { en: 'These areas have tree cover but are excluded from sampling due to steepness', ne: 'यी क्षेत्रहरूमा रूख आवरण छ तर ढलानका कारण नमूनाबाट बिर्ता गरिएका हुन्छन्' },
  'sampling.visualizationHelps': { en: 'This visualization helps plan efficient field work', ne: 'यो दृश्यावलोकनले कुशल फिल्ड कार्य योजना बनाउन मद्दत गर्दछ' },
  'sampling.areaCalculationsNoteTitle': { en: 'Area Calculations Note', ne: 'क्षेत्रफल गणना नोट' },
  'sampling.areaCalculationsNoteBody': { en: 'Areas are calculated from raster analysis. Tree cover comes from satellite data. Slope is derived from digital elevation model. Small discrepancies may occur due to raster resolution.', ne: 'क्षेत्रफलहरू र्याष्टर विश्लेषणबाट गणना गरिएका हुन्छन्। रूख आवरण उपग्रह डेटाबाट आउँछ। ढलान डिजिटल एलिभेसन मोडलबाट प्राप्त हुन्छ। र्याष्टर रेजोल्युसनका कारण साना भिन्नताहरू हुन सक्छन्।' },
  'common.hide': { en: 'Hide', ne: 'छिपाउनुहोस्' },
  'common.show': { en: 'Show', ne: 'देखाउनुहोस्' },

  // Analysis Options Panel
  'analysis.optionsTitle': { en: 'Analysis Options', ne: 'विश्लेषण विकल्पहरू' },
  'analysis.selectAll': { en: 'Select All', ne: 'सबै छान्नुहोस्' },
  'analysis.deselectAll': { en: 'Deselect All', ne: 'सबै बिर्ता गर्नुहोस्' },
  'analysis.presetConfig': { en: 'Preset Configuration', ne: 'प्रिसेट कन्फिगरेसन' },
  'analysis.runRasterAnalysis': { en: 'Run Raster Analysis', ne: 'र्याष्टर विश्लेषण चलाउनुहोस्' },
  'analysis.runRasterAnalysisDesc': { en: 'Master switch - if disabled, all raster analyses will be skipped', ne: 'मास्टर स्विच - अक्षम भएमा सबै र्याष्टर विश्लेषणहरू बिर्ता हुन्छन्' },
  'analysis.rasterParams': { en: 'Raster Analysis Parameters (15 options)', ne: 'र्याष्टर विश्लेषण परिमितिहरू (१५ विकल्प)' },
  'analysis.autoGenOptions': { en: 'Auto-Generation Options (2 options)', ne: 'स्वचालित उत्पादन विकल्पहरू (२ विकल्प)' },
  'analysis.autoFieldbook': { en: 'Auto-generate Fieldbook', ne: 'फिल्डबुक स्वचालित उत्पादन गर्नुहोस्' },
  'analysis.autoFieldbookDesc': { en: 'Automatically extract boundary vertices with 50m interpolation', ne: '५०म इन्टरपोलेशनसहित सीमा वर्टेक्सहरू स्वचालित निकाल्नुहोस्' },
  'analysis.autoSampling': { en: 'Auto-generate Sampling Design', ne: 'नमूना डिजाइन स्वचालित उत्पादन गर्नुहोस्' },
  'analysis.autoSamplingDesc': { en: 'Automatically create systematic sampling (250m grid, 500m² plots)', ne: 'व्यवस्थित नमूनाकरण स्वचालित सिर्जना गर्नुहोस् (२५०म ग्रिड, ५००म² प्लट)' },
  'analysis.selectedLabel': { en: 'Selected', ne: 'छानिएको' },
  'analysis.optionsEnabled': { en: 'options enabled', ne: 'विकल्पहरू सक्षम' },

  // Category keys
  'analysis.categoryTerrain': { en: 'Terrain', ne: 'भूभाग' },
  'analysis.categoryForestStructure': { en: 'Forest Structure', ne: 'वन संरचना' },
  'analysis.categoryClassification': { en: 'Classification', ne: 'वर्गीकरण' },
  'analysis.categoryChangeDetection': { en: 'Change Detection', ne: 'परिवर्तन पता लगाउने' },
  'analysis.categoryClimate': { en: 'Climate', ne: 'जलवायु' },
  'analysis.categorySoil': { en: 'Soil', ne: 'माटो' },
  'analysis.categoryVector': { en: 'Vector', ne: 'भेक्टर' },

  // Preset keys
  'analysis.presetQuick': { en: 'Quick', ne: 'चाँडो' },
  'analysis.presetQuickDesc': { en: 'Essential analyses only - Elevation, Slope, Aspect, Administrative location', ne: 'आवश्यक विश्लेषणहरू मात्र - एलिभेसन, ढलान, आस्पेक्ट, प्रशासनिक स्थान' },
  'analysis.estimatedTimeQuick': { en: '~30 seconds', ne: '~३० सेकेन्ड' },
  'analysis.presetStandard': { en: 'Standard', ne: 'मानक' },
  'analysis.presetStandardDesc': { en: 'Most common analyses - Terrain, Forest structure, Land cover, Climate, Auto-fieldbook', ne: 'सबैभन्दा सामान्य विश्लेषणहरू - भूभाग, वन संरचना, भूमि आवरण, जलवायु, स्वचालित फिल्डबुक' },
  'analysis.estimatedTimeStandard': { en: '~2 minutes', ne: '~२ मिनेट' },
  'analysis.presetComplete': { en: 'Complete', ne: 'पुरा' },
  'analysis.presetCompleteDesc': { en: 'All analyses including change detection, climate, proximity, and auto-sampling', ne: 'परिवर्तन पता लगाउने, जलवायु, निकटता, र स्वचालित नमूनासहित सबै विश्लेषणहरू' },
  'analysis.estimatedTimeComplete': { en: '~5 minutes', ne: '~५ मिनेट' },
  'analysis.presetCustom': { en: 'Custom', ne: 'कस्टम' },
  'analysis.presetCustomDesc': { en: 'Select individual analyses manually', ne: 'व्यक्तिगत विश्लेषणहरू म्यानुअली छान्नुहोस्' },
  'analysis.estimatedTimeCustom': { en: 'Varies', ne: 'भिन्न हुन्छ' },

  // Analysis option labels
  'analysis.elevation': { en: 'Elevation (DEM)', ne: 'एलिभेसन (डिएम)' },
  'analysis.elevationDesc': { en: 'Min, max, and mean elevation from digital elevation model', ne: 'डिजिटल एलिभेसन मोडलबाट न्यूनतम, अधिकतम, र औसत एलिभेसन' },
  'analysis.slope': { en: 'Slope', ne: 'ढलान' },
  'analysis.slopeDesc': { en: '4-class slope classification (Gentle, Moderate, Steep, Very Steep)', ne: '४-वर्ग ढलान वर्गीकरण (नरम, मध्यम, ढलाउँ, धेरै ढलाउँ)' },
  'analysis.aspect': { en: 'Aspect', ne: 'आस्पेक्ट' },
  'analysis.aspectDesc': { en: '8-directional aspect distribution (N, NE, E, SE, S, SW, W, NW)', ne: '८-दिशात्मक आस्पेक्ट वितरण (उ, उ.प, प, द.प, द, द.प, प, उ.प)' },
  'analysis.canopy': { en: 'Canopy Height', ne: 'क्यानपि उचाई' },
  'analysis.canopyDesc': { en: 'Forest canopy structure classification (Open, Medium, Dense, Very Dense)', ne: 'वन क्यानपि संरचना वर्गीकरण (खुला, मध्यम, घन, धेरै घन)' },
  'analysis.biomass': { en: 'Above-ground Biomass', ne: 'भूमि उपरको बायोमास' },
  'analysis.biomassDesc': { en: 'Biomass and carbon stock estimation', ne: 'बायोमास र कार्बन स्टक अनुमान' },
  'analysis.forestHealth': { en: 'Forest Health', ne: 'वन स्वास्थ्य' },
  'analysis.forestHealthDesc': { en: '5-class forest health assessment', ne: '५-वर्ग वन स्वास्थ्य मूल्यांकन' },
  'analysis.forestType': { en: 'Forest Type', ne: 'वन प्रकार' },
  'analysis.forestTypeDesc': { en: 'Species-based forest type classification', ne: 'प्रजाति-आधारित वन प्रकार वर्गीकरण' },
  'analysis.landcover': { en: 'Land Cover', ne: 'भूमि आवरण' },
  'analysis.landcoverDesc': { en: 'ESA WorldCover land cover classes', ne: 'ईएसए वर्ल्डकभर भूमि आवरण वर्गहरू' },
  'analysis.forestLoss': { en: 'Forest Loss', ne: 'वन ह्रास' },
  'analysis.forestLossDesc': { en: 'Hansen forest loss detection by year', ne: 'हान्सेन वन ह्रास पता लगाउने वार्षिक' },
  'analysis.forestGain': { en: 'Forest Gain', ne: 'वन वृद्धि' },
  'analysis.forestGainDesc': { en: 'Hansen forest gain detection', ne: 'हान्सेन वन वृद्धि पता लगाउने' },
  'analysis.fireLoss': { en: 'Fire Loss', ne: 'आगलागी ह्रास' },
  'analysis.fireLossDesc': { en: 'Fire-related forest loss by year', ne: 'आगलागी-सम्बन्धी वन ह्रास वार्षिक' },
  'analysis.temperature': { en: 'Temperature', ne: 'तापमान' },
  'analysis.temperatureDesc': { en: 'Annual mean temperature and minimum coldest month', ne: 'वार्षिक औसत तापमान र न्यूनतम सबैभन्दा ठण्डो महिना' },
  'analysis.precipitation': { en: 'Precipitation', ne: 'वर्षपात' },
  'analysis.precipitationDesc': { en: 'Annual precipitation', ne: 'वार्षिक वर्षपात' },
  'analysis.soil': { en: 'Soil Texture', ne: 'माटो संरचना' },
  'analysis.soilDesc': { en: 'SoilGrids soil texture classification', ne: 'सोइलग्रिड्स माटो संरचना वर्गीकरण' },
  'analysis.proximity': { en: 'Proximity Analysis', ne: 'निकटता विश्लेषण' },
  'analysis.proximityDesc': { en: 'Distance to settlements, roads, and rivers', ne: 'बस्ती, बाटो, र नदीहरूको दुरी' },
};

function generateKey(key) {
  if (translations[key]) return translations[key];

  // For keys not in explicit map, generate reasonable defaults
  const parts = key.split('.');
  const lastPart = parts[parts.length - 1];
  const namespace = parts[0];

  const toTitleCase = (str) => str
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, c => c.toUpperCase())
    .replace(/Colon$/, ':')
    .replace(/20012023$/, ' (2001-2023)')
    .replace(/20002012$/, ' (2000-2012)')
    .trim();

  const baseEn = toTitleCase(lastPart);

  if (namespace === 'common') {
    return { en: baseEn, ne: baseEn };
  }

  return { en: baseEn, ne: baseEn };
}

const outputDir = 'frontend/.i18n-4c';

// Clear and recreate
if (fs.existsSync(outputDir)) {
  fs.rmSync(outputDir, { recursive: true });
}
fs.mkdirSync(outputDir, { recursive: true });

let written = 0;
const files = {};

for (const key of keys) {
  const namespace = key.split('.')[0];
  if (!files[namespace]) files[namespace] = [];
  const t = generateKey(key);
  files[namespace].push({ key, en: t.en, ne: t.ne });
  written++;
}

for (const [ns, rows] of Object.entries(files)) {
  fs.writeFileSync(path.join(outputDir, `${ns}.json`), JSON.stringify(rows, null, 2));
  console.log(`Wrote ${rows.length} keys to ${ns}.json`);
}

console.log(`Total: ${written} keys written to ${Object.keys(files).length} files`);