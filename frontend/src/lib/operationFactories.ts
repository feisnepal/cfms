import type {
  RenameOperation,
  SplitOperation,
  MergeOperation,
  VertexEditOperation,
  DeleteOperation,
  DuplicateOperation,
  VisibilityOperation,
  LabelsOperation,
  LabelFieldOperation,
  StyleOperation,
  BatchOperation,
  SplitPiece,
  VertexEditType,
  GeometryOperation,
  OperationMeta,
  DigitizeAddFeatureOperation,
  DigitizeDeleteFeatureOperation,
  DigitizeDeleteFeatureByIdOperation,
  FeatureDeleteOperation,
  FeaturePasteOperation,
  AttributeEditOperation,
} from './editOperations';
import { createOperationMeta } from './editOperations';
import type { GeoJSON } from 'geojson';
import type { PathStyleOptions } from '../store/workspaceStore';

export function createRenameOperation(
  layerId: string,
  featureId: string,
  previousName: string,
  newName: string,
  userId: string,
  sessionId?: string,
): RenameOperation {
  return {
    type: 'rename',
    kind: 'rename',
    meta: createOperationMeta(userId, `Rename "${previousName}" → "${newName}"`, sessionId),
    layerId,
    featureId,
    previousName,
    newName,
  };
}

export function createSplitOperation(
  layerId: string,
  sourceFeatureId: string,
  sourceGeometry: GeoJSON.Geometry,
  cutGeometry: GeoJSON.LineString,
  pieces: SplitPiece[],
  userId: string,
  sessionId?: string,
  undo?: Partial<Pick<
    SplitOperation,
    'calcId' | 'layerType' | 'importLayerId' | 'sourceSnapshot' | 'pieceIds' | 'boundaryPieceBlockIds' | 'sourceFeature' | 'sourceFeatureIndex' | 'pieceFeatureIds'
  >>,
): SplitOperation {
  return {
    type: 'split',
    kind: 'split',
    meta: createOperationMeta(
      userId,
      `Split ${sourceFeatureId} into ${pieces.length} pieces`,
      sessionId,
    ),
    layerId,
    sourceFeatureId,
    sourceGeometry,
    cutGeometry,
    pieces,
    ...undo,
  };
}

export function createMergeOperation(
  layerId: string,
  sourceFeatureIds: string[],
  sourceGeometries: GeoJSON.Geometry[],
  sourceProperties: Record<string, unknown>[],
  mergedFeatureId: string,
  mergedGeometry: GeoJSON.Geometry,
  mergedProperties: Record<string, unknown>,
  userId: string,
  sessionId?: string,
  undo?: Partial<Pick<
    MergeOperation,
    'calcId' | 'layerType' | 'importLayerId' | 'sourceSnapshots' | 'mergedRowId' | 'sourceFeatures' | 'sourceIndices'
  >>,
): MergeOperation {
  return {
    type: 'merge',
    kind: 'merge',
    meta: createOperationMeta(
      userId,
      `Merge ${sourceFeatureIds.length} features into 1`,
      sessionId,
    ),
    layerId,
    sourceFeatureIds,
    sourceGeometries,
    sourceProperties,
    mergedFeatureId,
    mergedGeometry,
    mergedProperties,
    ...undo,
  };
}

export function createVertexEditOperation(
  layerId: string,
  featureId: string,
  vertexEditType: VertexEditType,
  vertexIndex: number | { ring: number; index: number },
  previousCoordinate: GeoJSON.Position,
  newCoordinate: GeoJSON.Position,
  previousGeometry: GeoJSON.Geometry,
  newGeometry: GeoJSON.Geometry,
  userId: string,
  sessionId?: string,
  undo?: Partial<Pick<VertexEditOperation, 'calcId' | 'layerType' | 'importLayerId' | 'featureIndex' | 'sharedMovePartners'>>,
): VertexEditOperation {
  const actionLabel =
    vertexEditType === 'drag'
      ? `Drag vertex on ${featureId}`
      : vertexEditType === 'add'
        ? `Add vertex to ${featureId}`
        : `Delete vertex from ${featureId}`;

  return {
    type: 'vertex_edit',
    kind: 'vertex_edit',
    meta: createOperationMeta(userId, actionLabel, sessionId),
    layerId,
    featureId,
    vertexEditType,
    vertexIndex,
    previousCoordinate,
    newCoordinate,
    previousGeometry,
    newGeometry,
    ...undo,
  };
}

export function createDeleteOperation(
  layerId: string,
  featureId: string,
  deletedFeature: GeoJSON.Feature,
  userId: string,
  sessionId?: string,
): DeleteOperation {
  return {
    type: 'delete',
    kind: 'delete',
    meta: createOperationMeta(userId, `Delete ${featureId}`, sessionId),
    layerId,
    featureId,
    deletedFeature,
  };
}

export function createDuplicateOperation(
  layerId: string,
  sourceFeatureId: string,
  newFeatureId: string,
  geometry: GeoJSON.Geometry,
  properties: Record<string, unknown>,
  userId: string,
  sessionId?: string,
): DuplicateOperation {
  return {
    type: 'duplicate',
    kind: 'duplicate',
    meta: createOperationMeta(
      userId,
      `Duplicate ${sourceFeatureId} → ${newFeatureId}`,
      sessionId,
    ),
    layerId,
    sourceFeatureId,
    newFeatureId,
    geometry,
    properties,
  };
}

export function createBatchOperation(
  operations: GeometryOperation[],
  overrides?: Partial<OperationMeta>,
): BatchOperation {
  const kinds = [...new Set(operations.map(o => o.kind))];
  const label = `Batch: ${kinds.join(', ')} (${operations.length} ops)`;
  return {
    type: 'batch',
    kind: 'batch',
    meta: {
      ...(operations[0]?.meta ?? createOperationMeta('system', label)),
      ...overrides,
      label: overrides?.label ?? label,
    },
    operations: Object.freeze([...operations]),
  };
}

export function createVisibilityOperation(
  layerId: string,
  layerType: 'builtin' | 'imported',
  previousVisible: boolean,
  newVisible: boolean,
  userId: string,
  sessionId?: string,
): VisibilityOperation {
  return {
    type: 'visibility',
    kind: 'visibility',
    meta: createOperationMeta(userId, `${newVisible ? 'Show' : 'Hide'} layer ${layerId}`, sessionId),
    layerId,
    layerType,
    previousVisible,
    newVisible,
  };
}

export function createLabelsOperation(
  layerId: string,
  previousVisible: boolean,
  newVisible: boolean,
  userId: string,
  sessionId?: string,
): LabelsOperation {
  return {
    type: 'labels',
    kind: 'labels',
    meta: createOperationMeta(userId, `${newVisible ? 'Show' : 'Hide'} labels on ${layerId}`, sessionId),
    layerId,
    previousVisible,
    newVisible,
  };
}

export function createStyleOperation(
  layerId: string,
  previousStyle: PathStyleOptions,
  newStyle: PathStyleOptions,
  userId: string,
  sessionId?: string,
): StyleOperation {
  return {
    type: 'style',
    kind: 'style',
    meta: createOperationMeta(userId, `Style layer ${layerId}`, sessionId),
    layerId,
    previousStyle,
    newStyle,
  };
}

export function createLabelFieldOperation(
  layerId: string,
  previousField: string | null,
  newField: string | null,
  userId: string,
  sessionId?: string,
): LabelFieldOperation {
  return {
    type: 'label_field',
    kind: 'label_field',
    meta: createOperationMeta(
      userId,
      `Label ${layerId}: ${previousField ?? 'none'} → ${newField ?? 'none'}`,
      sessionId,
    ),
    layerId,
    previousField,
    newField,
  };
}

export function createDigitizeAddOperation(
  layerId: number,
  feature: GeoJSON.Feature,
  userId: string,
  sessionId?: string,
): DigitizeAddFeatureOperation {
  return {
    type: 'digitize_add',
    kind: 'digitize_add',
    meta: createOperationMeta(userId, `Draw feature on digitize layer ${layerId}`, sessionId),
    layerId,
    feature,
  };
}

export function createDigitizeDeleteOperation(
  layerId: number,
  featureId: string,
  userId: string,
  sessionId?: string,
): DigitizeDeleteFeatureOperation {
  return {
    type: 'digitize_delete',
    kind: 'digitize_delete',
    meta: createOperationMeta(userId, `Remove feature ${featureId} from digitize layer ${layerId}`, sessionId),
    layerId,
    featureId,
  };
}

export function createDigitizeDeleteByIdOperation(
  layerId: number,
  featureId: string,
  deletedFeature: GeoJSON.Feature,
  userId: string,
  sessionId?: string,
): DigitizeDeleteFeatureByIdOperation {
  return {
    type: 'digitize_delete_by_id',
    kind: 'digitize_delete_by_id',
    meta: createOperationMeta(userId, `Delete feature ${featureId} from digitize layer ${layerId}`, sessionId),
    layerId,
    featureId,
    deletedFeature,
  };
}

/**
 * P3.5 — an undoable attribute-table edit (name / category / per-feature colour
 * / opacity) on a builtin unit or sub-area row, or a property rename on an
 * imported-layer feature (pass `opts.importLayerId` + `opts.featureIndex`).
 * Undo re-PATCHes `previousPayload`; redo re-PATCHes `newPayload`.
 */
export function createAttributeEditOperation(
  calcId: string,
  layerId: string,
  featureId: string,
  label: string,
  previousPayload: Record<string, unknown>,
  newPayload: Record<string, unknown>,
  userId: string,
  opts?: { sessionId?: string; importLayerId?: number; featureIndex?: number },
): AttributeEditOperation {
  return {
    type: 'attribute_edit',
    kind: 'attribute_edit',
    meta: createOperationMeta(userId, label, opts?.sessionId),
    calcId,
    layerId,
    featureId,
    previousPayload,
    newPayload,
    importLayerId: opts?.importLayerId,
    featureIndex: opts?.featureIndex,
  };
}

/** E3 — attribute-table per-row delete on any builtin or imported layer. */
export function createFeatureDeleteOperation(
  calcId: string,
  layerType: string,
  featureId: string,
  snapshot: Record<string, unknown>,
  userId: string,
  opts?: { importLayerId?: number; featureIndex?: number; sessionId?: string },
): FeatureDeleteOperation {
  return {
    type: 'feature_delete',
    kind: 'feature_delete',
    meta: createOperationMeta(userId, `Delete ${featureId} from ${layerType}`, opts?.sessionId),
    calcId,
    layerType,
    featureId,
    importLayerId: opts?.importLayerId,
    featureIndex: opts?.featureIndex,
    snapshot,
  };
}

/** Toolbar Paste — one undo step for every feature a single paste created. */
export function createFeaturePasteOperation(
  calcId: string,
  layerType: string,
  features: readonly GeoJSON.Feature[],
  createdIds: string[],
  userId: string,
  opts?: {
    importLayerId?: number;
    baseIndex?: number;
    payloads?: readonly Record<string, unknown>[];
    sessionId?: string;
    label?: string;
  },
): FeaturePasteOperation {
  return {
    type: 'feature_paste',
    kind: 'feature_paste',
    meta: createOperationMeta(
      userId,
      opts?.label ?? `Paste ${features.length} feature(s) into ${layerType}`,
      opts?.sessionId,
    ),
    calcId,
    layerType,
    features: Object.freeze([...features]),
    payloads: opts?.payloads ? Object.freeze([...opts.payloads]) : undefined,
    importLayerId: opts?.importLayerId,
    baseIndex: opts?.baseIndex,
    state: { createdIds: [...createdIds] },
  };
}
