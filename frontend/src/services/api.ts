/**
 * API client — centralised HTTP layer for all backend endpoints.
 *
 * Provides typed API client objects (authApi, forestApi, inventoryApi,
 * fieldInventoryApi, operationalPlanApi, etc.) built on Axios with
 * automatic JWT bearer-token injection and error handling.
 */
import axios from 'axios';
import { clearOfflineApiCache } from '../pwa/offline';
import type {
  LoginRequest,
  RegisterRequest,
  Designation,
  UserType,
  TokenResponse,
  User,
  CommunityForest,
  MyForestsResponse,
  Calculation,
} from '../types';
import { downloadFromApi } from '../utils/download';
import type { UploadSchema } from '../lib/classifyUpload';

export interface ExportRequirementItem {
  key: string;
  /** the rail step (context id) where it is done */
  step?: string | null;
  done: boolean;
  label_en: string;
  label_ne: string;
  hint_en: string;
  hint_ne: string;
  detail: Record<string, unknown>;
}
export type ShareScope = 'private' | 'office' | 'public';
export type TemplateLicense = 'cc_by' | 'cc0' | 'view_only';
export type TemplateTier = 'community' | 'verified' | 'official';
export interface PublishCheckIssue {
  severity: 'error' | 'warning';
  code: string;
  message: string;
  node_id?: string | null;
  title?: string;
  name?: string;
  numbers?: string[];
}
export interface PublishCheck {
  ok: boolean;
  errors: PublishCheckIssue[];
  warnings: PublishCheckIssue[];
}
export interface LineageItem {
  id: string | null;
  name: string | null;
  author_name: string | null;
  tier: TemplateTier;
  /** the name and author may be shown (the template was shared at some time) */
  visible: boolean;
  /** the viewer can open it (a withdrawn or private template cannot be opened, but its credit stays) */
  openable?: boolean;
  withdrawn?: boolean;
  created_at: string | null;
}
export interface TemplateReport {
  id: string;
  template_id: string;
  template_name: string | null;
  template_status: string | null;
  share_scope: string | null;
  reason: string;
  status: 'open' | 'dismissed' | 'actioned';
  reporter: string | null;
  created_at: string | null;
  handled_note: string | null;
}
export interface PlanValidityIssue {
  severity: 'error' | 'warning';
  code: string;
  message: string;
  node_id?: string | null;
  token?: string | null;
  title?: string;
}
export interface PlanValidity {
  ok: boolean;
  errors: PlanValidityIssue[];
  warnings: PlanValidityIssue[];
}
export interface PlanReadiness {
  total: number;
  resolved: number;
  missing: { key: string; known: boolean; label_en: string; label_ne: string }[];
  empty_lists: { key: string; label_en: string; label_ne: string }[];
  unmet_maps: { token: string; reason_en: string; reason_ne: string }[];
  unverified: number;
  ready: boolean;
}
export interface ExportRequirements {
  ready: boolean;
  items: ExportRequirementItem[];
}

/** Auto-Block MMU (Phase B) shared types. */
export interface AutoBlockPreviewMeta {
  source_layer: string;
  basis: string;
  level: string;
  boundary_ha: number;
  pieces_ha: number;
  slivers_absorbed: number;
  piece_count: number;
  minimize_n: number;
  adjacency_edge_count: number;
  sliver_area_m2: number;
  minimize_floor_ha: number;
}

export interface AutoBlockEdge {
  a: number;
  b: number;
  shared_m: number;
}

export type AutoBlockSource =
  | 'mmu' | 'slope' | 'aspect' | 'canopy' | 'nasa_quality'
  // RS-9.1/9.2/9.3/9.5 (P9, owner directive 2026-10-01)
  | 'forest_health' | 'landcover' | 'dem' | 'forest_type'
  // RS-10.2 (P10, owner directive 2026-10-01): Union, Mode B (zonal/default).
  | 'union_zonal'
  // RS-10.3/10.3b (P10): Union, Mode A (fusion/opt-in) — pixel-level fusion
  // of a SELECTABLE subset of the classified rasters (slope is always
  // included; every other source is optional, owner question 2026-10-01).
  | 'union_fusion';

/** RS-2.16/P2.5: one Auto-Block layer. `promotedAs` null = a non-counting
 *  trial overlay; 'blocks'/'compartments' = the forest's real structure. */
export interface RasterLayerInfo {
  id: string;
  source: AutoBlockSource | string;
  name: string;
  promoted_as: 'blocks' | 'compartments' | null;
  promoted_at: string | null;
}

export interface AutoBlockCommitBlock {
  index: number;
  name: string;
  block_name: string;
  natural_name: string | null;
  /** Slope band (1-4) that dominated this piece, when source === 'slope'. */
  dominant_slope_band?: number | null;
  /** Aspect code (1-8), when source === 'aspect'. */
  dominant_aspect?: number | null;
  /** Canopy-height structure class (1-4), when source === 'canopy'. */
  dominant_canopy_class?: number | null;
  /** NASA 2020 forest-quality class (1-3), when source === 'nasa_quality'.
   * `null` for a piece dominated by class 0 (non-forest), which D41 carves as
   * geometry but deliberately leaves anonymous. */
  dominant_nasa_quality?: number | null;
  /** Forest-health (NDVI) class (1-5), when source === 'forest_health'. */
  dominant_health_class?: number | null;
  /** ESA WorldCover land-cover code, when source === 'landcover'. */
  dominant_landcover?: number | null;
  /** Elevation band (1-N, per-forest contour cuts), when source === 'dem'.
   * NOT the same column as the RS-2.19 relative attribute of the same
   * name — see `dominant_contour_band`, which is what this source actually
   * writes; this field name is reserved for the RS-2.19 attribute. */
  dominant_elevation_zone?: number | null;
  /** DEM contour-carve band (1-N), when source === 'dem'. */
  dominant_contour_band?: number | null;
  /** FRTC forest type (1-25), when source === 'forest_type'. `null` for a
   * piece dominated by class 26 ("Unclassified"), carved as geometry but
   * never claimed as one of the 25 named types. */
  dominant_forest_type?: number | null;
  /** RS-10.1/10.2: largest-overlap ForestSubArea category for this piece,
   * when source === 'union_zonal' (or the planned 'union_fusion'). `null`
   * means no sub-area was ever drawn here — the normal case for most of a
   * forest, never an error. */
  sub_area_category?: string | null;
  /** True when the majority-overlap sub-area is Private Land (`is_excluded`
   * on the `ForestSubArea` row) — tagged, not omitted, so a Union piece
   * tells a planner *why* it has no classification. */
  sub_area_excluded?: boolean;
  area_hectares: number;
  geometry: GeoJSON.Geometry;
}

/** Divide-equal-areas (compartment rewire, P1/P13) — request body. */
export interface DivideRequest {
  layer_type: 'compartments' | 'sub_compartments' | 'blocks' | 'sub_blocks' | 'boundary';
  feature_id: string;
  method: 'strips' | 'grid';
  count?: number | null;
  rows?: number | null;
  cols?: number | null;
  direction?: 'vertical' | 'horizontal';
  /** Optional split angle in degrees (legacy convention 0=N-S, 90=E-W) — supersedes `direction`. */
  direction_angle?: number;
  naming_pattern?: string;
  reassign_trees?: boolean;
  notes?: string;
  /** Multi-island boundary: pieces per polygon part, in the boundary's part
   *  order. When omitted the backend derives them from `count`
   *  (MULTI_ISLAND_DIVIDE_PLAN.md). */
  island_counts?: number[];
  /** By-area divide: fixed area in square metres per piece (the last piece
   *  receives the remainder). When set, `method` is forced to `strips` on the
   *  backend and `count`/`rows`/`cols`/`island_counts` are ignored.
   *  Compartment min floor is 1 ha (MIN_COMPARTMENT_AREA_M2). */
  target_area_sqm?: number;
}

/** One row of the multi-island preview breakdown (P2). */
export interface DivideIslandRow {
  index: number;
  area_ha: number;
  suggested_count: number;
  avg_piece_ha: number;
  undersized: boolean;
}

/** Labelled preview piece (P13) — geometry + name + area for the ghost overlay. */
export interface DividePreviewPiece {
  geometry: GeoJSON.Geometry;
  name: string;
  area_hectares: number;
  area_sqm: number;
  index: number;
}

/** POST divide-equal-areas response for compartments/sub_compartments. */
export interface DivideResponse {
  success: boolean;
  parent_id: string;
  children: string[];
  split_history_id: string;
  trees_reassigned: number;
  warnings: string[];
  n_children: number;
  boundary_pieces_stored_as: string;
}

/** POST divide-preview response (labelled pieces, P13). */
export interface DividePreviewResponse {
  success: boolean;
  pieces: DividePreviewPiece[];
  warnings: string[];
  total_pieces: number;
  parent_id?: string;
  /** Failure reason when success is false: 'TOLERANCE_EXCEEDED' | 'TOO_FEW_PIECES'. */
  reason?: string;
  /** Multi-island parent only (MULTI_ISLAND_DIVIDE_PLAN.md P2). */
  islands?: DivideIslandRow[];
  target_area_ha?: number;
  n_effective?: number;
}


export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';
// Canonical API version prefix. All new requests should target /api/v1.
// The backend keeps /api as a deprecated shim (Deprecation header), so this
// client is already on the versioned path.
export const API_V1_PREFIX = '/api/v1';

const api = axios.create({
  // In dev mode, use relative URLs so Vite proxy handles them
  // In production, use absolute URL
  baseURL: import.meta.env.DEV ? undefined : API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
    // Gap 6.3 (CSRF hardening): marks every request as same-origin AJAX so the
    // backend can reject cross-site form posts. Auth here is JWT-Bearer (no
    // cookies), so this is defense-in-depth + documentation, not the primary
    // control.
    'X-Requested-With': 'XMLHttpRequest',
  },
});

// Debug interceptor to log full URL
api.interceptors.request.use(
  (config) => {
    const fullUrl = config.baseURL ? `${config.baseURL}${config.url}` : config.url;
    console.log('Axios request URL:', fullUrl);
    return config;
  },
  (error) => Promise.reject(error)
);


/**
 * H2.5 / S1-05: persist a token pair.
 *
 * Refresh tokens are rotated on every use — the old one is dead the moment the
 * new one is issued — so the stored value must be replaced, never appended to
 * or kept "just in case". Presenting a superseded token is what the server
 * treats as theft, and it revokes the whole session family in response.
 */
export function storeTokens(data: { access_token: string; refresh_token?: string; expires_in: number }) {
  localStorage.setItem('access_token', data.access_token);
  if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
  // Five minutes of headroom before the real expiry.
  localStorage.setItem('token_expiry', String(Date.now() + (data.expires_in - 300) * 1000));
}

/** The last signed-in user, kept so an offline start can still show who is signed in (see AuthContext). */
export const LAST_USER_KEY = 'cf_last_user';

export function clearTokens() {
  clearOfflineApiCache();   // the answers kept for offline use belong to whoever was signed in
  localStorage.removeItem(LAST_USER_KEY);
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('token_expiry');
  localStorage.removeItem('last_active');
  localStorage.removeItem('refresh_fail_count');
}

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // Track last API activity for idle timeout
    localStorage.setItem('last_active', String(Date.now()));

    // If sending FormData, remove Content-Type header so browser sets it with boundary
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type'];
    }

    return config;
  },
  (error) => Promise.reject(error)
);

/**
 * H3.7 / S2-xx — single-flight token refresh.
 *
 * The 401 interceptor below used to refresh independently for every failed
 * request. Before H2.5 that was merely wasteful; after it, it logs the user out.
 *
 * Refresh tokens are now single-use and rotated, and presenting a spent one is
 * treated as theft: the server revokes the whole family. So when three requests
 * 401 together, all three read the SAME token from localStorage, the first
 * rotates it, and the other two present a token the server has already
 * consumed — reuse detected, family revoked, session over. The more concurrent
 * requests, the more certain it is.
 *
 * This is not hypothetical. On 2026-08-24 the live database held **six browser
 * token families revoked with `reuse_detected`** and no other revocation reason
 * anywhere: six sessions ended by their own client racing itself.
 *
 * So every caller shares one in-flight promise. The first starts the refresh;
 * the rest await the same result and retry with the token it produced. One
 * rotation per expiry, whatever the concurrency.
 */
let refreshInFlight: Promise<TokenResponse> | null = null;

export function refreshTokenOnce(): Promise<TokenResponse> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) throw new Error('No refresh token');
    // Deliberately a bare axios call, not `api.post`: going through the
    // instance would re-enter the response interceptor on failure and start a
    // second refresh from inside the first.
    // Mirrors the instance's own baseURL rule (line ~108): in dev the Vite
    // proxy serves /api, so an absolute base would bypass it.
    const base = import.meta.env.DEV ? '' : API_BASE_URL;
    const response = await axios.post<TokenResponse>(
      `${base}/api/auth/refresh`,
      { refresh_token: refreshToken },
      { headers: { 'Content-Type': 'application/json' } },
    );
    storeTokens(response.data);
    return response.data;
  })();

  // Cleared on BOTH paths. Leaving a rejected promise cached would make every
  // later refresh fail with the first failure's error, turning one bad moment
  // into a permanently broken session.
  refreshInFlight = refreshInFlight.finally(() => {
    refreshInFlight = null;
  }) as Promise<TokenResponse>;

  return refreshInFlight;
}

/** Test seam: forget any in-flight refresh. */
export function __resetRefreshInFlight() {
  refreshInFlight = null;
}

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // On 401, try once to refresh the token, then retry the request
    // Never retry the refresh endpoint itself (would infinite loop)
    if (error.response?.status === 401
        && !originalRequest._retry
        && !originalRequest.url?.includes('/api/auth/refresh')) {
      originalRequest._retry = true;
      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) {
        clearTokens();
        window.location.href = '/login';
        return Promise.reject(error);
      }
      try {
        // Shared with every other 401 in flight and with AuthContext's timer —
        // one rotation, however many requests are waiting on it.
        const data = await refreshTokenOnce();
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        return api(originalRequest);
      } catch {
        // The refresh token is spent, revoked, or the family was killed after a
        // reuse was detected. Any of those mean this session is over.
        clearTokens();
        window.location.href = '/login';
      }
    }
    // The backend's error bodies carry a top-level `correlation_id` (catch-all
    // 500 + DB error handlers in main.py). Surface it to readDetail() so the
    // "quote the reference code below" sentence gets a code beneath it.
    const resData = error.response?.data as { correlation_id?: unknown; detail?: unknown } | undefined;
    if (resData && resData.correlation_id && resData.detail
        && typeof resData.detail === 'object' && !Array.isArray(resData.detail)) {
      (resData.detail as Record<string, unknown>).reference = String(resData.correlation_id);
    }
    return Promise.reject(error);
  }
);

// Cache-invalidation interceptor (Cache Plan Phase 6.5): the backend can
// signal which client caches to drop via response headers, keeping the
// IndexedDB cache consistent after server-side data changes.
import { browserCache } from './browserCache';

api.interceptors.response.use(
  (response) => {
    const invalidated = response.headers['x-cache-invalidated'];
    const calcId = response.headers['x-cache-calc-id'];
    if (invalidated && calcId) {
      const categories = invalidated.split(',');
      if (categories.includes('maps')) browserCache.clearMaps(calcId);
      if (categories.includes('charts')) browserCache.clearCharts(calcId);
      if (categories.includes('analysis')) browserCache.clearAnalysis(calcId);
      if (categories.includes('all')) browserCache.clearAll(calcId);
    }
    return response;
  },
  (error) => Promise.reject(error)
);

// Error code patterns for validation - moved outside function to avoid parser issues
const ERROR_CODE_PATTERNS = [
  'password', 'email', 'token', 'user', 'geometry', 'boundary', 'file',
  'format', 'validation', 'permission', 'unauthorized', 'not_found',
  'committee', 'household', 'sampling', 'activity', 'boundary', 'inventory',
  'passwordMinLength', 'passwordUppercase', 'passwordLowercase', 'passwordDigit',
  'genderInvalid', 'positionInvalid', 'casteInvalid', 'mobileLength', 'mobileDigits',
  'mainCommitteeMax', 'advisoryCommitteeMax', 'financialCommitteeMax',
  'landUnitInvalid', 'prosperityInvalid', 'landAreaNegative', 'livestockNegative',
  'intensityRange', 'plotSizeInvalid', 'minPlotsInvalid', 'gridSpacingInvalid', 'boundaryBufferInvalid',
  'geometryRequired', 'geometryInvalid', 'geometryTypeMismatch', 'pointCoordsInvalid',
  'pointCoordsNumeric', 'lineStringMinPoints', 'lineStringPointFormat', 'polygonRingsRequired',
  'polygonMinPoints', 'polygonRingClosed', 'polygonInvalid', 'subAreaRequiresBlock',
  'activityNameRequired', 'quantityPositive', 'budgetNonNegative', 'yearRange',
  'formatUnsupported', 'fileTooLarge', 'fileEmpty', 'shpMissing', 'noFeatures', 'noGeometries',
  'invalidGeometry', 'noPolygonGeometries',
  'geometryRequired', 'geometryInvalid', 'geometryEmpty', 'selfIntersection', 'areaZero', 'crsInvalid',
  'dbhRange', 'heightRange', 'heightGteDbh', 'speciesRequired', 'speciesUnknown', 'plotIdRequired',
  'treeIdRequired', 'duplicatePlotTree', 'blockRequired', 'coordinatesRequired',
  'notFound', 'permissionDenied', 'unauthorized', 'tokenExpired', 'validationError',
  'serverError', 'networkError', 'fileTooLarge', 'formatUnsupported', 'processingError'
];

// Error code extraction utility for i18n integration
// Backend validation errors should return structured error codes that map to i18n keys
export const extractErrorCode = (error: any): string | null => {
  if (!error?.response?.data) return null;
  
  const detail = error.response.data.detail;
  
  // Handle structured error objects
  if (typeof detail === 'object' && detail !== null) {
    // FastAPI validation errors: { detail: [{ loc: [...], msg: "error_code", type: ... }] }
    if (Array.isArray(detail)) {
      const firstError = detail[0];
      if (firstError?.msg && typeof firstError.msg === 'string') {
        // Check if msg is a validation code (contains underscore, no spaces)
        if (firstError.msg.includes('_') && !firstError.msg.includes(' ')) {
          return firstError.msg;
        }
      }
    }
    // Custom error format: { code: "ERROR_CODE", message: "..." }
    if (detail.code) return detail.code;
    if (detail.error_code) return detail.error_code;
    if (detail.key) return detail.key;
  }
  
  // String error codes (underscore format, no spaces)
  if (typeof detail === 'string' && detail.includes('_') && !detail.includes(' ')) {
    return detail;
  }
  
  return null;
};

// Map backend error codes to i18n keys
export const mapErrorCodeToI18nKey = (errorCode: string): string => {
  const mapping: Record<string, string> = {
    // Auth
    'passwordMinLength': 'authValidation.passwordMinLength',
    'passwordUppercase': 'authValidation.passwordUppercase',
    'passwordLowercase': 'authValidation.passwordLowercase',
    'passwordDigit': 'authValidation.passwordDigit',
    'passwordSpecial': 'authValidation.passwordSpecial',
    'emailInvalid': 'authValidation.emailInvalid',
    'emailRequired': 'authValidation.emailRequired',
    'passwordRequired': 'authValidation.passwordRequired',
    'invalidCredentials': 'authValidation.invalidCredentials',
    'tokenInvalid': 'authValidation.tokenInvalid',
    'userNotFound': 'authValidation.userNotFound',
    'userInactive': 'authValidation.userInactive',
    
    // Committee
    'genderInvalid': 'committeeValidation.genderInvalid',
    'positionInvalid': 'committeeValidation.positionInvalid',
    'casteInvalid': 'committeeValidation.casteInvalid',
    'mobileLength': 'committeeValidation.mobileLength',
    'mobileDigits': 'committeeValidation.mobileDigits',
    'mainCommitteeMax': 'committeeValidation.mainCommitteeMax',
    'advisoryCommitteeMax': 'committeeValidation.advisoryCommitteeMax',
    'financialCommitteeMax': 'committeeValidation.financialCommitteeMax',
    
    // Household
    'landUnitInvalid': 'householdValidation.landUnitInvalid',
    'prosperityInvalid': 'householdValidation.prosperityInvalid',
    'landAreaNegative': 'householdValidation.landAreaNegative',
    'livestockNegative': 'householdValidation.livestockNegative',
    
    // Sampling
    'intensityRange': 'samplingValidation.intensityRange',
    'plotSizeInvalid': 'samplingValidation.plotSizeInvalid',
    'minPlotsInvalid': 'samplingValidation.minPlotsInvalid',
    'gridSpacingInvalid': 'samplingValidation.gridSpacingInvalid',
    'boundaryBufferInvalid': 'samplingValidation.boundaryBufferInvalid',
    'plotShapeRequired': 'samplingValidation.plotShapeRequired',
    'samplingTypeInvalid': 'samplingValidation.samplingTypeInvalid',
    'noAccessibleForest': 'samplingValidation.noAccessibleForest',
    'samplingDesignNotFound': 'samplingValidation.samplingDesignNotFound',
    'samplingDesignEmpty': 'samplingValidation.samplingDesignEmpty',
    
    // Tree model / all-tree export
    'invalidRoles': 'treeValidation.invalidRoles',
    'ratioSumInvalid': 'treeValidation.ratioSumInvalid',
    'invalidDistribution': 'treeValidation.invalidDistribution',
    
    // Forest
    'invalidCategory': 'forestValidation.invalidCategory',
    
    // Activity
    'geometryValidationFailed': 'activityValidation.geometryValidationFailed',
    'geometryTypeMismatch': 'activityValidation.geometryTypeMismatch',
    'pointCoordsInvalid': 'activityValidation.pointCoordsInvalid',
    'pointCoordsNumeric': 'activityValidation.pointCoordsNumeric',
    'lineStringMinPoints': 'activityValidation.lineStringMinPoints',
    'lineStringPointFormat': 'activityValidation.lineStringPointFormat',
    'polygonRingsRequired': 'activityValidation.polygonRingsRequired',
    'polygonMinPoints': 'activityValidation.polygonMinPoints',
    'polygonRingClosed': 'activityValidation.polygonRingClosed',
    'polygonInvalid': 'activityValidation.polygonInvalid',
    'subAreaRequiresBlock': 'activityValidation.subAreaRequiresBlock',
    'activityNameRequired': 'activityValidation.activityNameRequired',
    'quantityPositive': 'activityValidation.quantityPositive',
    'budgetNonNegative': 'activityValidation.budgetNonNegative',
    'yearRange': 'activityValidation.yearRange',
    
    // File
    'fileEmpty': 'fileValidation.fileEmpty',
    'shpMissing': 'fileValidation.shpMissing',
    'noFeatures': 'fileValidation.noFeatures',
    'noGeometries': 'fileValidation.noGeometries',
    'invalidGeometry': 'fileValidation.invalidGeometry',
    'noPolygonGeometries': 'fileValidation.noPolygonGeometries',
    
    // Boundary
    'geometryRequired': 'boundaryValidation.geometryRequired',
    'geometryInvalid': 'boundaryValidation.geometryInvalid',
    'geometryEmpty': 'boundaryValidation.geometryEmpty',
    'selfIntersection': 'boundaryValidation.selfIntersection',
    'areaZero': 'boundaryValidation.areaZero',
    'crsInvalid': 'boundaryValidation.crsInvalid',
    
    // Inventory
    'dbhRange': 'inventoryValidation.dbhRange',
    'heightRange': 'inventoryValidation.heightRange',
    'heightGteDbh': 'inventoryValidation.heightGteDbh',
    'speciesRequired': 'inventoryValidation.speciesRequired',
    'speciesUnknown': 'inventoryValidation.speciesUnknown',
    'plotIdRequired': 'inventoryValidation.plotIdRequired',
    'treeIdRequired': 'inventoryValidation.treeIdRequired',
    'duplicatePlotTree': 'inventoryValidation.duplicatePlotTree',
    'blockRequired': 'inventoryValidation.blockRequired',
    'coordinatesRequired': 'inventoryValidation.coordinatesRequired',
    
    // General
    'notFound': 'generalErrors.notFound',
    'permissionDenied': 'generalErrors.permissionDenied',
    'unauthorized': 'generalErrors.unauthorized',
    'tokenExpired': 'generalErrors.tokenExpired',
    'validationError': 'generalErrors.validationError',
    'serverError': 'generalErrors.serverError',
    'networkError': 'generalErrors.networkError',
    'fileTooLarge': 'generalErrors.fileTooLarge',
    'formatUnsupported': 'generalErrors.formatUnsupported',
    'processingError': 'generalErrors.processingError',
  };
  
  return mapping[errorCode] || `validation.${errorCode}`;
};

export const getErrorI18nKey = (error: any): string => {
  const code = extractErrorCode(error);
  if (code) {
    return mapErrorCodeToI18nKey(code);
  }
  return 'generalErrors.serverError';
};

// Auth endpoints
export interface OrgMember {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  org_member_role: 'owner' | 'member' | null;
  org_vouched_at: string | null;
  is_approved: boolean;
  type_details: Record<string, string> | null;
}

export const authApi = {
  login: async (credentials: LoginRequest): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>('/api/auth/login', credentials);
    return response.data;
  },

  register: async (userData: RegisterRequest): Promise<User> => {
    const response = await api.post<User>('/api/auth/register', userData);
    return response.data;
  },

  me: async (): Promise<User> => {
    const response = await api.get<User>('/api/auth/me');
    return response.data;
  },

  /** Step 1 of sign-up: text a code to the number. */
  signupPhoneCode: async (phone: string): Promise<void> => {
    await api.post('/api/auth/signup/phone-code', { phone });
  },

  /** Sign in by phone: ask for a code (the answer is the same for any number), then exchange it. */
  loginPhoneCode: async (phone: string): Promise<void> => {
    await api.post('/api/auth/login/phone-code', { phone });
  },
  loginPhone: async (phone: string, code: string): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>('/api/auth/login/phone', { phone, code });
    return response.data;
  },
  loginFacebook: async (access_token: string): Promise<TokenResponse> => {
    const response = await api.post<TokenResponse>('/api/auth/login/facebook', { access_token });
    return response.data;
  },

  forgotPassword: async (identifier: string): Promise<void> => {
    await api.post('/api/auth/forgot-password', { identifier });
  },
  resetPassword: async (body: { new_password: string; token?: string; phone?: string; code?: string }): Promise<void> => {
    await api.post('/api/auth/reset-password', body);
  },
  verifyEmail: async (token: string): Promise<User> => {
    const response = await api.post<User>('/api/auth/email/verify', { token });
    return response.data;
  },

  updateProfile: async (body: {
    full_name?: string;
    user_type?: UserType;
    designation?: Designation;
    sub_division?: string;
    details?: Record<string, string>;
    instagram_handle?: string;
  }): Promise<User> => {
    const response = await api.patch<User>('/api/auth/me/profile', body);
    return response.data;
  },
  myPhoneCode: async (phone: string): Promise<void> => {
    await api.post('/api/auth/me/phone/code', { phone });
  },
  verifyMyPhone: async (phone: string, code: string): Promise<User> => {
    const response = await api.post<User>('/api/auth/me/phone/verify', { phone, code });
    return response.data;
  },
  organizationMembers: async (): Promise<OrgMember[]> => {
    const response = await api.get<OrgMember[]>('/api/auth/organization/members');
    return response.data;
  },
  vouchForMember: async (userId: string): Promise<void> => {
    await api.post(`/api/auth/organization/members/${userId}/vouch`);
  },
  myEmailLink: async (email: string): Promise<void> => {
    await api.post('/api/auth/me/email/link', { email });
  },

  /**
   * H2.5 / S1-05: exchange the refresh token for a new pair.
   *
   * This used to POST with no body and let the request interceptor attach the
   * access token — which the server accepted even when long expired, making
   * every token ever issued a permanent credential. The refresh token now
   * travels explicitly, and is single-use: the response carries its successor.
   */
  refresh: async (): Promise<TokenResponse> => {
    // H3.7: routed through the shared single-flight. AuthContext's five-minute
    // timer and the 401 interceptor are two independent paths to this call, and
    // if they overlap one of them presents a spent token and kills the session.
    return refreshTokenOnce();
  },

  logout: async (): Promise<void> => {
    // Best-effort: the server ends every session for this user. If the call
    // fails the client still clears its own storage, but the tokens would
    // remain valid server-side, so the failure is worth not swallowing silently.
    await api.post('/api/auth/logout');
  },

};

// Forest endpoints
export const forestApi = {
  listCommunityForests: async (params?: {
    search?: string;
    regime?: string;
    limit?: number;
    offset?: number;
  }): Promise<CommunityForest[]> => {
    const response = await api.get<CommunityForest[]>('/api/forests/community-forests', {
      params,
    });
    return response.data;
  },

  getCommunityForest: async (id: number): Promise<CommunityForest> => {
    const response = await api.get<CommunityForest>(`/api/forests/community-forests/${id}`);
    return response.data;
  },

  getMyForests: async (): Promise<MyForestsResponse> => {
    const response = await api.get<MyForestsResponse>('/api/forests/my-forests');
    return response.data;
  },

  uploadBoundary: async (
    file: File,
    forestName?: string,
    analysisOptions?: Record<string, boolean>,
    mapOptions?: Record<string, boolean>,
    polygonType?: 'block' | 'compartment',
    compartmentCodeColumn?: string,
    confirmed?: boolean
  ): Promise<Calculation> => {
    const formData = new FormData();
    formData.append('file', file);
    if (forestName) formData.append('forest_name', forestName);
    if (polygonType) formData.append('polygon_type', polygonType);
    if (compartmentCodeColumn) formData.append('compartment_code_column', compartmentCodeColumn);
    if (confirmed) formData.append('confirmed', 'true');

    // Append analysis options as form fields
    if (analysisOptions) {
      Object.entries(analysisOptions).forEach(([key, value]) => {
        formData.append(key, String(value));
      });
    }

    // Append map options as form fields
    if (mapOptions) {
      Object.entries(mapOptions).forEach(([key, value]) => {
        formData.append(key, String(value));
      });
    }

    const response = await api.post<Calculation>('/api/forests/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  createFromMap: async (data: {
    forest_name: string;
    outer_boundary: any;
    gps_points?: any[];
    blocks: any[];
    sub_areas?: any[];
    analysis_options?: Record<string, boolean>;
    map_options?: Record<string, boolean>;
    polygon_type?: 'block' | 'compartment';
    compartment_code_column?: string;
    confirmed?: boolean;
  }): Promise<Calculation> => {
    const response = await api.post<Calculation>('/api/forests/create-from-map', data);
    return response.data;
  },

  listCalculations: async (): Promise<Calculation[]> => {
    const response = await api.get<Calculation[]>('/api/forests/calculations');
    return response.data;
  },

  getCalculation: async (id: string): Promise<Calculation> => {
    const response = await api.get<Calculation>(`/api/forests/calculations/${id}`);
    return response.data;
  },

  updateResultData: async (id: string, data: Record<string, any>): Promise<void> => {
    await api.patch(`/api/forests/calculations/${id}/result-data`, data);
  },

  deleteCalculation: async (id: string): Promise<void> => {
    await api.delete(`/api/forests/calculations/${id}`);
  },

  reanalyze: async (
    id: string,
    analysisOptions: Partial<Record<string, boolean>>
  ): Promise<Calculation> => {
    const response = await api.post<Calculation>(
      `/api/forests/calculations/${id}/reanalyze`,
      analysisOptions
    );
    return response.data;
  },

  generateMaps: async (
    id: string,
    mapOptions: Record<string, boolean>
  ): Promise<{
    calculation_id: string;
    status: string;
    generated_maps: Array<{
      map_type: string;
      status: string;
      download_url: string;
    }>;
    failed_maps: Array<{
      map_type: string;
      status: string;
      error: string;
    }>;
    not_implemented: string[];
    message: string;
  }> => {
    const response = await api.post(
      `/api/forests/calculations/${id}/generate-maps`,
      mapOptions
    );
    return response.data;
  },

  // Species confirmation endpoints
  toggleSpeciesConfirmation: async (
    calculationId: string,
    scientificName: string,
    confirmed: boolean,
    blockName?: string  // NEW: Optional block identifier
  ): Promise<Calculation> => {
    const response = await api.patch<Calculation>(
      `/api/forests/calculations/${calculationId}/species/${encodeURIComponent(scientificName)}/confirm`,
      {
        confirmed,
        block_name: blockName  // NEW: Pass block_name if provided
      }
    );
    return response.data;
  },

  confirmAllSpecies: async (
    calculationId: string,
    confirmed: boolean
  ): Promise<Calculation> => {
    const response = await api.post<Calculation>(
      `/api/forests/calculations/${calculationId}/species/confirm-all`,
      { confirmed }
    );
    return response.data;
  },

  getSpeciesSummary: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/forests/calculations/${calculationId}/species-summary`);
    return response.data;
  },

  // Accessible forest area endpoint (Phase 2)
  getAccessibleForestArea: async (
    calculationId: string,
    params?: {
      filter_slope?: boolean;
      max_slope_degrees?: number;
    }
  ): Promise<any> => {
    const response = await api.get(
      `/api/forests/calculations/${calculationId}/accessible-area`,
      { params }
    );
    return response.data;
  },

  // Tree cover areas endpoint - calculate effective forest areas for all blocks
  calculateTreeCoverAreas: async (calculationId: string): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/tree-cover-areas`
    );
    return response.data;
  },

  // Block area detail (Table 5) - get per-block forest area description
  getBlockAreaDetail: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/forests/calculations/${calculationId}/block-area-detail`
    );
    return response.data;
  },

  // Geometry editing endpoints
  updateGeometry: async (
    calculationId: string,
    geometry: any,
    reanalyze: boolean = false
  ): Promise<any> => {
    const response = await api.patch(
      `/api/forests/calculations/${calculationId}/geometry`,
      { geometry, reanalyze }
    );
    return response.data;
  },

  // Sub-area management endpoints
  addSubArea: async (
    calculationId: string,
    data: {
      name: string;
      category: string;
      geometry: any;
      block_id?: string;
      block_name?: string;
      block_breakdown?: Array<{ blockId: string; blockName: string; area: number; percentage: number }>;
      is_excluded?: boolean;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/sub-areas`,
      data
    );
    return response.data;
  },

  listSubAreas: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/forests/calculations/${calculationId}/sub-areas`
    );
    return response.data;
  },

  updateSubArea: async (
    calculationId: string,
    subAreaId: string,
    data: {
      name?: string;
      category?: string;
      geometry?: any;
      block_id?: string;
      block_name?: string;
      is_excluded?: boolean;
    }
  ): Promise<any> => {
    const response = await api.patch(
      `/api/forests/calculations/${calculationId}/sub-areas/${subAreaId}`,
      data
    );
    return response.data;
  },

  /** `planLines` says what happens to the yearly-plan lines tied to the sub-area; without it the server answers 409 when there are any. */
  deleteSubArea: async (
    calculationId: string,
    subAreaId: string,
    planLines?: 'delete' | 'keep'
  ): Promise<any> => {
    const response = await api.delete(
      `/api/forests/calculations/${calculationId}/sub-areas/${subAreaId}`,
      { params: planLines ? { plan_lines: planLines } : undefined }
    );
    return response.data;
  },

  clearSubAreas: async (calculationId: string, planLines?: 'delete' | 'keep'): Promise<any> => {
    const response = await api.delete(
      `/api/forests/calculations/${calculationId}/sub-areas`,
      { params: planLines ? { plan_lines: planLines } : undefined }
    );
    return response.data;
  },

  // Protection Working Circle (PROTECTION_WORKING_CIRCLE_PLAN.md P3):
  // promote a protected sub-area to a P-N protection working-circle unit, and back.
  promoteSubAreaToUnit: async (
    calculationId: string,
    subAreaId: string
  ): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/sub-areas/${subAreaId}/promote-to-unit`
    );
    return response.data;
  },

  demoteProtectionUnit: async (
    calculationId: string,
    blockId: string
  ): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/protection-units/${blockId}/demote-to-subarea`
    );
    return response.data;
  },

  // Interactive boundary editing
  editBoundary: async (
    calculationId: string,
    data: {
      operation: string;
      features?: any[];
      target_index?: number;
      reanalyze?: boolean;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/edit-boundary`,
      data
    );
    return response.data;
  },

  // Block naming endpoints
  getPolygons: async (calculationId: string): Promise<{
    polygons: Array<{
      index: number;
      geometry: any;
      area_hectares: number;
      current_name: string;
    }>;
    total_count: number;
  }> => {
    const response = await api.get(
      `/api/forests/calculations/${calculationId}/polygons`
    );
    return response.data;
  },

  /**
   * Create a single default block (or, with isCompartment, compartment) from
   * the calculation's boundary. Used when user chooses "Single Block"/"Single
   * Compartment", and by the workspace's "Import Block/Compartment from
   * Forest Boundary" menu command.
   */
  createSingleBlock: async (
    calculationId: string,
    blockName?: string,
    isCompartment?: boolean
  ): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/create-single-block`,
      null,
      { params: { block_name: blockName, is_compartment: isCompartment } }
    );
    return response.data;
  },

  /**
   * Update block geometries (from block editor)
   * Handles vertex editing with automatic sub-area clipping
   */
  updateBlocksGeometry: async (
    calculationId: string,
    data: {
      blocks: Array<{
        block_id: string;
        block_name: string;
        geometry: any;
        area_hectares: number;
        index: number;
      }>;
      update_boundary: boolean;
    }
  ): Promise<any> => {
    const response = await api.patch(
      `/api/forests/calculations/${calculationId}/update-blocks`,
      data
    );
    return response.data;
  },

  /**
   * Save work-in-progress polygon creation as draft
   */
  saveDraft: async (draftData: {
    forest_name: string;
    islands: Array<{
      id: string;
      geometry: any;
      area: number;
    }>;
    mode: 'auto' | 'manual';
    draft_id?: string;
  }): Promise<any> => {
    const response = await api.post('/api/forests/save-draft', draftData);
    return response.data;
  },

  /**
   * List all drafts for current user
   */
  listDrafts: async (): Promise<any[]> => {
    const response = await api.get('/api/forests/drafts');
    return response.data;
  },

  /**
   * Get full draft data including all islands
   */
  getDraft: async (draftId: string): Promise<any> => {
    const response = await api.get(`/api/forests/drafts/${draftId}`);
    return response.data;
  },

  /**
   * Delete a draft
   */
  deleteDraft: async (draftId: string): Promise<void> => {
    await api.delete(`/api/forests/drafts/${draftId}`);
  },

  /**
   * Create a CFOP draft by name only (name-first, no geometry yet).
   * The boundary/geometry is added afterwards in the workspace.
   * Returns the created draft.
   */
  createDraftByName: async (forestName: string): Promise<any> => {
    const response = await api.post(
      '/api/forests/drafts/create-name-only',
      { forest_name: forestName }
    );
    return response.data;
  },

  /**
   * Create multiple blocks from polygon mapping
   * Note: run_analysis parameter removed - analysis triggered separately from Analysis page
   */
  createBlocks: async (calculationId: string, blocks: Array<{
    polygon_index: number;
    name: string;
  }>): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/blocks`,
      { blocks }
    );
    return response.data;
  },

  /**
   * Update forest boundary geometry
   */
  updateBoundaryGeometry: async (calculationId: string, data: {
    geometry: any;
    area_hectares: number;
    confirmed?: boolean;
  }): Promise<any> => {
    const response = await api.put(
      `/api/forests/calculations/${calculationId}/boundary`,
      data
    );
    return response.data;
  },

  /** Boundary point-file flow: preview column mapping + Nepal-validated 4326 points (CSV/XLSX/TXT). */
  previewBoundaryMapping: async (
    calculationId: string,
    file: File,
    opts?: { crsEpsg?: number; mapping?: Record<string, string>; fixSwap?: boolean },
  ): Promise<any> => {
    const formData = new FormData();
    formData.append('file', file);
    if (opts?.crsEpsg) formData.append('crs_epsg', String(opts.crsEpsg));
    if (opts?.mapping) formData.append('mapping', JSON.stringify(opts.mapping));
    if (opts?.fixSwap) formData.append('fix_swap', 'true');
    const response = await api.post(
      `/api/v1/workspace/${calculationId}/boundary/preview-mapping`,
      formData,
    );
    return response.data;
  },

  /** Boundary point-file flow: write ordered/hull polygon as the forest boundary. */
  updateBoundaryFromPoints: async (
    calculationId: string,
    points: { lng: number; lat: number }[],
    method: 'ordered' | 'hull',
  ): Promise<any> => {
    const response = await api.post(
      `/api/v1/workspace/${calculationId}/polygon-from-points`,
      { points: points.map((p) => [p.lng, p.lat]), target_type: 'boundary', name: 'Forest Boundary' },
    );
    return response.data;
  },

  /**
   * Merge one or more geometry pieces (Block / Compartment / Forest-boundary)
   * into the single forest boundary of a calculation.
   */
  mergeForestBoundary: async (calculationId: string, geometries: any[]): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/merge-forest-boundary`,
      { geometries }
    );
    return response.data;
  },

  getBlocks: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/forests/calculations/${calculationId}/blocks`
    );
    return response.data;
  },

  deleteBlocks: async (calculationId: string): Promise<any> => {
    const response = await api.delete(
      `/api/forests/calculations/${calculationId}/blocks`
    );
    return response.data;
  },

  /**
   * Delete the forest boundary (editing.py `delete_boundary`). Guarded server-side:
   * rejected 409 when blocks/compartments/sub-compartments/sub-areas still exist.
   */
  deleteBoundary: async (calculationId: string): Promise<void> => {
    await api.delete(`/api/v1/calculations/${calculationId}/boundary`);
  },

  // --- Boundary overlap+gap preview (PB-2 / PF-1) ---
  previewBoundaryOverlap: async (payload: {
    geometry: GeoJSON.Geometry
    method: string
    forest_id?: string
  }): Promise<any> => {
    const response = await api.post('/api/forests/boundary/preview', payload)
    return response.data
  },

  /**
   * Parse an uploaded boundary file server-side into a single boundary Feature.
   * GeoPackage is SQLite and cannot be decoded in the browser, so GPKG files are
   * sent to `POST /forests/boundary/parse-file`, which runs the same
   * Feature-to-Polygon pipeline as the workspace import.
   */
  parseBoundaryFileServerSide: async (file: File): Promise<GeoJSON.Feature> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/api/forests/boundary/parse-file', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  confirmBoundary: async (payload: {
    resolved_geometry: GeoJSON.Geometry
    original_geometry: GeoJSON.Geometry
    forest_name: string
    method: string
    calculation_id?: string
  }): Promise<any> => {
    const response = await api.post('/api/forests/boundary/confirm', payload)
    return response.data
  },

  includeGapInBoundary: async (
    payload: {
      geometry: GeoJSON.Geometry
      original_geometry: GeoJSON.Geometry
      forest_name: string
      method: string
      gaps: { forest_id: string; gap_ha: number }[]
    },
    calculationId?: string,
  ): Promise<any> => {
    const body: Record<string, unknown> = { ...payload }
    if (calculationId) body.calculation_id = calculationId
    const response = await api.post('/api/forests/boundary/include-gap', body)
    return response.data
  },

  fetchNearbyRelations: async (forestId: string): Promise<any> => {
    const response = await api.get(`/api/forests/${forestId}/nearby`)
    return response.data
  },

  importBlocks: async (calculationId: string, blocks: any[]): Promise<any> => {
    const response = await api.post(
      `/api/forests/calculations/${calculationId}/import-blocks`,
      { blocks }
    );
    return response.data;
  },

  /** Auto-Block (Phase B): clip the chosen source layer to the boundary and
   *  return descending preview pieces + adjacency edges WITHOUT writing.
   *  `source`: 'mmu' (rivers & ridges, default), 'slope' (slope-class
   *  breaks, कार्यविधि §15.2), 'aspect' (compass direction, rasters.aspect)
   *  or 'canopy' (canopy-height structure class, canopy_height5m.tif), or
   *  'nasa_quality' (NASA 2020 forest-quality class, rasters.nasa_forest_2020). */
  autoBlocksPreview: async (
    calculationId: string,
    level: 'blocks' | 'compartments',
    desiredN?: number,
    sliverAreaM2?: number,
    source: AutoBlockSource = 'mmu',
    forceAbsorbOrphans?: boolean,
    /** `union_fusion` only (RS-10.3b, owner question 2026-10-01: "Can user
     *  select some of the raster instead select all raster?"). `sources`:
     *  which optional attributes to pixel-fuse (slope is always included
     *  and can't be deselected) — omitted/undefined fuses all of them.
     *  `includeCanopy`: attach canopy per final piece or skip it. */
    fusionOptions?: { sources?: string[]; includeCanopy?: boolean },
  ): Promise<{
    ok: boolean;
    meta: AutoBlockPreviewMeta;
    pieces: GeoJSON.FeatureCollection;
    edges: AutoBlockEdge[];
  }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/auto-blocks/preview`,
      {
        level, source, desired_n: desiredN ?? null, sliver_area_m2: sliverAreaM2 ?? null,
        force_absorb_orphans: forceAbsorbOrphans ?? false,
        fusion_sources: fusionOptions?.sources ?? null,
        fusion_include_canopy: fusionOptions?.includeCanopy ?? null,
      }
    );
    return response.data;
  },

  /** RS-0.4: is a national raster usable for this forest (table installed
   *  AND intersects the boundary)? Used to pre-flight Union(fusion)'s
   *  optional-attribute checklist so a source with no coverage here (e.g.
   *  NASA 2020 outside its tile extent) is disabled up front instead of
   *  surfacing as `no_union_fusion_coverage` only after Preview runs. */
  rasterCoverage: async (
    calculationId: string,
    layer: string,
  ): Promise<{ layer: string; table: string; table_present: boolean; covered: boolean; tile_count: number }> => {
    const response = await api.get(`/api/v1/calculations/${calculationId}/raster-coverage/${layer}`);
    return response.data;
  },

  /** Auto-Block MMU (Phase B): persist the accepted serial/merged blocks. */
  autoBlocksCommit: async (
    calculationId: string,
    level: 'blocks' | 'compartments',
    blocks: AutoBlockCommitBlock[],
    sliverAreaM2?: number,
    source: AutoBlockSource = 'mmu',
  ): Promise<{ ok: boolean; blocks: unknown[] }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/auto-blocks/commit`,
      { level, blocks, sliver_area_m2: sliverAreaM2 ?? null, source }
    );
    return response.data;
  },

  /** Divide ONE selected block / compartment along river-ridge, slope, aspect or canopy breaks (preview, writes nothing). */
  autoDividePreview: async (
    calculationId: string,
    parentId: string,
    opts: { source: AutoBlockSource; sliverAreaM2?: number; forceAbsorbOrphans?: boolean; desiredN?: number },
  ): Promise<{
    ok: boolean;
    meta: AutoBlockPreviewMeta & { parent_id?: string; parent_name?: string; child_layer?: 'sub_blocks' | 'sub_compartments' };
    pieces: GeoJSON.FeatureCollection;
    edges: AutoBlockEdge[];
  }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/blocks/${parentId}/auto-divide/preview`,
      {
        source: opts.source,
        desired_n: opts.desiredN ?? null,
        sliver_area_m2: opts.sliverAreaM2 ?? null,
        force_absorb_orphans: opts.forceAbsorbOrphans ?? false,
      },
    );
    return response.data;
  },

  /** Persist the accepted pieces as children of the selected feature. */
  autoDivideCommit: async (
    calculationId: string,
    parentId: string,
    source: AutoBlockSource,
    blocks: AutoBlockCommitBlock[],
    sliverAreaM2?: number,
  ): Promise<{ ok: boolean; children: string[]; n_children: number; child_layer: string; undivided_blocks?: number }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/blocks/${parentId}/auto-divide/commit`,
      { source, blocks, sliver_area_m2: sliverAreaM2 ?? null },
    );
    return response.data;
  },

  /** RS-2.16/P2.5: every Auto-Block layer for this forest (promoted + trial).
   *  Path is `auto-block-layers`, not `raster-layers` -- the latter already
   *  names the unrelated raster TILE catalog endpoint below this file. */
  listRasterLayers: async (
    calculationId: string,
  ): Promise<{ layers: RasterLayerInfo[] }> => {
    const response = await api.get(
      `/api/v1/calculations/${calculationId}/auto-block-layers`
    );
    return response.data;
  },

  /** Make ``layerId`` the forest's real blocks/compartments. 409 with
   *  code ``blocks.promoted_layer_exists`` when another layer already holds
   *  that role and ``force`` was not set — call again with `force: true`
   *  to switch (D51 "offers to switch"). */
  promoteRasterLayer: async (
    calculationId: string,
    layerId: string,
    asLevel: 'blocks' | 'compartments',
    force?: boolean,
  ): Promise<{ ok: boolean; layer: RasterLayerInfo }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/auto-block-layers/${layerId}/promote`,
      { as_level: asLevel, force: force ?? false }
    );
    return response.data;
  },

  /** RS-2.17 sub-unit assignment: candidate parents for "Assign to existing
   *  block/compartment…" — every undivided top-level unit. */
  listEligibleParentsForLayer: async (
    calculationId: string,
    layerId: string,
  ): Promise<{ parents: { id: string; name: string; is_compartment: boolean; area_hectares: number }[] }> => {
    const response = await api.get(
      `/api/v1/calculations/${calculationId}/auto-block-layers/${layerId}/eligible-parents`
    );
    return response.data;
  },

  /** RS-2.17: promote a layer's pieces as the CHILDREN of one existing
   *  parent (sub-blocks/sub-compartments follow from which parent is
   *  picked). Does not change the layer's own `promoted_as`. */
  assignRasterLayerToParent: async (
    calculationId: string,
    layerId: string,
    parentId: string,
  ): Promise<{ ok: boolean; parent_id: string; layer_type: string; child_ids: string[]; n_children: number }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/auto-block-layers/${layerId}/assign-children`,
      { parent_id: parentId }
    );
    return response.data;
  },

  /** Owner report 2026-10-01: "I can not remove auto created layer. Make it
   *  deletable." Refuses 409 if the layer is currently promoted — demote it
   *  first. Cascades to the layer's own pieces server-side. */
  deleteRasterLayer: async (
    calculationId: string,
    layerId: string,
  ): Promise<{ ok: boolean; id: string }> => {
    const response = await api.delete(
      `/api/v1/calculations/${calculationId}/auto-block-layers/${layerId}`
    );
    return response.data;
  },

  /** Return a promoted layer to being a non-counting overlay. */
  demoteRasterLayer: async (
    calculationId: string,
    layerId: string,
  ): Promise<{ ok: boolean; layer: RasterLayerInfo }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/auto-block-layers/${layerId}/demote`,
      {}
    );
    return response.data;
  },

  /** Divide-equal-areas (compartment rewire, P1): dry-run labels without persist. */
  dividePreview: async (
    calculationId: string,
    req: DivideRequest,
  ): Promise<DividePreviewResponse> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/geometry/divide-preview`,
      req
    );
    return response.data;
  },

  /** Divide-equal-areas (compartment rewire, P1): persist child-persist pieces. */
  divideEqualAreas: async (
    calculationId: string,
    req: DivideRequest,
  ): Promise<DivideResponse> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/geometry/divide-equal-areas`,
      req
    );
    return response.data;
  },

  convertImportedToBuiltin: async (calculationId: string, layerId: number, targetType: string, opts?: { confirm?: boolean }): Promise<any> => {
    const response = await api.post(
      `/api/v1/workspace/${calculationId}/import-layers/${layerId}/convert-to-builtin`,
      { target_type: targetType, ...(opts?.confirm ? { confirm: true } : {}) }
    );
    return response.data;
  },

  updateImportLayer: async (calculationId: string, layerId: number, data: { purpose?: string; name?: string }): Promise<any> => {
    const response = await api.patch(
      `/api/v1/workspace/${calculationId}/import-layers/${layerId}`,
      data
    );
    return response.data;
  },

  /** An imported / digitize layer's current authoritative feature list (the
   *  server's order — the index a per-feature PATCH / DELETE addresses). */
  getImportedLayerFeatures: async (
    calculationId: string,
    layerId: number,
  ): Promise<{ features: GeoJSON.Feature[] }> => {
    const response = await api.get(
      `/api/v1/workspace/${calculationId}/import-layers/${layerId}/features`
    );
    return response.data as { features: GeoJSON.Feature[] };
  },

  /**
   * Upload a file as a NEW imported workspace layer (the same route the Add Layer
   * dialog uses). Every feature of the file stays its own feature with its own
   * attributes — unlike finalizing a digitized layer, which merges a purposed
   * layer's geometries into one.
   */
  importWorkspaceLayer: async (
    calculationId: string,
    file: File,
    opts: { purpose?: string; customName?: string } = {},
  ): Promise<{
    id: number;
    name: string;
    feature_count: number;
    geometry_types: string[];
  }> => {
    const formData = new FormData();
    formData.append('file', file);
    // FormData coerces values to strings: never append an undefined purpose.
    if (opts.purpose) formData.append('purpose', opts.purpose);
    if (opts.customName) formData.append('custom_name', opts.customName);
    const response = await api.post(
      `/api/v1/workspace/${calculationId}/import-layer`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data as { id: number; name: string; feature_count: number; geometry_types: string[] };
  },

  /** Patch one imported-layer feature's properties. Shared by the attribute-table
   *  inline editor and the undo/redo path so the edit is reversible. */
  updateImportedFeature: async (
    calculationId: string,
    layerId: number,
    featureIndex: number,
    properties: Record<string, unknown>,
  ): Promise<{ properties: Record<string, unknown> }> => {
    const response = await api.patch(
      `/api/v1/workspace/${calculationId}/import-layers/${layerId}/features/${featureIndex}`,
      { properties }
    );
    return response.data as { properties: Record<string, unknown> };
  },

  updateBlock: async (
    calculationId: string,
    blockId: string,
    name: string
  ): Promise<any> => {
    const response = await api.patch(
      `/api/forests/calculations/${calculationId}/blocks/${blockId}`,
      null,
      { params: { name } }
    );
    return response.data;
  },

  /** Save a polygon's management orientation (Production / Conservation / Protection) - the user's own stratum choice. */
  setUnitOrientation: async (
    calculationId: string,
    blockId: string,
    orientation: 'Production' | 'Conservation' | 'Protection',
  ): Promise<any> => {
    const response = await api.patch(`/api/forests/calculations/${calculationId}/blocks/${blockId}`, {
      management_orientation: orientation,
    });
    return response.data;
  },

  deleteBlock: async (
    calculationId: string,
    blockId: string
  ): Promise<void> => {
    await api.delete(
      `/api/forests/calculations/${calculationId}/blocks/${blockId}`
    );
  },

  /** Block-boundary invariant (E.7): persist a user-drawn block/compartment,
   *  clipped to the forest boundary. Any boundary area the draw leaves uncovered
   *  is silently auto-filled as a Remainder Block/Compartment. Rejects
   *  OUTSIDE_BOUNDARY (400) / material overlap TOPOLOGY_REJECTED (409). */
  drawBlock: async (
    calculationId: string,
    data: {
      level: 'blocks' | 'compartments';
      name?: string;
      geometry: GeoJSON.Geometry;
    },
  ): Promise<{
    success: boolean;
    level: string;
    block: {
      id: string;
      name: string;
      block_name: string;
      natural_name: string | null;
      area_hectares: number;
      index: number;
    };
    clipped: boolean;
    removed_ha: number;
    warnings: string[];
    invariant: {
      remainder_added: boolean;
      gap_ha: number;
      union_ha: number;
      boundary_ha: number;
      warnings: string[];
    };
  }> => {
    const response = await api.post(
      `/api/v1/calculations/${calculationId}/blocks/draw`,
      data,
    );
    return response.data;
  },
};

// Boundary overlap+gap (PF-1) — standalone alias for the preview workflow
export const boundaryApi = {
  previewBoundaryOverlap: forestApi.previewBoundaryOverlap,
  confirmBoundary: forestApi.confirmBoundary,
  includeGapInBoundary: forestApi.includeGapInBoundary,
  fetchNearbyRelations: forestApi.fetchNearbyRelations,
}

// Tree Model endpoints
export const treeModelApi = {
  generate: async (calculationId: string, config?: {
    min_dbh_cm?: number;
    min_height_m?: number;
    max_trees_per_ha?: number;
    spatial_distribution?: string;
    plot_buffer_meters?: number;
    algorithm_version?: string;
  }) => {
    const response = await api.post(`/api/calculations/${calculationId}/generate-tree-model`, {
      config: config || null
    });
    return response.data;
  },

  getModel: async (modelId: string) => {
    const response = await api.get(`/api/tree-models/${modelId}`);
    return response.data;
  },

  listModels: async (calculationId: string) => {
    const response = await api.get(`/api/calculations/${calculationId}/tree-models`);
    return response.data;
  },

  download: async (modelId: string) => {
    const response = await api.get(`/api/tree-models/${modelId}/download`, {
      responseType: 'blob'
    });
    return response.data;
  },

  delete: async (modelId: string) => {
    const response = await api.delete(`/api/tree-models/${modelId}`);
    return response.data;
  },
};

export const allTreeExportApi = {
  generate: async (calculationId: string, config?: {
    min_dbh_cm?: number;
    max_dbh_cm?: number;
    min_height_m?: number;
    max_trees_per_ha?: number;
    algorithm_version?: string;
    species_role_target_ratio?: Record<string, number> | null;
  }, unitIds?: string[]) => {
    const response = await api.post(`/api/calculations/${calculationId}/generate-all-trees`, {
      config: config || null,
      // Omitted/empty = the whole forest boundary
      unit_ids: unitIds && unitIds.length > 0 ? unitIds : null,
    });
    return response.data;
  },

  getExport: async (exportId: string) => {
    const response = await api.get(`/api/all-tree-exports/${exportId}`);
    return response.data;
  },

  listExports: async (calculationId: string) => {
    const response = await api.get(`/api/calculations/${calculationId}/all-tree-exports`);
    return response.data;
  },

  downloadGpkg: async (exportId: string) => {
    const response = await api.get(`/api/all-tree-exports/${exportId}/download`, {
      responseType: 'blob'
    });
    return response.data;
  },

  downloadExcel: async (exportId: string) => {
    const response = await api.get(`/api/all-tree-exports/${exportId}/download-excel`, {
      responseType: 'blob'
    });
    return response.data;
  },

  downloadCsv: async (exportId: string) => {
    const response = await api.get(`/api/all-tree-exports/${exportId}/download-csv`, {
      responseType: 'blob'
    });
    return response.data;
  },

  delete: async (exportId: string) => {
    const response = await api.delete(`/api/all-tree-exports/${exportId}`);
    return response.data;
  },
};

export const exportCleanupApi = {
  cleanup: async (retentionDays: number = 7) => {
    const response = await api.post(`/api/exports/cleanup?retention_days=${retentionDays}`);
    return response.data;
  },
};

export default api;


// Inventory endpoints
export const inventoryApi = {
  listSpecies: async (): Promise<any[]> => {
    const response = await api.get("/api/inventory/species");
    return response.data;
  },

  downloadTemplate: async (): Promise<Blob> => {
    const response = await api.get("/api/inventory/template", {
      responseType: "blob",
    });
    return response.data;
  },

  uploadInventory: async (
    file: File,
    gridSpacing: number = 20.0,
    projectionEpsg?: number,
    calculationId?: string
  ): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("grid_spacing_meters", gridSpacing.toString());
    if (projectionEpsg) {
      formData.append("projection_epsg", projectionEpsg.toString());
    }
    if (calculationId) {
      formData.append("calculation_id", calculationId);
    }

    const response = await api.post("/api/inventory/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  // Preview column mapping for uploaded CSV
  previewColumnMapping: async (file: File): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await api.post("/api/inventory/preview-mapping", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  // Confirm column mapping and save preferences
  confirmColumnMapping: async (
    file: File,
    mapping: Record<string, string>,
    savePreference: boolean,
    gridSpacing: number,
    calculationId?: string,
    projectionEpsg?: number,
    correctionStrategy?: string
  ): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mapping", JSON.stringify(mapping));
    formData.append("save_preference", savePreference.toString());
    formData.append("grid_spacing_meters", gridSpacing.toString());
    if (calculationId) {
      formData.append("calculation_id", calculationId);
    }
    if (projectionEpsg) {
      formData.append("projection_epsg", projectionEpsg.toString());
    }
    if (correctionStrategy) {
      formData.append("correction_strategy", correctionStrategy);
    }

    const response = await api.post("/api/inventory/confirm-mapping", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  processInventory: async (id: string, file: File): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await api.post(`/api/inventory/${id}/process`, formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  listMyInventories: async (): Promise<any> => {
    const response = await api.get("/api/inventory/my-inventories");
    return response.data;
  },

  getInventoryStatus: async (id: string): Promise<any> => {
    const response = await api.get(`/api/inventory/${id}/status`);
    return response.data;
  },

  getInventorySummary: async (id: string): Promise<any> => {
    const response = await api.get(`/api/inventory/${id}/summary`);
    return response.data;
  },

  // Get tree mapping data for a calculation
  getTreeMappingByCalculation: async (calculationId: string): Promise<any> => {
    // The route is `/by-calculation/{id}` (api/inventory.py:1414). This used to
    // call `/api/inventory/tree-mapping/{id}`, which does not exist, so the call
    // always 404'd and the Data pane's fetch-by-calculation path was dead.
    const response = await api.get(`/api/inventory/by-calculation/${calculationId}`);
    return response.data;
  },

  // Check if ANY tree mapping exists (regardless of owner)
  checkTreeMappingExists: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/inventory/by-calculation/${calculationId}/check`);
    return response.data;
  },

  listInventoryTrees: async (
    id: string,
    params?: {
      page?: number;
      page_size?: number;
      remark?: string;
    }
  ): Promise<any> => {
    const response = await api.get(`/api/inventory/${id}/trees`, { params });
    return response.data;
  },

exportInventory: async (id: string, format: "csv" | "geojson" | "excel"): Promise<{blob: Blob, filename: string}> => {
    const response = await api.get(`/api/inventory/${id}/export`, {
      params: { format },
      responseType: "blob",
    });
    return {
      blob: response.data,
      filename: `inventory_${id}.${format}`
    };
  },

  deleteInventory: async (id: string): Promise<void> => {
    await api.delete(`/api/inventory/${id}`);
  },

  // Force delete tree mapping by calculation (ignores user ownership)
  forceDeleteByCalculation: async (calculationId: string): Promise<any> => {
    const response = await api.delete(`/api/inventory/by-calculation/${calculationId}/force`);
    return response.data;
  },

  // Get correction preview for boundary correction
  getCorrectionPreview: async (inventoryId: string): Promise<any> => {
    const response = await api.get(`/api/inventory/${inventoryId}/correction-preview`);
    return response.data;
  },

  // Accept boundary corrections
  acceptCorrections: async (inventoryId: string, file: File): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await api.post(`/api/inventory/${inventoryId}/accept-corrections`, formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  // Update block/sub-area via spatial intersection
  updateTreeBlockSubarea: async (inventoryId: string): Promise<any> => {
    const response = await api.post(`/api/inventory/${inventoryId}/update-block-subarea`);
    return response.data;
  },

  // Get grid cells for a specific inventory calculation
  getGridCells: async (inventoryId: string): Promise<any> => {
    const response = await api.get(`/api/inventory/${inventoryId}/grid-cells`);
    return response.data;
  },

  // Export grid cells as GeoJSON or KML
  exportGrid: async (inventoryId: string, format: 'geojson' | 'kml'): Promise<Blob> => {
    const response = await api.get(`/api/inventory/${inventoryId}/export-grid`, {
      params: { format },
      responseType: 'blob',
    });
    return response.data;
  },

  // Get tree mapping analysis data
  getInventoryAnalysis: async (inventoryId: string) => {
    const response = await api.get(`/api/inventory/${inventoryId}/analysis`);
    return response.data;
  },
};

// Field Inventory endpoints
export const fieldInventoryApi = {
  previewMapping: async (file: File): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await api.post("/api/field-inventory/preview-mapping", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  upload: async (
    file: File,
    calculationId: string,
    mapping: Record<string, string>,
    sampleSizes: {
      regeneration_area_sqm: number;
      sapling_area_sqm: number;
      pole_area_sqm: number;
      tree_area_sqm: number;
    },
    crsEpsg?: number | null,
    corrections?: { row: number; column: string; value: number }[] | null,
  ): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("calculation_id", calculationId);
    if (corrections?.length) formData.append("corrections", JSON.stringify(corrections));  // the proposed replacements the user accepted
    if (crsEpsg) formData.append("crs_epsg", String(crsEpsg));  // the coordinate system chosen in Add data
    formData.append("mapping", JSON.stringify(mapping));
    formData.append("regeneration_area_sqm", sampleSizes.regeneration_area_sqm.toString());
    formData.append("sapling_area_sqm", sampleSizes.sapling_area_sqm.toString());
    formData.append("pole_area_sqm", sampleSizes.pole_area_sqm.toString());
    formData.append("tree_area_sqm", sampleSizes.tree_area_sqm.toString());

    const response = await api.post("/api/field-inventory/upload", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  process: async (fieldInventoryId: string, file: File, crsEpsg?: number | null, corrections?: { row: number; column: string; value: number }[] | null): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);
    if (corrections?.length) formData.append("corrections", JSON.stringify(corrections));  // the same accepted corrections as at upload
    if (crsEpsg) formData.append("crs_epsg", String(crsEpsg));  // the same choice as at upload, or the two reads would disagree

    const response = await api.post(`/api/field-inventory/${fieldInventoryId}/process`, formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  getStatus: async (fieldInventoryId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/status`);
    return response.data;
  },

  getSummary: async (fieldInventoryId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/summary`);
    return response.data;
  },

  listBlocks: async (fieldInventoryId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/blocks`);
    return response.data;
  },

  getSpeciesBreakdown: async (fieldInventoryId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/species-breakdown`);
    return response.data;
  },

  getMaiAah: async (
    fieldInventoryId: string,
    aahGood: number = 75,
    aahModerate: number = 60,
    aahWeak: number = 40,
    customMultipliers?: Record<string, number>
  ): Promise<any> => {
    const params: any = {
      aah_good: aahGood,
      aah_moderate: aahModerate,
      aah_weak: aahWeak
    };

    if (customMultipliers && Object.keys(customMultipliers).length > 0) {
      params.custom_multipliers = JSON.stringify(customMultipliers);
    }

    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/mai-aah`, { params });
    return response.data;
  },

  getByCalculation: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/by-calculation/${calculationId}`);
    return response.data;
  },

  delete: async (fieldInventoryId: string): Promise<void> => {
    await api.delete(`/api/field-inventory/${fieldInventoryId}`);
  },

  getTotalInventory: async (
    fieldInventoryId: string,
    blockAreas: Record<string, number>,
    customMultipliers?: Record<string, number>,
    aahGood: number = 75,
    aahModerate: number = 60,
    aahWeak: number = 40
  ): Promise<any> => {
    const params: any = {
      block_areas: JSON.stringify(blockAreas),
      aah_good: aahGood,
      aah_moderate: aahModerate,
      aah_weak: aahWeak
    };

    if (customMultipliers && Object.keys(customMultipliers).length > 0) {
      params.custom_multipliers = JSON.stringify(customMultipliers);
    }

    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/total-inventory`, { params });
    return response.data;
  },

  getRegulationSpecies: async (fieldInventoryId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/regulation-species`);
    return response.data;
  },

  getSpeciesDbhBreakdown: async (fieldInventoryId: string): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/species-dbh-breakdown`);
    return response.data;
  },

  exportExcel: async (
    fieldInventoryId: string,
    aahGood: number = 75,
    aahModerate: number = 60,
    aahWeak: number = 40,
    customMultipliers?: Record<string, number>
  ): Promise<Blob> => {
    const params: any = {
      aah_good: aahGood,
      aah_moderate: aahModerate,
      aah_weak: aahWeak
    };

    if (customMultipliers && Object.keys(customMultipliers).length > 0) {
      params.custom_multipliers = JSON.stringify(customMultipliers);
    }

    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/export-excel`, {
      params,
      responseType: 'blob'
    });
    return response.data;
  },

  exportDfoSummary: async (
    fieldInventoryId: string,
    calculationId: string,
    aahGood: number = 75,
    aahModerate: number = 60,
    aahWeak: number = 40,
  ): Promise<Blob> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/export-dfo-summary`, {
      params: {
        calculation_id: calculationId,
        aah_good: aahGood,
        aah_moderate: aahModerate,
        aah_weak: aahWeak,
      },
      responseType: 'blob'
    });
    return response.data;
  },

  getManagementPlanData: async (
    fieldInventoryId: string,
    calculationId: string,
    aahGood?: number,
    aahModerate?: number,
    aahWeak?: number,
  ): Promise<any> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/management-plan-data`, {
      params: {
        calculation_id: calculationId,
        aah_good: aahGood,
        aah_moderate: aahModerate,
        aah_weak: aahWeak,
      },
    });
    return response.data;
  },

  exportManagementPlanDocx: async (
    fieldInventoryId: string,
    calculationId: string,
    aahGood?: number,
    aahModerate?: number,
    aahWeak?: number,
  ): Promise<Blob> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/export-management-plan-docx`, {
      params: {
        calculation_id: calculationId,
        aah_good: aahGood,
        aah_moderate: aahModerate,
        aah_weak: aahWeak,
      },
      responseType: 'blob'
    });
    return response.data;
  },

  export10yrPlanDocx: async (
    fieldInventoryId: string,
    calculationId: string,
    aahGood?: number,
    aahModerate?: number,
    aahWeak?: number,
    includeMaps?: boolean,
    includeCharts?: boolean,
  ): Promise<Blob> => {
    const response = await api.get(`/api/field-inventory/${fieldInventoryId}/export-10yr-plan-docx`, {
      params: {
        calculation_id: calculationId,
        aah_good: aahGood,
        aah_moderate: aahModerate,
        aah_weak: aahWeak,
        include_maps: includeMaps,
        include_charts: includeCharts,
      },
      responseType: 'blob'
    });
    return response.data;
  },
};

// Fieldbook endpoints
export const fieldbookApi = {
  generate: async (
    calculationId: string,
    params: {
      interpolation_distance_meters: number;
      extract_elevation: boolean;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/fieldbook/generate`,
      params
    );
    return response.data;
  },

  list: async (calculationId: string, includeTopographic: boolean = false): Promise<any> => {
    const response = await api.get(`/api/calculations/${calculationId}/fieldbook`, {
      params: { include_topographic: includeTopographic }
    });
    return response.data;
  },

  // Explicitly request with topographic features
  listWithTopographic: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/calculations/${calculationId}/fieldbook`, {
      params: { include_topographic: true }
    });
    return response.data;
  },

  delete: async (calculationId: string): Promise<void> => {
    await api.delete(`/api/calculations/${calculationId}/fieldbook`);
  },

  export: async (
    calculationId: string,
    format: "csv" | "excel" | "gpx" | "geojson"
  ): Promise<Blob> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/fieldbook`,
      {
        params: { format },
        responseType: "blob",
      }
    );
    return response.data;
  },
};

// Sampling endpoints
export interface SamplingCreateParams {
  // Method selection (NEW - Phase 3: Guideline-2061)
  sampling_method?: "guideline_2061" | "manual"; // Default: guideline_2061

  // Guideline-2061 specific parameters
  productive_intensity?: "0.5" | "1.0"; // For productive blocks (default: 0.5)
  sample_protected_zone?: boolean; // Include protected zone at 0.1% (default: false)
  plot_size_sqm?: number; // 100-500 for production, 25-100 for protected (default: 500)

  // Manual method parameters
  sampling_type?: "systematic" | "random" | "stratified";
  sampling_intensity_percent?: number; // Percentage of block area (0.1-10%, default 0.5%)
  min_samples_per_block?: number; // Minimum samples for blocks >= 1ha (2-10, default 5)
  min_samples_small_blocks?: number; // Minimum samples for blocks < 1ha (1-5, default 2)
  intensity_per_hectare?: number; // DEPRECATED: Use sampling_intensity_percent instead
  grid_spacing_meters?: number; // DEPRECATED: Calculated automatically
  min_distance_meters?: number;

  // Common parameters
  plot_shape?: "circular" | "square" | "rectangular";
  plot_radius_meters?: number; // For manual method
  plot_length_meters?: number; // For manual method
  plot_width_meters?: number; // For manual method
  notes?: string;

  // Accessible forest filtering (common to both methods)
  filter_tree_cover?: boolean; // Filter to tree cover only (default: true)
  filter_slope?: boolean; // Filter by slope (default: false)
  max_slope_degrees?: number; // Max slope threshold (default: 45.0)
  boundary_buffer_meters?: number; // Minimum distance from boundary (default: 50)
}

export interface SamplingPointsGeoJSON {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: any;
  }>;
}

export interface SamplingPreviewInfo {
  preview_token: string;
  total_points: number;
  total_blocks: number;
  forest_area_hectares: number;
  requested_intensity_percent: number;
  actual_intensity_per_hectare: number;
  plot_area_sqm: number | null;
  total_sampled_area_hectares: number | null;
  sampling_percentage: number | null;
  blocks_info: any[];
  sampling_points_geojson: SamplingPointsGeoJSON;
  area_basis: string;
}

export interface SamplingPreviewResponse {
  preview_token: string;
  total_points: number;
  total_units: number;
  requested_intensity_percent: number;
  sampling_percentage: number | null;
  area_basis: string;
  blocks_info: any[];
  sampling_points_geojson: SamplingPointsGeoJSON;
  boundary_layer: any;
  forest_blocks_layer: any;
  filter_settings: any;
  calculation_id: string;
  sampling_type: string;
  total_blocks: number;
  forest_area_hectares: number;
  actual_intensity_per_hectare: number;
  plot_area_sqm: number | null;
  total_sampled_area_hectares: number | null;
}

export interface SamplingUnitRow {
  unit_id: string;
  /** the key sampling files plots under (code, else block name, else name) - use `display_name` on screen */
  name: string;
  /** the unit's Name as the workspace attribute table shows it */
  display_name?: string;
  area_ha: number;
  slope_band: number | null;
  stratum: 'production' | 'conservation' | 'protection';
  /** why this stratum: the user's own choice, SFM, the slope, a protected area / working circle, or the default */
  stratum_source: 'user' | 'sfm' | 'slope' | 'protected_area' | 'working_circle' | 'default';
  management_orientation: string | null;
  floor_pct: number;
  plot_size_sqm: number;
  sampled_plots: number;
  /** from the unit's stored analysis; null / empty until it has been analysed */
  landcover_dominant?: string | null;
  landcover_dominant_pct?: number | null;
  landcover_breakdown?: { name: string; pct: number }[];
  forest_pct?: number | null;
}

/** What one polygon's intensity amounts to, and the number of plots we suggest (never fewer than 5). */
export interface SamplingSuggestion {
  area_ha: number;
  plot_size_sqm: number;
  intensity_pct: number;
  /** the plots the intensity amounts to */
  computed: number;
  /** what we suggest: at least 5 (0 when the polygon is excluded at 0 %) */
  suggested: number;
  raised_to_minimum: boolean;
  equivalent_pct: number;
  /** the legal range of plots for this polygon: the stratum's minimum intensity .. the 5 % ceiling */
  min_plots_legal: number;
  max_plots_legal: number;
}

export interface SamplingSuggestions {
  minimum_suggested: number;
  units: Record<string, SamplingSuggestion>;
}

export interface SamplingUnitPlan {
  state: 'ready' | 'no_units';
  design_id: string | null;
  units: SamplingUnitRow[];
  field_data_exists: boolean;
}

export interface UserGroupAnalysisStatus {
  state: 'idle' | 'running' | 'done' | 'failed' | 'skipped';
  started_at?: string;
  finished_at?: string | null;
  message?: string | null;
  steps: { settlements?: 'done' | 'failed'; land_cover?: 'done' | 'failed' };
}

export const samplingApi = {
  /** Sample plots prepared elsewhere (the Sample_Plots template, Excel / CSV) become the forest's sampling design. */
  importPlots: async (calculationId: string, file: File, crsEpsg?: number | null, renumber?: boolean): Promise<any> => {
    const form = new FormData();
    form.append('file', file);
    if (crsEpsg) form.append('crs_epsg', String(crsEpsg));
    if (renumber) form.append('renumber', 'true');
    const response = await api.post(`/api/calculations/${calculationId}/sampling/import-plots`, form);
    return response.data;
  },

  create: async (
    calculationId: string,
    params: SamplingCreateParams
  ): Promise<any> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/sampling/create`,
      params
    );
    return response.data;
  },

  preview: async (
    calculationId: string,
    params: SamplingCreateParams
  ): Promise<SamplingPreviewResponse> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/sampling/preview`,
      params
    );
    return response.data;
  },

  /** One row per polygon for the sampling screen, for ANY forest: stratum with the reason, the legal minimum, slope band and how many
   *  plots the forest's design already holds there. `field_data_exists` = plots can no longer be added or deleted. */
  unitPlan: async (calculationId: string): Promise<SamplingUnitPlan> => {
    const response = await api.get(`/api/calculations/${calculationId}/sampling/unit-plan`);
    return response.data;
  },

  /** How many plots each polygon's intensity amounts to, and the number we suggest (never fewer than 5). */
  suggestedCounts: async (calculationId: string, intensities: Record<string, number>, method: 'guideline' | 'manual'): Promise<SamplingSuggestions> => {
    const response = await api.post(`/api/calculations/${calculationId}/sampling/suggested-counts`, { intensities, method });
    return response.data;
  },

  /** Preview a LATER ROUND for the forest's one design: only the ticked polygons that have no plots yet. */
  previewAdd: async (calculationId: string, designId: string, params: SamplingCreateParams): Promise<SamplingPreviewResponse> => {
    const response = await api.post(`/api/calculations/${calculationId}/sampling/preview`, params, { params: { add_to_design: designId } });
    return response.data;
  },

  /** Append the previewed round (`params.preview`) to the design. Existing plots do not move. */
  addUnits: async (calculationId: string, designId: string, params: SamplingCreateParams): Promise<{ design_id: string; added: number; total_points: number; units: string[] }> => {
    const response = await api.post(`/api/calculations/${calculationId}/sampling/${designId}/add-units`, params);
    return response.data;
  },

  /** Delete every plot of one polygon so it can be sampled again (refused once field inventory data exists). */
  deleteUnitPlots: async (designId: string, unitName: string): Promise<{ removed: number; remaining_points: number }> => {
    const response = await api.delete(`/api/sampling/${designId}/units/${encodeURIComponent(unitName)}/points`);
    return response.data;
  },

  /** Add ONE sample plot at (longitude, latitude) to the end of a design's
   *  point set. Backend refuses (409) once field inventory data exists for
   *  the forest, or (400) if the point is outside the forest boundary --
   *  block/compartment/sub-area assignment is recomputed automatically. */
  addSamplePlot: async (
    designId: string,
    longitude: number,
    latitude: number,
  ): Promise<{ success: boolean; plot_number: number; total_points: number; block_name: string | null }> => {
    const response = await api.post(`/api/sampling/${designId}/points`, { longitude, latitude });
    return response.data;
  },

  /** Move ONE existing sample plot (1-based `plotNumber`) to a new
   *  (longitude, latitude). Same refusal rules as `addSamplePlot`; the
   *  plot's block/compartment/sub-area assignment is recomputed from the
   *  new location automatically. */
  moveSamplePlot: async (
    designId: string,
    plotNumber: number,
    longitude: number,
    latitude: number,
  ): Promise<{ success: boolean; plot_number: number; block_name: string | null }> => {
    const response = await api.patch(`/api/sampling/${designId}/points/${plotNumber}`, { longitude, latitude });
    return response.data;
  },

  /** Type ONE coordinate of a sample plot: a latitude, a longitude, a UTM easting or a UTM northing (the value not typed is taken from the
   *  plot as it is; the UTM zone is the plot's own). The server refuses, with a friendly message, a value that is not a number, out of range,
   *  or outside the forest boundary - and once field inventory data exists. */
  setSamplePlotCoordinate: async (
    designId: string,
    plotNumber: number,
    coordinate: { latitude?: number; longitude?: number; utm_easting?: number; utm_northing?: number },
  ): Promise<{ success: boolean; plot_number: number; block_name: string | null; longitude: number; latitude: number; utm_zone: number; utm_easting: number; utm_northing: number }> => {
    const response = await api.patch(`/api/sampling/${designId}/points/${plotNumber}`, coordinate);
    return response.data;
  },

  /** Delete ONE sample plot (1-based `plotNumber`) from a design's point
   *  set. Backend refuses (409) once the forest has any field inventory
   *  data uploaded -- `handleDeleteSamplePlot` (MapWorkspace.tsx) checks
   *  that itself first so the user gets a clear reason before confirming,
   *  but the backend is the real gate regardless of what the UI showed. */
  deleteSamplePlot: async (designId: string, plotNumber: number): Promise<void> => {
    await api.delete(`/api/sampling/${designId}/points/${plotNumber}`);
  },

  /** Live blocks/compartments/sub-compartments GeoJSON for a calculation --
   *  same shape as a Preview response's `forest_blocks_layer` / a design's
   *  `/map-layers.forest_blocks`, but always current. Owner report
   *  2026-10-02: a captured Preview's block geometry goes stale the moment
   *  the user edits blocks elsewhere (promote/split/merge) -- the Preview
   *  response itself is a one-shot snapshot, never live. SamplingMapView
   *  calls this to refresh just that layer instead of trusting the snapshot. */
  getCurrentBlocksLayer: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/calculations/${calculationId}/sampling/blocks-layer`);
    return response.data;
  },

  getProtectedZones: async (calculationId: string): Promise<{
    has_protected: boolean;
    protected_area_hectares: number;
    protected_zone_names: string[];
    protected_zone_count: number;
    productive_area_hectares: number;
    total_area_hectares: number;
  }> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/protected-zones`
    );
    return response.data;
  },

  list: async (calculationId: string): Promise<any[]> => {
    const response = await api.get(`/api/calculations/${calculationId}/sampling`);
    return response.data;
  },

  getDesign: async (designId: string): Promise<any> => {
    const response = await api.get(`/api/sampling/${designId}`);
    return response.data;
  },

  getPoints: async (
    designId: string,
    options?: {
      format?: "json" | "geojson";
      include_elevation?: boolean;
      include_topographic_features?: boolean;
    }
  ): Promise<any> => {
    const params: any = {};
    if (options?.format) params.format = options.format;
    if (options?.include_elevation !== undefined) params.include_elevation = options.include_elevation;
    if (options?.include_topographic_features !== undefined) params.include_topographic_features = options.include_topographic_features;

    const response = await api.get(`/api/sampling/${designId}/points`, {
      params: Object.keys(params).length > 0 ? params : undefined,
    });
    return response.data;
  },

  delete: async (designId: string): Promise<void> => {
    await api.delete(`/api/sampling/${designId}`);
  },

  export: async (
    designId: string,
    format: "csv" | "gpx" | "geojson" | "kml"
  ): Promise<Blob> => {
    const response = await api.get(`/api/sampling/${designId}/points`, {
      params: { format },
      responseType: "blob",
    });
    return response.data;
  },

  getMapLayers: async (designId: string): Promise<any> => {
    const response = await api.get(`/api/sampling/${designId}/map-layers`);
    return response.data;
  },

  previewAccessibleForest: async (
    calculationId: string,
    options: {
      filter_tree_cover?: boolean;
      filter_slope?: boolean;
      max_slope_degrees?: number;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/preview-accessible-forest`,
      null,
      {
        params: {
          filter_tree_cover: options.filter_tree_cover ?? true,
          filter_slope: options.filter_slope ?? false,
          max_slope_degrees: options.max_slope_degrees ?? 45.0,
        },
      }
    );
    return response.data;
  },
};

// ============================================================================
// User Group Map API
// ============================================================================

export const userGroupApi = {
  /**
   * Upload user group extent boundary file
   */
  uploadExtent: async (
    calculationId: string,
    file: File
  ): Promise<{ extent_id: number; message: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await api.post(
      `/api/calculations/${calculationId}/user-group/upload`,
      formData
    );
    return response.data;
  },

  /**
   * Create manual extent from digitized polygon
   */
  createManualExtent: async (
    calculationId: string,
    geometry: any
  ): Promise<{ extent_id: number; message: string }> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/user-group/manual`,
      { geometry }
    );
    return response.data;
  },

  /**
   * Import an extent from a file — Forest-Boundary-identical (point / line /
   * polygon; SHP zipped or bare, KML, KMZ, GeoJSON, GeoPackage, GPX, CSV, XLSX).
   */
  /** Where the automatic analysis (settlements, then land cover & biomass) stands; stored with the calculation. */
  getAnalysisStatus: async (calculationId: string): Promise<UserGroupAnalysisStatus> => {
    const response = await api.get(`/api/calculations/${calculationId}/user-group/analysis-status`);
    return response.data;
  },

  importExtent: async (
    calculationId: string,
    file: File,
    opts?: { lat_col?: string; lon_col?: string }
  ): Promise<{ extent_id: number; message: string; findings?: import('../lib/uploadFindings').UploadFinding[] }> => {
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (opts?.lat_col) params.set('lat_col', opts.lat_col);
    if (opts?.lon_col) params.set('lon_col', opts.lon_col);
    const qs = params.toString();
    const response = await api.post(
      `/api/calculations/${calculationId}/user-group/import${qs ? `?${qs}` : ''}`,
      formData
    );
    return response.data;
  },

  /**
   * Thin read of the current extent for the workspace layer (all-null when none).
   */
  getExtent: async (
    calculationId: string
  ): Promise<{
    extent_id: number | null;
    source_type: string | null;
    buffer_distance_m: number | null;
    area_hectares: number | null;
    geometry: GeoJSON.Geometry | null;
  }> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/user-group/extent`
    );
    return response.data;
  },

  /**
   * Create auto-buffer extent
   */
  createAutoBuffer: async (
    calculationId: string,
    bufferDistance: number = 1000
  ): Promise<{ extent_id: number; message: string }> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/user-group/auto-buffer`,
      null,
      { params: { buffer_distance: bufferDistance } }
    );
    return response.data;
  },

  /**
   * Run building and settlement analysis
   */
  analyzeUserGroup: async (
    calculationId: string,
    extentId: number
  ): Promise<{ message: string; settlements_analyzed: number; total_buildings: number }> => {
    const response = await api.post(
      `/api/calculations/${calculationId}/user-group/analyze`,
      null,
      { params: { extent_id: extentId } }
    );
    return response.data;
  },

  /**
   * Get analysis results for visualization
   */
  getResults: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/user-group/results`
    );
    return response.data;
  },

  /**
   * Get POI layers (points of interest, education, health, rivers)
   */
  getPOILayers: async (
    calculationId: string,
    layerType: 'all' | 'poi' | 'education' | 'health' | 'rivers' = 'all'
  ): Promise<any> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/user-group/poi`,
      { params: { layer_type: layerType } }
    );
    return response.data;
  },

  /**
   * Delete user group extent and all related data
   */
  deleteExtent: async (calculationId: string): Promise<void> => {
    await api.delete(`/api/calculations/${calculationId}/user-group`);
  },

  /**
   * Export user group map (PDF, GPKG, GeoJSON, CSV)
   */
  exportMap: async (
    extentId: number,
    format: 'pdf' | 'gpkg' | 'geojson' | 'csv'
  ): Promise<Blob> => {
    const response = await api.get(`/api/user-group/${extentId}/export`, {
      params: { format },
      responseType: 'blob',
    });
    return response.data;
  },

  /**
   * Query land cover and biomass at a specific point
   */
  queryPoint: async (
    calculationId: string,
    lat: number,
    lon: number
  ): Promise<{
    location: { lat: number; lon: number };
    land_cover: { class_code: number; class_name: string } | null;
    biomass: { value_mg_ha: number; volume_m3_ha: number } | null;
  }> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/user-group/query`,
      {
        params: { lat, lon },
      }
    );
    return response.data;
  },

  /**
   * Analyze land cover and biomass for user group extent
   *
   * Performs comprehensive spatial analysis including:
   * - Land use classification (ESA World Cover)
   * - Biomass estimation (AGB 2022 Nepal)
   * - Community forest overlap exclusion
   * - Timber volume calculation
   *
   * Prerequisites:
   * 1. Community forest boundary must be uploaded (Analysis tab)
   * 2. User group extent must be created (Forest User Map tab)
   */
  analyzeLandCover: async (calculationId: string, forceRefresh: boolean = false): Promise<{
    user_group_area_ha: number;
    forest_overlap_area_ha: number;
    net_analysis_area_ha: number;
    land_cover_classes: Array<{
      class_code: number;
      class_name: string;
      area_ha: number;
      percentage: number;
      avg_biomass_mg_per_ha: number;
      min_biomass_mg_per_ha: number;
      max_biomass_mg_per_ha: number;
      total_biomass_mg: number;
      avg_volume_m3_per_ha: number;
      total_volume_m3: number;
      pixel_count: number;
    }>;
    total_biomass_mg: number;
    total_volume_m3: number;
    avg_biomass_mg_per_ha: number;
    avg_volume_m3_per_ha: number;
    analysis_date: string;
    has_forest_overlap: boolean;
    from_cache?: boolean;
  }> => {
    const response = await api.get(
      `/api/calculations/${calculationId}/user-group/land-cover`,
      {
        params: { force_refresh: forceRefresh }
      }
    );
    return response.data;
  },

  // ============================================================================
  // Household Information API
  // ============================================================================

  /**
   * Download Excel template for household information entry
   */
  downloadHouseholdTemplate: async (
    calculationId: string,
    options: { land_unit: 'ropani' | 'kaththa'; include_coordinates: boolean }
  ): Promise<Blob> => {
    const response = await api.post(
      `/api/household/calculations/${calculationId}/template`,
      options,
      {
        responseType: 'blob',
      }
    );
    return response.data;
  },

  /**
   * Upload filled Excel file with household data
   */
  uploadHouseholdData: async (
    calculationId: string,
    file: File,
    options: { replaceAll?: boolean } = {}
  ): Promise<any> => {
    const formData = new FormData();
    formData.append('file', file);

    // replaceAll (owner decision D5): households that are not in the file are removed; by default the file only updates and adds
    const response = await api.post(
      `/api/household/calculations/${calculationId}/upload`,
      formData,
      options.replaceAll ? { params: { replace_all: true } } : undefined
    );
    return response.data;
  },

  /**
   * Get all household records for a calculation
   */
  getHouseholds: async (
    calculationId: string,
    skip = 0,
    limit = 100
  ): Promise<any[]> => {
    const response = await api.get(
      `/api/household/calculations/${calculationId}/households`,
      {
        params: { skip, limit },
      }
    );
    return response.data;
  },

  /**
   * Get a single household by ID
   */
  getHousehold: async (householdId: string): Promise<any> => {
    const response = await api.get(`/api/household/households/${householdId}`);
    return response.data;
  },

  /**
   * Create a new household record
   */
  createHousehold: async (calculationId: string, data: any): Promise<any> => {
    const response = await api.post(
      `/api/household/calculations/${calculationId}/households`,
      data
    );
    return response.data;
  },

  /**
   * Update a household record
   */
  updateHousehold: async (householdId: string, data: any): Promise<any> => {
    console.log('API: updateHousehold called', householdId, data);
    const response = await api.put(
      `/api/household/households/${householdId}`,
      data
    );
    console.log('API: updateHousehold response', response.data);
    return response.data;
  },

  /**
   * Delete a household record
   */
  deleteHousehold: async (householdId: string): Promise<void> => {
    await api.delete(`/api/household/households/${householdId}`);
  },

  /**
   * Delete all household records for a calculation
   */
  deleteAllHouseholds: async (calculationId: string): Promise<any> => {
    const response = await api.delete(
      `/api/household/calculations/${calculationId}/households`
    );
    return response.data;
  },

  /**
   * Get summary statistics for household data
   */
  /** Summary-only entry (totals, no household rows). `null` when none is saved. */
  getHouseholdSummaryEntry: async (calculationId: string): Promise<any | null> => {
    const response = await api.get(`/api/household/calculations/${calculationId}/summary-entry`);
    return response.data;
  },

  saveHouseholdSummaryEntry: async (calculationId: string, body: any): Promise<any> => {
    const response = await api.put(`/api/household/calculations/${calculationId}/summary-entry`, body);
    return response.data;
  },

  previewHouseholdSummaryDemands: async (calculationId: string, body: any): Promise<any> => {
    const response = await api.post(
      `/api/household/calculations/${calculationId}/summary-entry/preview-demands`,
      body,
    );
    return response.data;
  },

  deleteHouseholdSummaryEntry: async (calculationId: string): Promise<void> => {
    await api.delete(`/api/household/calculations/${calculationId}/summary-entry`);
  },

  getHouseholdSummary: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/household/calculations/${calculationId}/summary`
    );
    return response.data;
  },

  /**
   * Export household analysis to Excel
   */
  exportHouseholdAnalysis: async (calculationId: string): Promise<Blob> => {
    const response = await api.get(
      `/api/household/calculations/${calculationId}/export`,
      {
        responseType: 'blob',
      }
    );
    return response.data;
  },

  /**
   * Get surname suggestions for autocomplete
   */
  getSurnameSuggestions: async (
    query: string,
    limit = 10
  ): Promise<any[]> => {
    const response = await api.get(`/api/household/surnames`, {
      params: { q: query, limit },
    });
    return response.data;
  },

  /**
   * Lookup caste classification by surname
   */
  lookupCasteBySurname: async (surname: string): Promise<any[]> => {
    const response = await api.get(`/api/household/caste-lookup/${surname}`);
    return response.data;
  },

  // ============================================================================
  // Forest Committee API
  // ============================================================================

  /**
   * Get all committee data for a user group
   */
  getAllCommittees: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/forest-committee/user-groups/${calculationId}`);
    return response.data;
  },

  /**
   * Create/replace all committees in bulk
   */
  createCommitteesBulk: async (calculationId: string, data: any): Promise<any> => {
    const response = await api.post(`/api/forest-committee/user-groups/${calculationId}/bulk`, data);
    return response.data;
  },

  /**
   * Create a main committee member
   */
  createMainCommitteeMember: async (calculationId: string, member: any): Promise<any> => {
    const response = await api.post(`/api/forest-committee/user-groups/${calculationId}/main`, member);
    return response.data;
  },

  /**
   * Update a main committee member
   */
  updateMainCommitteeMember: async (memberId: string, updates: any): Promise<any> => {
    const response = await api.put(`/api/forest-committee/main/${memberId}`, updates);
    return response.data;
  },

  /**
   * Delete a main committee member
   */
  deleteMainCommitteeMember: async (memberId: string): Promise<void> => {
    await api.delete(`/api/forest-committee/main/${memberId}`);
  },

  /**
   * Create an advisory committee member
   */
  createAdvisoryMember: async (calculationId: string, member: any): Promise<any> => {
    const response = await api.post(`/api/forest-committee/user-groups/${calculationId}/advisory`, member);
    return response.data;
  },

  /**
   * Update an advisory committee member
   */
  updateAdvisoryMember: async (memberId: string, updates: any): Promise<any> => {
    const response = await api.put(`/api/forest-committee/advisory/${memberId}`, updates);
    return response.data;
  },

  /**
   * Delete an advisory committee member
   */
  deleteAdvisoryMember: async (memberId: string): Promise<void> => {
    await api.delete(`/api/forest-committee/advisory/${memberId}`);
  },

  /**
   * Create a financial committee member
   */
  createFinancialMember: async (calculationId: string, member: any): Promise<any> => {
    const response = await api.post(`/api/forest-committee/user-groups/${calculationId}/financial`, member);
    return response.data;
  },

  /**
   * Update a financial committee member
   */
  updateFinancialMember: async (memberId: string, updates: any): Promise<any> => {
    const response = await api.put(`/api/forest-committee/financial/${memberId}`, updates);
    return response.data;
  },

  /**
   * Delete a financial committee member
   */
  deleteFinancialMember: async (memberId: string): Promise<void> => {
    await api.delete(`/api/forest-committee/financial/${memberId}`);
  },

  /**
   * Delete all committee data for a user group
   */
  deleteAllCommittees: async (calculationId: string): Promise<any> => {
    const response = await api.delete(`/api/forest-committee/user-groups/${calculationId}`);
    return response.data;
  },

  /**
   * Get demand vs supply data for forest products
   */
  getDemandSupply: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/calculations/${calculationId}/demand-supply`);
    return response.data;
  },
};

/**
 * Yearly Activities API - Manage yearly program activities with spatial integration
 */
// ── Yearly plan facade (YEARLY_ACTIVITIES_WORKSPACE_PLAN section 5.1) ───────────────────────────────
export interface YearlyPlanYear {
  year: number;
  quantity: number;
  budget: number;
  planned: boolean;
  has_row: boolean;
}

export type LocationMode = 'not_applicable' | 'places' | 'whole_forest' | 'units' | 'needs_location';

export interface YearlyPlanLine {
  id: string;
  potential_activity_id: number;
  activity: string | null;
  program: string | null;
  unit: string | null;
  requires_map: boolean;
  default_quantity: number;
  default_yearly_budget: number;
  years: YearlyPlanYear[];
  planned_years: number[];
  total_budget: number;
  version: number;
  reviewed_at: string | null;
  placeholder_fields: Array<'quantity' | 'budget'>;
  feature_count: number;
  /** the forest units (blocks / compartments) the line's places fall in — derived by the server, never stored */
  location_units?: string[];
  /** the sub-areas the line's drawn places fall in, derived by the server: those of the activity kind's own category first */
  sub_areas?: Array<{ id: string; name: string; category: string; matches: boolean }>;
  /** what the drawn places measure for the activity's unit (ha / km / count); null when nothing can be measured */
  measured_quantity?: number | null;
  location_mode: LocationMode;
  assign_to_all_blocks: boolean;
  status: string;
  notes: string | null;
}

export interface PlanHealthIssue {
  code: string;
  severity: 'todo' | 'info' | 'warn' | 'check' | 'error';
  params: Record<string, unknown>;
  action: string;
}

export interface PlanHealthItem {
  activity_id: string;
  potential_activity_id: number;
  activity: string | null;
  state: 'needs_location' | 'needs_numbers' | 'needs_review' | 'ready';
  issues: PlanHealthIssue[];
}

export interface YearlyPlanHealth {
  summary: { ready: number; needs_attention: number; total: number; total_budget: number };
  next_step: {
    code: string;
    activity_id: string | null;
    activity?: string | null;
    params: Record<string, unknown>;
    action: string;
  };
  items: PlanHealthItem[];
  plan_issues: PlanHealthIssue[];
}

export interface PlanLineEdit {
  default_quantity?: number;
  default_yearly_budget?: number;
  years?: Array<{ year: number; quantity?: number; budget?: number }>;
  notes?: string | null;
  status?: string;
  expected_version?: number;
  /** Undo: put the line back to "not reviewed" (it was, before the edit being undone). */
  unreview?: boolean;
}

export interface PlanLineResult {
  plan_line: YearlyPlanLine;
  filled_years: number[];
}

/** A unit (block / compartment) an activity can be assigned to, with the sub-areas inside it. */
export interface PlanUnit {
  block_id: string;
  block_name: string;
  sub_areas: Array<{ id: string; name: string; category: string }>;
}

export interface CbaPlanDrift {
  out_of_date: boolean;
  added: string[];
  removed: string[];
  changed: string[];
}

const YP = '/api/yearly-activities/calculations';

/** One sub-area as the plan sees it: exempt (private land) / planned / needs_plan / no_unit (lies in no unit) / no_id. */
export interface SubAreaPlanItem {
  id: string;
  name: string;
  category: string;
  area_ha: number | null;
  state: 'exempt' | 'planned' | 'needs_plan' | 'no_unit' | 'no_id';
  unit_id: string | null;
  line_ids: string[];
  suggestions?: Array<{ id: number; activity: string; program: string | null; unit: string | null; map_kind: string | null }>;
}

export interface SubAreaPlanStatus {
  sub_areas: SubAreaPlanItem[];
  needs_plan: number;
}

export const subAreaPlanApi = {
  status: async (calculationId: string): Promise<SubAreaPlanStatus> =>
    (await api.get(`${YP}/${calculationId}/sub-areas/plan-status`)).data,

  /** Tie one sub-area to the plan: one line per chosen activity. */
  plan: async (calculationId: string, subAreaId: string, potentialActivityIds: number[]) =>
    (await api.post(`${YP}/${calculationId}/sub-areas/${subAreaId}/plan`, { potential_activity_ids: potentialActivityIds })).data,

  /** Plan every sub-area that needs one with the first suggested activity of its category. */
  planSuggested: async (
    calculationId: string,
  ): Promise<{ planned: Array<{ id: string; name: string; activity: string }>; skipped: Array<{ id: string; name: string; reason: string }> }> =>
    (await api.post(`${YP}/${calculationId}/sub-areas/plan-suggested`)).data,
};

export interface YearlyPlanStatus {
  done: boolean;
  done_at: string | null;
  done_by: string | null;
  /** 'plan_changed' when the system reopened a Done plan because an activity was added or edited */
  reopened_reason: string | null;
}

export const yearlyPlanApi = {
  /** Has the owner said the yearly activities are finished? (Reopens by itself when the plan changes.) */
  getStatus: async (calculationId: string): Promise<YearlyPlanStatus> =>
    (await api.get(`${YP}/${calculationId}/yearly-plan/status`)).data,

  /** Mark the yearly activities done, or open them again. */
  setDone: async (calculationId: string, done: boolean): Promise<YearlyPlanStatus> =>
    (await api.put(`${YP}/${calculationId}/yearly-plan/status`, { done })).data,

  /** Every plan line with the per-year matrix, the location mode and the review state. */
  getPlan: async (calculationId: string): Promise<{ lines: YearlyPlanLine[]; total_budget: number }> =>
    (await api.get(`${YP}/${calculationId}/yearly-plan`)).data,

  /** What is missing, as codes (never sentences); the frontend words them from its catalogue. */
  getHealth: async (calculationId: string): Promise<YearlyPlanHealth> =>
    (await api.get(`${YP}/${calculationId}/yearly-plan/health`)).data,

  /** Edit a line's numbers in one all-or-nothing request (409 with both versions when stale). */
  updateLine: async (calculationId: string, lineId: string, edit: PlanLineEdit): Promise<PlanLineResult> =>
    (await api.put(`${YP}/${calculationId}/yearly-plan/${lineId}`, edit)).data,

  /** "These numbers are right": marks the line reviewed without changing it. */
  confirmLine: async (calculationId: string, lineId: string, expectedVersion?: number): Promise<PlanLineResult> =>
    (
      await api.post(`${YP}/${calculationId}/yearly-plan/${lineId}/confirm`, {
        expected_version: expectedVersion ?? null,
      })
    ).data,

  /** Add an activity to the plan without a place (the wizard); a new line is created reviewed. */
  addLine: async (
    calculationId: string,
    body: Record<string, unknown>,
  ): Promise<{ plan_line: YearlyPlanLine; created_plan_line: boolean; unit: string | null }> =>
    (await api.post(`${YP}/${calculationId}/yearly-plan`, body)).data,

  /** Draw a place: the plan line, its year rows and the feature are created in one transaction. */
  createFeature: async (calculationId: string, body: Record<string, unknown>): Promise<Record<string, unknown>> =>
    (await api.post(`${YP}/${calculationId}/activity-features`, body)).data,

  updateFeature: async (
    calculationId: string,
    featureId: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> =>
    (await api.patch(`${YP}/${calculationId}/activity-features/${featureId}`, body)).data,

  deleteFeature: async (calculationId: string, featureId: string, removePlanLine = false): Promise<void> => {
    await api.delete(`${YP}/${calculationId}/activity-features/${featureId}`, {
      params: { remove_plan_line: removePlanLine },
    });
  },

  /** The one exporter both screens use (saved data, same bytes). `kind`: the yearly plan or the places. */
  exportCsv: async (calculationId: string, kind: 'plan' | 'features', lang: 'en' | 'ne'): Promise<Blob> => {
    const path = kind === 'plan' ? 'yearly-plan' : 'activity-features';
    const response = await api.get(`${YP}/${calculationId}/${path}/export`, {
      params: { format: 'csv', lang },
      responseType: 'blob',
    });
    return response.data as Blob;
  },

  /** The forest's leaf blocks / compartments with their sub-areas: where an activity can be assigned (owner only). */
  getUnits: async (calculationId: string): Promise<PlanUnit[]> =>
    (await api.get(`${YP}/${calculationId}/plan-units`)).data,

  /** Has the plan moved on from this cost-benefit scenario? Read-only; never updates anything. */
  getCbaPlanDrift: async (cbaId: string): Promise<CbaPlanDrift> => (await api.get(`/api/cba/${cbaId}/plan-drift`)).data,
};

export const yearlyActivitiesApi = {
  /**
   * List all potential activities from master list
   */
  listPotentialActivities: async (filters?: {
    project_name?: string;
    program?: string;
    is_default?: string;
    is_active?: boolean;
  }): Promise<any[]> => {
    const params = { is_active: true, ...filters };
    const response = await api.get('/api/yearly-activities/potential-activities', { params });
    return response.data;
  },

  /**
   * List proposed activities for a calculation with spatial filtering
   */
  listProposedActivities: async (
    calculationId: string,
    filters?: {
      block_id?: string;
      sub_area_id?: string;
      sub_area_category?: string;
      status?: string;
    }
  ): Promise<any[]> => {
    const params = filters || {};
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/proposed-activities`,
      { params }
    );
    return response.data;
  },

  /**
   * Create a new proposed activity
   */
  createProposedActivity: async (
    calculationId: string,
    data: {
      potential_activity_id: number;
      block_id?: string;
      sub_area_id?: string;
      default_quantity: number;
      default_yearly_budget: number;
      notes?: string;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/yearly-activities/calculations/${calculationId}/proposed-activities`,
      data
    );
    return response.data;
  },

  /**
   * Update a proposed activity (including spatial assignment)
   */
  updateProposedActivity: async (
    proposedActivityId: string,
    data: {
      block_id?: string;
      sub_area_id?: string;
      default_quantity?: number;
      default_yearly_budget?: number;
      notes?: string;
      status?: string;
      /** the whole forest (the plan table and the plan check read this flag) */
      assign_to_all_blocks?: boolean;
    }
  ): Promise<any> => {
    const response = await api.patch(
      `/api/yearly-activities/proposed-activities/${proposedActivityId}`,
      data
    );
    return response.data;
  },

  /**
   * Delete a proposed activity
   */
  deleteProposedActivity: async (proposedActivityId: string): Promise<void> => {
    await api.delete(`/api/yearly-activities/proposed-activities/${proposedActivityId}`);
  },

  /**
   * Get activities with geometry for map visualization
   */
  getActivitiesWithGeometry: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/proposed-activities/spatial`
    );
    return response.data;
  },

  /**
   * Get location summary (activities by block/sub-area)
   */
  getLocationSummary: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/location-summary`
    );
    return response.data;
  },

  /**
   * Get activity summary statistics
   */
  getSummary: async (calculationId: string): Promise<any> => {
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/summary`
    );
    return response.data;
  },

  // ===== NEW: SPATIAL ASSIGNMENT APIs =====

  /**
   * Get spatial assignments for a proposed activity
   */
  getSpatialAssignments: async (activityId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/proposed-activities/${activityId}/spatial`
    );
    return response.data;
  },

  /**
   * Create spatial assignment
   */
  createSpatialAssignment: async (
    activityId: string,
    data: {
      block_id?: string;
      sub_area_id?: string;
      assignment_type: string;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/yearly-activities/proposed-activities/${activityId}/spatial`,
      data
    );
    return response.data;
  },

  /**
   * Delete spatial assignment
   */
  deleteSpatialAssignment: async (
    activityId: string,
    assignmentId: string
  ): Promise<void> => {
    await api.delete(
      `/api/yearly-activities/proposed-activities/${activityId}/spatial/${assignmentId}`
    );
  },

  // ===== NEW: DRAWN FEATURES APIs =====

  /**
   * Get drawn features for a proposed activity
   */
  getDrawnFeatures: async (activityId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/proposed-activities/${activityId}/drawn-features`
    );
    return response.data;
  },

  /**
   * Create drawn feature
   */
  createDrawnFeature: async (
    activityId: string,
    data: {
      feature_type: string;
      geometry: string;
      properties: object;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/yearly-activities/proposed-activities/${activityId}/drawn-features`,
      data
    );
    return response.data;
  },

  /**
   * Update drawn feature
   */
  updateDrawnFeature: async (
    activityId: string,
    featureId: string,
    data: {
      feature_type?: string;
      geometry?: string;
      properties?: object;
    }
  ): Promise<any> => {
    const response = await api.patch(
      `/api/yearly-activities/proposed-activities/${activityId}/drawn-features/${featureId}`,
      data
    );
    return response.data;
  },

  /**
   * Delete drawn feature
   */
  deleteDrawnFeature: async (
    activityId: string,
    featureId: string
  ): Promise<void> => {
    await api.delete(
      `/api/yearly-activities/proposed-activities/${activityId}/drawn-features/${featureId}`
    );
  },

  // ===== YEAR DETAILS APIs =====

  /**
   * Get year details for a proposed activity
   */
  getYearDetails: async (activityId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/proposed-activities/${activityId}/year-details`
    );
    return response.data;
  },

  /**
   * Create year detail
   */
  createYearDetail: async (
    activityId: string,
    data: {
      year_number: number;
      quantity?: number;
      yearly_budget?: number;
      notes?: string;
    }
  ): Promise<any> => {
    const response = await api.post(
      `/api/yearly-activities/proposed-activities/${activityId}/year-details`,
      data
    );
    return response.data;
  },

  /**
   * Update year detail
   */
  updateYearDetail: async (
    activityId: string,
    detailId: string,
    data: {
      quantity?: number;
      yearly_budget?: number;
      notes?: string;
    }
  ): Promise<any> => {
    const response = await api.patch(
      `/api/yearly-activities/proposed-activities/${activityId}/year-details/${detailId}`,
      data
    );
    return response.data;
  },

  /**
   * Delete year detail
   */
  deleteYearDetail: async (
    activityId: string,
    detailId: string
  ): Promise<void> => {
    await api.delete(
      `/api/yearly-activities/proposed-activities/${activityId}/year-details/${detailId}`
    );
  },

  // ===== EXPORT SPATIAL FEATURES =====

  /**
   * Export spatial features to KML format
   */
  exportSpatialFeaturesKml: async (activityId: string): Promise<void> => {
    try {
      await downloadFromApi(
        `/api/yearly-activities/proposed-activities/${activityId}/export/kml`,
        'spatial.kml'
      );
    } catch (error: any) {
      console.error('KML export error:', error);
      const errorMsg = error.response?.data?.detail || 'Failed to export KML';
      throw new Error(errorMsg);
    }
  },

  /**
   * Export spatial features to GPKG format
   */
  exportSpatialFeaturesGpkg: async (activityId: string): Promise<void> => {
    try {
      await downloadFromApi(
        `/api/yearly-activities/proposed-activities/${activityId}/export/gpkg`,
        'spatial.gpkg'
      );
    } catch (error: any) {
      console.error('GPKG export error:', error);
      const errorMsg = error.response?.data?.detail || 'Failed to export GPKG';
      throw new Error(errorMsg);
    }
  },

  // ===== NEW PAGE API METHODS =====

  /**
   * Get potential activities (master list) for a calculation
   */
  getPotentialActivities: async (calculationId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/potential-activities`
    );
    return response.data;
  },

  /**
   * Get proposed activities for a calculation
   */
  getProposedActivities: async (calculationId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/proposed-activities`
    );
    return response.data;
  },

  /**
   * Get all year details for a proposed activity
   */
  getAllYearDetails: async (activityId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/proposed-activities/${activityId}/year-details`
    );
    return response.data;
  },

  /**
   * Copy drawn feature to another year
   */
  copyDrawnFeature: async (
    activityId: string,
    featureId: string,
    targetYear: number
  ): Promise<any> => {
    const response = await api.post(
      `/api/yearly-activities/proposed-activities/${activityId}/drawn-features/${featureId}/copy`,
      { target_year: targetYear }
    );
    return response.data;
  },

  /**
   * Get blocks with sub-areas for a calculation
   */
  getBlocksWithSubareas: async (calculationId: string): Promise<any[]> => {
    const response = await api.get(
      `/api/yearly-activities/calculations/${calculationId}/blocks-with-subareas`
    );
    return response.data;
  },

  /**
   * Update spatial assignment
   */
  updateSpatialAssignment: async (
    activityId: string,
    assignmentId: string,
    data: {
      block_id?: string;
      sub_area_id?: string;
    }
  ): Promise<any> => {
    const response = await api.patch(
      `/api/yearly-activities/proposed-activities/${activityId}/spatial/${assignmentId}`,
      data
    );
    return response.data;
  },
};


// ============================================================================
// Compartment Management API
// ============================================================================

/** One tree from `compartmentApi.getTreesForMap` — see `get_trees_for_map` (compartments.py). */
export interface TreeMapPoint {
  id: string;
  latitude: number;
  longitude: number;
  species: string;
  dbh_cm: number;
  height_m: number;
  volume_m3: number;
  dbh_class: string;
  block_id: string | null;
  block_name: string | null;
  remark: string | null;
  grid_cell_id: number | null;
  source: string;
}

export const compartmentApi = {
  getAvailableBlocks: async (calculationId: string): Promise<any[]> => {
    const response = await api.get(`/api/compartments/available-blocks/${calculationId}`);
    return response.data;
  },

  getAllBlocks: async (calculationId: string): Promise<any[]> => {
    const response = await api.get(`/api/compartments/calculation/${calculationId}/all-blocks`);
    return response.data;
  },

  previewSplit: async (request: {
    block_id: string;
    method: 'parallel' | 'grid' | 'custom';
    parameters: Record<string, any>;
  }): Promise<any> => {
    const response = await api.post('/api/compartments/preview-split', request);
    return response.data;
  },

  executeSplit: async (request: {
    block_id: string;
    method: 'parallel' | 'grid' | 'custom';
    parameters: Record<string, any>;
    naming_pattern?: string;
    reassign_trees?: boolean;
    notes?: string;
  }): Promise<any> => {
    const response = await api.post('/api/compartments/execute-split', request);
    return response.data;
  },

  getSplitDirections: async (): Promise<any[]> => {
    const response = await api.get('/api/compartments/split-directions');
    return response.data;
  },

  undoSplit: async (splitHistoryId: string): Promise<any> => {
    const response = await api.delete(`/api/compartments/split/${splitHistoryId}`);
    return response.data;
  },

  deleteCompartments: async (blockId: string): Promise<any> => {
    const response = await api.delete(`/api/compartments/block/${blockId}/compartments`);
    return response.data;
  },

  deleteCompartment: async (compartmentId: string): Promise<any> => {
    const response = await api.delete(`/api/compartments/${compartmentId}`);
    return response.data;
  },

  /**
   * Update compartment name
   */
  updateCompartmentName: async (compartmentId: string, name: string): Promise<any> => {
    const response = await api.patch(`/api/compartments/${compartmentId}/name`, { name });
    return response.data;
  },

  getTreesNeedingAssignment: async (blockId: string): Promise<any> => {
    const response = await api.get(`/api/compartments/trees-needing-assignment/${blockId}`);
    return response.data;
  },

  reassignTrees: async (request: {
    block_id: string;
    auto_assign?: boolean;
    manual_assignments?: Record<string, string>;
  }): Promise<any> => {
    const response = await api.post('/api/compartments/reassign-trees', request);
    return response.data;
  },

  getTreesForMap: async (
    calculationId: string
  ): Promise<{
    count: number;
    trees: TreeMapPoint[];
    grid_spacing_meters: number | null;
    inventory_id: string | null;
  }> => {
    const response = await api.get(`/api/compartments/calculation/${calculationId}/trees`);
    return response.data;
  },

  exportGpkg: async (calculationId: string): Promise<void> => {
    await downloadFromApi(
      `/api/compartments/calculation/${calculationId}/export-gpkg`,
      'compartments.gpkg'
    );
  },

  exportKml: async (calculationId: string): Promise<void> => {
    await downloadFromApi(
      `/api/compartments/calculation/${calculationId}/export-kml`,
      'compartments.kml'
    );
  },

  /**
   * Toggle lock status for a block/compartment
   */
  toggleLockBlock: async (blockId: string): Promise<any> => {
    const response = await api.patch(`/api/compartments/blocks/${blockId}/toggle-lock`);
    return response.data;
  },

  /**
   * Get hierarchical compartment tree for a calculation
   */
  getCompartmentTree: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/compartments/calculations/${calculationId}/compartment-tree`);
    return response.data;
  },

  /**
   * Sub-divide a compartment into sub-compartments
   */
  subdivideBlock: async (
    blockId: string,
    config: {
      method: 'parallel' | 'grid' | 'custom';
      parameters: Record<string, any>;
      naming_pattern?: string;
      reassign_trees?: boolean;
      notes?: string;
    }
  ): Promise<any> => {
    const response = await api.post(`/api/compartments/blocks/${blockId}/sub-divide`, config);
    return response.data;
  },

  renameCompartment: async (compartmentId: string, newName: string): Promise<any> => {
    const response = await api.put(`/api/compartments/${compartmentId}/rename`, { name: newName });
    return response.data;
  },
};

export const operationalPlanApi = {
  create: async (
    calculationId: string, forestName?: string, templateId?: string, customNotes?: string,
    planRegime?: string, planStage?: string, authoring?: boolean, replace?: boolean,
  ): Promise<any> => {
    const qs = new URLSearchParams();
    if (templateId) qs.set('template_id', templateId);
    if (replace) qs.set('replace', 'true');
    if (planRegime) qs.set('plan_regime', planRegime);
    if (planStage) qs.set('plan_stage', planStage);
    if (authoring) qs.set('authoring', 'true');
    const params = qs.toString() ? `?${qs.toString()}` : '';
    const response = await api.post(`/api/operational-plans${params}`, { calculation_id: calculationId, forest_name: forestName, custom_notes: customNotes });
    return response.data;
  },

  getByCalculation: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/calculation/${calculationId}`);
    return response.data;
  },

  /** Does the forest already have a plan, and may "start again" replace it? */
  planReplaceStatus: async (calculationId: string): Promise<{ exists: boolean; plan_id?: string; template_name?: string | null; can_replace?: boolean; blocked_reason?: string | null }> => {
    const response = await api.get(`/api/operational-plans/calculation/${calculationId}/replace-status`);
    return response.data;
  },

  update: async (planId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/${planId}`, data);
    return response.data;
  },

  updateSection: async (planId: string, sectionKey: string, data: any, autoData?: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/${planId}/sections/${sectionKey}`, { content: data, auto_data: autoData });
    return response.data;
  },

  autoPopulate: async (planId: string): Promise<any> => {
    const response = await api.post(`/api/operational-plans/${planId}/auto-populate`);
    return response.data;
  },

  getTree: async (planId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/${planId}/tree`);
    return response.data;
  },

  addNode: async (planId: string, data: any): Promise<any> => {
    const response = await api.post(`/api/operational-plans/${planId}/tree/nodes`, data);
    return response.data;
  },

  updateNode: async (planId: string, nodeId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/${planId}/tree/nodes/${nodeId}`, data);
    return response.data;
  },

  deleteNode: async (planId: string, nodeId: string): Promise<any> => {
    const response = await api.delete(`/api/operational-plans/${planId}/tree/nodes/${nodeId}`);
    return response.data;
  },

  reorderTree: async (planId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/${planId}/tree/reorder`, data);
    return response.data;
  },

  getMetadataForm: async (planId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/${planId}/metadata-form`);
    return response.data;
  },

  updateMetadataForm: async (planId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/${planId}/metadata-form`, data);
    return response.data;
  },

  // ── Cascading Location Data (from admin.admin_nepal) ──
  getProvinces: async (): Promise<string[]> => {
    const response = await api.get('/api/operational-plans/locations/provinces');
    return response.data;
  },

  getDivisions: async (province?: string): Promise<string[]> => {
    const params = province ? { province } : {};
    const response = await api.get('/api/operational-plans/locations/divisions', { params });
    return response.data;
  },

  getSubDivisions: async (province?: string, division?: string): Promise<string[]> => {
    const params: Record<string, string> = {};
    if (province) params.province = province;
    if (division) params.division = division;
    const response = await api.get('/api/operational-plans/locations/sub-divisions', { params });
    return response.data;
  },

  getMunicipalities: async (province?: string, division?: string, subDivision?: string): Promise<{ name: string; type: string }[]> => {
    const params: Record<string, string> = {};
    if (province) params.province = province;
    if (division) params.division = division;
    if (subDivision) params.sub_division = subDivision;
    const response = await api.get('/api/operational-plans/locations/municipalities', { params });
    return response.data;
  },

  getWards: async (province?: string, division?: string, subDivision?: string, municipality?: string): Promise<string[]> => {
    const params: Record<string, string> = {};
    if (province) params.province = province;
    if (division) params.division = division;
    if (subDivision) params.sub_division = subDivision;
    if (municipality) params.municipality = municipality;
    const response = await api.get('/api/operational-plans/locations/wards', { params });
    return response.data;
  },

  getPhysiographyJurisdiction: async (province?: string, division?: string, subDivision?: string, municipality?: string): Promise<{ physiography_zone: string; protected_area_status: string }> => {
    const params: Record<string, string> = {};
    if (province) params.province = province;
    if (division) params.division = division;
    if (subDivision) params.sub_division = subDivision;
    if (municipality) params.municipality = municipality;
    const response = await api.get('/api/operational-plans/locations/physiography-jurisdiction', { params });
    return response.data;
  },

  // ── District-based Cascade (new civil admin hierarchy) ──
  getDistricts: async (province?: string): Promise<string[]> => {
    const params = province ? { province } : {};
    const response = await api.get('/api/operational-plans/locations/districts', { params });
    return response.data;
  },

  getMunicipalitiesByDistrict: async (province: string, district: string): Promise<{ name: string; type: string }[]> => {
    const response = await api.get('/api/operational-plans/locations/municipalities-by-district', { params: { province, district } });
    return response.data;
  },

  getWardsByDistrict: async (province: string, district: string, municipality: string): Promise<string[]> => {
    const response = await api.get('/api/operational-plans/locations/wards-by-district', { params: { province, district, municipality } });
    return response.data;
  },

  getPhysiographyByDistrict: async (province: string, district: string, municipality: string): Promise<{ physiography_zone: string; protected_area_status: string }> => {
    const response = await api.get('/api/operational-plans/locations/physiography-by-district', { params: { province, district, municipality } });
    return response.data;
  },

  listVariables: async (params?: { category?: string; search?: string }): Promise<any> => {
    const response = await api.get('/api/operational-plans/variables', { params });
    return response.data;
  },

  getVariable: async (key: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/variables/${key}`);
    return response.data;
  },

  getVariableCatalog: async (
    calculationId: string,
    params?: { category?: string; search?: string; keys?: string },
  ): Promise<any> => {
    const response = await api.get(`/api/operational-plans/${calculationId}/variable-catalog`, { params });
    return response.data;
  },

  // THEMATIC_MAP_VARIABLES_PLAN §3.9 — the map-variable reference page.
  listMapVariables: async (params?: { calc_id?: string; family?: string }): Promise<any> => {
    const response = await api.get('/api/operational-plans/map-variables', { params });
    return response.data;
  },

  // Forests the user can evaluate map-variable availability against (super
  // admin → all completed calcs; else → own). Powers the page's forest picker.
  listMapVariableForests: async (): Promise<{
    forests: Array<{
      calc_id: string;
      forest_name: string;
      status: string;
      has_field_inventory: boolean;
      created_at: string | null;
    }>;
  }> => {
    const response = await api.get('/api/operational-plans/map-variables/forests');
    return response.data;
  },

  // The preview endpoint is auth-gated, so an <img src> cannot reach it —
  // fetch the PNG as a blob (auth header injected by the axios interceptor)
  // and hand back an object URL. Callers must revokeObjectURL when done.
  mapVariablePreviewObjectUrl: async (
    key: string,
    calcId?: string,
    variant?: SfmVariant,
  ): Promise<string> => {
    // `key` (e.g. "thememap:unit__growing_stock") goes in the path un-encoded —
    // the backend route is `{key:path}` and ":" is a legal path character.
    const params: Record<string, string> = { ...(calcId ? { calc_id: calcId } : {}) };
    if (variant) params.variant = variant;
    const response = await api.get(
      `/api/operational-plans/map-variables/${key}/preview.png`,
      { params: Object.keys(params).length ? params : undefined, responseType: 'blob' },
    );
    return URL.createObjectURL(response.data as Blob);
  },

  listTables: async (): Promise<any> => {
    const response = await api.get('/api/op-tables');
    return response.data;
  },

  getTableData: async (tableId: string, calculationId: string): Promise<any> => {
    const response = await api.get(`/api/op-tables/${tableId}/data`, { params: { calculation_id: calculationId } });
    return response.data;
  },

  updateTableData: async (tableId: string, calculationId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/op-tables/${tableId}/data?calculation_id=${calculationId}`, data);
    return response.data;
  },

  autoPopulateTable: async (tableId: string, calculationId: string): Promise<any> => {
    const response = await api.post(`/api/op-tables/${tableId}/auto-populate?calculation_id=${calculationId}`);
    return response.data;
  },

  exportDocx: async (planId: string, forestName: string): Promise<void> => {
    await downloadFromApi(
      `/api/operational-plans/${planId}/export`,
      `${forestName}_OP_DOCX.docx`,
      undefined,
      { method: 'GET', timeoutMs: 300000 }
    );
  },

  /** Mandatory steps the export is gated on (owner rule 2026-10-10). */
  getExportRequirements: async (planId: string): Promise<ExportRequirements> => {
    const response = await api.get(`/api/operational-plans/${planId}/export-requirements`);
    return response.data;
  },

  /** Save the edited plan as the caller's own private template (the forest's values are turned back into tokens). */
  saveAsMyTemplate: async (
    planId: string,
    data: { name: string; description?: string },
  ): Promise<{ template: { id: string; name: string }; report: { restored: number; edited: { id: string; title: string }[]; new: { id: string; title: string }[]; values_turned_into_tokens: number; parent_found: boolean } }> => {
    const response = await api.post(`/api/operational-plans/${planId}/save-as-my-template`, data);
    return response.data;
  },

  /** What stops this template from being shared (errors) and what to look at (warnings). */
  checkTemplateForSharing: async (templateId: string): Promise<PublishCheck> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/publish-check`);
    return response.data;
  },

  /** Set who can see the template. A 422 carries `detail.issues` (the publish check's errors). */
  shareTemplate: async (templateId: string, scope: ShareScope, license: TemplateLicense): Promise<any> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/share`, { scope, license });
    return response.data;
  },

  getTemplateLineage: async (templateId: string): Promise<{ chain: LineageItem[] }> => {
    const response = await api.get(`/api/operational-plans/templates/${templateId}/lineage`);
    return response.data;
  },

  reportTemplate: async (templateId: string, reason: string): Promise<{ id: string; already_reported: boolean }> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/report`, { reason });
    return response.data;
  },

  /** Super admin: the complaints queue. */
  listTemplateReports: async (status: 'open' | 'dismissed' | 'actioned' | 'all' = 'open'): Promise<{ total: number; reports: TemplateReport[] }> => {
    const response = await api.get(`/api/operational-plans/templates/reports?status=${status}`);
    return response.data;
  },

  handleTemplateReport: async (reportId: string, action: 'dismiss' | 'unpublish', note = ''): Promise<{ id: string; status: string }> => {
    const response = await api.put(`/api/operational-plans/templates/reports/${reportId}`, { action, note });
    return response.data;
  },

  /** Super admin: make a shared template Verified or Official (or back to Community). */
  setTemplateTier: async (templateId: string, tier: TemplateTier, note = ''): Promise<any> => {
    const response = await api.put(`/api/operational-plans/templates/${templateId}/tier`, { tier, note });
    return response.data;
  },

  /** Super admin: anonymous counts of what people change in the plans built from each template. */
  getTemplateAnalytics: async (minOwners = 2): Promise<{ min_owners: number; templates: any[] }> => {
    const response = await api.get(`/api/operational-plans/templates/analytics?min_owners=${minOwners}`);
    return response.data;
  },

  /** The section library: one chapter of a plan, shared like a template. */
  listSections: async (scope: 'mine' | 'published' | 'all' = 'published', search?: string): Promise<{ total: number; sections: any[] }> => {
    const q = new URLSearchParams({ scope });
    if (search) q.set('search', search);
    const response = await api.get(`/api/operational-plans/sections?${q.toString()}`);
    return response.data;
  },

  /** Save one chapter of the plan to my library (its forest values become variables again). */
  saveSection: async (planId: string, data: { node_id: string; name: string; description?: string }): Promise<{ section: { id: string; name: string }; report: { nodes: number; edited: { id: string; title: string }[] } }> => {
    const response = await api.post(`/api/operational-plans/${planId}/sections/save`, data);
    return response.data;
  },

  /** Insert a library section into the plan; the reply carries the new tree and the ids of the new chapters. */
  insertSection: async (planId: string, data: { section_id: string; parent_id?: string | null; position?: number }): Promise<{ inserted: string[]; locked: boolean; tree: any[] }> => {
    const response = await api.post(`/api/operational-plans/${planId}/sections/insert`, data);
    return response.data;
  },

  /** Print the template's credit line at the end of the exported plan (off by default). */
  setPlanCreditLine: async (planId: string, show: boolean): Promise<{ show: boolean }> => {
    const response = await api.put(`/api/operational-plans/${planId}/credit-line`, { show });
    return response.data;
  },

  /** "Check my document": problems the edits would leave in the printed plan. */
  getPlanValidity: async (planId: string): Promise<PlanValidity> => {
    const response = await api.get(`/api/operational-plans/${planId}/validity`);
    return response.data;
  },

  /** The mandatory-steps checklist for a forest, before any plan exists. */
  getExportRequirementsForCalculation: async (calculationId: string): Promise<ExportRequirements> => {
    const response = await api.get(`/api/operational-plans/calculation/${calculationId}/export-requirements`);
    return response.data;
  },

  /** Which of this plan's variables / maps have no data for the forest (they print "No data" in the export). */
  getPlanReadiness: async (planId: string): Promise<PlanReadiness> => {
    const response = await api.get(`/api/operational-plans/${planId}/readiness`);
    return response.data;
  },

  exportHeartbeat: async (planId: string): Promise<void> => {
    await api.post(`/api/operational-plans/${planId}/export-heartbeat`);
  },

  exportVariablesCsv: async (): Promise<void> => {
    await downloadFromApi(
      '/api/operational-plans/variables/export/csv',
      'OP_Variable_Registry.csv'
    );
  },

  // mode: 'values' (default) resolves every {{token}}; 'tokens' keeps them
  // verbatim for template proofing (OP_TEMPLATE_MANAGEMENT_PLAN.md T2).
  previewOperationalPlan: async (
    planId: string, mode: 'values' | 'tokens' = 'values',
  ): Promise<string> => {
    const response = await api.get(`/api/operational-plans/${planId}/render`, {
      params: { mode },
      responseType: 'text',
    });
    return response.data;
  },

  previewOperationalPlanSection: async (
    planId: string, nodeId: string, mode: 'values' | 'tokens' = 'values',
  ): Promise<string> => {
    const response = await api.get(
      `/api/operational-plans/${planId}/render/section/${nodeId}`,
      { params: { mode }, responseType: 'text' },
    );
    return response.data;
  },

  /** Render a template against a forest's data WITHOUT creating a plan
   *  ("Preview with my forest"). Nothing is persisted. Pass `nodeId` to render
   *  only one section (the designer's in-editor preview). */
  previewTemplateWithForest: async (
    templateId: string, calculationId: string,
    mode: 'values' | 'tokens' = 'values', nodeId?: string,
  ): Promise<string> => {
    const params: Record<string, string> = { calculation_id: calculationId, mode };
    if (nodeId) params.node_id = nodeId;
    const response = await api.get(
      `/api/operational-plans/templates/${templateId}/preview`,
      { params, responseType: 'text' },
    );
    return response.data;
  },

  getChartData: async (planId: string, chartType: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/${planId}/chart-data/${chartType}`);
    return response.data;
  },

  getMapGeojson: async (planId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/${planId}/map-geojson`);
    return response.data;
  },

  clearMapCache: async (planId: string, layer?: string): Promise<any> => {
    const params = layer ? `?layer=${encodeURIComponent(layer)}` : '';
    const response = await api.post(`/api/operational-plans/${planId}/clear-map-cache${params}`);
    return response.data;
  },

  getEditingStatus: async (planId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/${planId}/editing-status`);
    return response.data;
  },

  // ── Template Management ──

  listTemplates: async (scope: string = 'mine', tag?: string): Promise<any> => {
    let url = `/api/operational-plans/templates?scope=${scope}`;
    if (tag) url += `&tag=${encodeURIComponent(tag)}`;
    const response = await api.get(url);
    return response.data;
  },

  listPublicTemplates: async (tag?: string, search?: string): Promise<any> => {
    let url = '/api/operational-plans/templates/public';
    const params: any = {};
    if (tag) params.tag = tag;
    if (search) params.search = search;
    const response = await api.get(url, { params });
    return response.data;
  },


  getTemplate: async (templateId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/templates/${templateId}`);
    return response.data;
  },

  createTemplate: async (data: { name: string; description?: string; tree: any[]; is_default?: boolean; visibility?: string; tags?: string[]; plan_regime?: string; plan_stage?: string }): Promise<any> => {
    const response = await api.post('/api/operational-plans/templates', data);
    return response.data;
  },

  updateTemplate: async (templateId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/templates/${templateId}`, data);
    return response.data;
  },

  /** Delete a template. One that was shared or copied is withdrawn instead (`status: 'withdrawn'`); the super admin may
   *  pass `permanent` to delete it for good (`status: 'deleted_permanently'`). */
  deleteTemplate: async (templateId: string, opts?: { permanent?: boolean }): Promise<any> => {
    const response = await api.delete(`/api/operational-plans/templates/${templateId}${opts?.permanent ? '?permanent=true' : ''}`);
    return response.data;
  },


  // approve = one-click publish (validate + snapshot + publish); reject needs a note.

  // ── OP multi-template lifecycle (OP_MULTI_TEMPLATE_PLAN.md §3.3) ──
  unpublishTemplate: async (templateId: string, note?: string): Promise<any> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/unpublish`, { note: note || '' });
    return response.data;
  },

  deprecateTemplate: async (templateId: string, note?: string, supersededByTemplateId?: string): Promise<any> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/deprecate`, {
      note: note || '', superseded_by_template_id: supersededByTemplateId || null,
    });
    return response.data;
  },

  retireTemplate: async (templateId: string, note: string): Promise<any> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/retire`, { note });
    return response.data;
  },

  validateTemplate: async (templateId: string): Promise<{
    ok: boolean;
    errors: Array<{ severity: string; code: string; message: string; node_id?: string | null; token?: string | null }>;
    warnings: Array<{ severity: string; code: string; message: string; node_id?: string | null; token?: string | null }>;
  }> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/validate`);
    return response.data;
  },

  getTemplateAudit: async (templateId: string): Promise<any[]> => {
    const response = await api.get(`/api/operational-plans/templates/${templateId}/audit`);
    return response.data;
  },

  listPlanKinds: async (activeOnly = false): Promise<any[]> => {
    const response = await api.get('/api/operational-plans/plan-kinds', { params: { active_only: activeOnly } });
    return response.data;
  },

  // ── Phase 4: plan <-> template link ──
  getPlanTemplateStatus: async (planId: string): Promise<{
    has_template: boolean;
    template_id?: string | null;
    template_name?: string | null;
    template_status?: string | null;
    pinned_version?: number | null;
    latest_published_version?: number | null;
    upgrade_available: boolean;
    changelog_since: string[];
  }> => {
    const response = await api.get(`/api/operational-plans/${planId}/template-status`);
    return response.data;
  },

  upgradePlanTemplate: async (planId: string, confirm: boolean): Promise<{
    applied: boolean;
    from_version?: number | null;
    to_version?: number | null;
    diff: { added: string[]; removed: string[]; kept: number; content_preserved: number };
  }> => {
    const response = await api.post(`/api/operational-plans/${planId}/template-upgrade`, { confirm });
    return response.data;
  },

  suggestKind: async (calculationId: string, regime?: string): Promise<{
    suggested_stage: 'new' | 'revision'; has_prior_plan: boolean; reason: string;
  }> => {
    const response = await api.get('/api/operational-plans/suggest-kind', {
      params: { calculation_id: calculationId, regime },
    });
    return response.data;
  },

  updatePlanKind: async (key: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/plan-kinds/${key}`, data);
    return response.data;
  },

  savePlanAsTemplate: async (planId: string, data: { name: string; description?: string; tree?: any[]; is_default?: boolean; is_system?: boolean; visibility?: string; tags?: string[] }): Promise<any> => {
    const response = await api.post(`/api/operational-plans/${planId}/save-as-template`, data);
    return response.data;
  },

  /** The one System Template + its version history + seed-tree sync status. */
  getSystemTemplate: async (): Promise<any> => {
    const response = await api.get('/api/operational-plans/templates/system');
    return response.data;
  },

  /** Rebuild the System Template's structure from a plan (super admin).
   *  confirm=false → dry-run diff only; confirm=true → snapshot + apply. */
  adoptSystemTemplateFromPlan: async (planId: string, confirm: boolean): Promise<any> => {
    const response = await api.post(
      '/api/operational-plans/templates/system/adopt-from-plan',
      undefined,
      { params: { plan_id: planId, confirm } },
    );
    return response.data;
  },

  publishTemplate: async (templateId: string, is_active: boolean): Promise<any> => {
    const response = await api.put(`/api/operational-plans/templates/${templateId}/publish`, { is_active });
    return response.data;
  },

  templateParentStatus: async (templateId: string): Promise<{ has_parent: boolean; parent_name?: string; update_available?: boolean; added?: string[]; parent_version?: number | null }> => {
    const response = await api.get(`/api/operational-plans/templates/${templateId}/parent-status`);
    return response.data;
  },

  addParentUpdates: async (templateId: string): Promise<{ added: string[]; version: number | null }> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/add-parent-updates`);
    return response.data;
  },

  cloneTemplate: async (
    templateId: string,
    name?: string,
    target?: { target_plan_kind?: string; target_plan_regime?: string; target_plan_stage?: string },
  ): Promise<any> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/clone`, { name, ...(target || {}) });
    return response.data;
  },

  getTemplateVersions: async (templateId: string): Promise<any> => {
    const response = await api.get(`/api/operational-plans/templates/${templateId}/versions`);
    return response.data;
  },

  rollbackTemplate: async (templateId: string, version: number): Promise<any> => {
    const response = await api.post(`/api/operational-plans/templates/${templateId}/rollback`, { version });
    return response.data;
  },

  listTemplateCategories: async (): Promise<any> => {
    const response = await api.get('/api/operational-plans/template-categories');
    return response.data;
  },

  createTemplateCategory: async (data: { key: string; label_ne: string; label_en: string; description?: string; color?: string; sort_order?: number }): Promise<any> => {
    const response = await api.post('/api/operational-plans/template-categories', data);
    return response.data;
  },

  updateTemplateCategory: async (categoryId: string, data: any): Promise<any> => {
    const response = await api.put(`/api/operational-plans/template-categories/${categoryId}`, data);
    return response.data;
  },

  deleteTemplateCategory: async (categoryId: string): Promise<any> => {
    const response = await api.delete(`/api/operational-plans/template-categories/${categoryId}`);
    return response.data;
  },
};

export const biodiversityApi = {
  getCalculationSpecies: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/biodiversity/calculations/${calculationId}/species`);
    return response.data;
  },
};

export const dbhClassApi = {
  listSystems: async (): Promise<any> => {
    const response = await api.get('/api/dbh-classes/systems');
    return response.data;
  },

  getSystem: async (systemName: string): Promise<any> => {
    const response = await api.get(`/api/dbh-classes/systems/${systemName}`);
    return response.data;
  },

  classifyDbh: async (dbh: number, system: string = 'guideline_2061'): Promise<any> => {
    const response = await api.post(`/api/dbh-classes/classify?dbh=${dbh}&system=${system}`);
    return response.data;
  },

  getHistory: async (systemName: string): Promise<any> => {
    const response = await api.get(`/api/dbh-classes/systems/${systemName}/history`);
    return response.data;
  },

  updateSystem: async (systemName: string, data: Record<string, any>): Promise<any> => {
    const response = await api.put(`/api/dbh-classes/systems/${systemName}`, data);
    return response.data;
  },

  deleteSystem: async (systemName: string): Promise<any> => {
    const response = await api.delete(`/api/dbh-classes/systems/${systemName}`);
    return response.data;
  },
};

export const reportApi = {
  checkDataCompleteness: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/report/${calculationId}/data-completeness`);
    return response.data;
  },

  getAvailableSections: async (calculationId: string): Promise<any> => {
    const response = await api.get(`/api/report/${calculationId}/sections-available`);
    return response.data;
  },

  /**
   * Start a generation job.
   *
   * Three things about the wire format, each of which was wrong at some point and
   * is pinned by `reportApi.test.ts`:
   *
   *  * The section list is `sections`, not `selected_sections`. The endpoint's
   *    body model only knows `metadata` and `sections`, so the old key was
   *    dropped and the picker silently generated *every* section instead of the
   *    chosen ones.
   *  * `include_images` is a **query** parameter, not a body field — the images
   *    toggle was therefore dead and every report included images.
   *  * `metadata` is optional and should not be sent. The server reads the saved
   *    forest metadata record (D5) and a posted value only fills gaps, so
   *    passing a stale copy from a form is how the cover page used to end up
   *    disagreeing with the record.
   */
  generateReport: async (
    calculationId: string,
    selectedSections: string[],
    includeImages: boolean,
  ): Promise<any> => {
    const response = await api.post(
      `/api/report/${calculationId}/generate`,
      { sections: selectedSections },
      { params: { include_images: includeImages } },
    );
    return response.data;
  },

  getReportStatus: async (jobId: string): Promise<any> => {
    const response = await api.get(`/api/report/${jobId}/status`);
    return response.data;
  },

  getSection: async (jobId: string, sectionKey: string): Promise<any> => {
    const response = await api.get(`/api/report/${jobId}/sections/${sectionKey}`);
    return response.data;
  },

  previewReport: async (jobId: string): Promise<any> => {
    const response = await api.get(`/api/report/${jobId}/preview`);
    return response.data;
  },

  downloadReport: async (jobId: string): Promise<void> => {
    const response = await api.get(`/api/report/${jobId}/download`, {
      responseType: 'blob',
    });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `report_${jobId}.docx`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  },
};

/**
 * Forest metadata — the facts a person writes down about a forest.
 *
 * WORKSPACE_FLOW_NAV_PLAN D5. This is the field the .docx cover page used to
 * take straight from a form: the user typed it, pressed Generate, and the values
 * were gone. It is a record now, so it is fetched from and written to one place
 * that outlives the pane, and `reportApi.generateReport` no longer needs to be
 * handed it.
 *
 * Every value is `string | null` and every one of them may be absent: the GET
 * seeds what the calculation already knows and marks it `persisted: false` until
 * somebody saves, so the form opens with sensible content on a forest that has
 * never been described. The fiscal-year fields are strings on purpose — they are
 * printed verbatim and are written in Latin or Devanagari digits.
 */
export interface ForestMetadata {
  forest_name: string | null;
  group_name: string | null;
  province: string | null;
  district: string | null;
  palika: string | null;
  ward: string | null;
  division: string | null;
  sub_division: string | null;
  cf_national_code: string | null;
  fy_start: string | null;
  fy_end: string | null;
  /** Optional plan details of the forest (officers, dates, history, service provider). */
  sub_division_chief?: string | null;
  forest_management_section_chief?: string | null;
  division_forest_officer?: string | null;
  technical_assistance_org?: string | null;
  cf_handover_date?: string | null;
  cf_first_renewal_date?: string | null;
  cf_history_note?: string | null;
  cf_registration_number?: string | null;
  constitution_approved_year?: string | null;
  user_group_reg_no?: string | null;
  cf_sn_number?: string | null;
  cf_boundary_east?: string | null;
  cf_boundary_south?: string | null;
  cf_boundary_west?: string | null;
  cf_boundary_north?: string | null;
  physiography_zone?: string | null;
  protected_area_status?: string | null;
  forest_type?: string | null;
  forest_abundance?: string | null;
  forest_avg_age?: string | null;
  main_non_timber_fp?: string | null;
  avg_crown_density_pct?: string | null;
  ug_province?: string | null;
  ug_district?: string | null;
  ug_municipality?: string | null;
  ug_municipality_type?: string | null;
  ug_ward?: string | null;
  ug_division?: string | null;
  ug_sub_division?: string | null;
  ug_settlement?: string | null;
  ug_boundary_east?: string | null;
  ug_boundary_south?: string | null;
  ug_boundary_west?: string | null;
  ug_boundary_north?: string | null;
  /** False until saved: the values above are suggestions from the calculation. */
  persisted: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Every editable field, in the order the form presents them. */
export const FOREST_METADATA_FIELDS: (keyof Omit<ForestMetadata, 'persisted' | 'created_at' | 'updated_at'>)[] = [
  'forest_name',
  'group_name',
  'province',
  'district',
  'palika',
  'ward',
  'division',
  'sub_division',
  'cf_national_code',
  'fy_start',
  'fy_end',
];

/** Optional plan details, in the order the form presents them. Not part of the mandatory form. */
export const FOREST_METADATA_OPTIONAL_FIELDS = [
  'sub_division_chief',
  'forest_management_section_chief',
  'division_forest_officer',
  'technical_assistance_org',
  'cf_handover_date',
  'cf_first_renewal_date',
  'cf_history_note',
  'cf_registration_number',
  'constitution_approved_year',
  'user_group_reg_no',
  'cf_sn_number',
  'cf_boundary_east',
  'cf_boundary_south',
  'cf_boundary_west',
  'cf_boundary_north',
  'physiography_zone',
  'protected_area_status',
  'forest_type',
  'forest_abundance',
  'forest_avg_age',
  'main_non_timber_fp',
  'avg_crown_density_pct',
  'ug_province',
  'ug_district',
  'ug_municipality',
  'ug_municipality_type',
  'ug_ward',
  'ug_division',
  'ug_sub_division',
  'ug_settlement',
  'ug_boundary_east',
  'ug_boundary_south',
  'ug_boundary_west',
  'ug_boundary_north',
] as const;

export type ForestMetadataDraft = Partial<Record<string, string | null>>;

export const forestMetadataApi = {
  /** Fill the forest's details from the Forest_Metadata template (Excel / CSV, one row). A detail the file leaves empty keeps its saved value. */
  importFile: async (calculationId: string, file: File): Promise<any> => {
    const form = new FormData();
    form.append('file', file);
    return (await api.post(`/api/calculations/${calculationId}/forest-metadata/import`, form)).data;
  },

  /**
   * Read the record, seeded from the calculation. A GET never creates a row, so
   * `persisted: false` with populated fields is the normal first state.
   */
  get: async (calculationId: string): Promise<ForestMetadata> => {
    const response = await api.get<ForestMetadata>(
      `/api/calculations/${calculationId}/forest-metadata`,
    );
    return response.data;
  },

  /**
   * Save. The backend decides what is actually stored: a blank field clears the
   * column rather than storing '', and the returned `data` is the row as saved,
   * which is what the form should then display.
   */
  save: async (
    calculationId: string,
    draft: ForestMetadataDraft,
  ): Promise<{ message?: string; message_np?: string; data: ForestMetadata }> => {
    const response = await api.put<{
      message?: string;
      message_np?: string;
      data: ForestMetadata;
    }>(`/api/calculations/${calculationId}/forest-metadata`, draft);
    return response.data;
  },
};

export interface AdminTranslationRow {
  id: number;
  key: string;
  en?: string | null;
  ne?: string | null;
  context?: string | null;
  source_file: string;
  is_override: boolean;
  reviewed: boolean;
  updated_by?: string | null;
  history_count: number;
  updated_at?: string | null;
}

export interface TranslationListPage {
  items: AdminTranslationRow[];
  total: number;
  page: number;
  per_page: number;
}

export interface TranslationStats {
  total_keys: number;
  ne_keys: number;
  en_keys: number;
  untranslated_ne: number;
  overrides: number;
  reviewed: number;
}

// Translation admin endpoints (Phase 3 — DB-backed translations editor).
export const translationAdminApi = {
  list: async (params: Record<string, string | number | boolean> = {}): Promise<TranslationListPage> => {
    const response = await api.get<TranslationListPage>('/api/translations', { params });
    return response.data;
  },

  upsert: async (key: string, payload: { en?: string | null; ne?: string | null; note?: string | null }): Promise<AdminTranslationRow> => {
    const response = await api.put<AdminTranslationRow>(`/api/translations/${encodeURIComponent(key)}`, payload);
    return response.data;
  },

  stats: async (): Promise<TranslationStats> => {
    const response = await api.get<TranslationStats>('/api/translations/stats');
    return response.data;
  },

  overlay: async (): Promise<{ ne: Record<string, unknown>; en: Record<string, unknown> }> => {
    const response = await api.get('/api/translations/overlay');
    return response.data;
  },
};

// Per-forest compute cost aggregation (CB-2 — super-admin cost estimation).
export interface ForestCostRow {
  forest_name: string;
  calculation_count: number;
  total_cpu_seconds: number;
  total_peak_memory_mb: number;
  total_cpu_cost: number;
  total_memory_cost: number;
  total_cost: number;
  currency: string;
  last_run_at?: string | null;
}

export interface ForestCostsResponse {
  rows: ForestCostRow[];
  grand_total: number;
  currency: string;
}

export const forestCostsApi = {
  list: async (): Promise<ForestCostsResponse> => {
    const response = await api.get<ForestCostsResponse>('/api/admin/costs/forests');
    return response.data;
  },
};

/**
 * Unified upload (UNIFIED_UPLOAD_PLAN.md) — the canonical schema and the one
 * downloadable "Forest Data Workbook" that is generated from it.
 */
/** How a dropped file's features sit against the forest boundary (POST /uploads/classify?calculation_id=...). */
export interface ForestOverlap {
  status: 'inside' | 'partial' | 'outside' | 'unknown';
  features: number;
  inside: number;
  outside: number;
  distance_km: number | null;
}

export const uploadApi = {
  /** The canonical upload schema — purposes, columns, classification signals,
   *  validation rules. Backed by `GET /uploads/schema`. */
  getSchema: async (): Promise<UploadSchema> => {
    const response = await api.get<UploadSchema>('/api/uploads/schema');
    return response.data;
  },

  /** Download the Forest Data Workbook in the requested form. */
  downloadWorkbook: async (format: 'xlsx' | 'gpkg'): Promise<void> => {
    await downloadFromApi(
      '/api/uploads/workbook',
      `Forest_Data_Workbook.${format}`,
      { format },
    );
  },

  /** Download the data-template zip: Excel and CSV templates for every kind of data, with guidelines and the required coordinate-system column. */
  downloadTemplates: async (landUnit: 'ropani' | 'kaththa' = 'ropani'): Promise<void> => {
    await downloadFromApi('/api/uploads/templates.zip', 'Forest_Data_Templates.zip', { land_unit: landUnit });
  },

  /** Read a CSV/Excel file's columns and sample rows for the column picker (UP-3.2). */
  getCsvColumns: async (file: File): Promise<{
    columns: string[];
    sample_rows: string[][];
    lat_col: string | null;
    lon_col: string | null;
    total_rows: number;
  }> => {
    const form = new FormData();
    form.append('file', file);
    const response = await api.post('/api/uploads/csv-columns', form);
    return response.data;
  },

  /** Identify what a loose file is from its contents (UP-4.2a). */
  classifyUpload: async (
    file: File,
    expected?: string,
    calculationId?: string,
  ): Promise<{
    forest_overlap?: ForestOverlap;
    best: string | null;
    best_label: { en: string; ne: string } | null;
    candidates: { purpose_id: string; score: number; reasons: string[] }[];
    columns: string[];
    layer_names: string[];
    geometry_type: string | null;
    lat_col: string | null;
    lon_col: string | null;
    expected?: string;
    expected_label?: { en: string; ne: string } | null;
    looks_like_other?: boolean;
  }> => {
    const form = new FormData();
    form.append('file', file);
    const params = new URLSearchParams();
    if (expected) params.set('expected', expected);
    if (calculationId) params.set('calculation_id', calculationId);
    const qs = params.toString() ? `?${params.toString()}` : '';
    const response = await api.post(`/api/uploads/classify${qs}`, form);
    return response.data;
  },

  /** Which coordinate system is this table in? Read-only; the dialog pre-selects the answer and asks when it is unsure (VALIDATION_TRACKER C2). */
  coordinateSystem: async (file: File, calculationId?: string): Promise<CoordinateSystemInfo> => {
    const form = new FormData();
    form.append('file', file);
    const qs = calculationId ? `?calculation_id=${encodeURIComponent(calculationId)}` : '';
    const response = await api.post(`/api/uploads/coordinate-system${qs}`, form);
    return response.data;
  },
};

/** The answer of `POST /api/uploads/coordinate-system`. */
export interface CoordinateSystemInfo {
  has_coordinates: boolean;
  reason?: string;
  lon_column?: string;
  lat_column?: string;
  labels?: Record<string, string>;
  /** The form most points are in: degrees | utm | swapped | swapped_utm | outside_nepal | unknown. */
  dominant?: string | null;
  candidates?: { epsg: number; zone: number | null; label: string; inside_fraction: number; near_forest: boolean }[];
  suggested_epsg?: number | null;
  ambiguous?: boolean;
  none_fit?: boolean;
  missing_rows?: number[];
  strays?: [number, string][];
  point_count?: number;
  /** The coordinate system the file DECLARES in its `coordinate_system_epsg` column (the templates make it required). */
  declared?: { column: string | null; epsg: number | null; values: number[]; mixed: boolean; unsupported: number[]; blank_rows: number[] };
  declared_epsg?: number | null;
  /** True when the numbers land inside Nepal in the declared system; false when they do not; null when nothing is declared. */
  declared_ok?: boolean | null;
  declared_fraction?: number;
}

// ── RUSLE soil-loss parameters (RUSLE_SOIL_LOSS_IMPLEMENTATION_PLAN.md §0.1) ──
// Per-forest override (result_data) + org-wide profiles. The params object is a
// sparse subset of SoilErosionParams; the backend validates any patch.
export type SoilErosionParams = Record<string, unknown>;

export interface SoilErosionParamsResponse {
  params: SoilErosionParams;
  provenance: Record<string, 'default' | 'profile' | 'forest'>;
  customised: boolean;
}

export const soilErosionApi = {
  /** Resolved params + per-field provenance for one forest. */
  get: async (calculationId: string): Promise<SoilErosionParamsResponse> => {
    const r = await api.get<SoilErosionParamsResponse>(
      `/api/calculations/${calculationId}/soil-erosion-params`,
    );
    return r.data;
  },
  /** Merge a partial patch into the per-forest override (422 on an invalid value). */
  patch: async (
    calculationId: string,
    partial: SoilErosionParams,
  ): Promise<SoilErosionParamsResponse> => {
    const r = await api.patch<SoilErosionParamsResponse>(
      `/api/calculations/${calculationId}/soil-erosion-params`,
      partial,
    );
    return r.data;
  },
  /** Drop the per-forest override (revert to profile / code default). */
  reset: async (calculationId: string): Promise<SoilErosionParamsResponse> => {
    const r = await api.delete<SoilErosionParamsResponse>(
      `/api/calculations/${calculationId}/soil-erosion-params`,
    );
    return r.data;
  },
};

export interface SoilErosionProfile {
  key: string;
  label_ne: string;
  label_en: string;
  physiography_hint: string | null;
  params: SoilErosionParams;
  is_active: boolean;
  sort_order: number;
}

export const soilErosionProfileApi = {
  list: async (): Promise<SoilErosionProfile[]> => {
    const r = await api.get<SoilErosionProfile[]>('/api/admin/soil-erosion-profiles');
    return r.data;
  },
  get: async (key: string): Promise<SoilErosionProfile> => {
    const r = await api.get<SoilErosionProfile>(
      `/api/admin/soil-erosion-profiles/${encodeURIComponent(key)}`,
    );
    return r.data;
  },
  upsert: async (
    key: string,
    body: Omit<SoilErosionProfile, 'key'>,
  ): Promise<SoilErosionProfile> => {
    const r = await api.put<SoilErosionProfile>(
      `/api/admin/soil-erosion-profiles/${encodeURIComponent(key)}`,
      body,
    );
    return r.data;
  },
  remove: async (key: string): Promise<void> => {
    await api.delete(`/api/admin/soil-erosion-profiles/${encodeURIComponent(key)}`);
  },
};

// ── Landslide-hazard + household-vulnerability parameters ──────────────────
// (HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md §0.1) Per-forest override
// (result_data) + org-wide profiles. `params` is a *nested* sparse patch
// (landslide / factor_of_safety / household); the backend validates any patch.
export type HazardVulnParams = Record<string, Record<string, unknown>>;

export interface HazardVulnParamsResponse {
  params: Record<string, unknown>;
  provenance: Record<string, 'default' | 'profile' | 'forest'>;
  customised: boolean;
}

export const hazardVulnApi = {
  /** Resolved params + per-group provenance for one forest. */
  get: async (calculationId: string): Promise<HazardVulnParamsResponse> => {
    const r = await api.get<HazardVulnParamsResponse>(
      `/api/calculations/${calculationId}/hazard-vuln-params`,
    );
    return r.data;
  },
  /** Merge a nested partial patch into the per-forest override (422 on invalid). */
  patch: async (
    calculationId: string,
    partial: HazardVulnParams,
  ): Promise<HazardVulnParamsResponse> => {
    const r = await api.patch<HazardVulnParamsResponse>(
      `/api/calculations/${calculationId}/hazard-vuln-params`,
      partial,
    );
    return r.data;
  },
  /** Drop the per-forest override (revert to profile / code default). */
  reset: async (calculationId: string): Promise<HazardVulnParamsResponse> => {
    const r = await api.delete<HazardVulnParamsResponse>(
      `/api/calculations/${calculationId}/hazard-vuln-params`,
    );
    return r.data;
  },
};

export interface HazardVulnProfile {
  key: string;
  label_ne: string;
  label_en: string;
  physiography_hint: string | null;
  params: HazardVulnParams;
  is_active: boolean;
  sort_order: number;
}

export const hazardVulnProfileApi = {
  list: async (): Promise<HazardVulnProfile[]> => {
    const r = await api.get<HazardVulnProfile[]>('/api/admin/hazard-vuln-profiles');
    return r.data;
  },
  get: async (key: string): Promise<HazardVulnProfile> => {
    const r = await api.get<HazardVulnProfile>(
      `/api/admin/hazard-vuln-profiles/${encodeURIComponent(key)}`,
    );
    return r.data;
  },
  upsert: async (
    key: string,
    body: Omit<HazardVulnProfile, 'key'>,
  ): Promise<HazardVulnProfile> => {
    const r = await api.put<HazardVulnProfile>(
      `/api/admin/hazard-vuln-profiles/${encodeURIComponent(key)}`,
      body,
    );
    return r.data;
  },
  remove: async (key: string): Promise<void> => {
    await api.delete(`/api/admin/hazard-vuln-profiles/${encodeURIComponent(key)}`);
  },
};

// ── Hazard & Erosion context aggregator (HAZARD_EROSION_CONTEXT_PLAN.md P0) ──
export interface HazardErosionPrereq {
  tag: string;
  status: 'available' | 'partial' | 'unavailable';
  met: boolean;
  reason_ne: string;
  reason_en: string;
  hint_ne: string;
  hint_en: string;
}

export interface HazardErosionMap {
  key: string; // full token, e.g. "thememap:hazard__landslide_susceptibility"
  label_ne: string;
  label_en: string;
  section: string;
  is_factor_band: boolean;
  is_user_group: boolean;
  available: boolean;
  reason_ne: string;
}

export interface HazardErosionSummary {
  calculation_id: string;
  forest_name: string | null;
  physiography_zone: string | null;
  has_user_group: boolean;
  prereqs: HazardErosionPrereq[];
  soil: {
    available: boolean;
    mean_t_ha: number | null;
    total_t_yr: number | null;
    pct_above_tolerable: number | null;
    dominant_factor: string | null;
    customised: boolean;
    sdr_enabled: boolean;
  };
  hazard: {
    available: boolean;
    lsi_prone_pct: number | null;
    lsi_prone_ha: number | null;
    lsi_high_units: string | null;
    fs_enabled: boolean;
    fs_unstable_pct: number | null;
    fs_marginal_pct: number | null;
    hh_count: number;
    hh_priority_count: number;
    hh_mean_score: number | null;
    hazard_layer_informative: boolean;
    /** "survey" | "building_footprint" | "settlement_centroid" | "none" */
    hh_coord_source: string;
    hh_basis?: "households" | "buildings";
    customised: boolean;
  };
  maps: HazardErosionMap[];
}

/** Devanagari-keyed rows; keys vary per table, values are string | number. */
export type HazardTableRow = Record<string, string | number | null>;

export interface HazardErosionTables {
  calculation_id: string;
  fs_enabled: boolean;
  hh_available: boolean;
  has_user_group: boolean;
  soil_loss_by_unit: HazardTableRow[];
  soil_loss_aoi_comparison: HazardTableRow[];
  lsi_area_by_class: HazardTableRow[];
  lsi_by_unit: HazardTableRow[];
  fs_by_unit: HazardTableRow[];
  hazard_aoi_comparison: HazardTableRow[];
  hh_priority_table: HazardTableRow[];
  hh_settlement_rollup_table: HazardTableRow[];
  hh_driver_counts: HazardTableRow[];
}

/** methodology / findings / prescription prose + caveat lists, both languages. */
export interface HazardNarrationBlock {
  methodology_ne: string;
  methodology_en: string;
  findings_ne: string;
  findings_en: string;
  prescription_ne: string;
  prescription_en: string;
  assumptions_ne: string[];
  assumptions_en: string[];
}

export interface HazardErosionNarration {
  calculation_id: string;
  soil_available: boolean;
  hazard_available: boolean;
  soil: HazardNarrationBlock;
  hazard: HazardNarrationBlock;
}

export interface HazardOpInsertResult {
  status: 'inserted' | 'already_present';
  inserted: string[];
  plan_id: string;
}

/** The legend of a hazard raster map (GET /hazard-legend/{layer}): the classes this forest has, with hectares and share. */
export type HazardMapLegend =
  | { state: 'not_computed' | 'no_data' | 'no_user_group'; key: string }
  | {
      state: 'ready';
      key: string;
      area?: 'forest' | 'user_group';
      relative: boolean;
      total_ha: number;
      classes: Array<{ index: number; color: string; label_ne: string; label_en: string; from: number; to: number | null; area_ha: number; share_pct: number }>;
    };

/** What the household-vulnerability / priority-settlement dots span, for their legend (never the households themselves). */
export type HazardDotsSummary =
  | { state: 'not_computed' | 'no_user_group' | 'no_data'; kind: string }
  | { state: 'ready'; kind: string; count: number; n_priority: number; min: number; max: number };

export const hazardErosionApi = {
  getMapLegend: async (calculationId: string, layer: string, area: 'forest' | 'user_group' = 'forest'): Promise<HazardMapLegend> => {
    const r = await api.get<HazardMapLegend>(`/api/calculations/${calculationId}/hazard-legend/${layer}`, { params: { area } });
    return r.data;
  },
  getDotsSummary: async (calculationId: string, kind: 'households' | 'settlements', area: 'forest' | 'user_group' = 'forest'): Promise<HazardDotsSummary> => {
    const r = await api.get<any>(`/api/calculations/${calculationId}/hazard-households/${kind}`, { params: { area } });
    const d = r.data;
    if (d?.state !== 'ready') return { state: d?.state ?? 'no_data', kind };
    return { state: 'ready', kind, count: d.count ?? 0, n_priority: d.n_priority ?? 0, min: d.min ?? 0, max: d.max ?? 1 };
  },
  /** Header + prereq pills + key numbers + the per-forest map list, in one call. */
  summary: async (calculationId: string): Promise<HazardErosionSummary> => {
    const r = await api.get<HazardErosionSummary>(
      `/api/calculations/${calculationId}/hazard-erosion/summary`,
    );
    return r.data;
  },
  /** The Devanagari-keyed list-of-dict tables (PII-safe household rows). */
  tables: async (calculationId: string): Promise<HazardErosionTables> => {
    const r = await api.get<HazardErosionTables>(
      `/api/calculations/${calculationId}/hazard-erosion/tables`,
    );
    return r.data;
  },
  /** Adaptive methodology / findings / prescription prose + caveats (both langs). */
  narration: async (calculationId: string): Promise<HazardErosionNarration> => {
    const r = await api.get<HazardErosionNarration>(
      `/api/calculations/${calculationId}/hazard-erosion/narration`,
    );
    return r.data;
  },
  /** Append the seed ३.८ / ३.९ subsections to the calc's OP tree. Idempotent. */
  insertOpSubsections: async (calculationId: string): Promise<HazardOpInsertResult> => {
    const r = await api.post<HazardOpInsertResult>(
      `/api/calculations/${calculationId}/hazard-erosion/insert-op-subsections`,
    );
    return r.data;
  },
  /** Drop the RUSLE / LSI / FS GeoTIFF caches + the map + op-data caches. 202. */
  recompute: async (calculationId: string): Promise<{ status: string; cleared: string[] }> => {
    const r = await api.post<{ status: string; cleared: string[] }>(
      `/api/calculations/${calculationId}/hazard-erosion/recompute`,
    );
    return r.data;
  },
  /** Every OP variable the page surfaces, grouped/ordered as it reads on screen. */
  variables: async (calculationId: string): Promise<HazardVariableGroups> => {
    const r = await api.get<HazardVariableGroups>(
      `/api/calculations/${calculationId}/hazard-erosion/variables`,
    );
    return r.data;
  },
};

export interface HazardVariableRow {
  key: string;
  label_ne: string;
  label_en: string;
  var_type?: string;
  sub_group?: string;
  registered?: boolean;
  is_factor_band?: boolean;
  is_user_group?: boolean;
}
export interface HazardVariableGroups {
  calculation_id: string;
  groups: {
    id: string;
    label_ne: string;
    label_en: string;
    variables: HazardVariableRow[];
  }[];
}

// ── Sustainable Forest Management (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4) ──
// दिगो वन व्यवस्थापन — 14-type classification + growing-stock (not MAI) yield
// per felling series. Read endpoints build result_data['sfm'] on first access.

export interface SfmSpeciesShare {
  scientific: string;
  local: string | null;
  genus: string;
  group: string;
  share_pct: number;
}

export interface SfmBlockInputs {
  block_name: string;
  area_ha: number;
  dominant_species: SfmSpeciesShare[];
  associate_species: SfmSpeciesShare[];
  dominant_group: string | null;
  codominant_group: string | null;
  seedlings_per_ha: number | null;
  saplings_per_ha: number | null;
  regen_adequate: boolean | null;
  growing_stock_m3_per_ha: number | null;
  gs_ge40_m3_per_ha: number | null;
  gs_ge40_m3: number | null;
  mother_trees_per_ha: number | null;
  crown_density_pct: number;
  origin: 'natural' | 'plantation';
  conversion_target: boolean;
  mean_altitude_m: number | null;
  invasive_present: boolean;
  riparian: boolean;
  source: 'stem_mapping' | 'field_inventory' | 'prior';
  unmapped_species: string[];
}

export interface SfmPrescriptionCard {
  type_no: number | null;
  type_name_ne?: string;
  type_name_en?: string;
  branch: string;
  method?: string | null;
  orientation?: string | null;
  system_ne: string;
  system_en: string;
  felling_cycle_years?: number | null;
  regeneration_period_years?: number | null;
  rotation_years?: number | null;
  regen_method_ne?: string | null;
  regen_method_en?: string | null;
  mother_tree_target?: number[] | number | null;
  yield_basis?: string | null;
  yield_pct?: number | null;
  gs_ge40_m3_per_ha?: number | null;
  yield_note_ne?: string;
  yield_note_en?: string;
  target_stems_per_ha?: number | null;
  note_ne: string;
  note_en: string;
}

export interface SfmZone {
  sfm_zone: string;
  inner_terai: boolean;
  dom_phys: string | null;
  slope_band: number | null;
  slope_band_area_pct: Record<string, number>;
  mean_altitude_m: number | null;
}

export interface SfmWorkingCircleProposal {
  target: string;
  justification_ne: string;
  justification_en: string;
}

/** classified: forest, ≥5 plots · provisional: forest, 1–4 plots · inventory_missing: forest, no plots · non_forest */
export type SfmBlockState = 'classified' | 'provisional' | 'inventory_missing' | 'non_forest';
export type SfmLandClass =
  | 'forest'
  | 'grassland'
  | 'rangeland'
  | 'river'
  | 'water'
  | 'snow'
  | 'other_nonforest';
export const SFM_LAND_CLASSES: SfmLandClass[] = [
  'forest', 'grassland', 'rangeland', 'river', 'water', 'snow', 'other_nonforest',
];

export interface SfmBlock {
  block_name: string;
  area_ha: number;
  inputs: SfmBlockInputs;
  /** null for a block that is not forest land, or has no sample plots of its own */
  proposed_type_no: number | null;
  /** the raster prior for a block with no plots — an estimate, never the block's type */
  estimate_type_no: number | null;
  state: SfmBlockState;
  plot_count: number;
  land_class: SfmLandClass;
  land_class_source: 'esa' | 'user';
  land_class_suggestion: SfmLandClass;
  override_land_class: SfmLandClass | null;
  confidence: number;
  needs_review: boolean;
  /** classifier rationale — one " · "-joined string per language */
  reasons_ne: string;
  reasons_en: string;
  override_type_no: number | null;
  override_crown_density_pct: number | null;
  override_origin: 'natural' | 'plantation' | null;
  wc_accept: boolean;
  effective_type_no: number | null;
  prescription: SfmPrescriptionCard | null;
  orientation: string | null;
  working_circle_proposal: SfmWorkingCircleProposal | null;
  felling_series_id: number | null;
}

export interface SfmFellingSeries {
  id: number;
  type_no: number;
  branch: string;
  method: string | null;
  C: number | null;
  R: number | null;
  N: number | null;
  area_ha: number;
  annual_felling_area_ha: number | null;
  gs_ge40_m3_per_ha: number | null;
  gs_ge40_m3: number | null;
  pct: number | null;
  annual_harvest_m3: number | null;
  note_ne: string;
  note_en: string;
}

export interface SfmSamplingRow {
  block_name: string;
  stratum: 'production' | 'conservation' | 'protection';
  intensity_pct: number;
  plot_size_sqm: number;
  plots: number;
}

export interface SfmForestSummary {
  dominant_type_no: number | null;
  type_area_breakdown: Record<string, number>;
  production_area_ha: number;
  protection_area_ha: number;
  total_annual_harvest_m3: number;
  sampling_plan: SfmSamplingRow[];
  /** forest blocks with no sample plots (the plan cannot be accepted) or fewer than 5 (provisional) */
  inventory_gaps?: SfmInventoryGap[];
}

export interface SfmNarrationBlock {
  methodology: { ne: string; en: string };
  findings: { ne: string; en: string };
  prescription: { ne: string; en: string };
}

/** SFM variant naming used across api + UI (`?variant=` query param / switcher). */
export type SfmVariant = 'baseline' | 'user';

export interface SfmSummaryResponse {
  forest_summary: SfmForestSummary;
  felling_series: SfmFellingSeries[];
  source: string | null;
  generated_at: string | null;
}

export interface SfmBlocksResponse {
  blocks: SfmBlock[];
  zone_by_block: Record<string, SfmZone>;
  source: string | null;
  generated_at: string | null;
}

export interface SfmBlockPatch {
  override_type_no?: number | null;
  crown_density_pct?: number | null;
  origin?: 'natural' | 'plantation' | null;
  accept_working_circle?: boolean;
  /** null = back to ESA's suggestion */
  land_class?: SfmLandClass | null;
}

export interface SfmPatchBlockResponse {
  block: SfmBlock | null;
  felling_series: SfmFellingSeries | null;
  forest_summary: SfmForestSummary;
}

/** Full cached SFM blob as returned inside the compare payload (backend `sfm`/`sfm_user`). */
export interface SfmVariantBlob {
  version: number;
  params_hash: string;
  input_token: string;
  generated_at: string;
  source: string | null;
  zone_by_block: Record<string, SfmZone>;
  blocks: SfmBlock[];
  felling_series: SfmFellingSeries[];
  forest_summary: SfmForestSummary;
  narration: SfmNarrationBlock;
}

/** A before/after singleton pair (absent = unchanged in this position). */
export interface SfmComparePair<T> {
  before: T;
  after: T;
}

/** Stratum + sampling intensity pair (per block, when the stratum changed). */
export interface SfmStratumDelta {
  stratum: string | null;
  intensity_pct: number | null;
}

/** Per-block divergence row — only blocks whose outputs differ appear (SV-1.5). */
export interface SfmCompareBlockRow {
  block_name: string;
  slope_band?: SfmComparePair<number | null>;
  slope_source: 'workspace' | 'raster';
  stratum?: SfmComparePair<SfmStratumDelta>;
  orientation?: SfmComparePair<string | null>;
  orientation_source: 'workspace' | 'raster';
  type_no?: SfmComparePair<number | null>;
  prescription?: SfmComparePair<string | null>;
  working_circle?: SfmComparePair<string | null>;
  area_source: 'shared' | 'workspace';
}

/** Forest-level deltas — absent keys mean unchanged (identical). */
export interface SfmCompareForest {
  production_area_ha?: SfmComparePair<number>;
  protection_area_ha?: SfmComparePair<number>;
  total_annual_harvest_m3?: SfmComparePair<number>;
  felling_series?: {
    type_no: number;
    branch: string;
    annual_harvest_m3: SfmComparePair<number | null>;
  }[];
  sampling?: {
    block_name: string;
    stratum: SfmComparePair<string | null>;
    intensity_pct: SfmComparePair<number | null>;
  }[];
}

/** Payload of `GET /sustainable-fm/compare` (SV-1.5 / SV-1.7). */
export interface SfmCompareResponse {
  baseline: SfmVariantBlob;
  user: SfmVariantBlob;
  blocks: SfmCompareBlockRow[];
  forest: SfmCompareForest;
  identical: boolean;
}

// ── P11: slope-class helper overlay + assisted protection digitizing ──
export interface SfmSlopeClassFeature {
  type: 'Feature';
  properties: {
    band: number;
    label_ne: string;
    label_en: string;
    area_ha: number;
  };
  geometry: Record<string, unknown>;
}
export interface SfmSlopeClassFC {
  type: 'FeatureCollection';
  features: SfmSlopeClassFeature[];
}
export interface SfmSlopeProfile {
  dominant_band: number | null;
  area_pct_by_band: Record<string, number>;
}
export interface SfmDraftProtectionResponse {
  min_band: number;
  category: 'protected';
  polygon: Record<string, unknown>;
  slope_profile: SfmSlopeProfile;
  hint_ne: string;
  hint_en: string;
}

export interface SfmParamsResponse {
  params: Record<string, unknown>;
  provenance: Record<string, 'default' | 'profile' | 'forest'>;
  customised: boolean;
}

/** Sparse per-key patch of the SfmParams schema (a key present = an override). */
export type SfmParamPatch = Record<string, unknown>;

export interface SfmInventoryGap {
  block_name: string;
  area_ha: number;
  state: SfmBlockState;
  plot_count: number;
}

export interface SfmBlockTypeInfo {
  /** null: not forest land, or no sample plots */
  type_no: number | null;
  state: SfmBlockState;
  land_class: SfmLandClass;
  plot_count: number;
  proposed_type_no: number | null;
  /** true when the user overrode the classifier's proposal */
  overridden: boolean;
  orientation: string | null;
  /** ≥40 cm growing stock, m³/ha (null: no plots / not forest) */
  gs_ge40_m3_per_ha?: number | null;
  /** the block's area in hectares (for the legend's class areas) */
  area_ha?: number | null;
  /** the block's dominant slope band: the code 1-4 the zone classifier stores (shown as <19° … >45°) */
  slope_band?: number | string | null;
  confidence: number | null;
  needs_review: boolean;
  reasons_ne: string | null;
  reasons_en: string | null;
}

/** Trees and volume per hectare for one DBH range. */
export interface StemSuggestionRange {
  count_per_ha: number;
  volume_m3_per_ha: number;
}
export interface StemSuggestionRow {
  block_name: string;
  area_ha: number | null;
  plot_count: number;
  has_inventory: boolean;
  stem_mapped: boolean;
  suggested: boolean;
  ranges: { from10_to40: StemSuggestionRange; from10: StemSuggestionRange; from40: StemSuggestionRange } | null;
}
export interface StemMappingSuggestion {
  applies: boolean;
  series: string[];
  rows: StemSuggestionRow[];
  suggested: string | null;
}

/** One class of a map's dynamic legend: a class this forest actually has, with what it covers. */
export interface MapLegendClass {
  key: string;
  color: string;
  label_ne: string;
  label_en: string;
  /** units (blocks / compartments) in the class - SFM maps */
  count?: number;
  area_ha: number;
  share_pct: number;
}
export type SfmMapLegend =
  | { state: 'not_computed' | 'no_data'; key: string }
  | { state: 'ready'; key: string; variant?: string; custom_colours?: boolean; total_ha: number; classes: MapLegendClass[] };

export const sfmApi = {
  /** The legend of one SFM map: only the classes this forest has, with units, hectares and share (same colours as the map). */
  getMapLegend: async (calculationId: string, specKey: string, variant?: SfmVariant): Promise<SfmMapLegend> => {
    const r = await api.get<SfmMapLegend>(
      `/api/calculations/${calculationId}/sustainable-fm/map-legend/${specKey}`,
      { params: variant ? { variant } : undefined },
    );
    return r.data;
  },
  /** Under shelterwood: the units ranked by growing stock of trees of 40 cm and above - where to do stem mapping. */
  getStemMappingSuggestion: async (calculationId: string): Promise<StemMappingSuggestion> => {
    const r = await api.get<StemMappingSuggestion>(
      `/api/calculations/${calculationId}/sustainable-fm/stem-mapping-suggestion`,
    );
    return r.data;
  },
  /** Per-block effective forest type, read from the cache (never builds it) — for the workspace map. */
  getBlockTypes: async (calculationId: string): Promise<Record<string, SfmBlockTypeInfo>> => {
    const r = await api.get<Record<string, SfmBlockTypeInfo>>(
      `/api/calculations/${calculationId}/sustainable-fm/block-types`,
    );
    return r.data;
  },
  /** The 14 अनुसूची-१ forest types — reference data any signed-in user may read (inline help). */
  getForestTypes: async (): Promise<SfmPrescription[]> => {
    const r = await api.get<SfmPrescription[]>('/api/sustainable-fm/forest-types');
    return r.data;
  },
  getSummary: async (
    calculationId: string,
    variant?: SfmVariant,
  ): Promise<SfmSummaryResponse> => {
    const r = await api.get<SfmSummaryResponse>(
      `/api/calculations/${calculationId}/sustainable-fm/summary`,
      { params: variant ? { variant } : undefined },
    );
    return r.data;
  },
  getBlocks: async (
    calculationId: string,
    variant?: SfmVariant,
  ): Promise<SfmBlocksResponse> => {
    const r = await api.get<SfmBlocksResponse>(
      `/api/calculations/${calculationId}/sustainable-fm/blocks`,
      { params: variant ? { variant } : undefined },
    );
    return r.data;
  },
  getNarration: async (
    calculationId: string,
    variant?: SfmVariant,
  ): Promise<SfmNarrationBlock> => {
    const r = await api.get<SfmNarrationBlock>(
      `/api/calculations/${calculationId}/sustainable-fm/narration`,
      { params: variant ? { variant } : undefined },
    );
    return r.data;
  },
  compareSfm: async (calculationId: string): Promise<SfmCompareResponse> => {
    const r = await api.get<SfmCompareResponse>(
      `/api/calculations/${calculationId}/sustainable-fm/compare`,
    );
    return r.data;
  },
  patchBlock: async (
    calculationId: string,
    blockName: string,
    patch: SfmBlockPatch,
  ): Promise<SfmPatchBlockResponse> => {
    const r = await api.patch<SfmPatchBlockResponse>(
      `/api/calculations/${calculationId}/sustainable-fm/blocks/${encodeURIComponent(blockName)}`,
      patch,
    );
    return r.data;
  },
  getParams: async (calculationId: string): Promise<SfmParamsResponse> => {
    const r = await api.get<SfmParamsResponse>(
      `/api/calculations/${calculationId}/sustainable-fm-params`,
    );
    return r.data;
  },
  patchParams: async (
    calculationId: string,
    partial: Record<string, unknown>,
  ): Promise<SfmParamsResponse> => {
    const r = await api.patch<SfmParamsResponse>(
      `/api/calculations/${calculationId}/sustainable-fm-params`,
      partial,
    );
    return r.data;
  },
  // ── P11 — slope-class digitizing aid (nothing here is authoritative) ──
  slopeClassPolygons: async (
    calculationId: string,
    refresh = false,
  ): Promise<SfmSlopeClassFC> => {
    const r = await api.get<SfmSlopeClassFC>(
      `/api/calculations/${calculationId}/sustainable-fm/slope-class-polygons`,
      { params: refresh ? { refresh: true } : undefined },
    );
    return r.data;
  },
  draftProtectionSubarea: async (
    calculationId: string,
    minBand: number,
  ): Promise<SfmDraftProtectionResponse> => {
    const r = await api.post<SfmDraftProtectionResponse>(
      `/api/calculations/${calculationId}/sustainable-fm/draft-protection-subarea`,
      { min_band: minBand },
    );
    return r.data;
  },
  slopeProfile: async (
    calculationId: string,
    geometry: Record<string, unknown>,
  ): Promise<SfmSlopeProfile> => {
    const r = await api.post<SfmSlopeProfile>(
      `/api/calculations/${calculationId}/sustainable-fm/slope-profile`,
      { geometry },
    );
    return r.data;
  },
};

export interface SfmVariableRow {
  key: string;
  label_ne: string;
  label_en: string;
  var_type?: string;
  sub_group?: string;
  registered?: boolean;
}
export interface SfmVariableGroups {
  calculation_id: string;
  groups: {
    id: string;
    label_ne: string;
    label_en: string;
    variables: SfmVariableRow[];
  }[];
}

/** Every OP variable the SFM tab surfaces, grouped/ordered as it reads (P8). */
export const sfmVariablesApi = {
  get: async (calculationId: string): Promise<SfmVariableGroups> => {
    const r = await api.get<SfmVariableGroups>(
      `/api/calculations/${calculationId}/sustainable-fm/variables`,
    );
    return r.data;
  },
};

/** ParamsApi<SfmParamPatch> adapter for `useResolvedParams` (SfmParamsPanel). */
export const sfmParamsApi = {
  get: (calculationId: string) => sfmApi.getParams(calculationId),
  patch: (calculationId: string, partial: SfmParamPatch) =>
    sfmApi.patchParams(calculationId, partial),
  reset: async (calculationId: string): Promise<SfmParamsResponse> => {
    const r = await api.delete<SfmParamsResponse>(
      `/api/calculations/${calculationId}/sustainable-fm-params`,
    );
    return r.data;
  },
};

// ── SFM admin: the अनुसूची-१ prescriptions + org-wide parameter profiles ──
export interface SfmYieldStep {
  gs_per_ha_min: number | null;
  gs_per_ha_max: number | null;
  pct: number;
}
export interface SfmBranch {
  method:
    | 'selection_felling_cycle'
    | 'shelterwood_periodic_block'
    | 'stem_count'
    | 'area_coupe';
  system_ne: string;
  system_en: string;
  felling_cycle_years: number | null;
  regeneration_period_years: number | null;
  rotation_years: number | number[] | null;
  regen_method_ne: string;
  regen_method_en: string;
  mother_trees_per_ha: number[] | null;
  yield_rules: {
    basis: 'growing_stock_pct_ge40' | 'stem_count' | 'area_volume' | 'none';
    steps: SfmYieldStep[];
    target_stems_per_ha: number[] | null;
    note_ne: string;
    note_en: string;
  };
  note_ne: string;
  note_en: string;
}
export interface SfmPrescription {
  type_no: number;
  name_ne: string;
  name_en: string;
  species_groups: string[];
  zone_triggers: string[];
  slope_band: number | null;
  origin: 'natural' | 'plantation' | null;
  orientation: string;
  branches: Record<string, SfmBranch>;
  notes_ne: string | null;
  notes_en: string | null;
  is_active: boolean;
  sort_order: number;
}

export const sfmPrescriptionApi = {
  list: async (): Promise<SfmPrescription[]> => {
    const r = await api.get<SfmPrescription[]>('/api/admin/sfm-prescriptions');
    return r.data;
  },
  get: async (typeNo: number): Promise<SfmPrescription> => {
    const r = await api.get<SfmPrescription>(`/api/admin/sfm-prescriptions/${typeNo}`);
    return r.data;
  },
  put: async (
    typeNo: number,
    body: Omit<SfmPrescription, 'type_no'>,
  ): Promise<SfmPrescription> => {
    const r = await api.put<SfmPrescription>(
      `/api/admin/sfm-prescriptions/${typeNo}`,
      body,
    );
    return r.data;
  },
};

export interface SfmProfile {
  key: string;
  label_ne: string;
  label_en: string;
  physiography_hint: string | null;
  params: SfmParamPatch;
  is_active: boolean;
  sort_order: number;
}

export const sfmProfileApi = {
  list: async (): Promise<SfmProfile[]> => {
    const r = await api.get<SfmProfile[]>('/api/admin/sfm-profiles');
    return r.data;
  },
  get: async (key: string): Promise<SfmProfile> => {
    const r = await api.get<SfmProfile>(
      `/api/admin/sfm-profiles/${encodeURIComponent(key)}`,
    );
    return r.data;
  },
  upsert: async (
    key: string,
    body: Omit<SfmProfile, 'key'>,
  ): Promise<SfmProfile> => {
    const r = await api.put<SfmProfile>(
      `/api/admin/sfm-profiles/${encodeURIComponent(key)}`,
      body,
    );
    return r.data;
  },
  remove: async (key: string): Promise<void> => {
    await api.delete(`/api/admin/sfm-profiles/${encodeURIComponent(key)}`);
  },
};

// ── Cost-Benefit Analysis (CBA_MODULE_PLAN.md P4) ────────────────────────────
// Decimal-backed fields arrive as strings over the wire (Pydantic v2); the
// editors coerce with Number(). `null` where the backend column is nullable.

export interface CbaScenarioListItem {
  id: string;
  name: string;
  is_base_scenario: boolean;
  status: string;
  discount_rate: string;
  cost_count: number;
  benefit_count: number;
  has_result: boolean;
  npv: string | null;
  irr: string | null;
  benefit_cost_ratio: string | null;
  payback_period_years: string | null;
  created_at: string;
}

export interface CbaCostItem {
  id: string;
  cba_id: string;
  category: string;
  description: string;
  year_from: number;
  year_to: number;
  amount_per_year: string;
  is_recurring: boolean;
  total_amount: string | null;
  source_link: string | null;
  notes: string | null;
  display_order: number;
  created_at: string;
  updated_at: string;
}

export interface CbaBenefitItem extends Omit<CbaCostItem, 'category'> {
  source: string;
  quantity: string | null;
  unit_price: string | null;
}

export interface CbaCashFlowRow {
  year: number;
  cost: number;
  benefit: number;
  net: number;
}

export interface CbaResult {
  npv: string | null;
  irr: string | null;
  benefit_cost_ratio: string | null;
  payback_period_years: string | null;
  total_cost_pv: string | null;
  total_benefit_pv: string | null;
  cash_flow_data: CbaCashFlowRow[] | null;
  computed_at: string | null;
}

export interface CbaScenario {
  id: string;
  calculation_id: string;
  name: string;
  description: string | null;
  discount_rate: string;
  time_horizon_years: number;
  irr_start_year: number;
  currency: string;
  default_rates: Record<string, number>;
  is_base_scenario: boolean;
  status: string;
  cost_items: CbaCostItem[];
  benefit_items: CbaBenefitItem[];
  result: CbaResult | null;
  created_at: string;
  updated_at: string;
}

export interface CbaScenarioCreate {
  name?: string;
  description?: string;
  discount_rate?: number;
  time_horizon_years?: number;
  irr_start_year?: number;
  currency?: string;
  default_rates?: Record<string, number>;
}

export type CbaScenarioUpdate = CbaScenarioCreate & { status?: string };

export interface CbaCostItemInput {
  category?: string;
  description?: string;
  year_from?: number;
  year_to?: number;
  amount_per_year?: number;
  is_recurring?: boolean;
  source_link?: string | null;
  notes?: string;
  display_order?: number;
}

export interface CbaBenefitItemInput extends Omit<CbaCostItemInput, 'category'> {
  source?: string;
  quantity?: number;
  unit_price?: number;
}

export interface CbaCompareItem {
  cba_id: string;
  name: string;
  npv: string | null;
  irr: string | null;
  benefit_cost_ratio: string | null;
  payback_period_years: string | null;
  total_cost: string | null;
  total_benefit: string | null;
  cost_count: number;
  benefit_count: number;
}

export interface CbaRepopulateResult {
  updated: { costs: number; benefits: number };
  inserted: { costs: number; benefits: number };
  deleted: { costs: number; benefits: number };
  message: string;
  /** e.g. a manual row named like an activity that is now also added automatically (never deleted) */
  warnings?: string[];
}

export interface CbaBreakdownRow {
  label: string;
  amount: number;
  percent: number;
}

export interface CbaExportData {
  base_npv: string | null;
  base_irr: number | null;
  base_bc_ratio: string | null;
  base_payback: string | null;
  summary_table: Array<Record<string, string | number | null>>;
  cash_flow_table: CbaCashFlowRow[];
  cost_breakdown: CbaBreakdownRow[];
  benefit_breakdown: CbaBreakdownRow[];
}

export const cbaApi = {
  listScenarios: async (calcId: string): Promise<CbaScenarioListItem[]> => {
    const r = await api.get<CbaScenarioListItem[]>(`/api/calculations/${calcId}/cba`);
    return r.data;
  },
  createScenario: async (calcId: string, body: CbaScenarioCreate): Promise<CbaScenario> => {
    const r = await api.post<CbaScenario>(`/api/calculations/${calcId}/cba`, body);
    return r.data;
  },
  getScenario: async (calcId: string, cbaId: string): Promise<CbaScenario> => {
    const r = await api.get<CbaScenario>(`/api/calculations/${calcId}/cba/${cbaId}`);
    return r.data;
  },
  updateScenario: async (
    calcId: string,
    cbaId: string,
    body: CbaScenarioUpdate,
  ): Promise<CbaScenario> => {
    const r = await api.put<CbaScenario>(`/api/calculations/${calcId}/cba/${cbaId}`, body);
    return r.data;
  },
  deleteScenario: async (calcId: string, cbaId: string): Promise<void> => {
    await api.delete(`/api/calculations/${calcId}/cba/${cbaId}`);
  },
  setBase: async (calcId: string, cbaId: string): Promise<CbaScenarioListItem[]> => {
    const r = await api.post<CbaScenarioListItem[]>(
      `/api/calculations/${calcId}/cba/${cbaId}/set-base`,
    );
    return r.data;
  },
  clone: async (calcId: string, cbaId: string, name?: string): Promise<CbaScenario> => {
    const r = await api.post<CbaScenario>(`/api/calculations/${calcId}/cba/${cbaId}/clone`, {
      name,
    });
    return r.data;
  },
  listCosts: async (cbaId: string): Promise<CbaCostItem[]> => {
    const r = await api.get<CbaCostItem[]>(`/api/cba/${cbaId}/costs`);
    return r.data;
  },
  createCost: async (cbaId: string, body: CbaCostItemInput): Promise<CbaCostItem> => {
    const r = await api.post<CbaCostItem>(`/api/cba/${cbaId}/costs`, body);
    return r.data;
  },
  updateCost: async (
    cbaId: string,
    itemId: string,
    body: CbaCostItemInput,
  ): Promise<CbaCostItem> => {
    const r = await api.put<CbaCostItem>(`/api/cba/${cbaId}/costs/${itemId}`, body);
    return r.data;
  },
  deleteCost: async (cbaId: string, itemId: string): Promise<void> => {
    await api.delete(`/api/cba/${cbaId}/costs/${itemId}`);
  },
  listBenefits: async (cbaId: string): Promise<CbaBenefitItem[]> => {
    const r = await api.get<CbaBenefitItem[]>(`/api/cba/${cbaId}/benefits`);
    return r.data;
  },
  createBenefit: async (cbaId: string, body: CbaBenefitItemInput): Promise<CbaBenefitItem> => {
    const r = await api.post<CbaBenefitItem>(`/api/cba/${cbaId}/benefits`, body);
    return r.data;
  },
  updateBenefit: async (
    cbaId: string,
    itemId: string,
    body: CbaBenefitItemInput,
  ): Promise<CbaBenefitItem> => {
    const r = await api.put<CbaBenefitItem>(`/api/cba/${cbaId}/benefits/${itemId}`, body);
    return r.data;
  },
  deleteBenefit: async (cbaId: string, itemId: string): Promise<void> => {
    await api.delete(`/api/cba/${cbaId}/benefits/${itemId}`);
  },
  autoPopulate: async (cbaId: string): Promise<CbaRepopulateResult> => {
    const r = await api.post<CbaRepopulateResult>(`/api/cba/${cbaId}/auto-populate`);
    return r.data;
  },
  compute: async (cbaId: string): Promise<CbaResult> => {
    const r = await api.post<CbaResult>(`/api/cba/${cbaId}/compute`);
    return r.data;
  },
  compare: async (calcId: string, cbaIds: string[]): Promise<CbaCompareItem[]> => {
    const r = await api.post<CbaCompareItem[]>(`/api/calculations/${calcId}/cba/compare`, {
      cba_ids: cbaIds,
    });
    return r.data;
  },
  exportData: async (cbaId: string): Promise<CbaExportData> => {
    const r = await api.get<CbaExportData>(`/api/cba/${cbaId}/export-data`);
    return r.data;
  },
};

// ── CBA org-wide rate profile (CBA_MODULE_PLAN.md P8) ────────────────────────

export interface CbaRatesResponse {
  rates: Record<string, number>;
  defaults: Record<string, number>;
}

export const cbaRateApi = {
  get: async (): Promise<CbaRatesResponse> => {
    const r = await api.get<CbaRatesResponse>('/api/admin/cba-rates');
    return r.data;
  },
  put: async (rates: Record<string, number | null>): Promise<CbaRatesResponse> => {
    const r = await api.put<CbaRatesResponse>('/api/admin/cba-rates', { rates });
    return r.data;
  },
};

// ── workflow readiness (WORKSPACE_FLOW_NAV_PLAN P3) ───────────────────────
export interface WorkflowStepState {
  done: boolean;
  status: 'available' | 'partial' | 'unavailable';
  reason_en: string;
  reason_ne: string;
  hint_en: string;
  hint_ne: string;
}

export interface WorkflowReadiness {
  geometry_version: number | null;
  map_finished: boolean;
  steps: Record<string, WorkflowStepState>;
  done_count: number;
  tracked_count: number;
  non_tracked: string[];
}

/**
 * Per-step completion for the guided workflow. Reports only — the caller must
 * never treat a step being incomplete as a reason to hide or refuse it.
 */
export const workflowApi = {
  readiness: async (calculationId: string): Promise<WorkflowReadiness> => {
    const r = await api.get<WorkflowReadiness>(
      `/api/calculations/${calculationId}/workflow-readiness`,
    );
    return r.data;
  },
};

// ---------------------------------------------------------------------------
// P8 - unit size review, and the field-inventory note that names the units an
// unsampled unit otherwise disappears from. Read-only on the server.
// ---------------------------------------------------------------------------

/** Which band a unit falls in. Only `sub_mmu` may ever authorise a merge. */
export type UnitBand = "sub_mmu" | "review" | "ok";

/** What the review proposes for a unit. Never an action - the user decides. */
export type UnitReviewAction = "merge_offer" | "flag_only" | "none";

export interface UnitSizeCandidate {
  block_name: string;
  /** The unit's row id. merge-features takes feature_ids, not names. */
  id: string | null;
  /** Derived server-side from the unit's own row, so like-with-like is structural. */
  layer_type: string | null;
  area_ha: number;
  band: UnitBand;
  action: UnitReviewAction;
  neighbour: string | null;
  neighbour_id: string | null;
  neighbour_area_ha?: number | null;
  unmergeable: boolean;
  /** Carries the why in numbers, e.g. "below the 1 ha MMU: too small to hold 5 x 500 m2 plots". */
  reason: string;
}

export interface UnitSizeSummary {
  total: number;
  sub_mmu: number;
  review: number;
  ok: number;
  merge_offers: number;
  unmergeable: number;
}

export interface UnitSizeReviewResponse {
  calculation_id: string;
  boundary_area_ha: number;
  mmu_ha: number;
  review_pct: number;
  summary: UnitSizeSummary;
  candidates: UnitSizeCandidate[];
  read_only: boolean;
}

export interface UnsampledUnitsResponse {
  field_inventory_id: string;
  calculation_id: string;
  total_units: number;
  summarised_units: number;
  review_pct: number;
  unsampled_units: UnitSizeCandidate[];
  summary: UnitSizeSummary;
  read_only: boolean;
}

/** Tier 1 of P8: classify every leaf unit by size BEFORE sampling, and propose a
 *  merge for the sub-MMU ones. Purely a read: the server changes nothing, and a
 *  merge is applied by the user through the existing geometry path. */
export async function getUnitSizeReview(
  calculationId: string,
  reviewPct?: number
): Promise<UnitSizeReviewResponse> {
  const response = await api.get(
    `/api/v1/calculations/${calculationId}/unit-size-review`,
    { params: reviewPct === undefined ? undefined : { review_pct: reviewPct } }
  );
  return response.data;
}

/** The field-inventory side of the same story: the units that received no sample
 *  point and therefore have no summary row at all. Naming them is what turns the
 *  21-of-24 count into something explained. */
export async function getUnsampledUnits(
  fieldInventoryId: string,
  reviewPct?: number
): Promise<UnsampledUnitsResponse> {
  const response = await api.get(
    `/api/field-inventory/${fieldInventoryId}/unsampled-units`,
    { params: reviewPct === undefined ? undefined : { review_pct: reviewPct } }
  );
  return response.data;
}


/**
 * Apply a proposed merge from the P8 unit-size review.
 *
 * Deliberately the EXISTING geometry endpoint, not a second merge path: it unions the
 * features, makes them valid, deletes the source rows and stores the merged piece,
 * and `structure_write` then bumps the geometry clock, sets the stale flags, re-syncs
 * tree/plot unit assignments and invalidates the render and SFM caches. A parallel
 * implementation would be a second way to invalidate a forest.
 *
 * `layer_type` is supplied by the caller but originates from the server's per-unit
 * `layer_of()` classification, so a sub-compartment cannot be merged into a block.
 */
export async function mergeFeatures(
  calculationId: string,
  layerType: string,
  featureIds: [string, string]
): Promise<unknown> {
  const response = await api.post(
    `/api/v1/calculations/${calculationId}/geometry/merge-features`,
    { layer_type: layerType, feature_ids: featureIds }
  );
  return response.data;
}


/** "Update attribute": the attribute components a forest has (raster analysis, inventory analysis, SFM, hazard & erosion). */
export interface AttributeComponent {
  key: 'raster' | 'classification' | 'inventory' | 'sfm' | 'hazard';
  label_en: string;
  label_ne: string;
  state: 'up_to_date' | 'out_of_date' | 'never' | 'unavailable';
  available: boolean;
  can_run: boolean;
  reason_en: string;
  reason_ne: string;
  open_step: string;
}
export interface AttributeRunResult {
  ok: boolean;
  skipped?: boolean;
  error?: string;
  reason_en?: string;
  reason_ne?: string;
}
export const attributeComponentsApi = {
  list: async (calculationId: string): Promise<AttributeComponent[]> =>
    (await api.get(`/api/calculations/${calculationId}/attribute-components`)).data.components,
  run: async (
    calculationId: string,
    keys: string[],
  ): Promise<{ results: Record<string, AttributeRunResult>; components: AttributeComponent[] }> =>
    (await api.post(`/api/calculations/${calculationId}/attribute-components/run`, { keys }, { timeout: 600000 })).data,
};


export interface NationalCodeMatchCandidate {
  province_code: string;
  division_code: string;
  division_name: string;
  district: string;
  local_no: string;
  local_name: string;
}
export interface NationalCodeMatch {
  province_code: string | null;
  division_code: string | null;
  local_no: string | null;
  local_name: string | null;
  division_name: string | null;
  district: string | null;
  confidence: 'exact' | 'close' | 'ambiguous' | 'none';
  candidates: NationalCodeMatchCandidate[];
}

/** Schedule 11 (national database code of a community forest user group): the reference table and an advisory check. */
export const nationalCodeApi = {
  reference: async (): Promise<{ source: string; provinces: import('../lib/cfNationalCode').NationalCodeProvince[] }> =>
    (await api.get('/api/calculations/forest-metadata/national-code-reference')).data,
  /** Preselect the code's parts from the forest's Province and Municipality. */
  match: async (
    calculationId: string,
    hints: { province: string; palika: string; district: string },
  ): Promise<NationalCodeMatch> =>
    (await api.get(`/api/calculations/${calculationId}/forest-metadata/national-code-match`, { params: hints })).data,
  check: async (code: string): Promise<{ ok: boolean; parts: Record<string, string> | null; problems: string[] }> =>
    (await api.get('/api/calculations/forest-metadata/national-code-check', { params: { code } })).data,
};

// ── Fire lines (FIRELINE_RIVERBANK_PLAN.md, FL-5) ───────────────────────────────────────────────────────────────
// Every candidate is created automatically; the owner unticks the boundaries that are not fire lines, draws one with a
// width for every segment (PER SIDE, metres), and re-widens one afterwards.
export interface FireLineRow {
  unit_key: string;
  name: string;
  group: 'boundary' | 'road' | 'river';
  highway: string;
  river_name?: string;
  ticked: boolean;
  strip_id: string | null;
  length_m: number;
  area_ha: number;
  edited: boolean;
  centerline?: GeoJSON.LineString | null;
  segment_widths_m?: number[];
}

export interface FireLineDrawn {
  strip_id: string;
  name: string;
  length_m: number;
  area_ha: number;
  segment_widths_m: number[];
  centerline?: GeoJSON.LineString | null;
}

export interface FireLineTotals {
  count: number;
  km: number;
  ha: number;
}

export interface FireLineSummary {
  status: { state: string; [k: string]: unknown };
  rows: FireLineRow[];
  drawn: FireLineDrawn[];
  kind?: 'fire_line' | 'river_bank';
  totals: Partial<Record<'boundary' | 'road' | 'river' | 'drawn', FireLineTotals>>;
  excluded: string[];
  result?: { state: string; [k: string]: unknown };
}

export interface FireLinePreview {
  name: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  parts: number;
  length_m: number;
  area_ha: number;
  segment_widths_m: number[];
  zone_overlap_ha: Record<string, number>;
  warnings: string[];
}

export interface FireLinePlanActivity {
  id: number;
  activity: string;
  program: string;
  unit: string;
  map_kind: string;
}

export interface FireLinePlanResult {
  created: number;
  existing: number;
  skipped_roads: number;
  no_unit: string[];
  strips: number;
}

const stripApi = (path: 'fire-lines' | 'river-banks') => ({
  list: async (calculationId: string): Promise<FireLineSummary> =>
    (await api.get(`/api/calculations/${calculationId}/${path}`)).data,
  decide: async (calculationId: string, changes: Array<{ unit_key: string; included: boolean }>): Promise<FireLineSummary> =>
    (await api.post(`/api/calculations/${calculationId}/${path}/decisions`, { changes })).data,
  regenerate: async (calculationId: string): Promise<FireLineSummary> =>
    (await api.post(`/api/calculations/${calculationId}/${path}/regenerate`, { force: true })).data,
  preview: async (calculationId: string, centerline: GeoJSON.LineString, widths: number | number[]): Promise<FireLinePreview> =>
    (await api.post(`/api/calculations/${calculationId}/${path}/preview`, { centerline, widths_m: widths })).data,
  create: async (
    calculationId: string,
    body: { centerline: GeoJSON.LineString; widths_m: number | number[]; name?: string; client_id?: string },
  ): Promise<{ created: string[]; replayed: boolean; name?: string; area_ha?: number }> =>
    (await api.post(`/api/calculations/${calculationId}/${path}`, body)).data,
  setWidths: async (calculationId: string, stripId: string, widths: number | number[]) =>
    (await api.patch(`/api/calculations/${calculationId}/${path}/${stripId}/widths`, { widths_m: widths })).data,
});

/** The same calls for either kind (`StripApi`); the fire line also has the yearly-plan calls. */
export type StripApi = ReturnType<typeof stripApi>;

export const fireLineApi = {
  ...stripApi('fire-lines'),
  planOptions: async (calculationId: string): Promise<{ activities: FireLinePlanActivity[] }> =>
    (await api.get(`/api/calculations/${calculationId}/fire-lines/plan-options`)).data,
  plan: async (
    calculationId: string,
    body: { potential_activity_id: number; strip_ids?: string[]; include_roads?: boolean },
  ): Promise<FireLinePlanResult> => (await api.post(`/api/calculations/${calculationId}/fire-lines/plan`, body)).data,
};

export const riverBankApi = stripApi('river-banks');

// ─── NTFP inventory (the optional page in the Advanced band) ─────────────────────────────────────────────────────────────────────
export interface NtfpPrice { npr_per_unit: number; unit: string; basis: 'schedule7' | 'relative' | 'part_median'; estimated: boolean; note: string }
export interface NtfpPriceLine { group: string; group_ne: string; group_en: string; price: number; unit: string; basis: 'schedule7' | 'relative' | 'part_median'; estimated: boolean; basis_note: string }
export type NtfpCardStatus = 'documented' | 'provisional' | 'expert_confirmed';
export type NtfpValueStatus = 'documented' | 'derived' | 'provisional' | 'expert_confirmed';
export interface NtfpFactValue {
  id: string; value_num: number | null; value_num2: number | null; value_text: string | null; unit: string | null; calendar: 'AD' | 'BS' | null;
  source_key: string; source_title: string | null; source_year: string | null; source_url: string | null; source_tier: number | null;
  locator: string | null; status: NtfpValueStatus; chosen: boolean; note: string | null; reviewed_by: string | null; reviewed_at: string | null;
}
export interface NtfpFact { field: string; part_group: string | null; chosen: NtfpFactValue | null; others: NtfpFactValue[]; conflict: boolean }
export interface NtfpCardSource { title: string; publisher: string | null; year: string | null; url: string | null; tier: number; read_status: 'read' | 'lead'; licence: string | null }
export interface NtfpCard {
  species_key: string; nepali_name: string; scientific_name: string | null; aliases: string[]; card_status: NtfpCardStatus | null; has_method_card: boolean;
  growth_class: string | null; part_groups: string[]; facts: NtfpFact[]; sources: Record<string, NtfpCardSource>;
}
export interface NtfpListedValue extends NtfpFactValue { field: string; part_group: string | null }
export interface NtfpAah { pct_min: number; pct_max: number; source_key: string; source_title: string | null; locator: string | null; status: NtfpValueStatus; note: string | null }
export interface NtfpSpecies {
  card_status: NtfpCardStatus | null;
  aah: NtfpListedValue[];
  season: NtfpListedValue[];
  species_key: string;
  scientific_name: string | null;
  aliases: string[];
  nepali_name: string;
  priority_serial: number | null;
  has_method_card: boolean;
  growth_class: string | null;
  life_form_ne: string | null;
  part_ne: string | null;
  part_groups: string[];
  sampling_method: 'destructive' | 'semi_destructive' | 'non_destructive' | null;
  plot_min_sqm: number | null;
  plot_max_sqm: number | null;
  altitude_min_m: number | null;
  altitude_max_m: number | null;
  conversion_factor: number | null;
  prices: NtfpPriceLine[];
  default_plot_sqm: number | null;
  default_intensity_pct: number | null;
}
export interface NtfpSpeciesChoice { species_key: string; plot_sqm?: number | null; intensity_pct?: number | null; growth_class?: string | null }
export interface NtfpDesignRequest { species: NtfpSpeciesChoice[]; plot_shape: 'square' | 'circular'; seed?: number | null; min_plots?: number }
export interface NtfpPlot { plot_number: number; stratum: string; transect: number; longitude: number; latitude: number; species_keys: string[] }
export interface NtfpDesignSpecies {
  species_key: string; label: string; growth_class: string; plot_sqm: number; intensity_pct: number;
  plots: number; intensity_achieved_pct: number; plots_by_stratum: Record<string, number>;
  /** the intensity asked is under the guideline's lowest figure for this growth form and forest size */
  below_guideline?: boolean;
}
export interface NtfpDesignStratum { name: string; area_ha: number; plots_wanted: number; plots_laid: number; spacing_m: number; warnings: string[] }
export interface NtfpDesign {
  id?: string; plot_shape: string; seed: number; min_plots: number; forest_area_ha?: number;
  species: NtfpDesignSpecies[]; strata: NtfpDesignStratum[]; plots: NtfpPlot[]; warnings: string[];
  transects: { type: 'FeatureCollection'; features: any[] }; layout: any; created_at?: string | null;
}
export interface NtfpFinding { severity: 'error' | 'warning'; sheet: string; row: number | null; column: string | null; code: string; message: string; species_key?: string }
export interface NtfpUploadResult { ok: boolean; findings: NtfpFinding[]; observations_written: number; weights_written: number }
/** A write that may be sent again later (from the offline outbox): its key lets the server recognise a repeat. */
export interface NtfpWriteOptions { idempotencyKey?: string }

// ── reference-data layers of the map workspace (rivers, roads, wards ...): read-only shared data cut to the forest's neighbourhood ──
export interface ReferenceLayerInfo {
  key: string; label_en: string; label_ne: string; geometry: 'line' | 'polygon' | 'point'; style: Record<string, unknown>; group: string;
  source: string; licence: string | null; licence_note: string | null; max_features: number; default_buffer_m: number; max_buffer_m: number;
}
export interface ReferenceFeatureCollection {
  type: 'FeatureCollection'; features: any[]; key: string; count: number; truncated: boolean; buffer_m: number; max_features: number;
}
export const referenceLayersApi = {
  catalog: async (calculationId: string): Promise<{ layers: ReferenceLayerInfo[] }> => (await api.get(`/api/calculations/${calculationId}/reference-layers`)).data,
  features: async (calculationId: string, key: string, bufferM?: number): Promise<ReferenceFeatureCollection> =>
    (await api.get(`/api/calculations/${calculationId}/reference-layers/${encodeURIComponent(key)}`, { params: bufferM == null ? undefined : { buffer_m: bufferM } })).data,
};
const writeHeaders = (opts?: NtfpWriteOptions) => (opts?.idempotencyKey ? { headers: { 'Idempotency-Key': opts.idempotencyKey } } : undefined);
export type NtfpEntryMode = 'upload' | 'manual';
export type NtfpVerdict = 'at' | 'far' | 'uncertain';
export interface NtfpPresence { latitude: number; longitude: number; accuracy_m: number | null; distance_m: number; verdict: NtfpVerdict; checked_at: string; near_m: number }
export interface NtfpPhoto { id: string; file_name: string; content_type: string; size_bytes: number; caption: string | null; latitude: number | null; longitude: number | null; created_at: string | null }
export interface NtfpPlotExtras { plot_number: number; presence: NtfpPresence | null; photos: NtfpPhoto[] }
export interface NtfpPlotBadge { verdict: NtfpVerdict | null; photos: number }
export interface NtfpWeightRecord { sample_no: number; part_group: string | null; fresh_weight_g: number; dry_weight_g: number | null; notes: string | null }
export interface NtfpObservationRecord {
  plot_number: number; species_key: string; visit_date: string | null; count_total: number; count_mature: number | null; count_small: number | null;
  clumps: number | null; tillers: number | null; notes: string | null; source: NtfpEntryMode; weights: NtfpWeightRecord[];
}
export interface NtfpRecords { pairs_assigned: number; pairs_recorded: number; weights: number; observations: NtfpObservationRecord[]; mode?: NtfpEntryMode | null }
/** One species of one plot as typed on the map; an entry with nothing filled in clears that species' record. */
export interface NtfpSpeciesEntry {
  species_key: string; visit_date?: string | null; count_total?: number | null; count_mature?: number | null; count_small?: number | null;
  clumps?: number | null; tillers?: number | null; notes?: string | null;
  weights: { sample_no?: number | null; part_group?: string | null; fresh_weight_g?: number | null; dry_weight_g?: number | null; notes?: string | null }[];
}
export interface NtfpPartResult {
  part_group: string | null; samples: number; dry_pairs: number; mean_fresh_g: number | null; scale_factor: number; mean_whole_fresh_g: number | null; conversion_factor: number | null;
  conversion_factor_reference: number | null; harvest_fraction_pct: number | null; yield_fresh_kg_ha: number | null; yield_dry_kg_ha: number | null;
  yield_precision_pct: number | null; stock_fresh_kg: number | null; stock_dry_kg: number | null; warnings: string[]; price?: NtfpPrice;
}
export interface NtfpSpeciesResult {
  species_key: string; label: string; nepali_name: string; scientific_name: string | null; plot_sqm: number;
  plots_assigned: number; plots_surveyed: number; plots_present: number; frequency_pct: number | null; count_total: number;
  density_per_ha: number | null; density_precision_pct: number | null; coverage_pct: number | null;
  relative_frequency_pct: number | null; relative_density_pct: number | null; ivi: number | null; ivi_rank: number | null;
  parts: NtfpPartResult[]; warnings: string[];
}
export interface NtfpResults {
  forest_area_ha: number; plots_in_design: number; ivi_parts: number; species: NtfpSpeciesResult[]; notes: string[];
  survey: { pairs_assigned: number; pairs_recorded: number; weights: number };
}

export const ntfpApi = {
  species: async (calculationId: string, params?: { q?: string; with_card?: boolean }): Promise<{ forest_area_ha: number | null; species: NtfpSpecies[] }> =>
    (await api.get(`/api/calculations/${calculationId}/ntfp/species`, { params })).data,
  getDesign: async (calculationId: string): Promise<{ design: NtfpDesign | null }> =>
    (await api.get(`/api/calculations/${calculationId}/ntfp/design`)).data,
  previewDesign: async (calculationId: string, body: NtfpDesignRequest): Promise<NtfpDesign> =>
    (await api.post(`/api/calculations/${calculationId}/ntfp/design/preview`, body)).data,
  createDesign: async (calculationId: string, body: NtfpDesignRequest): Promise<NtfpDesign> =>
    (await api.post(`/api/calculations/${calculationId}/ntfp/design`, body)).data,
  deleteDesign: async (calculationId: string): Promise<{ deleted: boolean }> =>
    (await api.delete(`/api/calculations/${calculationId}/ntfp/design`)).data,
  formPath: (calculationId: string): string => `/api/calculations/${calculationId}/ntfp/form`,
  uploadForm: async (calculationId: string, file: File): Promise<NtfpUploadResult> => {
    const form = new FormData();
    form.append('file', file);
    return (await api.post(`/api/calculations/${calculationId}/ntfp/upload`, form)).data;
  },
  savePlot: async (calculationId: string, plotNumber: number, entries: NtfpSpeciesEntry[], opts?: NtfpWriteOptions): Promise<NtfpUploadResult & { cleared: number }> =>
    (await api.put(`/api/calculations/${calculationId}/ntfp/plots/${plotNumber}/observations`, { entries }, writeHeaders(opts))).data,
  checkPresence: async (calculationId: string, plotNumber: number, pos: { latitude: number; longitude: number; accuracy_m: number | null }, opts?: NtfpWriteOptions): Promise<NtfpPresence> =>
    (await api.post(`/api/calculations/${calculationId}/ntfp/plots/${plotNumber}/presence`, pos, writeHeaders(opts))).data,
  plotExtras: async (calculationId: string, plotNumber: number): Promise<NtfpPlotExtras> =>
    (await api.get(`/api/calculations/${calculationId}/ntfp/plots/${plotNumber}/extras`)).data,
  allExtras: async (calculationId: string): Promise<{ plots: Record<string, NtfpPlotBadge> }> =>
    (await api.get(`/api/calculations/${calculationId}/ntfp/plots/extras`)).data,
  uploadPhoto: async (calculationId: string, plotNumber: number, file: Blob, fileName: string, pos?: { latitude: number; longitude: number } | null, opts?: NtfpWriteOptions): Promise<NtfpPhoto> => {
    const form = new FormData();
    form.append('file', file, fileName);
    if (pos) { form.append('latitude', String(pos.latitude)); form.append('longitude', String(pos.longitude)); }
    return (await api.post(`/api/calculations/${calculationId}/ntfp/plots/${plotNumber}/photos`, form, writeHeaders(opts))).data;
  },
  photoBlob: async (calculationId: string, photoId: string): Promise<Blob> =>
    (await api.get(`/api/calculations/${calculationId}/ntfp/photos/${photoId}`, { responseType: 'blob' })).data,
  deletePhoto: async (calculationId: string, photoId: string): Promise<{ deleted: boolean }> =>
    (await api.delete(`/api/calculations/${calculationId}/ntfp/photos/${photoId}`)).data,
  records: async (calculationId: string): Promise<NtfpRecords> => (await api.get(`/api/calculations/${calculationId}/ntfp/observations`)).data,
  deleteRecords: async (calculationId: string): Promise<{ deleted: number }> =>
    (await api.delete(`/api/calculations/${calculationId}/ntfp/observations`)).data,
  results: async (calculationId: string): Promise<NtfpResults> => (await api.get(`/api/calculations/${calculationId}/ntfp/results`)).data,
  reviewQueue: async (): Promise<{ cards: NtfpReviewCard[] }> => (await api.get('/api/calculations/ntfp-cards/review')).data,
  review: async (rows: NtfpReviewRow[]): Promise<{ cards_confirmed: number; values_written: number; skipped: string[]; remaining: number }> =>
    (await api.post('/api/calculations/ntfp-cards/review', { rows })).data,
  card: async (calculationId: string, speciesKey: string): Promise<NtfpCard> =>
    (await api.get(`/api/calculations/${calculationId}/ntfp/profiles/${encodeURIComponent(speciesKey)}`)).data,
};

export interface NtfpReviewCard {
  species_key: string; nepali_name: string; scientific_name: string | null; part_ne: string | null; part_groups: string[];
  growth_class: string | null; growth_how: string; growth_guessed: boolean; sampling_method: string | null;
  plot_min_sqm: number | null; plot_max_sqm: number | null; n_individuals_min: number | null; n_individuals_max: number | null;
  maturity: string | null; conversion_factor: number | null; sample_fraction_pct: number | null; aah_pct_min: number | null; aah_pct_max: number | null; aah_source_key: string | null;
}
/** The columns a reviewer can correct; a row with only `confirmed` confirms the card as it stands. */
export type NtfpReviewEdits = Partial<Pick<NtfpReviewCard, 'growth_class' | 'sampling_method' | 'plot_min_sqm' | 'plot_max_sqm' | 'n_individuals_min' | 'n_individuals_max' | 'aah_pct_min' | 'aah_pct_max'>>;
export interface NtfpReviewRow extends NtfpReviewEdits { species_key: string; confirmed: boolean }

export interface NtfpHarvestPlanRow { annual_quantity: number; unit: 'kg' | 'piece'; weight_basis: 'fresh' | 'dry'; price_override: number | null; notes: string | null }
export interface NtfpHarvestRow {
  species_key: string; nepali_name: string; scientific_name: string | null; part_group: string;
  stock_fresh_kg: number | null; stock_dry_kg: number | null; yield_precision_pct: number | null;
  price: { npr_per_unit: number; unit: string; basis: 'schedule7' | 'relative' | 'part_median' | 'owner'; estimated: boolean; note: string } | null;
  plan: NtfpHarvestPlanRow | null; value_npr_per_year: number | null;
  aah?: NtfpAah | null;
}
export interface NtfpHarvestPlan { rows: NtfpHarvestRow[]; totals: { rows_planned: number; kg_per_year: number; value_npr_per_year: number } }
export interface NtfpHarvestSave { species_key: string; part_group: string; annual_quantity: number; unit: 'kg' | 'piece'; weight_basis: 'fresh' | 'dry'; price_override?: number | null; notes?: string | null }
export interface NtfpYearlyLink { created: boolean; line_id: string; quantity: number; kg_planned: number; activity: string }

export const ntfpHarvestApi = {
  get: async (calculationId: string): Promise<NtfpHarvestPlan> => (await api.get(`/api/calculations/${calculationId}/ntfp/harvest-plan`)).data,
  save: async (calculationId: string, rows: NtfpHarvestSave[]): Promise<NtfpHarvestPlan> =>
    (await api.put(`/api/calculations/${calculationId}/ntfp/harvest-plan`, { rows })).data,
  toYearlyPlan: async (calculationId: string): Promise<NtfpYearlyLink> =>
    (await api.post(`/api/calculations/${calculationId}/ntfp/harvest-plan/yearly-plan`)).data,
};
