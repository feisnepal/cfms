/**
 * Server calls behind the toolbar Paste — kept out of the UI hook so the undo /
 * redo handlers (`useContextMenuUndoRedo`) can replay exactly the same requests.
 *
 * Everything goes through the shared axios client (`forestApi`), so it inherits
 * the 401-refresh-and-retry and the correlation-id handling.
 *
 * Why sub-areas do not go through `layerRegistry.sub_areas.dataSource.create`:
 * that helper returns `resp.json()` without looking at `resp.ok`, so a server
 * rejection ("entirely within existing sub-areas", "outside the forest
 * boundary", a 423 structure lock) comes back as an ordinary object and the
 * caller believes it succeeded. Paste has to tell "3 pasted, 2 rejected" apart
 * from "5 pasted", so a refusal here is an exception.
 */
import type { GeoJSON } from 'geojson';
import { isAxiosError } from 'axios';
import { forestApi } from '../services/api';
import { flushDigitizeBufferWithRetry } from '../hooks/useDraftSync';

/** A create the server refused — carries the server's own explanation. */
export class PasteRejectedError extends Error {
  status: number;
  code?: string;
  messageNp?: string;
  constructor(status: number, message: string, code?: string, messageNp?: string) {
    super(message);
    this.name = 'PasteRejectedError';
    this.status = status;
    this.code = code;
    this.messageNp = messageNp;
  }
}

/** Server response for a created sub-area (only the fields paste reads). */
export interface CreatedSubArea {
  id: string;
  name?: string;
  category?: string;
  geometry: GeoJSON.Geometry;
  area_hectares?: number;
}

/** Body accepted by `POST /calculations/{id}/sub-areas`. */
export interface SubAreaCreateBody {
  name: string;
  category: string;
  geometry: GeoJSON.Geometry;
  is_excluded: boolean;
}

function readRejection(status: number, body: unknown): PasteRejectedError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return new PasteRejectedError(status, detail);
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: unknown; message_np?: unknown; code?: unknown };
    return new PasteRejectedError(
      status,
      typeof d.message === 'string' ? d.message : `Request failed (${status})`,
      typeof d.code === 'string' ? d.code : undefined,
      typeof d.message_np === 'string' ? d.message_np : undefined,
    );
  }
  return new PasteRejectedError(status, `Request failed (${status})`);
}

/** Axios error → PasteRejectedError carrying the server's explanation. */
function asRejection(err: unknown): PasteRejectedError {
  if (err instanceof PasteRejectedError) return err;
  if (isAxiosError(err) && err.response) return readRejection(err.response.status, err.response.data);
  return new PasteRejectedError(500, err instanceof Error ? err.message : 'Request failed');
}

/**
 * Create one sub-area. The endpoint itself clips the geometry to the forest and
 * subtracts every existing sub-area (first created keeps the ground), so what
 * comes back can be smaller than what was sent — callers compare areas to tell
 * the user a paste was trimmed.
 */
export async function createSubAreaFromPaste(
  calcId: string,
  body: SubAreaCreateBody,
): Promise<CreatedSubArea> {
  try {
    return (await forestApi.addSubArea(calcId, body)) as CreatedSubArea;
  } catch (err) {
    throw asRejection(err);
  }
}

/** The layer's current authoritative feature list. */
export async function fetchImportedFeatures(
  calcId: string,
  layerId: number,
): Promise<GeoJSON.Feature[]> {
  try {
    return (await forestApi.getImportedLayerFeatures(calcId, layerId)).features ?? [];
  } catch (err) {
    throw asRejection(err);
  }
}

/** A layer created from the clipboard. */
export interface CreatedLayer {
  id: number;
  name: string;
  featureCount: number;
  geometryTypes: string[];
}

/**
 * Turn the clipboard into a NEW imported layer of purpose `other` (any mix of
 * points, lines and polygons, no topology rules), by uploading it as a GeoJSON
 * file through the ordinary import route.
 *
 * Deliberately NOT the digitize-draft → finalize path: finalizing a purposed
 * digitized layer merges all of its geometries into ONE multi-geometry and keeps
 * only the first feature's attributes, which would silently turn "paste 5
 * features as a layer" into a layer with one. The import route keeps each
 * feature, with its attributes, as its own row.
 */
export async function importClipboardAsLayer(
  calcId: string,
  features: readonly GeoJSON.Feature[],
  name: string,
): Promise<CreatedLayer> {
  const collection: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [...features] };
  const file = new File([JSON.stringify(collection)], 'pasted-features.geojson', { type: 'application/geo+json' });
  try {
    const res = await forestApi.importWorkspaceLayer(calcId, file, { purpose: 'other', customName: name });
    return {
      id: res.id,
      name: res.name || name,
      featureCount: res.feature_count ?? features.length,
      geometryTypes: res.geometry_types ?? [],
    };
  } catch (err) {
    throw asRejection(err);
  }
}

/**
 * Append features to an existing layer through the same bulk endpoint the
 * digitizer uses (`mode: 'append'` for a finalized layer, `'draft'` for a
 * draft). The server validates against the layer's purpose, so a geometry the
 * layer must not hold is refused there, not silently accepted.
 */
export async function appendFeaturesToImportedLayer(
  calcId: string,
  layerId: number,
  features: GeoJSON.Feature[],
  mode: 'append' | 'draft',
): Promise<void> {
  try {
    await flushDigitizeBufferWithRetry(calcId, layerId, features, { mode });
  } catch (err) {
    throw new PasteRejectedError(
      (err as { status?: number })?.status ?? 500,
      err instanceof Error ? err.message : 'Append failed',
    );
  }
}
