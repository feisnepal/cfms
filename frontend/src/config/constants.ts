/**
 * Centralized frontend constants
 * Based on audit: other_hardcoded_report.md (2026-07-26)
 */

// ── Unit Conversions ─────────────────────────────────────────
export const CONVERSIONS = {
  /** kg per bhari (भारी) — SSOT with backend BHARI_KG */
  BHARI_KG: 30,

  /** Cubic feet per cubic meter */
  CFT_PER_M3: 35.3147,

  /** Square meters per hectare */
  SQM_PER_HA: 10_000,

  /** Cubic meters per chatta (चत्ता) — firewood stacking measure */
  M3_PER_CHATTA: 9.486,

  /** Kilograms per tonne */
  KG_PER_TONNE: 1_000,

  /** Millimeters per inch */
  MM_PER_INCH: 25.4,
} as const;

// ── Map Defaults ─────────────────────────────────────────────
export const MAP_DEFAULTS = {
  /** Nepal approximate center [lat, lng] */
  CENTER: [28.3949, 84.124] as [number, number],
  ZOOM: 7,
  MIN_ZOOM: 5,
  MAX_ZOOM: 18,
  DETAIL_ZOOM: 13,
  EDITOR_ZOOM: 14,
  SPLIT_PREVIEW_ZOOM: 15,
} as const;

// ── Timeouts (ms) ────────────────────────────────────────────
export const TIMEOUTS = {
  DOWNLOAD: 120_000,
  AI_REQUEST: 60_000,
  AI_OLLAMA: 120_000,
} as const;

// ── Color Palettes ───────────────────────────────────────────
export const COLORS = {
  CASTE: [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
  ],
  ISLAND: [
    '#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628',
  ],
  CHART_DEFAULT: [
    '#4e79a7', '#f28e2c', '#e15759', '#76b7b2', '#59a14f',
    '#edc949', '#af7aa1', '#ff9da7', '#9c755f', '#bab0ab',
  ],
} as const;

// ── API Path Helpers ─────────────────────────────────────────
export const API_ENDPOINTS = {
  auth: {
    login: '/api/auth/login',
    refresh: '/api/auth/refresh',
  },
  forests: {
    calculations: (id: string) => `/api/forests/calculations/${id}`,
    blocks: (calcId: string) => `/api/forests/calculations/${calcId}/blocks`,
    compartments: (calcId: string) => `/api/forests/calculations/${calcId}/compartments`,
    analysis: (calcId: string) => `/api/forests/calculations/${calcId}/analysis`,
    sampling: (calcId: string) => `/api/forests/calculations/${calcId}/sampling`,
  },
  operationalPlans: {
    generate: '/api/operational-plans/generate',
    download: (id: string) => `/api/operational-plans/${id}/download`,
  },
  tiles: {
    png: (calcId: string, layerId: string, z: number, x: number, y: number) =>
      `/api/calculations/${calcId}/tiles/${layerId}/${z}/${x}/${y}.png`,
  },
  location: {
    districts: '/api/location/districts',
    municipalities: '/api/location/municipalities',
  },
} as const;

// ── Sampling Defaults ────────────────────────────────────────
export const SAMPLING_DEFAULTS = {
  INTENSITY_PCT: 0.5,
  MIN_SAMPLES_LARGE_BLOCK: 5,
  MIN_SAMPLES_SMALL_BLOCK: 2,
  BOUNDARY_BUFFER_M: 50,
  MIN_BOUNDARY_DISTANCE_M: 20,
  MAX_SLOPE_DEG: 45,
  CIRCULAR_RADIUS_M: 12.6156, // sqrt(500 / π)
} as const;

// ── User Roles ───────────────────────────────────────────────
export const ROLES = {
  SUPER_ADMIN: 'super_admin',
  ADMIN: 'admin',
  FOREST_OFFICER: 'forest_officer',
  USER: 'user',
} as const;
