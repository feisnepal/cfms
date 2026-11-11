/**
 * Symbols for the Activity Features layer: one per KIND of activity feature, drawn to suit its
 * geometry (a point becomes a coloured badge with an icon, a line a coloured/dashed stroke, a
 * polygon a tinted fill).
 *
 * The vocabulary is `backend/app/services/operational_plan/feature_kinds.py` (KINDS): the
 * operational-plan maps use the same colours, so a nursery is the same green on the workspace map
 * and in the printed plan. This is its frontend mirror (colours, geometry, labels), pinned by
 * `backend/tests/test_activity_kinds_sync.py`. The `icon` is a UI-only addition.
 *
 * Which kind a feature has is decided by the server (`kind` on each feature): its own
 * `properties.kind`, else its activity's default (`potential_activities.map_kind`), else "" for
 * the generic point / line / polygon.
 */
import i18n from 'i18next';
import type L from 'leaflet';
import { iconSvg, type ActivityKindIconName } from './activityKindIcons';

export type KindGeom = 'point' | 'line' | 'polygon';

export interface ActivityKindMeta {
  /** The geometry the kind is natively drawn as (backend table). */
  geom: KindGeom;
  color: string;
  /** SVG dash pattern for lines and polygon outlines ('' = solid). */
  dash: string;
  /** Line weight in px (native lines). */
  weight: number;
  /** Polygon fill opacity (native polygons). */
  alpha: number;
  ne: string;
  en: string;
  icon: ActivityKindIconName;
}

// One line per kind, in this exact shape: the backend sync test reads it.
export const ACTIVITY_KINDS: Record<string, ActivityKindMeta> = {
  coupe: { geom: 'polygon', color: '#e6550d', dash: '', weight: 2, alpha: 0.55, ne: 'कटान क्षेत्र', en: 'Coupe / felling area', icon: 'axe' },
  plantation: { geom: 'polygon', color: '#10b981', dash: '', weight: 2, alpha: 0.35, ne: 'रोपण क्षेत्र', en: 'Planting / enrichment', icon: 'treePine' },
  anr_area: { geom: 'polygon', color: '#84cc17', dash: '', weight: 2, alpha: 0.30, ne: 'प्राकृतिक पुनरुत्पादन', en: 'ANR area', icon: 'treeDeciduous' },
  grazing_closure: { geom: 'polygon', color: '#b08968', dash: '', weight: 2, alpha: 0.30, ne: 'चरन बन्द', en: 'Grazing closure', icon: 'fence' },
  biodiversity_block: { geom: 'polygon', color: '#06b6d4', dash: '', weight: 2, alpha: 0.35, ne: 'जैविक विविधता', en: 'Biodiversity block', icon: 'bird' },
  water_source_protection: { geom: 'polygon', color: '#0ea5e9', dash: '', weight: 2, alpha: 0.40, ne: 'मूल संरक्षण क्षेत्र', en: 'Water-source protection', icon: 'droplets' },
  wildlife_corridor: { geom: 'polygon', color: '#a855f7', dash: '', weight: 2, alpha: 0.30, ne: 'जैविक मार्ग', en: 'Wildlife corridor', icon: 'footprints' },
  ntfp_zone: { geom: 'polygon', color: '#8a6d3b', dash: '', weight: 2, alpha: 0.28, ne: 'गैरकाष्ठ वन पैदावार क्षेत्र', en: 'NTFP zone', icon: 'leaf' },
  propoor_plot: { geom: 'polygon', color: '#f59e0b', dash: '', weight: 2, alpha: 0.32, ne: 'विपन्न वर्ग भूखण्ड', en: 'Pro-poor plot', icon: 'users' },
  agroforestry_area: { geom: 'polygon', color: '#65a30d', dash: '', weight: 2, alpha: 0.30, ne: 'कृषिवन क्षेत्र', en: 'Agroforestry', icon: 'wheat' },
  silviculture_area: { geom: 'polygon', color: '#0f766e', dash: '', weight: 2, alpha: 0.30, ne: 'वन सम्बर्दन क्षेत्र', en: 'Silviculture area', icon: 'scissors' },
  encroachment: { geom: 'polygon', color: '#c62828', dash: '4 4', weight: 2, alpha: 0.15, ne: 'अतिक्रमण', en: 'Encroachment', icon: 'ban' },
  river_bank: { geom: 'polygon', color: '#1e40af', dash: '', weight: 2, alpha: 0.45, ne: 'खोला किनार (संरक्षण क्षेत्र)', en: 'River bank (protection area)', icon: 'droplets' },
  road: { geom: 'line', color: '#8d5524', dash: '', weight: 2.6, alpha: 1, ne: 'नयाँ बाटो', en: 'Road / track', icon: 'route' },
  trail: { geom: 'line', color: '#8d5524', dash: '8 6', weight: 1.6, alpha: 1, ne: 'गोरेटो', en: 'Trail / footpath', icon: 'signpost' },
  fire_line: { geom: 'line', color: '#c62828', dash: '6 3', weight: 2.0, alpha: 1, ne: 'आगो नियन्त्रण रेखा', en: 'Fire line', icon: 'flame' },
  patrol_route: { geom: 'line', color: '#6a1b9a', dash: '2 6', weight: 1.8, alpha: 1, ne: 'गस्ती मार्ग', en: 'Patrol route', icon: 'eye' },
  nursery: { geom: 'point', color: '#2e7d32', dash: '', weight: 3, alpha: 1, ne: 'नर्सरी', en: 'Nursery', icon: 'sprout' },
  depot: { geom: 'point', color: '#795548', dash: '', weight: 3, alpha: 1, ne: 'डिपो', en: 'Timber depot', icon: 'warehouse' },
  check_post: { geom: 'point', color: '#1565c0', dash: '', weight: 3, alpha: 1, ne: 'चेकपोस्ट', en: 'Check / guard post', icon: 'shield' },
  fire_tower: { geom: 'point', color: '#c62828', dash: '', weight: 3, alpha: 1, ne: 'अग्नि टावर', en: 'Fire / view tower', icon: 'towerControl' },
  water_hole: { geom: 'point', color: '#0ea5e9', dash: '', weight: 3, alpha: 1, ne: 'पानी पोखरी', en: 'Water hole / pond', icon: 'waves' },
  signboard: { geom: 'point', color: '#616161', dash: '', weight: 3, alpha: 1, ne: 'सूचना पाटी / सीमा स्तम्भ', en: 'Signboard / marker', icon: 'flag' },
  seed_stand: { geom: 'point', color: '#33691e', dash: '', weight: 3, alpha: 1, ne: 'बीउ रूख', en: 'Seed stand / mother tree', icon: 'trees' },
  ecotourism_site: { geom: 'point', color: '#ec4899', dash: '', weight: 3, alpha: 1, ne: 'पर्यापर्यटन स्थल', en: 'Ecotourism site', icon: 'binoculars' },
  religious_cultural: { geom: 'point', color: '#8b5cf6', dash: '', weight: 3, alpha: 1, ne: 'धार्मिक स्थल', en: 'Religious / cultural', icon: 'landmark' },
  permanent_sample_plot: { geom: 'point', color: '#08519c', dash: '', weight: 3, alpha: 1, ne: 'स्थायी नमूना प्लट', en: 'Permanent plot', icon: 'target' },
  monitoring_point: { geom: 'point', color: '#3182bd', dash: '', weight: 3, alpha: 1, ne: 'अनुगमन बिन्दु', en: 'Monitoring point', icon: 'circleDot' },
  community_infrastructure: { geom: 'point', color: '#475569', dash: '', weight: 3, alpha: 1, ne: 'सामुदायिक संरचना', en: 'Community infrastructure', icon: 'house' },
};

export const ACTIVITY_KIND_IDS = Object.keys(ACTIVITY_KINDS);

/** A feature with no kind: the plain grey marker the layer had before, now at least legible. */
const GENERIC_COLOR = '#616161';

/** Feature-count key the legend reads: `activity_features:kind:nursery`. */
export const activityKindCountKey = (kind: string) => `activity_features:kind:${kind}`;

export function activityKindLabel(kind: string | undefined | null, language: string = i18n.language): string {
  const meta = kind ? ACTIVITY_KINDS[kind] : undefined;
  if (!meta) return '';
  return language === 'ne' ? meta.ne : meta.en;
}

/** Leaflet path options for a line or polygon of this kind; null = keep the generic style. */
export function activityKindPathStyle(kind: string | undefined | null, geometryType: string): L.PathOptions | null {
  const meta = kind ? ACTIVITY_KINDS[kind] : undefined;
  if (!meta) return null;
  if (geometryType === 'LineString' || geometryType === 'MultiLineString') {
    const native = meta.geom === 'line';
    return { color: meta.color, weight: native ? meta.weight : 3, dashArray: native && meta.dash ? meta.dash : undefined, opacity: 1 };
  }
  if (geometryType === 'Polygon' || geometryType === 'MultiPolygon') {
    const native = meta.geom === 'polygon';
    return {
      color: meta.color,
      weight: 2,
      dashArray: native && meta.dash ? meta.dash : undefined,
      fillColor: meta.color,
      fillOpacity: native ? Math.max(meta.alpha, 0.15) : 0.3,
    };
  }
  return null;
}

/** The HTML of a point marker: a coloured badge with the kind's icon, white ring, soft shadow. */
export function activityKindMarker(kind: string | undefined | null): { html: string; size: number } {
  const meta = kind ? ACTIVITY_KINDS[kind] : undefined;
  const size = meta ? 28 : 22;
  const color = meta?.color ?? GENERIC_COLOR;
  const icon = meta?.icon ?? 'mapPin';
  const html =
    `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid #fff;` +
    `box-shadow:0 1px 4px rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;">` +
    `${iconSvg(icon, '#fff', Math.round(size * 0.58))}</div>`;
  return { html, size };
}

/** The kinds as options of a drop-down (the Symbol column of the activity-features table), sorted by name. */
export const ACTIVITY_KIND_OPTIONS: Array<{ value: string; label: string }> = Object.entries(ACTIVITY_KINDS)
  .map(([value, meta]) => ({ value, label: meta.en + ' · ' + meta.ne }))
  .sort((a, b) => a.label.localeCompare(b.label));
