import type { GeoJSON } from 'geojson';

/** E3 — a per-row attribute-table delete (any builtin or imported layer). */
export interface FeatureDeleteOperation {
  readonly type: 'feature_delete';
  readonly kind: 'feature_delete';
  readonly meta: OperationMeta;
  readonly calcId: string;
  readonly layerType: string;
  readonly featureId: string;
  readonly importLayerId?: number;
  readonly featureIndex?: number;
  /** captured by GET /geometry/feature before the delete (builtin row payload) */
  readonly snapshot: Record<string, unknown>;
}

/**
 * Toolbar Paste — features created in one layer from the feature clipboard.
 * Undo removes exactly the rows this paste created; redo re-creates them.
 *
 * `state.createdIds` is deliberately mutable: a redo re-POSTs the features and
 * the server mints fresh ids, so the op has to remember the *current* ids for
 * the next undo. (The op object itself is frozen shallowly — only this one
 * bookkeeping bag changes.)
 */
export interface FeaturePasteOperation {
  readonly type: 'feature_paste';
  readonly kind: 'feature_paste';
  readonly meta: OperationMeta;
  readonly calcId: string;
  /** 'sub_areas' or `import_<layerId>` — same vocabulary as FeatureDeleteOperation. */
  readonly layerType: string;
  /** The features as they were persisted (post-trim), replayed on redo. */
  readonly features: readonly GeoJSON.Feature[];
  /** Per-feature sub-area create bodies (name/category/…) — sub_areas only. */
  readonly payloads?: readonly Record<string, unknown>[];
  readonly importLayerId?: number;
  /** Imported layers: length of the layer before the paste — created rows sit at [baseIndex, baseIndex+n). */
  readonly baseIndex?: number;
  readonly state: { createdIds: string[] };
}

/**
 * P3.5 — an attribute-table edit to a builtin unit / sub-area row (name,
 * category, per-feature colour / opacity). `previousPayload` / `newPayload` are
 * the exact bodies handed to the layer's `dataSource.update`, so undo / redo is
 * just a re-PATCH of the other one.
 */
export interface AttributeEditOperation {
  readonly type: 'attribute_edit';
  readonly kind: 'attribute_edit';
  readonly meta: OperationMeta;
  readonly calcId: string;
  readonly layerId: string;
  readonly featureId: string;
  readonly previousPayload: Record<string, unknown>;
  readonly newPayload: Record<string, unknown>;
  /** Set for an imported-layer feature edit: undo/redo re-PATCHes
   *  `/import-layers/{importLayerId}/features/{featureIndex}` instead of the
   *  builtin `dataSource.update`. `*Payload` is then `{ properties: {...} }`. */
  readonly importLayerId?: number;
  readonly featureIndex?: number;
}

export type GeometryOperation =
  | RenameOperation
  | SplitOperation
  | MergeOperation
  | VertexEditOperation
  | DeleteOperation
  | DuplicateOperation
  | VisibilityOperation
  | LabelsOperation
  | StyleOperation
  | BatchOperation
  | LabelFieldOperation
  | DigitizeAddFeatureOperation
  | DigitizeDeleteFeatureOperation
  | DigitizeDeleteFeatureByIdOperation
  | FeatureDeleteOperation
  | FeaturePasteOperation
  | AttributeEditOperation;

export type OperationKind = 'rename' | 'split' | 'merge' | 'vertex_edit' | 'delete' | 'duplicate' | 'visibility' | 'labels' | 'style' | 'batch' | 'label_field' | 'digitize_add' | 'digitize_delete' | 'digitize_delete_by_id' | 'feature_delete' | 'feature_paste' | 'attribute_edit';

export interface OperationMeta {
  readonly timestamp: number;
  readonly userId: string;
  readonly sessionId?: string;
  readonly label: string;
}

export interface RenameOperation {
  readonly type: 'rename';
  readonly kind: 'rename';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly featureId: string;
  readonly previousName: string;
  readonly newName: string;
}

export interface SplitPiece {
  readonly pieceId: string;
  readonly geometry: GeoJSON.Geometry;
  readonly properties: Record<string, unknown>;
}

export interface SplitOperation {
  readonly type: 'split';
  readonly kind: 'split';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly sourceFeatureId: string;
  readonly sourceGeometry: GeoJSON.Geometry;
  readonly cutGeometry: GeoJSON.LineString;
  readonly pieces: readonly SplitPiece[];
  // ── UE-3.2 undo/redo across layers ──────────────────────────────────────
  readonly calcId?: string;
  /** backend layer_type: 'blocks' | 'compartments' | 'sub_compartments' | 'sub_areas' | 'boundary' | 'imported' */
  readonly layerType?: string;
  readonly importLayerId?: number;
  /** builtin: restorable source row (restore-feature) — blocks/compartments/sub_compartments/sub_areas */
  readonly sourceSnapshot?: Record<string, unknown>;
  /** builtin pieces created by the cut (row ids / sub-area ids) — delete on undo */
  readonly pieceIds?: readonly string[];
  /** boundary-cut pieces stored as NEW blocks — delete on undo (boundary unchanged) */
  readonly boundaryPieceBlockIds?: readonly string[];
  /** imported: original source feature (restore on undo) + its array index */
  readonly sourceFeature?: GeoJSON.Feature;
  readonly sourceFeatureIndex?: number;
  /** imported: piece featureIds created by the cut — delete on undo */
  readonly pieceFeatureIds?: readonly string[];
}

export interface MergeOperation {
  readonly type: 'merge';
  readonly kind: 'merge';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly sourceFeatureIds: readonly string[];
  readonly sourceGeometries: readonly GeoJSON.Geometry[];
  readonly sourceProperties: readonly Record<string, unknown>[];
  readonly mergedFeatureId: string;
  readonly mergedGeometry: GeoJSON.Geometry;
  readonly mergedProperties: Record<string, unknown>;
  // ── UE-3.2 undo/redo across layers ──────────────────────────────────────
  readonly calcId?: string;
  /** backend layer_type: 'blocks' | 'compartments' | 'sub_compartments' | 'sub_areas' | 'imported' */
  readonly layerType?: string;
  readonly importLayerId?: number;
  /** builtin: per-source restorable snapshots (GET /feature before delete) */
  readonly sourceSnapshots?: readonly Record<string, unknown>[];
  /** builtin: id of the merged row to delete on undo */
  readonly mergedRowId?: string;
  /** imported: source features + their indices (restore on undo) */
  readonly sourceFeatures?: readonly GeoJSON.Feature[];
  readonly sourceIndices?: readonly number[];
}

export type VertexEditType = 'drag' | 'add' | 'delete';

export interface VertexEditOperation {
  readonly type: 'vertex_edit';
  readonly kind: 'vertex_edit';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly featureId: string;
  readonly vertexEditType: VertexEditType;
  readonly vertexIndex: number | { ring: number; index: number };
  readonly previousCoordinate: GeoJSON.Position;
  readonly newCoordinate: GeoJSON.Position;
  readonly previousGeometry: GeoJSON.Geometry;
  readonly newGeometry: GeoJSON.Geometry;
  // ── UE-3.2 undo/redo across layers ──────────────────────────────────────
  readonly calcId?: string;
  /** backend layer_type: builtin polygon layers, 'boundary', or 'imported' */
  readonly layerType?: string;
  readonly importLayerId?: number;
  /** imported: array index of the edited feature (mirror restore on undo) */
  readonly featureIndex?: number;
  /** V-2 atomic shared-vertex move: other features rewritten in the SAME
   *  transaction as this one.  undo = per-feature previous geometries, redo =
   *  per-feature post-gesture geometries.  Undo/redo of the edited feature
   *  must also replay every shared partner in one batch (a single-feature
   *  undo would open a gap). */
  readonly sharedMovePartners?: readonly {
    readonly featureId: string;
    readonly previousGeometry: GeoJSON.Geometry;
    readonly newGeometry: GeoJSON.Geometry;
  }[];
}

export interface DeleteOperation {
  readonly type: 'delete';
  readonly kind: 'delete';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly featureId: string;
  readonly deletedFeature: GeoJSON.Feature;
}

export interface DuplicateOperation {
  readonly type: 'duplicate';
  readonly kind: 'duplicate';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly sourceFeatureId: string;
  readonly newFeatureId: string;
  readonly geometry: GeoJSON.Geometry;
  readonly properties: Record<string, unknown>;
}

import type { PathStyleOptions } from '../store/workspaceStore';

export interface VisibilityOperation {
  readonly type: 'visibility';
  readonly kind: 'visibility';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly layerType: 'builtin' | 'imported';
  readonly previousVisible: boolean;
  readonly newVisible: boolean;
}

export interface LabelsOperation {
  readonly type: 'labels';
  readonly kind: 'labels';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly previousVisible: boolean;
  readonly newVisible: boolean;
}

export interface StyleOperation {
  readonly type: 'style';
  readonly kind: 'style';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly previousStyle: PathStyleOptions;
  readonly newStyle: PathStyleOptions;
}

export interface LabelFieldOperation {
  readonly type: 'label_field';
  readonly kind: 'label_field';
  readonly meta: OperationMeta;
  readonly layerId: string;
  readonly previousField: string | null;
  readonly newField: string | null;
}

/** GD: a digitized feature appended to the draft buffer (undo removes it). */
export interface DigitizeAddFeatureOperation {
  readonly type: 'digitize_add';
  readonly kind: 'digitize_add';
  readonly meta: OperationMeta;
  readonly layerId: number;
  readonly feature: GeoJSON.Feature;
}

/** GD: a digitized feature removed from the draft buffer (undo restores it). */
export interface DigitizeDeleteFeatureOperation {
  readonly type: 'digitize_delete';
  readonly kind: 'digitize_delete';
  readonly meta: OperationMeta;
  readonly layerId: number;
  readonly featureId: string;
}

/** GD: selective delete of a specific buffered feature by id (undo restores the exact feature). */
export interface DigitizeDeleteFeatureByIdOperation {
  readonly type: 'digitize_delete_by_id';
  readonly kind: 'digitize_delete_by_id';
  readonly meta: OperationMeta;
  readonly layerId: number;
  readonly featureId: string;
  readonly deletedFeature: GeoJSON.Feature;
}

export interface BatchOperation {
  readonly type: 'batch';
  readonly kind: 'batch';
  readonly meta: OperationMeta;
  readonly operations: readonly GeometryOperation[];
}

export function isRenameOperation(op: GeometryOperation): op is RenameOperation {
  return op.kind === 'rename';
}
export function isSplitOperation(op: GeometryOperation): op is SplitOperation {
  return op.kind === 'split';
}
export function isMergeOperation(op: GeometryOperation): op is MergeOperation {
  return op.kind === 'merge';
}
export function isVertexEditOperation(op: GeometryOperation): op is VertexEditOperation {
  return op.kind === 'vertex_edit';
}
export function isDeleteOperation(op: GeometryOperation): op is DeleteOperation {
  return op.kind === 'delete';
}
export function isDuplicateOperation(op: GeometryOperation): op is DuplicateOperation {
  return op.kind === 'duplicate';
}
export function isVisibilityOperation(op: GeometryOperation): op is VisibilityOperation {
  return op.kind === 'visibility';
}
export function isLabelsOperation(op: GeometryOperation): op is LabelsOperation {
  return op.kind === 'labels';
}
export function isStyleOperation(op: GeometryOperation): op is StyleOperation {
  return op.kind === 'style';
}
export function isBatchOperation(op: GeometryOperation): op is BatchOperation {
  return op.kind === 'batch';
}
export function isLabelFieldOperation(op: GeometryOperation): op is LabelFieldOperation {
  return op.kind === 'label_field';
}
export function isDigitizeAddFeatureOperation(op: GeometryOperation): op is DigitizeAddFeatureOperation {
  return op.kind === 'digitize_add';
}
export function isDigitizeDeleteFeatureOperation(op: GeometryOperation): op is DigitizeDeleteFeatureOperation {
  return op.kind === 'digitize_delete';
}
export function isDigitizeDeleteFeatureByIdOperation(op: GeometryOperation): op is DigitizeDeleteFeatureByIdOperation {
  return op.kind === 'digitize_delete_by_id';
}
export function isFeatureDeleteOperation(op: GeometryOperation): op is FeatureDeleteOperation {
  return op.kind === 'feature_delete';
}
export function isFeaturePasteOperation(op: GeometryOperation): op is FeaturePasteOperation {
  return op.kind === 'feature_paste';
}
export function isAttributeEditOperation(op: GeometryOperation): op is AttributeEditOperation {
  return op.kind === 'attribute_edit';
}

export function getOperationLabel(op: GeometryOperation): string {
  switch (op.kind) {
    case 'rename':
      return `Rename "${op.previousName}" → "${op.newName}"`;
    case 'split':
      return `Split ${op.sourceFeatureId} into ${op.pieces.length} pieces`;
    case 'merge':
      return `Merge ${op.sourceFeatureIds.length} features into 1`;
    case 'vertex_edit':
      return `${capitalize(op.vertexEditType)} vertex on ${op.featureId}`;
    case 'delete':
      return `Delete ${op.featureId}`;
    case 'duplicate':
      return `Duplicate ${op.sourceFeatureId} → ${op.newFeatureId}`;
    case 'visibility':
      return `${op.newVisible ? 'Show' : 'Hide'} layer ${op.layerId}`;
    case 'labels':
      return `${op.newVisible ? 'Show' : 'Hide'} labels on ${op.layerId}`;
    case 'style':
      return `Style layer ${op.layerId}`;
    case 'batch':
      return op.meta.label;
    case 'label_field':
      return `Label ${op.layerId}: ${op.previousField ?? 'none'} → ${op.newField ?? 'none'}`;
    case 'digitize_add':
      return `Draw feature on digitize layer ${op.layerId}`;
    case 'digitize_delete':
      return `Remove feature ${op.featureId} from digitize layer ${op.layerId}`;
    case 'digitize_delete_by_id':
      return `Delete feature ${op.featureId} from digitize layer ${op.layerId}`;
    case 'feature_delete':
      return `Delete ${op.featureId} from ${op.layerType}`;
    case 'feature_paste':
      return op.meta.label;
    case 'attribute_edit':
      return op.meta.label;
  }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function createOperationMeta(
  userId: string,
  label: string,
  sessionId?: string,
): OperationMeta {
  return {
    timestamp: Date.now(),
    userId,
    sessionId,
    label,
  };
}

export type SerializedOperation = ReturnType<typeof serializeOperation>;

export function serializeOperation(op: GeometryOperation): unknown {
  const base = {
    ...op,
    pieces: op.kind === 'split' ? [...(op as SplitOperation).pieces] : undefined,
    pieceIds: op.kind === 'split' && (op as SplitOperation).pieceIds ? [...(op as SplitOperation).pieceIds!] : undefined,
    boundaryPieceBlockIds: op.kind === 'split' && (op as SplitOperation).boundaryPieceBlockIds ? [...(op as SplitOperation).boundaryPieceBlockIds!] : undefined,
    pieceFeatureIds: op.kind === 'split' && (op as SplitOperation).pieceFeatureIds ? [...(op as SplitOperation).pieceFeatureIds!] : undefined,
    sourceFeatureIds: op.kind === 'merge' ? [...(op as MergeOperation).sourceFeatureIds] : undefined,
    sourceGeometries: op.kind === 'merge' ? [...(op as MergeOperation).sourceGeometries] : undefined,
    sourceProperties: op.kind === 'merge' ? [...(op as MergeOperation).sourceProperties] : undefined,
    sourceSnapshots: op.kind === 'merge' && (op as MergeOperation).sourceSnapshots ? [...(op as MergeOperation).sourceSnapshots!] : undefined,
    sourceFeatures: op.kind === 'merge' && (op as MergeOperation).sourceFeatures ? [...(op as MergeOperation).sourceFeatures!] : undefined,
    sourceIndices: op.kind === 'merge' && (op as MergeOperation).sourceIndices ? [...(op as MergeOperation).sourceIndices!] : undefined,
    operations: op.kind === 'batch' ? [...(op as BatchOperation).operations.map(serializeOperation)] : undefined,
  };
  if (op.kind === 'style') {
    return { ...base, previousStyle: { ...(op as StyleOperation).previousStyle }, newStyle: { ...(op as StyleOperation).newStyle } };
  }
  return base;
}

export function deserializeOperation(data: unknown): GeometryOperation {
  return data as GeometryOperation;
}

export interface SplitOperationExtended extends SplitOperation {
  readonly pieceFeatureIds: readonly string[];
  readonly pieceAreasHa: readonly number[];
}

export interface SplitApiResponse {
  readonly success: boolean;
  readonly pieces: readonly GeoJSON.Feature[];
  readonly piece_count: number;
  readonly areas_ha: readonly number[];
  readonly total_area_ha: number;
  readonly error?: string;
}

export interface CutLineValidation {
  readonly isValid: boolean;
  readonly intersectionCount: number;
  readonly pieces: readonly GeoJSON.Feature<GeoJSON.Polygon>[];
  readonly pieceIds: readonly string[];
  readonly pieceAreas: readonly number[];
  readonly error?: string;
}

export interface SplitPreviewResult {
  readonly cutLine: GeoJSON.LineString;
  readonly pieces: readonly GeoJSON.Feature<GeoJSON.Polygon>[];
  readonly isValid: boolean;
  readonly error?: string;
  readonly pieceIds: readonly string[];
  readonly pieceAreas: readonly number[];
}

export interface GeomanModeConfig {
  readonly mode: 'split' | 'draw' | 'drag' | 'rotate' | 'cut' | 'edit' | 'delete' | 'none';
  readonly layerId: string;
  readonly options?: Record<string, unknown>;
}

export interface GeomanCreateEvent {
  readonly layer: L.Layer;
  readonly shape: string;
  readonly latlngs?: L.LatLng[];
}

export interface GeomanEditEvent {
  readonly layer: L.Layer;
  readonly sourceTarget?: L.Layer;
}
