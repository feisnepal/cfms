import { analysisDisplayValue } from './analysisValueLabels';
import { ANALYSIS_FIELDS } from './analysisFields';
import type { GeoJSON } from 'geojson';
import * as React from 'react';
import i18n from 'i18next';
import { SUB_AREA_COLORS } from './layerStyles';
import { withGeoProps } from '../utils/computeGeometryProps';
import { activityFeatureLabel, disambiguateLabels, type LabelOptions } from './activityFeatureLabel';
import { activityKindLabel, ACTIVITY_KIND_OPTIONS } from './activityKinds';
import { featureQuantityText, featureSharedTag, featureSharedTitle } from './activityFeatureQuantity';
import { samplingApi, compartmentApi, sfmApi, fieldbookApi } from '../services/api';
import { readDetail } from '../hooks/useErrorHandler';
import { DEPTH_TOP_COMPARTMENT, DEPTH_SUB } from './forestUnitConstants';

import { activityFeatureCreateBody, activityFeatureUpdateBody, ActivityFeatureApiError, type ActivityFeatureInput } from './activityFeaturePayload';
// ---------------------------------------------------------------------------
// Geometry-derived columns — always read-only, computed server-side. Shown by
// default (a forester expects lat/long/area/centroid in the table); the
// Columns… chooser lets any of them be turned off, and the choice persists.
// ---------------------------------------------------------------------------
export const GEO_BBOX_COLUMNS: ColumnDef[] = [
  { key: 'geo_bbox_ymin', label: 'Min Lat', labelKey: 'attributeTable.col.geo_bbox_ymin', width: 105, align: 'right', getValue: (f) => f.properties?.geo_bbox_ymin?.toFixed(6) ?? '-' },
  { key: 'geo_bbox_ymax', label: 'Max Lat', labelKey: 'attributeTable.col.geo_bbox_ymax', width: 105, align: 'right', getValue: (f) => f.properties?.geo_bbox_ymax?.toFixed(6) ?? '-' },
  { key: 'geo_bbox_xmin', label: 'Min Lng', labelKey: 'attributeTable.col.geo_bbox_xmin', width: 105, align: 'right', getValue: (f) => f.properties?.geo_bbox_xmin?.toFixed(6) ?? '-' },
  { key: 'geo_bbox_xmax', label: 'Max Lng', labelKey: 'attributeTable.col.geo_bbox_xmax', width: 105, align: 'right', getValue: (f) => f.properties?.geo_bbox_xmax?.toFixed(6) ?? '-' },
];

export const GEO_CENTROID_COLUMNS: ColumnDef[] = [
  { key: 'geo_centroid_lat', label: 'Centroid Lat', labelKey: 'attributeTable.col.geo_centroid_lat', width: 115, align: 'right', getValue: (f) => f.properties?.geo_centroid_lat?.toFixed(6) ?? '-' },
  { key: 'geo_centroid_lng', label: 'Centroid Lng', labelKey: 'attributeTable.col.geo_centroid_lng', width: 115, align: 'right', getValue: (f) => f.properties?.geo_centroid_lng?.toFixed(6) ?? '-' },
];

export const GEO_POLYGON_COLUMNS: ColumnDef[] = [
  { key: 'geo_area_ha', label: 'Area (ha)', labelKey: 'attributeTable.col.geo_area_ha', width: 105, align: 'right', getValue: (f) => f.properties?.geo_area_ha?.toFixed(2) ?? '-' },
  { key: 'geo_perimeter_km', label: 'Perimeter (km)', labelKey: 'attributeTable.col.geo_perimeter_km', width: 115, align: 'right', getValue: (f) => f.properties?.geo_perimeter_km?.toFixed(2) ?? '-' },
];

export const GEO_LINE_COLUMNS: ColumnDef[] = [
  { key: 'geo_length_km', label: 'Length (km)', labelKey: 'attributeTable.col.geo_length_km', width: 115, align: 'right', getValue: (f) => f.properties?.geo_length_km?.toFixed(2) ?? '-' },
];

// ---------------------------------------------------------------------------
// Per-feature style columns (WORKSPACE_LAYER_STYLING_PLAN.md P3.4) — a colour
// swatch + an opacity picker, wired to `onSaveProperty` in AttributeTable.
// Shown by default on the unit / sub-area layers whose PATCH persists `style`.
// ---------------------------------------------------------------------------
export const STYLE_COLUMNS: ColumnDef[] = [
  {
    key: 'style_fill', label: 'Colour', labelKey: 'attributeTable.col.styleFill',
    width: 84, align: 'center', editControl: 'color',
    getValue: (f) => (f.properties?.style && typeof f.properties.style === 'object' ? f.properties.style.fill : undefined),
  },
  {
    key: 'style_opacity', label: 'Opacity', labelKey: 'attributeTable.col.styleOpacity',
    width: 84, align: 'center', editControl: 'opacity',
    getValue: (f) => (f.properties?.style && typeof f.properties.style === 'object' ? f.properties.style.fillOpacity : undefined),
  },
];

// ---------------------------------------------------------------------------
// Slope-class column (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN Part A
// follow-on) — mirrors backend `slope_vectorize.BAND_LABELS`. Degree ranges
// read the same in either language, so one label serves both; NULL for any
// block not carved via the slope-class Auto-Block source.
// ---------------------------------------------------------------------------
export const SLOPE_BAND_LABEL: Record<number, string> = {
  1: '< 19°',
  2: '19–31°',
  3: '31–45°',
  4: '> 45°',
};

// User report, 2026-09-12: a merge auto-picks these 3 classification fields
// from the larger of the two merged features, but the user must still be
// able to correct the pick by hand -- editable everywhere, same as any other
// attribute (same `select`-dropdown pattern as the sub-area category
// column). `getValue` returns the raw numeric code (not the label text) so
// the dropdown's `value` binding matches an `<option value=...>` — the
// option's own label text is what actually renders in the closed select,
// same as the category column already does (its getValue returns the raw
// key, e.g. "plantation", not a translated label). AttributeTable itself
// always injects the blank "-" option, so `select` lists only the real
// choices.
export const SLOPE_BAND_COLUMN: ColumnDef = {
  key: 'dominant_slope_band', label: 'Slope Class', labelKey: 'attributeTable.col.slopeBand',
  emptyLabelKey: 'attributeTable.notSet',
  width: 90, align: 'center', editable: true,
  select: Object.entries(SLOPE_BAND_LABEL).map(([value, label]) => ({ value, label })),
  getValue: (f) => {
    const band = f.properties?.dominant_slope_band;
    return band != null ? String(band) : '';
  },
};

// Aspect + canopy-class columns — same shape as the slope-band column above,
// mirroring backend `aspect_vectorize.ASPECT_LABELS` /
// `canopy_vectorize.CANOPY_CLASS_LABELS`. NULL for any block not carved via
// the matching Auto-Block source.
export const ASPECT_LABEL: Record<number, string> = {
  1: 'N', 2: 'NE', 3: 'E', 4: 'SE', 5: 'S', 6: 'SW', 7: 'W', 8: 'NW',
};

export const ASPECT_COLUMN: ColumnDef = {
  key: 'dominant_aspect', label: 'Aspect', labelKey: 'attributeTable.col.aspect',
  emptyLabelKey: 'attributeTable.notSet',
  width: 80, align: 'center', editable: true,
  select: Object.entries(ASPECT_LABEL).map(([value, label]) => ({ value, label })),
  getValue: (f) => {
    const code = f.properties?.dominant_aspect;
    return code != null ? String(code) : '';
  },
};

export const CANOPY_CLASS_LABEL: Record<number, string> = {
  1: 'non-forest', 2: 'regeneration', 3: 'pole', 4: 'tree',
};

export const CANOPY_CLASS_COLUMN: ColumnDef = {
  key: 'dominant_canopy_class', label: 'Canopy Class', labelKey: 'attributeTable.col.canopyClass',
  emptyLabelKey: 'attributeTable.notSet',
  width: 100, align: 'center', editable: true,
  select: Object.entries(CANOPY_CLASS_LABEL).map(([value, label]) => ({ value, label })),
  getValue: (f) => {
    const cls = f.properties?.dominant_canopy_class;
    return cls != null ? String(cls) : '';
  },
};

// A unit that is not divided further. The Sub-block / Sub-compartment layers show
// every such unit of their branch -- NOT "everything at depth >= 2" -- so the layer
// always tiles the forest exactly once: a divided parent (C-1) is replaced by its
// children, an undivided top-level unit (C-2) stands in for itself. Owner decision
// 2026-10-03 (SUBCOMPARTMENT_LAYER_TRACKER.md SL-2/SL-3). `children` is the
// compartment-tree's own nesting, already filtered to real (promoted/unlayered) units.
export function isUndividedNode(node: { children?: unknown[] | null }): boolean {
  return !(node.children && node.children.length > 0);
}

// NASA 2020 forest-quality column. Owner report, 2026-09-30: "NASA is
// working fine but no value in attribute name and value" -- the carving, the
// persistence and the tile were all correct (the P2 dry run persisted
// dominant_nasa_quality and read it back), but the column was never registered
// here, so the attribute table showed neither a header nor any value. The
// backend has carried the field in the compartment-tree dict
// (compartments.py) and the block response (blocks.py) since migration 105;
// nothing on the frontend ever read it. Same shape as the three columns above,
// and same `getValue` convention: the RAW numeric code, not the label text, so
// the select's `value` binding matches its `<option value=...>`. Label text
// mirrors backend `forest_types.NASA_FOREST_QUALITY` -- keep the two in step.
export const NASA_QUALITY_LABEL: Record<number, string> = {
  1: 'Primary Forest',
  2: 'Young Secondary Forest',
  3: 'Old Secondary Forest',
};

export const NASA_QUALITY_COLUMN: ColumnDef = {
  key: 'dominant_nasa_quality', label: 'NASA Forest Quality',
  emptyLabelKey: 'attributeTable.notSet',
  labelKey: 'attributeTable.col.nasaQuality',
  width: 120, align: 'center', editable: true,
  select: Object.entries(NASA_QUALITY_LABEL).map(([value, label]) => ({ value, label })),
  getValue: (f) => {
    const code = f.properties?.dominant_nasa_quality;
    return code != null ? String(code) : '';
  },
};

// The raw raster class, 0-3, **including** code 0. Read-only and separate from
// the column above on purpose (RS-2.14).
//
// Owner report, 2026-09-30: "In preview I only see primary class in one
// polygon. other do not have any class ... why other polygon data is missing?"
// Nothing was missing. NASA code 0 is non-forest ground (grassland, bare, urban)
// that the plan carves as geometry but never reports as a class (RS-2.5 / D41),
// so `dominant_nasa_quality` is NULL for every compartment the raster called
// mostly non-forest. Measured on calc 62352bc1: 5 of the 7 substantial blocks
// are 0-dominated (Block-2 at 66.8% code 0, Block-6 at 55.3%). A blank cell
// therefore meant "not forest" *or* "no raster coverage" *or* "the query
// failed" -- `dominant_code` returned a bare `None` for all three.
//
// This column renders the stored raw class and **never leaves a blank cell**.
//
// Owner decisions, 2026-09-30, on the wording:
//   - code 0 renders "0 - Unclassified". The owner was offered "Data not
//     available" and "Unclassified" and chose the latter, correctly: code 0 is a
//     real class in the NASA product (non-forest ground), so the data *is*
//     available, and "Data not available" would have put back the exact false
//     statement D49 removed -- and would have collided with the null case below.
//   - the null case renders "Not determined", never "". The owner's instruction
//     was "The attribute table must not have blank which is now occuring": an
//     empty cell is indistinguishable from a missing field (D48) or from a
//     value that failed to load, and all three mean different things here.
//
// So the three states stay distinguishable *and* all three are visible:
//   0        -> "0 - Unclassified"   (classified; this compartment is not forest)
//   1 / 2 / 3 -> "N - <forest class>" (classified)
//   null     -> "Not determined"      (no raster coverage, or the query failed)
//
// It prefers the live preview's own `dominant_nasa_code` and falls back to the
// persisted column, so a freshly-carved preview shows the answer without a round
// trip, and a block committed before migration 106 still shows its class.
export const NASA_QUALITY_RAW_COLUMN: ColumnDef = {
  key: 'dominant_nasa_code', label: 'NASA Raster Class',
  labelKey: 'attributeTable.col.nasaRawClass',
  width: 150, align: 'center',
  getValue: (f) => {
    const raw = f.properties?.dominant_nasa_code ?? f.properties?.dominant_nasa_quality;
    // No blanks, owner decision 2026-09-30: "The attribute table must not have
    // blank which is now occuring." Every branch returns text, so an empty cell
    // can never be mistaken for a missing value or a missing field (D48).
    if (raw == null) return 'Not determined';
    if (Number(raw) === 0) return '0 · Unclassified';
    const label = NASA_QUALITY_LABEL[Number(raw)];
    return label ? `${raw} · ${label}` : String(raw);
  },
};

// ESA land cover and NDVI forest health (RS-5.4). Owner report, 2026-10-03: the
// "Land Cover" column showed on the un-promoted Auto-Block layer (which builds
// columns from the feature's own property keys) and vanished once promoted
// (which uses this hand-written list). Same bug as NASA above. Labels mirror
// backend `forest_types.ESA_WORLD_COVER` / `FOREST_HEALTH_CLASSES` -- keep in step.
export const ESA_LANDCOVER_LABEL: Record<number, string> = {
  10: 'Tree cover',
  20: 'Shrubland',
  30: 'Grassland',
  40: 'Cropland',
  50: 'Built-up',
  60: 'Bare / sparse vegetation',
  70: 'Snow and ice',
  80: 'Permanent water bodies',
  90: 'Herbaceous wetland',
  95: 'Mangroves',
  100: 'Moss and lichen',
};

export const FOREST_HEALTH_LABEL: Record<number, string> = {
  1: 'Stressed',
  2: 'Poor',
  3: 'Moderate',
  4: 'Healthy',
  5: 'Excellent',
};

export const LANDCOVER_COLUMN: ColumnDef = {
  key: 'dominant_landcover', label: 'Land Cover',
  emptyLabelKey: 'attributeTable.notSet',
  labelKey: 'attributeTable.col.landcover',
  width: 140, align: 'center', editable: true,
  select: Object.entries(ESA_LANDCOVER_LABEL).map(([value, label]) => ({ value, label })),
  getValue: (f) => {
    const code = f.properties?.dominant_landcover;
    return code != null ? String(code) : '';
  },
};

export const FOREST_HEALTH_COLUMN: ColumnDef = {
  key: 'dominant_health_class', label: 'Forest Health',
  emptyLabelKey: 'attributeTable.notSet',
  labelKey: 'attributeTable.col.forestHealth',
  width: 120, align: 'center', editable: true,
  select: Object.entries(FOREST_HEALTH_LABEL).map(([value, label]) => ({ value, label })),
  getValue: (f) => {
    const code = f.properties?.dominant_health_class;
    return code != null ? String(code) : '';
  },
};

// ---------------------------------------------------------------------------
// Management Orientation columns (user report, 2026-09-12) — tied to SFM
// (दिगो वन व्यवस्थापन): a slope-carved block's editable "Management
// Orientation" is auto-suggested at Auto-Block commit time from SFM's own
// classification pipeline (zone -> species -> forest type -> orientation),
// and a read-only "Suggested Orientation" reflects whatever SFM's own live
// cache currently says (updates itself once a field inventory is processed
// and SFM is next rebuilt) — visually flagged when the two disagree, so the
// user can tell at a glance whether their earlier confirmed value still
// matches SFM's latest classification. Both hidden until a block has been
// carved via the slope Auto-Block source (dominant_slope_band populated),
// matching the other 3 classification columns' scoping. Matches
// अनुसूची-१'s exact 3-value terminology, mirrored in
// `sfm.orientation.{Production,Conservation,Protection}` for the SFM tab.
export const MANAGEMENT_ORIENTATION_LABEL: Record<string, string> = {
  Production: 'Production oriented',
  Conservation: 'Conservation oriented',
  Protection: 'Protection',
};

// Owner report 2026-10-01: orientation is now filled at promotion for EVERY
// Auto-Block source (SFM falls back to the slope raster when a row has no
// slope band), so a row that already carries an orientation must show it
// even when it wasn't slope-carved -- otherwise an Aspect/NASA/Canopy
// layer's real values would be hidden behind a blank '-'.
function _isSlopeCarved(f: GeoJSON.Feature): boolean {
  const p = f.properties;
  return (
    p?.dominant_slope_band != null ||
    p?.suggested_orientation != null ||
    p?.management_orientation != null
  );
}

// Orientation comes from SFM, which decides the forest type from the field-inventory plots. Until the inventory is uploaded the
// honest cell text is the instruction, not a blank (owner rule 2026-10-10: the system tells the user to upload the sample field
// inventory).
function _needsInventoryCell(): React.ReactElement {
  return React.createElement(
    'span',
    { title: i18n.t('attributeTable.needsFieldInventoryWhy'), style: { fontStyle: 'italic', opacity: 0.75 } },
    i18n.t('attributeTable.needsFieldInventory'),
  );
}

export const MANAGEMENT_ORIENTATION_COLUMN: ColumnDef = {
  key: 'management_orientation', label: 'Management Orientation',
  labelKey: 'attributeTable.col.managementOrientation',
  width: 150, align: 'center', editable: true,
  emptyLabelKey: 'attributeTable.needsFieldInventory',
  select: Object.entries(MANAGEMENT_ORIENTATION_LABEL).map(([value, label]) => ({ value, label })),
  // Visibility is gated by _isSlopeCarved(f) in getValue — shows as soon as a
  // block is slope-carved (offering the auto-suggested default), not only once
  // a user has already set it by hand.
  getValue: (f) => (_isSlopeCarved(f) ? String(f.properties?.management_orientation ?? '') : null),
};

export const SUGGESTED_ORIENTATION_COLUMN: ColumnDef = {
  key: 'suggested_orientation', label: 'Suggested Orientation',
  labelKey: 'attributeTable.col.suggestedOrientation',
  width: 150, align: 'center',
  getValue: (f) => (_isSlopeCarved(f) ? String(f.properties?.suggested_orientation ?? '') : null),
  render: (value, f) => {
    if (!_isSlopeCarved(f)) return React.createElement('span', null, value ? String(value) : '-');
    if (!value) return _needsInventoryCell();
    const confirmed = f.properties?.management_orientation;
    const mismatch = confirmed != null && confirmed !== value;
    const label = MANAGEMENT_ORIENTATION_LABEL[String(value)] ?? String(value);
    if (!mismatch) return React.createElement('span', null, label);
    return React.createElement(
      'span',
      {
        title: 'Differs from the confirmed Management Orientation',
        style: {
          background: '#fff3cd', color: '#7a5b00', borderRadius: 4,
          padding: '1px 6px', display: 'inline-flex', alignItems: 'center', gap: 4,
        },
      },
      '⚠', label,
    );
  },
};

// User report, 2026-09-15: a Production/Conservation split within the same
// slope class (or same slope value across compartments) reads as
// contradictory without a visible reason -- orientation is actually driven
// by forest type first, with slope only overriding it at specific bands
// (सि.नं. reference; D7). Read-only, same hideIfEmpty/_isSlopeCarved gating
// as the two orientation columns above. English is the primary cell text;
// the Nepali reason is the hover title, matching the ⚠ mismatch tooltip
// pattern in SUGGESTED_ORIENTATION_COLUMN.render above.
export const ORIENTATION_JUSTIFICATION_COLUMN: ColumnDef = {
  key: 'orientation_justification_en', label: 'Justification',
  labelKey: 'attributeTable.col.orientationJustification',
  width: 280, align: 'left',
  getValue: (f) => (_isSlopeCarved(f) ? String(f.properties?.orientation_justification_en ?? '') : null),
  render: (value, f) => {
    if (!_isSlopeCarved(f)) return React.createElement('span', null, '-');
    if (!value) return _needsInventoryCell();
    const ne = f.properties?.orientation_justification_ne;
    return React.createElement('span', { title: ne ? String(ne) : undefined }, String(value));
  },
};

// Workspace "Analysis maps" (SFM): the classification the Sustainable FM tab produced, merged onto the unit features
// by `mergeSfmProps` (lib/sfmFeatureProps.ts). READ-ONLY here; a unit the tab has not classified shows "-".
const _sfmCol = (key: string, label: string, width: number, extra: Partial<ColumnDef> = {}): ColumnDef => ({
  key, label, labelKey: `attributeTable.col.${key}`, width, align: 'center', sortable: true, ...extra,
});
export const SFM_COLUMNS: ColumnDef[] = [
  _sfmCol('sfm_type', 'SFM Type', 90, {
    getValue: (f) => {
      const v = f.properties?.sfm_type;
      return v == null ? null : v === 'none' ? '-' : `Type-${v}`;
    },
    sortValue: (f) => {
      const v = Number(f.properties?.sfm_type);
      return Number.isFinite(v) ? v : null;
    },
  }),
  _sfmCol('sfm_state', 'SFM State', 110),
  _sfmCol('sfm_land_class', 'Land Class', 100),
  _sfmCol('sfm_plot_count', 'Sample Plots', 90),
  _sfmCol('sfm_orientation', 'SFM Orientation', 120, {
    getValue: (f) => {
      const v = f.properties?.sfm_orientation;
      return v == null ? null : v === 'none' ? '-' : String(v);
    },
  }),
  _sfmCol('sfm_gs', 'Stock ≥40 cm (m³/ha)', 130, {
    getValue: (f) => {
      const v = f.properties?.sfm_gs;
      return v == null ? null : Number(v).toFixed(1);
    },
    sortValue: (f) => (f.properties?.sfm_gs == null ? null : Number(f.properties.sfm_gs)),
  }),
  _sfmCol('sfm_slope_band', 'SFM Slope Band', 110),
];

// Hazard & Erosion, per unit (read-only; from the cached maps via `mergeHazardProps`). "-" = layer not computed.
const _pct = (key: string) => (f: GeoJSON.Feature) => (f.properties?.[key] == null ? null : Number(f.properties[key]).toFixed(1));
const _num = (key: string) => (f: GeoJSON.Feature) => (f.properties?.[key] == null ? null : Number(f.properties[key]));
const _hzCol = (key: string, label: string, width: number, extra: Partial<ColumnDef> = {}): ColumnDef => ({
  key, label, labelKey: `attributeTable.col.${key}`, width, align: 'center', sortable: true, ...extra,
});
export const HAZARD_COLUMNS: ColumnDef[] = [
  _hzCol('hz_soil_mean', 'Soil Loss (t/ha/yr)', 130, { getValue: (f) => (f.properties?.hz_soil_mean == null ? null : Number(f.properties.hz_soil_mean).toFixed(1)), sortValue: _num('hz_soil_mean') }),
  _hzCol('hz_soil_severe_pct', 'Severe Soil Loss %', 130, { getValue: _pct('hz_soil_severe_pct'), sortValue: _num('hz_soil_severe_pct') }),
  _hzCol('hz_lsi_class_en', 'Landslide Class (relative)', 150),
  _hzCol('hz_lsi_high_pct', 'High+ Landslide %', 120, { getValue: _pct('hz_lsi_high_pct'), sortValue: _num('hz_lsi_high_pct') }),
  _hzCol('hz_fs_unsafe_pct', 'Unsafe Slope %', 110, { getValue: _pct('hz_fs_unsafe_pct'), sortValue: _num('hz_fs_unsafe_pct') }),
  _hzCol('hz_prone_pct', 'Relatively High %', 120, { getValue: _pct('hz_prone_pct'), sortValue: _num('hz_prone_pct') }),
];

// Field inventory, per unit (read-only; the stored summary via `mergeUnitProps`). "-" = no inventory for the unit.
const _fiCol = (key: string, label: string, width: number, numeric = true): ColumnDef => ({
  key, label, labelKey: `attributeTable.col.${key}`, width, align: 'center', sortable: true,
  ...(numeric ? {
    getValue: (f: GeoJSON.Feature) => (f.properties?.[key] == null ? null : Number(f.properties[key]).toLocaleString(undefined, { maximumFractionDigits: 2 })),
    sortValue: (f: GeoJSON.Feature) => (f.properties?.[key] == null ? null : Number(f.properties[key])),
  } : {}),
});
// A condition with its CAUSE in brackets: "Weak (seedlings 1,200/ha < 2,000, saplings 300/ha < 800)". The cause is worked out by the
// server from the unit's stored numbers and the rule's own limits (`unit_maps.condition_why`), in the language of the app.
const _conditionCol = (key: string, label: string, width: number): ColumnDef => ({
  key, label, labelKey: `attributeTable.col.${key}`, width, align: 'left', sortable: true,
  getValue: (f: GeoJSON.Feature) => {
    const v = f.properties?.[key];
    if (v == null || v === '') return null;
    const ne = String(i18n.language ?? '').startsWith('ne');
    const why = f.properties?.[ne ? `${key}_why_ne` : `${key}_why`] ?? f.properties?.[`${key}_why`];
    return why ? `${v} (${why})` : String(v);
  },
  sortValue: (f: GeoJSON.Feature) => (f.properties?.[key] == null ? null : String(f.properties[key])),
});
export const FI_COLUMNS: ColumnDef[] = [
  _fiCol('fi_stock', 'Growing Stock (m\u00b3/ha)', 130),
  _fiCol('fi_basal_area', 'Basal Area (m\u00b2/ha)', 120),
  _fiCol('fi_aah', 'AAH (m\u00b3/ha/yr)', 110),
  _fiCol('fi_mai', 'MAI (m\u00b3/ha/yr)', 110),
  _fiCol('fi_mai_pct', 'MAI %', 80),
  _fiCol('fi_carbon', 'Carbon (tC/ha)', 110),
  _fiCol('fi_biomass', 'Biomass (t/ha)', 110),
  _fiCol('fi_co2', 'CO\u2082e (t/ha)', 100),
  _fiCol('fi_regeneration', 'Regeneration (/ha)', 120),
  _fiCol('fi_sapling', 'Saplings (/ha)', 100),
  _fiCol('fi_pole', 'Poles (/ha)', 90),
  _fiCol('fi_tree', 'Trees (/ha)', 90),
  _fiCol('fi_plots', 'Sample Plots (field inventory)', 120),
  _conditionCol('fi_condition', 'Forest Condition (field inventory)', 260),
  _conditionCol('fi_regen_condition', 'Regeneration Condition', 300),
];

// Run analysis, per unit (read-only; `an_*` values from GET /calculations/{id}/unit-analysis, merged by `mergeAnalysisProps`).
// Every value the analysis computed for the unit's own polygon, at every level; "-" = the analysis has not been run for it.
// Which values, their subject and their header live in `analysisFields.ts` (the table's "Raster analysis" sub-views read it too).
export const ANALYSIS_COLUMNS: ColumnDef[] = ANALYSIS_FIELDS.map((fld) => ({
  key: `an_${fld.key}`,
  label: fld.label,
  labelKey: `analysisColumn.${fld.key}`,
  width: 130,
  align: 'center' as const,
  sortable: true,
  getValue: (feat: GeoJSON.Feature) => {
    return analysisDisplayValue(fld.key, feat.properties?.[`an_${fld.key}`]);
  },
  sortValue: (feat: GeoJSON.Feature) => {
    const v = feat.properties?.[`an_${fld.key}`];
    return v == null ? null : (Number.isFinite(Number(v)) ? Number(v) : String(v));
  },
}));

/** How a sub-area stands with the yearly plan (the server's states), as the table's "Yearly plan" column shows it. */
export const SUB_AREA_PLAN_STATE_LABEL: Record<string, string> = {
  planned: 'Planned',
  needs_plan: 'Needs a plan',
  exempt: 'Not needed',
  no_unit: 'In no unit',
  no_id: 'Fix identity',
};

/**
 * A refused user group write (for example over the 5,000 ha limit) used to come back as a normal-looking body that the caller took for the
 * saved feature. Refusals are thrown instead, with the server's own words in the user's language.
 */
async function userGroupWriteResult(resp: Response): Promise<any> {
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(readDetail(body?.detail) || `HTTP ${resp.status}`);
  return body;
}

function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('access_token');
  const headers = new Headers(options.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  headers.set('Content-Type', 'application/json');
  // no-store: layer data is mutated in-place (boundary set/merge, block edits),
  // so refetches after a geometryVersion bump must never be served from the
  // browser HTTP cache (a stale empty boundary would hide new geometry).
  return fetch(url, { ...options, headers, cache: 'no-store' });
}

/**
 * `GET /yearly-activities/calculations/{id}/drawn-features` -> map features.
 *
 * The API contract types `geometry` as a GeoJSON *string* (DrawnFeatureBase.geometry), but
 * Leaflet needs the object; handing it the string drew nothing, so the Activity Features layer
 * stayed blank even once the server sent rows. A feature whose geometry cannot be read is
 * skipped rather than allowed to take the whole layer down.
 */
export function activityFeaturesFromApi(data: unknown, labelOptions: LabelOptions = {}): GeoJSON.Feature[] {
  if (!Array.isArray(data)) return [];
  const out: GeoJSON.Feature[] = [];
  for (const f of data as any[]) {
    let geometry: any = f?.geometry;
    if (typeof geometry === 'string') {
      try { geometry = JSON.parse(geometry); } catch { continue; }
    }
    if (!geometry || typeof geometry !== 'object' || !geometry.type) continue;
    const props: Record<string, unknown> = {
      id: f.id, name: f.properties?.name, year: f.properties?.year, years: f.properties?.years,
      length_m: f.properties?.length_m, area_sqm: f.properties?.area_sqm, ...f.properties,
      // Which activity this is, so the layer can say so instead of "Feature 1".
      activity_name: f.activity_name ?? null,
      program_name: f.program_name ?? null,
      block_name: f.block_name ?? null,
      created_at: f.created_at ?? null,
      // The plan line this place belongs to and what it shares with its sibling places (plan section 5.2): the
      // quantity is the LINE's, not the place's.
      proposed_activity_id: f.proposed_activity_id ?? null,
      plan_quantity: f.plan_quantity ?? null,
      plan_unit: f.plan_unit ?? null,
      shared_count: f.shared_count ?? 1,
      // The symbol kind, decided by the server: the feature's own kind, else its activity's default.
      kind: f.kind || '',
    };
    props.display_label = activityFeatureLabel(props, labelOptions);
    out.push({ type: 'Feature', geometry, properties: withGeoProps(props, geometry) });
  }
  // Two features that would read the same ("Nursery · Year 1") get (1) and (2).
  const labels = disambiguateLabels(
    out.map((f) => ({ label: String(f.properties?.display_label ?? ''), createdAt: f.properties?.created_at as string | null })),
    labelOptions.format,
  );
  out.forEach((f, i) => { if (f.properties) f.properties.display_label = labels[i]; });
  return out;
}

export interface LayerGeomanMode {
  mode: string;
  label: string;
  labelNp?: string;
  icon: string;
  subType?: 'point' | 'line' | 'polygon';
  allowSelfIntersection?: boolean;
  categoryRequired?: boolean;
}

export interface ToolbarButtonConfig {
  mode: string;
  label: string;
  icon: string;
}

export type LayerTypeId = 'boundary' | 'user_group' | 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments' | 'sub_areas' | 'activity_features' | 'sample_plots' | 'stem_mapping' | 'fieldbook';
export type ToolbarMode = 'select' | 'split' | 'merge' | 'move' | 'draw_polygon' | 'draw_point' | 'draw_line' | 'vertex_edit' | 'subarea_category' | null;

export interface CategoryDef {
  key: string;
  label: string;
  labelNp: string;
  styleKey?: string;
  contrastColor?: string;
  color?: string;
  isExcluded?: boolean;
}

export interface DataSource {
  fetch: (calculationId: string) => Promise<GeoJSON.Feature[]>;
  create: (calculationId: string, feature: GeoJSON.Feature) => Promise<GeoJSON.Feature>;
  update: (calculationId: string, featureId: string, feature: Partial<GeoJSON.Feature>) => Promise<GeoJSON.Feature>;
  delete: (calculationId: string, featureId: string) => Promise<void>;
}

export interface ColumnDef {
  key: string;
  label: string;
  labelKey?: string;
  width: number | 'flex';
  sortable?: boolean;
  /** Raw comparable value for sorting (owner request, 2026-09-15 — the
   *  underlying bug behind "sorting Area looks random"). Sorting falls back
   *  to `properties[key]`, which is wrong for a column whose display value
   *  is computed under a DIFFERENT key (e.g. `area`'s real data lives at
   *  `area_hectares`) and/or whose `getValue` formats a number into a
   *  string (`toFixed`), which then sorts lexicographically ("10" < "5").
   *  Set this whenever `key` isn't the raw property name, or `getValue`
   *  returns a formatted string for an otherwise-numeric field. */
  sortValue?: (feature: GeoJSON.Feature) => number | string | null | undefined;
  editable?: boolean;
  /* `defaultHidden` and `hideIfEmpty` are GONE, deliberately (owner report,
   * 2026-09-30: "Not all value are under the table some field are missing.
   * Whether it is small in size, regardless of this all table value should be
   * presented."). Both were read in exactly one place -- AttributeTable's
   * `isVisibleByDefault` -- and both made a field DISAPPEAR rather than appear
   * empty, which is the wrong failure mode for a value a user is meant to set:
   *
   *  - `hideIfEmpty` on the 4 Auto-Block class columns meant a forest carved by
   *    one source could not even SEE (let alone fill in) the other three, so
   *    the NASA class was unreachable from the table on a slope-carved forest.
   *  - `defaultHidden` hid 11 further fields outright.
   *
   * Every column is now visible by default and the Columns… chooser is the
   * only way to hide one. Do not reintroduce either flag to unclutter a table:
   * a column the user cannot see is a field they cannot set, and the width
   * cost is paid in the chooser instead. */
  align?: 'left' | 'center' | 'right';
  render?: (value: any, feature: GeoJSON.Feature) => React.ReactNode;
  getValue?: (feature: GeoJSON.Feature, index: number) => any;
  /** Renders an editable `<select>` drop-down in every cell (Phase 2 sub-areas category). */
  select?: Array<{ value: string; label: string }>;
  /** Label for the unset state of a `select` cell, as an i18n key.
   *
   * `AttributeTable` injects an empty-valued option into every `select` (it must,
   * so a value can be cleared) and that option read `-`. Owner decision
   * 2026-09-30: "The attribute table must not have blank which is now occuring."
   * A dash is not blank, but it says nothing, and on the Auto-Block class columns
   * "-" was ambiguous between "this source did not classify it" and "nobody has
   * chosen a value yet" -- the same collapse D48/RS-2.14 just undid one level up.
   *
   * Scoped deliberately: set it on the class columns, where the unset state is
   * meaningful. Leave it off elsewhere and those keep "-", which is right for a
   * genuinely optional free-text field. Note the option is still *cleared* to
   * `''` on save, so this is display text only -- it never persists a value. */
  emptyLabelKey?: string;
  /** Renders a per-feature style editor wired to `onSaveProperty` (P3.4).
   *  `color` → `<input type="color">` + a clear affordance; `opacity` → a
   *  0/25/50/75/100 % `<select>`. */
  editControl?: 'color' | 'opacity' | 'years';
  /** The raw value a `select` cell shows as chosen, when `getValue` returns a label (so sorting and export
   *  keep the label). */
  selectValue?: (feature: GeoJSON.Feature) => string;
}

export interface LayerTypeConfig {
  id: LayerTypeId;
  label: string;
  labelNp: string;
  icon: string;
  /**
   * Canonical position in the layer panel AND in the map's draw (z) order:
   * bottom-most = 0. Half-steps are allowed so a layer can be inserted between
   * two existing ones. This is the DEFAULT order — a user who reorders rows
   * gets an explicit numeric entry in `workspaceStore.layerOrder`, which
   * overrides this for that layer only.
   */
  order: number;
  /**
   * Whether the layer starts visible in a fresh workspace. This is the single
   * source of truth: `workspaceStore.initialLayerVisibility` is built from it,
   * so the panel, the map, the legend and the export all agree. Before this
   * field existed the default lived in a hand-written 4-entry map in
   * `workspaceStore` that listed 4 of 11 layers, and every read site fell back
   * to "visible" for the other 7 — so the panel's show/hide column and the
   * registry could drift apart silently.
   */
  defaultVisible: boolean;
  geometryTypes: string[];
  editable: boolean | ((context: { structure_locked: boolean }) => boolean);
  styleKey: keyof typeof STYLE_PRESETS;
  dataSource: DataSource;
  geomanModes: LayerGeomanMode[];
  columns: ColumnDef[];
  i18nPrefix: string;
  supportsSubLayers?: boolean;
  subLayers?: Array<{
    id: string;
    label: string;
    labelNp: string;
    geometryType: string;
    styleModifier?: Partial<L.PathOptions>;
  }>;
  alwaysReadOnly?: boolean;
  useHalo?: boolean;
  /** The map renderer assigns a distinct hue per feature (blocks/compartments/
   *  sub-compartments/sub-areas). A layer-level custom colour is ignored unless
   *  the style dialog's "override palette" is on (WORKSPACE_LAYER_STYLING_PLAN.md D2). */
  usesPalette?: boolean;
  supportsCategories?: boolean;
  categories?: CategoryDef[];
  isLockable?: boolean;
  lockReason?: string | null;
  labelFields?: string[];
  canRename?: boolean;
  canDuplicate?: boolean;
  canRemove?: boolean;
}

/**
 * Unified SSOT descriptor — every layer (built-in or imported) conforms to
 * this shape so the UI (layer panel, context menu, labels) treats them all
 * through one code path.
 */
export interface LayerDescriptor {
  key: string;
  kind: 'builtin' | 'imported';
  id: string;
  name: string;
  nameNp: string;
  icon: string;
  geometryTypes: string[];
  featureCount: number;
  editable: boolean;
  labelFields: string[];
  canRename: boolean;
  canDuplicate: boolean;
  canRemove: boolean;
  alwaysReadOnly?: boolean;
  supportsSubLayers?: boolean;
  subLayers?: LayerTypeConfig['subLayers'];
}

import { STYLE_PRESETS } from './layerStyles';
import { SUB_AREA_CATEGORIES, ALL_SUB_AREA_CATEGORIES, getCategoryLabel } from './subAreaCategories';

const nullDataSource: DataSource = {
  fetch: async () => [],
  create: async () => { throw new Error('Read-only layer'); },
  update: async () => { throw new Error('Read-only layer'); },
  delete: async () => { throw new Error('Read-only layer'); },
};

export const LAYER_REGISTRY: Record<LayerTypeId, LayerTypeConfig> = {
  boundary: {
    id: 'boundary',
    label: 'Forest Boundary',
    labelNp: 'वन सीमा',
    icon: '═',
    order: 0,
    defaultVisible: true,
    geometryTypes: ['Polygon', 'MultiPolygon'],
    editable: true,
    styleKey: 'forest_boundary',
    dataSource: {
      ...nullDataSource,
      // BOUNDARY_PIECES_PLAN.md P4: one attribute row per disjoint piece,
      // backed by the real `forest_boundary_pieces` table (persistent id +
      // rename) — not decomposed from raw MultiPolygon coordinates on the
      // fly any more (that gave a piece a position-derived label like
      // "Forest (2/3)" that couldn't be renamed and didn't survive a redraw
      // in the same slot). Falls back to the old on-the-fly split only if a
      // forest somehow has a boundary but zero piece rows (pre-P1 data that
      // missed the backfill) so a boundary can never go invisible.
      fetch: async (calcId) => {
        const piecesResp = await authFetch(`/api/forests/calculations/${calcId}/boundary-pieces`);
        if (piecesResp.ok) {
          const piecesData = await piecesResp.json();
          const pieces = piecesData?.pieces ?? [];
          if (pieces.length > 0) {
            return pieces.map((p: any) => ({
              type: 'Feature' as const,
              geometry: p.geometry,
              properties: withGeoProps({ id: p.id, name: p.name, area_hectares: p.area_hectares }, p.geometry),
            }));
          }
        }
        const response = await authFetch(`/api/forests/calculations/${calcId}`);
        const data = await response.json();
        const geom = data?.geometry ?? data?.result_data?.geometry;
        if (!geom) return [];
        const boundaryName = data?.forest_name ?? data?.result_data?.boundary_name ?? '';
        if (geom.type === 'MultiPolygon' && Array.isArray(geom.coordinates) && geom.coordinates.length > 1) {
          const n = geom.coordinates.length;
          return geom.coordinates.map((rings: number[][][], i: number) => {
            const partGeom = { type: 'Polygon' as const, coordinates: rings };
            return {
              type: 'Feature' as const,
              geometry: partGeom,
              properties: withGeoProps(
                { id: `boundary#${i}`, name: n > 1 ? `${boundaryName} (${i + 1}/${n})` : boundaryName, part_index: i, part_count: n },
                partGeom,
              ),
            };
          });
        }
        return [{ type: 'Feature', geometry: geom, properties: withGeoProps({ id: 'boundary', name: boundaryName, part_index: 0, part_count: 1 }, geom) }];
      },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/boundary-pieces/${featureId}`, {
          method: 'PATCH', body: JSON.stringify(feature),
        });
        return resp.json();
      },
    },
    geomanModes: [],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', editable: true, getValue: (f) => f?.properties?.name || 'Forest Boundary' },
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', getValue: (f) => f.properties?.area_hectares?.toFixed(2) },
      { key: 'perimeter', label: 'Perimeter (m)', labelKey: 'attributeTable.col.perimeter', width: 110, align: 'right', getValue: (f) => f.properties?.perimeter_m?.toFixed(0) },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
    ],
    i18nPrefix: 'layer.boundary',
    useHalo: false,
    labelFields: ['name', 'area_hectares'],
  },

  // User Group Boundary — the settlement catchment used for household /
  // settlement / land-cover analysis. Single feature, like the forest
  // boundary: draw / import / auto-buffer each REPLACE it (the backend
  // `_persist_extent` clears the prior row first). USER_GROUP_BOUNDARY_PLAN.md.
  user_group: {
    id: 'user_group',
    label: 'User Group Boundary',
    labelNp: 'उपयोग समूह सीमा क्षेत्र',
    icon: '⬡',
    order: 0.5,
    defaultVisible: false,
    geometryTypes: ['Polygon', 'MultiPolygon'],
    editable: (ctx) => !ctx.structure_locked,
    styleKey: 'user_group',
    dataSource: {
      fetch: async (calcId) => {
        // P7e: ONE FEATURE PER STORED ROW. Each user-group polygon is its own row
        // and therefore its own selectable, vertex-editable, cuttable feature with
        // its own attribute row (owner's model, 2026-09-28).
        //
        // This replaces a per-island split of a single row's MultiPolygon. The
        // split was a workaround for the old one-row-per-calculation model and it
        // is exactly what made the client and the server disagree: the client
        // invented `user_group#<id>#<part>` ids and the server had to splice parts
        // back into a MultiPolygon. There is no part index to invent now, because
        // a row IS a polygon. Part-index drift - a cut shifting every later
        // island's index - is gone with it, not merely guarded against.
        //
        // Note the plural endpoint: the singular `/user-group/extent` is the
        // UNION, which is what the analysis wants, not what the map layer wants.
        const resp = await authFetch(`/api/calculations/${calcId}/user-group/extents`);
        if (!resp.ok) return [];
        const data = await resp.json();
        const features = data?.features;
        if (!Array.isArray(features) || features.length === 0) return [];
        return features.map((f: any) => ({
          type: 'Feature' as const,
          geometry: f.geometry,
          properties: withGeoProps({
            ...(f.properties ?? {}),
            id: String(f.id ?? f.properties?.id ?? ''),
          }, f.geometry),
        }));
      },
      // P7e: create APPENDS a row (a second polygon is a second feature);
      // update targets that row by id. Both used to go through the replace-only
      // manual endpoint, which is what made drawing a second boundary impossible.
      create: async (calcId, feature) => {
        const resp = await authFetch(`/api/calculations/${calcId}/user-group/manual`, {
          method: 'POST', body: JSON.stringify({ geometry: feature.geometry }),
        });
        return userGroupWriteResult(resp);
      },
      update: async (calcId, _featureId, feature) => {
        const resp = await authFetch(`/api/calculations/${calcId}/user-group/manual`, {
          method: 'POST', body: JSON.stringify({ geometry: feature.geometry }),
        });
        return userGroupWriteResult(resp);
      },
      delete: async (calcId, featureId) => {
        // P7e: one row per feature, so delete that row. The id-less route deletes
        // the whole group, which is right for "clear the layer" and wrong for
        // removing one polygon the user selected.
        await authFetch(
          `/api/calculations/${calcId}/user-group/${encodeURIComponent(String(featureId ?? ''))}`,
          { method: 'DELETE' },
        );
      },
    },
    // Draw REPLACES the single extent (single-feature model), and in-place
    // vertex-edit / split act on the one stored row. No `drag`: whole-feature
    // move is a point-only gesture, so a polygon layer would only offer a
    // button that immediately refuses itself.
    geomanModes: [
      { mode: 'drawPolygon', label: 'Draw', labelNp: 'कोर्नुहोस्', icon: '▄', allowSelfIntersection: false },
      { mode: 'edit', label: 'Edit', icon: '◉', allowSelfIntersection: false },
      { mode: 'cut', label: 'Split', icon: '✂', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', getValue: (f) => f?.properties?.name || 'User Group Boundary' },
      { key: 'source', label: 'Source', labelKey: 'attributeTable.col.source', width: 130, align: 'center', getValue: (f) => {
        const s = f.properties?.source_type;
        if (s === 'auto_buffer') return f.properties?.buffer_distance_m ? `auto_buffer (${f.properties.buffer_distance_m} m)` : 'auto_buffer';
        return s || '-';
      } },
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', getValue: (f) => f.properties?.area_hectares?.toFixed(2) ?? '-' },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
    ],
    i18nPrefix: 'layer.user_group',
    useHalo: true,
    isLockable: false,
    labelFields: ['name', 'source_type', 'area_hectares'],
  },

  blocks: {
    id: 'blocks',
    label: 'Blocks',
    labelNp: 'ब्लकहरू',
    icon: '▦',
    order: 1,
    defaultVisible: true,
    geometryTypes: ['Polygon', 'MultiPolygon'],
    editable: (ctx) => !ctx.structure_locked,
    styleKey: 'blocks',
    dataSource: {
      fetch: async (calcId) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/blocks`);
        const data = await resp.json();
        return (data?.blocks || []).map((b: any, index: number) => ({
          type: 'Feature',
          geometry: b.geometry,
          properties: withGeoProps({ id: b.id, name: b.name, area_hectares: b.area_hectares, colorIndex: index, working_circle: b.working_circle || 'production', style: b.style ?? null, forest_condition: b.forest_condition ?? null, ...b }, b.geometry),
        }));
      },
      // A unit is never created by posting a bare feature: `POST .../blocks` is "create blocks from
      // polygon mapping" and DELETES every block of the forest first. Units come from the operations
      // that keep the area rule (draw/polygon-from-points, paste, divide, cut, merge, auto-block), and
      // nothing calls this. Rejecting makes a future caller fail loudly instead of wiping the forest.
      create: async () => { throw new Error('Units are created by draw / paste / divide, not by posting a feature'); },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'PATCH', body: JSON.stringify(feature) });
        return resp.json();
      },
      delete: async (calcId, featureId) => {
        await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'DELETE' });
      },
    },
    geomanModes: [
      { mode: 'edit', label: 'Edit', icon: '◉', allowSelfIntersection: false },
      { mode: 'drag', label: 'Drag', icon: '⊕', allowSelfIntersection: false },
      { mode: 'cut', label: 'Split', icon: '✂', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', editable: true, sortable: true, getValue: (f) => f.properties?.name || 'Unnamed' },
      { key: 'block_name', label: 'Block Name', labelKey: 'attributeTable.col.block_name', width: 120, editable: true, sortable: true, getValue: (f) => f.properties?.block_name || '-' },
      { key: 'natural_name', label: 'Natural Name', labelKey: 'attributeTable.col.natural_name', width: 120, editable: true, getValue: (f) => f.properties?.natural_name || '-' },
      SLOPE_BAND_COLUMN,
      ASPECT_COLUMN,
      CANOPY_CLASS_COLUMN,
  NASA_QUALITY_COLUMN,
  NASA_QUALITY_RAW_COLUMN,
      LANDCOVER_COLUMN,
      FOREST_HEALTH_COLUMN,
      MANAGEMENT_ORIENTATION_COLUMN,
      SUGGESTED_ORIENTATION_COLUMN,
      ...SFM_COLUMNS,
      ...HAZARD_COLUMNS,
      ...FI_COLUMNS,
      ...ANALYSIS_COLUMNS,
      ORIENTATION_JUSTIFICATION_COLUMN,
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', sortable: true, getValue: (f) => f.properties?.area_hectares?.toFixed(2), sortValue: (f) => f.properties?.area_hectares },
      { key: 'sub_areas', label: 'Sub-Areas', labelKey: 'attributeTable.col.sub_areas', width: 90, align: 'center', getValue: (f) => f.properties?.sub_area_count || 0 },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
      { key: 'locked', label: 'Lock', labelKey: 'attributeTable.col.locked', width: 60, align: 'center', getValue: (f) => f.properties?.locked ? '🔒' : '☐' },
      ...STYLE_COLUMNS,
    ],
    i18nPrefix: 'layer.blocks',
    usesPalette: true,
    useHalo: true,
    labelFields: ['name', 'area_hectares', 'dominant_slope_band', 'dominant_aspect', 'dominant_canopy_class', 'dominant_nasa_quality', 'dominant_nasa_code', 'dominant_landcover', 'dominant_health_class', 'id'],
  },

  sub_blocks: {
    id: 'sub_blocks',
    label: 'Sub-Blocks',
    labelNp: 'उप-ब्लकहरू',
    icon: '▦',
    order: 1.5,
    defaultVisible: true,
    geometryTypes: ['Polygon', 'MultiPolygon'],
    editable: (ctx) => !ctx.structure_locked,
    styleKey: 'sub_blocks',
    dataSource: {
      // FS-4a.16: the block branch's own "one level deeper" layer. No
      // dedicated block-tree endpoint exists (`/api/forests/.../blocks`
      // returns top-level blocks only) — the compartment-tree endpoint
      // already returns every `forest_blocks` row regardless of branch
      // (I10), so this mirrors `sub_compartments`' own fetch exactly,
      // just filtered to the OTHER branch (`!node.is_compartment`).
      fetch: async (calcId) => {
        const resp = await authFetch(`/api/compartments/calculations/${calcId}/compartment-tree`);
        const data = await resp.json();
        const features: GeoJSON.Feature[] = [];

        function extractSubBlocks(nodes: any[], level: number, parentId: string | null = null) {
          for (const node of nodes) {
            if (!node.is_compartment && isUndividedNode(node) && node.geometry) {
              features.push({
                type: 'Feature',
                geometry: node.geometry,
                properties: withGeoProps({
                  id: node.id,
                  name: node.name,
                  area_hectares: node.area_hectares,
                  block_name: node.block_name,
                  natural_name: node.natural_name,
                  dominant_slope_band: node.dominant_slope_band ?? null,
                  dominant_aspect: node.dominant_aspect ?? null,
                  dominant_canopy_class: node.dominant_canopy_class ?? null,
                  dominant_nasa_quality: node.dominant_nasa_quality ?? null,
                  dominant_nasa_code: node.dominant_nasa_code ?? null,
                  dominant_landcover: node.dominant_landcover ?? null,
                  dominant_health_class: node.dominant_health_class ?? null,
                  management_orientation: node.management_orientation ?? null,
                  suggested_orientation: node.suggested_orientation ?? null,
                  orientation_justification_ne: node.orientation_justification_ne ?? null,
                  orientation_justification_en: node.orientation_justification_en ?? null,
                  division_level: node.division_level,
                  color: node.color,
                  working_circle: node.working_circle || 'production',
                  style: node.style ?? null,
                  forest_condition: node.forest_condition ?? null,
                  parent_block_name: node.parent_block_name,
                  parent_block_id: node.parent_block_id ?? parentId,
                  tree_count: node.tree_count,
                  colorIndex: features.length,
                }, node.geometry),
              });
            }
            if (node.children && node.children.length > 0) {
              extractSubBlocks(node.children, level + 1, node.id ?? parentId);
            }
          }
        }

        if (data?.blocks) {
          extractSubBlocks(data.blocks, 0);
        }
        return features;
      },
      // A unit is never created by posting a bare feature: `POST .../blocks` is "create blocks from
      // polygon mapping" and DELETES every block of the forest first. Units come from the operations
      // that keep the area rule (draw/polygon-from-points, paste, divide, cut, merge, auto-block), and
      // nothing calls this. Rejecting makes a future caller fail loudly instead of wiping the forest.
      create: async () => { throw new Error('Units are created by draw / paste / divide, not by posting a feature'); },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'PATCH', body: JSON.stringify(feature) });
        return resp.json();
      },
      delete: async (calcId, featureId) => {
        await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'DELETE' });
      },
    },
    geomanModes: [
      { mode: 'edit', label: 'Edit', icon: '◉', allowSelfIntersection: false },
      { mode: 'drag', label: 'Drag', icon: '⊕', allowSelfIntersection: false },
      { mode: 'cut', label: 'Split', icon: '✂', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', editable: true, sortable: true, getValue: (f) => f.properties?.name || 'Unnamed' },
      { key: 'block_name', label: 'Block Name', labelKey: 'attributeTable.col.block_name', width: 120, editable: true, sortable: true, getValue: (f) => f.properties?.block_name || '-' },
      { key: 'natural_name', label: 'Natural Name', labelKey: 'attributeTable.col.natural_name', width: 120, editable: true, getValue: (f) => f.properties?.natural_name || '-' },
      SLOPE_BAND_COLUMN,
      ASPECT_COLUMN,
      CANOPY_CLASS_COLUMN,
  NASA_QUALITY_COLUMN,
  NASA_QUALITY_RAW_COLUMN,
      LANDCOVER_COLUMN,
      FOREST_HEALTH_COLUMN,
      MANAGEMENT_ORIENTATION_COLUMN,
      SUGGESTED_ORIENTATION_COLUMN,
      ...SFM_COLUMNS,
      ...HAZARD_COLUMNS,
      ...FI_COLUMNS,
      ...ANALYSIS_COLUMNS,
      ORIENTATION_JUSTIFICATION_COLUMN,
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', sortable: true, getValue: (f) => f.properties?.area_hectares?.toFixed(2), sortValue: (f) => f.properties?.area_hectares },
      { key: 'parent', label: 'Parent Block', labelKey: 'attributeTable.col.parentBlock', width: 120, getValue: (f) => f.properties?.parent_block_name || '-' },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
      ...STYLE_COLUMNS,
    ],
    i18nPrefix: 'layer.sub_blocks',
    usesPalette: true,
    useHalo: true,
    labelFields: ['name', 'area_hectares', 'dominant_slope_band', 'dominant_aspect', 'dominant_canopy_class', 'dominant_nasa_quality', 'dominant_nasa_code', 'dominant_landcover', 'dominant_health_class', 'parent_block_name', 'id'],
  },

  compartments: {
    id: 'compartments',
    label: 'Compartments',
    labelNp: 'कम्पार्टमेन्टहरू',
    icon: '▦',
    order: 2,
    defaultVisible: true,
    geometryTypes: ['Polygon', 'MultiPolygon'],
    editable: (ctx) => !ctx.structure_locked,
    styleKey: 'compartments',
    dataSource: {
      fetch: async (calcId) => {
        const resp = await authFetch(`/api/compartments/calculations/${calcId}/compartment-tree`);
        const data = await resp.json();
        const features: GeoJSON.Feature[] = [];
        
        // `parentId` carries the ENCLOSING tree node's id down the recursion.
        // The vertex rules need the real parent (it is the shell whose
        // vertices are locked); resolving it by spatial containment instead
        // picks the wrong block whenever a child's anchor point sits on a
        // shared boundary, where an even-odd ray cast is a coin flip.
        function extractCompartments(nodes: any[], level: number, parentId: string | null = null) {
          for (const node of nodes) {
            if (node.is_compartment && node.division_level === DEPTH_TOP_COMPARTMENT && node.geometry) {
              features.push({
                type: 'Feature',
                geometry: node.geometry,
                properties: withGeoProps({
                  id: node.id,
                  name: node.name,
                  area_hectares: node.area_hectares,
                  compartment_code: node.compartment_code,
                  block_name: node.block_name,
                  natural_name: node.natural_name,
                  dominant_slope_band: node.dominant_slope_band ?? null,
                  dominant_aspect: node.dominant_aspect ?? null,
                  dominant_canopy_class: node.dominant_canopy_class ?? null,
                  dominant_nasa_quality: node.dominant_nasa_quality ?? null,
                  dominant_nasa_code: node.dominant_nasa_code ?? null,
                  dominant_landcover: node.dominant_landcover ?? null,
                  dominant_health_class: node.dominant_health_class ?? null,
                  management_orientation: node.management_orientation ?? null,
                  suggested_orientation: node.suggested_orientation ?? null,
                  orientation_justification_ne: node.orientation_justification_ne ?? null,
                  orientation_justification_en: node.orientation_justification_en ?? null,
                  division_level: node.division_level,
                  color: node.color,
                  working_circle: node.working_circle || 'production',
                  style: node.style ?? null,
                  forest_condition: node.forest_condition ?? null,
                  parent_block_name: node.parent_block_name,
                  parent_block_id: node.parent_block_id ?? parentId,
                  tree_count: node.tree_count,
                  colorIndex: features.length,
                }, node.geometry),
              });
            }
            if (node.children && node.children.length > 0) {
              extractCompartments(node.children, level + 1, node.id ?? parentId);
            }
          }
        }
        
        if (data?.blocks) {
          extractCompartments(data.blocks, 0);
        }
        return features;
      },
      // A unit is never created by posting a bare feature: `POST .../blocks` is "create blocks from
      // polygon mapping" and DELETES every block of the forest first. Units come from the operations
      // that keep the area rule (draw/polygon-from-points, paste, divide, cut, merge, auto-block), and
      // nothing calls this. Rejecting makes a future caller fail loudly instead of wiping the forest.
      create: async () => { throw new Error('Units are created by draw / paste / divide, not by posting a feature'); },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'PATCH', body: JSON.stringify(feature) });
        return resp.json();
      },
      delete: async (calcId, featureId) => {
        await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'DELETE' });
      },
    },
    geomanModes: [
      { mode: 'edit', label: 'Edit', icon: '◉', allowSelfIntersection: false },
      { mode: 'drag', label: 'Drag', icon: '⊕', allowSelfIntersection: false },
      { mode: 'cut', label: 'Split', icon: '✂', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', editable: true, sortable: true, getValue: (f) => f.properties?.name || 'Unnamed' },
      { key: 'compartment_code', label: 'Code', labelKey: 'attributeTable.col.code', width: 100, editable: true, getValue: (f) => f.properties?.compartment_code || '-' },
      { key: 'natural_name', label: 'Natural Name', labelKey: 'attributeTable.col.natural_name', width: 120, editable: true, getValue: (f) => f.properties?.natural_name || '-' },
      SLOPE_BAND_COLUMN,
      ASPECT_COLUMN,
      CANOPY_CLASS_COLUMN,
  NASA_QUALITY_COLUMN,
  NASA_QUALITY_RAW_COLUMN,
      LANDCOVER_COLUMN,
      FOREST_HEALTH_COLUMN,
      MANAGEMENT_ORIENTATION_COLUMN,
      SUGGESTED_ORIENTATION_COLUMN,
      ...SFM_COLUMNS,
      ...HAZARD_COLUMNS,
      ...FI_COLUMNS,
      ...ANALYSIS_COLUMNS,
      ORIENTATION_JUSTIFICATION_COLUMN,
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', sortable: true, getValue: (f) => f.properties?.area_hectares?.toFixed(2), sortValue: (f) => f.properties?.area_hectares },
      { key: 'parent', label: 'Parent Block', labelKey: 'attributeTable.col.parentBlock', width: 120, getValue: (f) => f.properties?.parent_block_name || '-' },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
      ...STYLE_COLUMNS,
    ],
    i18nPrefix: 'layer.compartments',
    usesPalette: true,
    useHalo: true,
    labelFields: ['name', 'compartment_code', 'area_hectares', 'dominant_slope_band', 'dominant_aspect', 'dominant_canopy_class', 'dominant_nasa_quality', 'dominant_nasa_code', 'dominant_landcover', 'dominant_health_class', 'parent_block_name', 'id'],
  },

  sub_compartments: {
    id: 'sub_compartments',
    label: 'Sub-Compartments',
    labelNp: 'उप-कम्पार्टमेन्टहरू',
    icon: '▦',
    order: 3,
    defaultVisible: true,
    geometryTypes: ['Polygon', 'MultiPolygon'],
    editable: (ctx) => !ctx.structure_locked,
    styleKey: 'sub_compartments',
    dataSource: {
      fetch: async (calcId) => {
        const resp = await authFetch(`/api/compartments/calculations/${calcId}/compartment-tree`);
        const data = await resp.json();
        const features: GeoJSON.Feature[] = [];
        
        // `parentId` carries the ENCLOSING tree node's id down the recursion.
        // The vertex rules need the real parent (it is the shell whose
        // vertices are locked); resolving it by spatial containment instead
        // picks the wrong block whenever a child's anchor point sits on a
        // shared boundary, where an even-odd ray cast is a coin flip.
        function extractSubCompartments(nodes: any[], level: number, parentId: string | null = null) {
          for (const node of nodes) {
            if (node.is_compartment && isUndividedNode(node) && node.geometry) {
              features.push({
                type: 'Feature',
                geometry: node.geometry,
                properties: withGeoProps({
                  id: node.id,
                  name: node.name,
                  area_hectares: node.area_hectares,
                  compartment_code: node.compartment_code,
                  block_name: node.block_name,
                  natural_name: node.natural_name,
                  dominant_slope_band: node.dominant_slope_band ?? null,
                  dominant_aspect: node.dominant_aspect ?? null,
                  dominant_canopy_class: node.dominant_canopy_class ?? null,
                  dominant_nasa_quality: node.dominant_nasa_quality ?? null,
                  dominant_nasa_code: node.dominant_nasa_code ?? null,
                  dominant_landcover: node.dominant_landcover ?? null,
                  dominant_health_class: node.dominant_health_class ?? null,
                  management_orientation: node.management_orientation ?? null,
                  suggested_orientation: node.suggested_orientation ?? null,
                  orientation_justification_ne: node.orientation_justification_ne ?? null,
                  orientation_justification_en: node.orientation_justification_en ?? null,
                  division_level: node.division_level,
                  color: node.color,
                  working_circle: node.working_circle || 'production',
                  style: node.style ?? null,
                  forest_condition: node.forest_condition ?? null,
                  parent_block_name: node.parent_block_name,
                  parent_block_id: node.parent_block_id ?? parentId,
                  tree_count: node.tree_count,
                  colorIndex: features.length,
                }, node.geometry),
              });
            }
            if (node.children && node.children.length > 0) {
              extractSubCompartments(node.children, level + 1, node.id ?? parentId);
            }
          }
        }
        
        if (data?.blocks) {
          extractSubCompartments(data.blocks, 0);
        }
        return features;
      },
      // A unit is never created by posting a bare feature: `POST .../blocks` is "create blocks from
      // polygon mapping" and DELETES every block of the forest first. Units come from the operations
      // that keep the area rule (draw/polygon-from-points, paste, divide, cut, merge, auto-block), and
      // nothing calls this. Rejecting makes a future caller fail loudly instead of wiping the forest.
      create: async () => { throw new Error('Units are created by draw / paste / divide, not by posting a feature'); },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'PATCH', body: JSON.stringify(feature) });
        return resp.json();
      },
      delete: async (calcId, featureId) => {
        await authFetch(`/api/forests/calculations/${calcId}/blocks/${featureId}`, { method: 'DELETE' });
      },
    },
    geomanModes: [
      { mode: 'edit', label: 'Edit', icon: '◉', allowSelfIntersection: false },
      { mode: 'drag', label: 'Drag', icon: '⊕', allowSelfIntersection: false },
      { mode: 'cut', label: 'Split', icon: '✂', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', editable: true, sortable: true, getValue: (f) => f.properties?.name || 'Unnamed' },
      { key: 'compartment_code', label: 'Code', labelKey: 'attributeTable.col.code', width: 100, editable: true, getValue: (f) => f.properties?.compartment_code || '-' },
      { key: 'natural_name', label: 'Natural Name', labelKey: 'attributeTable.col.natural_name', width: 120, editable: true, getValue: (f) => f.properties?.natural_name || '-' },
      SLOPE_BAND_COLUMN,
      ASPECT_COLUMN,
      CANOPY_CLASS_COLUMN,
  NASA_QUALITY_COLUMN,
  NASA_QUALITY_RAW_COLUMN,
      LANDCOVER_COLUMN,
      FOREST_HEALTH_COLUMN,
      MANAGEMENT_ORIENTATION_COLUMN,
      SUGGESTED_ORIENTATION_COLUMN,
      ...SFM_COLUMNS,
      ...HAZARD_COLUMNS,
      ...FI_COLUMNS,
      ...ANALYSIS_COLUMNS,
      ORIENTATION_JUSTIFICATION_COLUMN,
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', sortable: true, getValue: (f) => f.properties?.area_hectares?.toFixed(2), sortValue: (f) => f.properties?.area_hectares },
      { key: 'parent', label: 'Parent Block', labelKey: 'attributeTable.col.parentBlock', width: 120, getValue: (f) => f.properties?.parent_block_name || '-' },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
      ...STYLE_COLUMNS,
    ],
    i18nPrefix: 'layer.sub_compartments',
    usesPalette: true,
    useHalo: true,
    labelFields: ['name', 'compartment_code', 'area_hectares', 'dominant_slope_band', 'dominant_aspect', 'dominant_canopy_class', 'dominant_nasa_quality', 'dominant_nasa_code', 'dominant_landcover', 'dominant_health_class', 'parent_block_name', 'id'],
  },

  sub_areas: {
    id: 'sub_areas',
    label: 'Sub-Areas',
    labelNp: 'उप-क्षेत्रहरू',
    icon: '▓',
    order: 4,
    defaultVisible: false,
    geometryTypes: ['Polygon'],
    editable: (ctx) => !ctx.structure_locked,
    styleKey: 'sub_areas_default',
    dataSource: {
      fetch: async (calcId) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/sub-areas`);
        const data = await resp.json();
        // Is each sub-area tied to the yearly plan? A column only: if this cannot be read the layer still loads.
        const planState = new Map<string, string>();
        try {
          const planResp = await authFetch(`/api/yearly-activities/calculations/${calcId}/sub-areas/plan-status`);
          if (planResp.ok) {
            const plan = await planResp.json();
            for (const item of plan?.sub_areas || []) planState.set(String(item.id), String(item.state));
          }
        } catch {
          /* the plan column stays empty */
        }
        return (data?.sub_areas || []).map((sa: any, index: number) => ({
          type: 'Feature',
          geometry: sa.geometry,
          properties: withGeoProps({
            id: sa.id,
            name: sa.name,
            category: sa.category,
            area_hectares: sa.area_hectares,
            fillColor: sa.fill_color,
            style: sa.style ?? null,
            block_name: sa.block_name,
            plan_state: planState.get(String(sa.id)) ?? null,
            colorIndex: index,
          }, sa.geometry),
        }));
      },
      create: async (calcId, feature) => {
        const geometry = feature.geometry;
        const props = feature.properties || ({} as Record<string, unknown>);
        const category = String(props.category || '');
        const name = String(props.name || '') || `${getCategoryLabel(category)}`;
        const payload = {
          name,
          category,
          geometry,
          is_excluded: Boolean(props.is_excluded ?? props.isExcluded ?? props.excluded),
        };
        const resp = await authFetch(`/api/forests/calculations/${calcId}/sub-areas`, { method: 'POST', body: JSON.stringify(payload) });
        return resp.json();
      },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/forests/calculations/${calcId}/sub-areas/${featureId}`, { method: 'PATCH', body: JSON.stringify(feature) });
        return resp.json();
      },
      delete: async (calcId, featureId) => {
        await authFetch(`/api/forests/calculations/${calcId}/sub-areas/${featureId}`, { method: 'DELETE' });
      },
    },
    geomanModes: [
      { mode: 'drawPolygon', label: 'Draw', icon: '▄', allowSelfIntersection: false },
      { mode: 'edit', label: 'Edit', icon: '◉', allowSelfIntersection: false },
      { mode: 'drag', label: 'Drag', icon: '⊕', allowSelfIntersection: false },
      { mode: 'cut', label: 'Split', icon: '✂', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center' },
      { key: 'color_swatch', label: '', width: 24, align: 'center', render: (_, f) => { const idx = f.properties?.colorIndex ?? 0; const color = SUB_AREA_COLORS[idx % SUB_AREA_COLORS.length]; return React.createElement('span', { style: { display: 'inline-block', width: 12, height: 12, borderRadius: 2, background: color } }); } },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 'flex', editable: true },
      { key: 'category', label: 'Category', labelKey: 'attributeTable.col.category', width: 150, align: 'center', editable: true, select: ALL_SUB_AREA_CATEGORIES.map((c) => ({ value: c.key, label: c.label })), getValue: (f) => f.properties?.category },
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 100, align: 'right', sortable: true },
      { key: 'block', label: 'Block', labelKey: 'attributeTable.col.block', width: 80, getValue: (f) => f.properties?.block_name || '-' },
      { key: 'plan_state', label: 'Yearly plan', labelKey: 'attributeTable.col.yearlyPlan', width: 130, align: 'center', getValue: (f) => SUB_AREA_PLAN_STATE_LABEL[String(f.properties?.plan_state)] ?? '-' },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
      ...STYLE_COLUMNS,
    ],
    i18nPrefix: 'layer.sub_areas',
    usesPalette: true,
    useHalo: true,
    supportsCategories: true,
    categories: ALL_SUB_AREA_CATEGORIES.map(c => ({
      key: c.key,
      label: c.label,
      labelNp: c.labelNp,
      color: c.color,
      isExcluded: c.isExcluded,
    })),
    labelFields: ['name', 'category', 'area_hectares', 'block_name', 'id'],
  },

  activity_features: {
    id: 'activity_features',
    label: 'Activity Features',
    labelNp: 'गतिविधि चिन्हहरू',
    icon: '◉',
    order: 6.5,
    defaultVisible: false,
    geometryTypes: ['Point', 'LineString', 'Polygon'],
    editable: true,
    styleKey: 'activity_features_default',
    dataSource: {
      fetch: async (calcId) => {
        const resp = await authFetch(`/api/yearly-activities/calculations/${calcId}/drawn-features`);
        // An error body is not a list of features. Saying nothing here is how the layer sat
        // empty without anyone being told why.
        if (!resp.ok) throw new Error(`Activity features request failed (${resp.status})`);
        return activityFeaturesFromApi(await resp.json());
      },
      // The facade routes (YEARLY_ACTIVITIES plan section 5.1): a place is drawn for an ACTIVITY, and the
      // plan line, its year rows and the feature are created together on the server. The old
      // `/calculations/{id}/drawn-features` POST / PATCH / DELETE routes never existed.
      create: async (calcId, feature) => {
        const resp = await authFetch(`/api/yearly-activities/calculations/${calcId}/activity-features`, {
          method: 'POST',
          body: JSON.stringify(activityFeatureCreateBody(feature as unknown as ActivityFeatureInput)),
        });
        const data = await resp.json().catch(() => null);
        if (!resp.ok) throw new ActivityFeatureApiError(data, resp.status);
        return data;
      },
      update: async (calcId, featureId, feature) => {
        const resp = await authFetch(`/api/yearly-activities/calculations/${calcId}/activity-features/${featureId}`, {
          method: 'PATCH',
          body: JSON.stringify(activityFeatureUpdateBody(feature as unknown as ActivityFeatureInput)),
        });
        const data = await resp.json().catch(() => null);
        if (!resp.ok) throw new ActivityFeatureApiError(data, resp.status);
        return data;
      },
      delete: async (calcId, featureId) => {
        const resp = await authFetch(`/api/yearly-activities/calculations/${calcId}/activity-features/${featureId}`, { method: 'DELETE' });
        if (!resp.ok) throw new ActivityFeatureApiError(await resp.json().catch(() => null), resp.status);
      },
    },
    geomanModes: [
      { mode: 'drawMarker', label: 'Point', labelNp: 'बिन्दु', icon: '●', subType: 'point' as const },
      { mode: 'drawLine', label: 'Line', labelNp: 'रेखा', icon: '═', subType: 'line' as const },
      { mode: 'drawPolygon', label: 'Polygon', labelNp: 'बहुभुज', icon: '▄', subType: 'polygon' as const },
      { mode: 'edit', label: 'Edit Vertices', labelNp: 'भर्टेक्स सम्पादन', icon: '◉', allowSelfIntersection: false },
      { mode: 'drag', label: 'Drag', labelNp: 'तान्नुहोस्', icon: '⊕', allowSelfIntersection: false },
    ],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'type_icon', label: '', width: 36, align: 'center', render: (_, f) => { const icons: Record<string, string> = { Point: '●', LineString: '═', Polygon: '▄' }; return React.createElement('span', { style: { fontSize: 16, lineHeight: 1 } }, icons[f.geometry.type] || '?'); } },
      { key: 'display_label', label: 'Label', labelKey: 'attributeTable.col.activityFeatureLabel', width: 'flex', getValue: (f) => f.properties?.display_label || f.properties?.name || 'Unnamed' },
      { key: 'activity_name', label: 'Activity', labelKey: 'attributeTable.col.activity', width: 170, getValue: (f) => f.properties?.activity_name || '-' },
      { key: 'kind', label: 'Symbol', labelKey: 'attributeTable.col.symbol', width: 190, select: ACTIVITY_KIND_OPTIONS, selectValue: (f) => (typeof f.properties?.kind === 'string' ? f.properties.kind : ''), getValue: (f) => activityKindLabel(f.properties?.kind) || '-' },
      { key: 'name', label: 'Name', labelKey: 'attributeTable.col.name', width: 150, editable: true, getValue: (f) => f.properties?.name || 'Unnamed' },
      {
        key: 'plan_quantity', label: 'Quantity', labelKey: 'attributeTable.col.planQuantity', width: 150, align: 'right',
        getValue: (f) => featureQuantityText(f.properties),
        sortValue: (f) => { const q = Number(f.properties?.plan_quantity); return Number.isFinite(q) ? q : null; },
        render: (_, f) => {
          const tag = featureSharedTag(f.properties);
          return React.createElement(
            'span', { title: featureSharedTitle(f.properties), 'data-testid': 'feature-quantity' },
            featureQuantityText(f.properties),
            tag ? React.createElement('span', { 'data-testid': 'feature-shared-tag', style: { marginLeft: 6, fontSize: 11, color: '#6b7280', background: '#f3f4f6', borderRadius: 4, padding: '0 4px', whiteSpace: 'nowrap' } }, tag) : null,
          );
        },
      },
      { key: 'year', label: 'Year(s)', labelKey: 'attributeTable.col.year', width: 120, align: 'center', editControl: 'years', getValue: (f) => f.properties?.years?.join(', ') || f.properties?.year || '-' },
      { key: 'length', label: 'Length (m)', labelKey: 'attributeTable.col.length', width: 95, align: 'right', getValue: (f) => f.properties?.length_m?.toFixed(0) || '-' },
      { key: 'area', label: 'Area (ha)', labelKey: 'attributeTable.col.area', width: 95, align: 'right', getValue: (f) => f.properties?.area_sqm ? (f.properties.area_sqm / 10000).toFixed(2) : '-' },
      ...GEO_POLYGON_COLUMNS,
      ...GEO_LINE_COLUMNS,
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
    ],
    i18nPrefix: 'geometry.activity',
    supportsSubLayers: true,
    subLayers: [
      { id: 'point', label: 'Points', labelNp: 'बिन्दुहरू', geometryType: 'Point', styleModifier: { color: '#1E90FF', radius: 8 } as L.CircleMarkerOptions },
      { id: 'line', label: 'Lines', labelNp: 'रेखाहरू', geometryType: 'LineString', styleModifier: { color: '#32CD32', weight: 3 } },
      { id: 'polygon', label: 'Polygons', labelNp: 'बहुभुजहरू', geometryType: 'Polygon', styleModifier: { color: '#FF8C00', fillColor: '#FF8C00', fillOpacity: 0.4 } },
    ],
    useHalo: true,
    isLockable: false,
    labelFields: ['display_label', 'activity_name', 'name', 'year', 'years', 'length_m', 'area_sqm', 'id'],
  },

  sample_plots: {
    id: 'sample_plots',
    label: 'Sample Plots',
    labelNp: 'नमूना स्थलहरू',
    icon: '✚',
    order: 5,
    defaultVisible: true,
    geometryTypes: ['Point'],
    editable: false,
    styleKey: 'sample_plots',
    dataSource: {
      ...nullDataSource,
      fetch: async (calcId) => {
        const designs = await samplingApi.list(calcId);
        if (!designs || designs.length === 0) return [];
        const layers = await samplingApi.getMapLayers(designs[0].id);
        const feats = layers?.sampling_points?.features || [];

        // Enrich with the same fields the Sampling tab's own "Sampling
        // Points" table shows (elevation/UTM/topo/distance-from-boundary +
        // SFM stratum) -- /map-layers alone only carries plot/block/zone.
        // Both are best-effort: a forest with no SFM classification, or a
        // points fetch that fails, just falls back to the lighter fields
        // already present on `feats`.
        let fullByPlot = new Map<number, any>();
        try {
          const pointsResp = await samplingApi.getPoints(designs[0].id, {
            include_elevation: true,
            include_topographic_features: true,
          });
          for (const p of pointsResp?.points || []) {
            if (p?.plot_number != null) fullByPlot.set(p.plot_number, p);
          }
        } catch {
          fullByPlot = new Map();
        }

        let stratumByBlock: Record<string, string | undefined> = {};
        try {
          const sfmSummary = await sfmApi.getSummary(calcId);
          for (const row of sfmSummary?.forest_summary?.sampling_plan || []) {
            if (row?.block_name) stratumByBlock[row.block_name] = row.stratum;
          }
        } catch {
          stratumByBlock = {};
        }

        return feats.map((f: any, index: number) => {
          const plotNumber = f.properties?.plot_number;
          const full = plotNumber != null ? fullByPlot.get(plotNumber) : undefined;
          const blockName = f.properties?.block_name;
          return {
            type: 'Feature',
            geometry: f.geometry,
            properties: withGeoProps({
              id: f.properties?.plot_id || plotNumber || `plot-${index + 1}`,
              // Owner report 2026-10-02: without this, the attribute table's
              // default (no header clicked yet) row order fell back to a
              // string compare of the feature `id` above ("P1", "P10", "P2",
              // ...), i.e. lexicographic, not numeric -- 1, 10, 11, 2, 3...
              // `index` is what AttributeTable's default sort checks FIRST
              // (ahead of that string fallback), same as every builtin
              // block/compartment layer already relies on for this.
              index: plotNumber ?? index + 1,
              name: `Plot ${plotNumber || index + 1}`,
              plot_number: plotNumber,
              plot_id: f.properties?.plot_id,
              // Delete-by-plot-number (owner report 2026-10-02) needs the
              // owning design's id -- carried on the feature so the row
              // delete handler doesn't need a second `samplingApi.list` call.
              design_id: designs[0].id,
              block_name: blockName,
              block_number: f.properties?.block_number,
              zone_type: f.properties?.zone_type || 'productive',
              stratum: blockName ? stratumByBlock[blockName] : undefined,
              elevation_m: full?.elevation_m,
              utm_easting: full?.utm_easting,
              utm_northing: full?.utm_northing,
              utm_zone: full?.utm_zone,
              topographic_context: full?.topographic_context,
              distance_from_boundary: full?.distance_from_boundary,
            }, f.geometry),
          };
        });
      },
      // Owner report 2026-10-02: a map-workspace Delete for one sample plot,
      // allowed only while this forest has no field inventory data uploaded
      // yet (handleDeleteSamplePlot in MapWorkspace.tsx checks that and
      // confirms before calling this). `featureId` here is the design id
      // carried on the feature's own `design_id` property by `fetch` above;
      // the actual plot number to delete is the SECOND arg, reusing the
      // generic `dataSource.delete(calcId, featureId)` shape by overloading
      // it as `delete(designId, plotNumber)`.
      delete: async (designId: string, plotNumber: string) => {
        await samplingApi.deleteSamplePlot(designId, Number(plotNumber));
      },
    },
    geomanModes: [],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'plot_number', label: 'Plot #', labelKey: 'attributeTable.col.plotNumber', width: 'flex', sortable: true, getValue: (f) => f.properties?.plot_number ?? '-' },
      { key: 'block_name', label: 'Block', labelKey: 'attributeTable.col.block', width: 120, getValue: (f) => f.properties?.block_name || '-' },
      { key: 'zone_type', label: 'Zone', labelKey: 'attributeTable.col.zoneType', width: 100, getValue: (f) => f.properties?.zone_type || 'productive' },
      { key: 'stratum', label: 'SFM Stratum', labelKey: 'attributeTable.col.sfmStratum', width: 120, getValue: (f) => f.properties?.stratum || '-' },
      { key: 'elevation_m', label: 'Elevation (m)', labelKey: 'attributeTable.col.elevationM', width: 105, align: 'right', getValue: (f) => f.properties?.elevation_m ?? '-' },
      { key: 'utm_easting', label: 'UTM Easting', labelKey: 'attributeTable.col.utmEasting', width: 110, align: 'right', editable: true, getValue: (f) => f.properties?.utm_easting?.toFixed?.(2) ?? f.properties?.utm_easting ?? '-' },
      { key: 'utm_northing', label: 'UTM Northing', labelKey: 'attributeTable.col.utmNorthing', width: 110, align: 'right', editable: true, getValue: (f) => f.properties?.utm_northing?.toFixed?.(2) ?? f.properties?.utm_northing ?? '-' },
      { key: 'utm_zone', label: 'UTM Zone', labelKey: 'attributeTable.col.utmZone', width: 90, getValue: (f) => f.properties?.utm_zone || '-' },
      { key: 'topographic_context', label: 'Nearest Ridge/Valley', labelKey: 'attributeTable.col.nearestRidgeValley', width: 150, getValue: (f) => f.properties?.topographic_context || '-' },
      { key: 'distance_from_boundary', label: 'Distance from Boundary (m)', labelKey: 'attributeTable.col.distanceFromBoundary', width: 150, align: 'right', getValue: (f) => f.properties?.distance_from_boundary?.toFixed?.(2) ?? f.properties?.distance_from_boundary ?? '-' },
      // WGS84 latitude / longitude: the plot's own position, editable. (The centroid and bounding-box columns of every other layer would
      // be the same two numbers repeated for a single point, so they are not shown here.)
      { key: 'latitude', label: 'Latitude (WGS84)', labelKey: 'attributeTable.col.latitudeWgs84', width: 125, align: 'right', editable: true, getValue: (f) => { const v = (f.geometry as GeoJSON.Point | null)?.coordinates?.[1]; return typeof v === 'number' ? v.toFixed(6) : '-'; } },
      { key: 'longitude', label: 'Longitude (WGS84)', labelKey: 'attributeTable.col.longitudeWgs84', width: 130, align: 'right', editable: true, getValue: (f) => { const v = (f.geometry as GeoJSON.Point | null)?.coordinates?.[0]; return typeof v === 'number' ? v.toFixed(6) : '-'; } },
    ],
    i18nPrefix: 'layer.sample_plots',
    alwaysReadOnly: true,
    useHalo: true,
    isLockable: false,
    labelFields: ['plot_number', 'block_name', 'plot_id', 'block_number'],
  },

  // Stem Mapping — one point per surveyed tree. Read-only, like Sample Plots:
  // the data comes from the existing Tree Mapping upload flow (Sampling &
  // Model tab / `inventory_trees`), this layer only displays it on the map.
  // `getTreesForMap` already existed (compartments.py, for the now-deleted
  // legacy compartment-assignment map view) — reused as-is, unpaginated,
  // same as every other point layer here.
  stem_mapping: {
    id: 'stem_mapping',
    label: 'Stem Mapping',
    labelNp: 'काण्ड म्यापिङ',
    icon: '♣',
    order: 6,
    defaultVisible: false,
    geometryTypes: ['Point'],
    editable: false,
    styleKey: 'stem_mapping',
    dataSource: {
      ...nullDataSource,
      fetch: async (calcId) => {
        const { trees } = await compartmentApi.getTreesForMap(calcId);
        return trees.map((tree) => {
          const geometry: GeoJSON.Point = { type: 'Point', coordinates: [tree.longitude, tree.latitude] };
          return {
            type: 'Feature',
            geometry,
            properties: withGeoProps({
              id: tree.id,
              name: tree.species || 'Tree',
              species: tree.species,
              dbh_cm: tree.dbh_cm,
              height_m: tree.height_m,
              volume_m3: tree.volume_m3,
              dbh_class: tree.dbh_class,
              block_name: tree.block_name,
              remark: tree.remark,
            }, geometry),
          };
        });
      },
    },
    geomanModes: [],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'species', label: 'Species', labelKey: 'attributeTable.col.species', width: 'flex', sortable: true, getValue: (f) => f.properties?.species || '-' },
      { key: 'dbh_cm', label: 'DBH (cm)', labelKey: 'attributeTable.col.dbh', width: 90, align: 'right', sortable: true, getValue: (f) => f.properties?.dbh_cm?.toFixed?.(1) ?? f.properties?.dbh_cm ?? '-' },
      { key: 'height_m', label: 'Height (m)', labelKey: 'attributeTable.col.height', width: 90, align: 'right', sortable: true, getValue: (f) => f.properties?.height_m?.toFixed?.(1) ?? f.properties?.height_m ?? '-' },
      { key: 'dbh_class', label: 'DBH Class', labelKey: 'attributeTable.col.dbhClass', width: 130, getValue: (f) => f.properties?.dbh_class || '-' },
      { key: 'volume_m3', label: 'Volume (m³)', labelKey: 'attributeTable.col.volume', width: 100, align: 'right', getValue: (f) => f.properties?.volume_m3?.toFixed?.(3) ?? f.properties?.volume_m3 ?? '-' },
      { key: 'block_name', label: 'Block', labelKey: 'attributeTable.col.block', width: 120, getValue: (f) => f.properties?.block_name || '-' },
      { key: 'remark', label: 'Remark', labelKey: 'attributeTable.col.remark', width: 100, getValue: (f) => f.properties?.remark || '-' },
      ...GEO_CENTROID_COLUMNS,
    ],
    i18nPrefix: 'layer.stem_mapping',
    alwaysReadOnly: true,
    useHalo: true,
    isLockable: false,
    labelFields: ['species', 'block_name', 'dbh_class'],
  },

  // Field Book — one point per walked boundary vertex/interpolated point
  // (fieldbook_implementation_plan.md / fieldbook_map_layer_plan.md). Read-only,
  // like Sample Plots: the data is server-generated (via the layer's own
  // "Generate Field Book" ⋮ menu command, wired in LayerPanel/MapWorkspace),
  // this layer only displays it. GET /calculations/{id}/fieldbook already
  // returns every field needed in one call -- no enrichment fetch required
  // (unlike sample_plots, which needs a follow-up call for elevation/UTM/topo).
  fieldbook: {
    id: 'fieldbook',
    label: 'Field Book',
    labelNp: 'फिल्डपुस्तिका',
    icon: '🧭',
    order: 7,
    defaultVisible: false,
    geometryTypes: ['Point'],
    editable: false,
    styleKey: 'fieldbook',
    dataSource: {
      ...nullDataSource,
      fetch: async (calcId) => {
        let resp: any;
        try {
          resp = await fieldbookApi.list(calcId);
        } catch {
          return [];
        }
        const points = resp?.points || [];
        return points.map((p: any) => {
          const geometry: GeoJSON.Point = { type: 'Point', coordinates: [Number(p.longitude), Number(p.latitude)] };
          return {
            type: 'Feature',
            geometry,
            properties: withGeoProps({
              id: p.id || `fb-${p.point_number}`,
              name: p.point_label || `P${p.point_number}`,
              point_number: p.point_number,
              point_label: p.point_label,
              boundary_class: p.boundary_class,
              junction_degree: p.junction_degree,
              is_junction: p.is_junction,
              adjacent_units: Array.isArray(p.adjacent_units) ? p.adjacent_units.join(', ') : p.adjacent_units,
              next_point_label: p.next_point_label,
              line_id: p.line_id,
              lines: p.lines,
              point_type: p.point_type,
              block_number: p.block_number,
              block_name: p.block_name,
              sub_area_name: p.sub_area_name,
              sub_area_category: p.sub_area_category,
              is_excluded: p.is_excluded,
              elevation: p.elevation,
              utm_easting: p.easting_utm,
              utm_northing: p.northing_utm,
              utm_zone: p.utm_zone,
              azimuth_to_next: p.azimuth_to_next,
              distance_to_next: p.distance_to_next,
              remarks: p.remarks,
              is_verified: p.is_verified,
            }, geometry),
          };
        });
      },
    },
    geomanModes: [],
    columns: [
      { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 },
      { key: 'point_number', label: 'Point #', labelKey: 'attributeTable.col.pointNumber', width: 'flex', sortable: true, getValue: (f) => f.properties?.point_label ?? f.properties?.point_number ?? '-' },
      { key: 'boundary_class', label: 'Boundary', labelKey: 'attributeTable.col.boundaryClass', width: 90, sortable: true, getValue: (f) => f.properties?.boundary_class || '-' },
      { key: 'is_junction', label: 'Junction', labelKey: 'attributeTable.col.junction', width: 90, align: 'center', getValue: (f) => f.properties?.is_junction ? `✦ ${f.properties?.junction_degree ?? ''}`.trim() : '-' },
      { key: 'next_point_label', label: 'Next', labelKey: 'attributeTable.col.nextPoint', width: 70, getValue: (f) => f.properties?.next_point_label || '-' },
      { key: 'line_id', label: 'Line', labelKey: 'attributeTable.col.line', width: 70, sortable: true, getValue: (f) => f.properties?.line_id || '-' },
      { key: 'point_type', label: 'Type', labelKey: 'attributeTable.col.type', width: 90, getValue: (f) => f.properties?.point_type === 'vertex' ? 'V' : 'I' },
      { key: 'remarks', label: 'Remark', labelKey: 'attributeTable.col.remark', width: 230, getValue: (f) => f.properties?.remarks || '-' },
      { key: 'sub_area_name', label: 'Sub-area', labelKey: 'attributeTable.col.subArea', width: 130, getValue: (f) => f.properties?.sub_area_name || '-' },
      { key: 'sub_area_category', label: 'Category', labelKey: 'attributeTable.col.subAreaCategory', width: 120, getValue: (f) => f.properties?.sub_area_category || '-' },
      { key: 'is_excluded', label: 'Excluded', labelKey: 'attributeTable.col.isExcluded', width: 90, getValue: (f) => f.properties?.is_excluded ? 'Yes' : 'No' },
      { key: 'elevation', label: 'Elevation (m)', labelKey: 'attributeTable.col.elevationM', width: 105, align: 'right', getValue: (f) => f.properties?.elevation?.toFixed?.(1) ?? f.properties?.elevation ?? '-' },
      { key: 'utm_easting', label: 'UTM Easting', labelKey: 'attributeTable.col.utmEasting', width: 110, align: 'right', getValue: (f) => f.properties?.utm_easting?.toFixed?.(2) ?? f.properties?.utm_easting ?? '-' },
      { key: 'utm_northing', label: 'UTM Northing', labelKey: 'attributeTable.col.utmNorthing', width: 110, align: 'right', getValue: (f) => f.properties?.utm_northing?.toFixed?.(2) ?? f.properties?.utm_northing ?? '-' },
      { key: 'utm_zone', label: 'UTM Zone', labelKey: 'attributeTable.col.utmZone', width: 90, getValue: (f) => f.properties?.utm_zone || '-' },
      { key: 'azimuth_to_next', label: 'Azimuth to Next (°)', labelKey: 'attributeTable.col.azimuthToNext', width: 130, align: 'right', getValue: (f) => f.properties?.azimuth_to_next?.toFixed?.(1) ?? f.properties?.azimuth_to_next ?? '-' },
      { key: 'distance_to_next', label: 'Distance to Next (m)', labelKey: 'attributeTable.col.distanceToNext', width: 130, align: 'right', getValue: (f) => f.properties?.distance_to_next?.toFixed?.(1) ?? f.properties?.distance_to_next ?? '-' },
      { key: 'is_verified', label: 'Verified', labelKey: 'attributeTable.col.verified', width: 90, getValue: (f) => f.properties?.is_verified ? 'Yes' : 'No' },
      ...GEO_CENTROID_COLUMNS,
      ...GEO_BBOX_COLUMNS,
    ],
    i18nPrefix: 'layer.fieldbook',
    alwaysReadOnly: true,
    useHalo: true,
    isLockable: false,
    labelFields: ['point_label', 'point_number', 'sub_area_name'],
  },
};

export function getLayerConfig(id: LayerTypeId | null): LayerTypeConfig | undefined {
  return id ? LAYER_REGISTRY[id] : undefined;
}

export function getAllLayerConfigs(): LayerTypeConfig[] {
  return Object.values(LAYER_REGISTRY).sort((a, b) => a.order - b.order);
}

/**
 * The canonical panel/map order, as a `layerId -> order` map, plus the default
 * visibility as a `layerId -> boolean` map. Both are derived from the registry
 * rather than hand-written, so adding a layer to `LAYER_REGISTRY` is enough to
 * have it appear in the panel in the right place with the right default.
 */
export const LAYER_ORDER: Record<LayerTypeId, number> = getAllLayerConfigs().reduce(
  (acc, cfg) => {
    acc[cfg.id] = cfg.order;
    return acc;
  },
  {} as Record<LayerTypeId, number>,
);

export const LAYER_DEFAULT_VISIBILITY: Record<LayerTypeId, boolean> =
  getAllLayerConfigs().reduce(
    (acc, cfg) => {
      acc[cfg.id] = cfg.defaultVisible;
      return acc;
    },
    {} as Record<LayerTypeId, boolean>,
  );

/** The built-in layers in canonical order — the order the panel must render. */
export const LAYER_ORDER_IDS: LayerTypeId[] = getAllLayerConfigs().map((c) => c.id);

/**
 * The order a layer renders in, given the user's overrides. A layer with no
 * explicit `layerOrder` entry falls back to the registry's canonical order
 * rather than to `0` — that `?? 0` is what let seven of eleven layers tie at
 * zero and land in an arbitrary slot. Imported layers (whose ids are not in the
 * registry) fall back to 0, which is all they ever had.
 *
 * Takes `string`, not `LayerTypeId`, because the panel sorts built-in and
 * imported rows through the same comparator.
 */
export function resolveLayerOrder(
  overrides: Record<string, number> | undefined,
  id: string,
): number {
  return overrides?.[id] ?? LAYER_ORDER[id as LayerTypeId] ?? 0;
}

/** A layer is visible unless explicitly hidden. Mirrors the read convention. */
export function isLayerVisibleByDefault(
  overrides: Record<string, boolean> | undefined,
  id: string,
): boolean {
  return overrides?.[id] ?? LAYER_DEFAULT_VISIBILITY[id as LayerTypeId] ?? true;
}

/** True when the layer id is a built-in TOC layer (as opposed to an imported layer). */
export function isBuiltinLayerId(id: string): id is LayerTypeId {
  return id in LAYER_REGISTRY;
}

/** Candidate label fields for a layer, or [] when the layer has no label picker. */
export function getLabelFieldsForLayer(id: string): string[] {
  const config = getLayerConfig(id as LayerTypeId);
  return config?.labelFields ?? [];
}

export function isLayerEditable(
  config: LayerTypeConfig,
  context: { structure_locked: boolean },
): boolean {
  if (typeof config.editable === 'function') {
    return config.editable(context);
  }
  return config.editable;
}
