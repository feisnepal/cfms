/**
 * U13 — Command History tests (dependency-graph undo/redo).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { CommandHistory, MAX_HISTORY, CommandResult, CommandStatus } from '../commandHistory';
import type { GeometryOperation, RenameOperation, VertexEditOperation, DeleteOperation } from '../editOperations';
import type { GeoJSON } from 'geojson';

// Mock feature getter
const mockFeatures = new Map<string, GeoJSON.Feature>();

function getFeature(layerId: string, featureId: string): GeoJSON.Feature | null {
  return mockFeatures.get(`${layerId}:${featureId}`) ?? null;
}

function setFeature(layerId: string, feature: GeoJSON.Feature) {
  mockFeatures.set(`${layerId}:${feature.id}`, feature);
}

function clearFeatures() {
  mockFeatures.clear();
}

function makeRenameOp(layerId: string, featureId: string, prev: string, next: string): RenameOperation {
  return {
    kind: 'rename',
    type: 'rename',
    meta: { timestamp: Date.now(), userId: 'u1', label: `Rename ${prev} → ${next}` },
    layerId,
    featureId,
    previousName: prev,
    newName: next,
  };
}

function makeVertexEditOp(layerId: string, featureId: string, prevCoord: GeoJSON.Position, newCoord: GeoJSON.Position, prevGeom: GeoJSON.Geometry, newGeom: GeoJSON.Geometry): VertexEditOperation {
  return {
    kind: 'vertex_edit',
    type: 'vertex_edit',
    meta: { timestamp: Date.now(), userId: 'u1', label: 'Drag vertex' },
    layerId,
    featureId,
    vertexEditType: 'drag',
    vertexIndex: 0,
    previousCoordinate: prevCoord,
    newCoordinate: newCoord,
    previousGeometry: prevGeom,
    newGeometry: newGeom,
  };
}

function makeDeleteOp(layerId: string, featureId: string, deletedFeature: GeoJSON.Feature): DeleteOperation {
  return {
    kind: 'delete',
    type: 'delete',
    meta: { timestamp: Date.now(), userId: 'u1', label: `Delete ${featureId}` },
    layerId,
    featureId,
    deletedFeature,
  };
}

describe('CommandHistory', () => {
  let history: CommandHistory;

  beforeEach(() => {
    vi.useFakeTimers();
    history = new CommandHistory();
    clearFeatures();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('pushes and undoes a single operation', () => {
    const op = makeRenameOp('layer1', 'f1', 'old', 'new');
    history.push(op);

    expect(history.canUndo).toBe(true);
    expect(history.canRedo).toBe(false);

    const result = history.undo();
    expect(result).not.toBeNull();
    expect(result!.primary.kind).toBe('rename');
    expect(result!.cascaded).toEqual([]);
    expect(history.canUndo).toBe(false);
  });

  it('cascades undo for dependent operations', () => {
    // Rename f1
    const op1 = makeRenameOp('L1', 'f1', 'A', 'B');
    history.push(op1);

    // Vertex edit on same feature f1 (depends on rename)
    const geom: GeoJSON.Point = { type: 'Point', coordinates: [0, 0] };
    const newGeom: GeoJSON.Point = { type: 'Point', coordinates: [1, 1] };
    const op2 = makeVertexEditOp('L1', 'f1', [0, 0], [1, 1], { type: 'Point', coordinates: [0, 0] }, { type: 'Point', coordinates: [1, 1] });
    history.push(op2);

    // Undo should cascade: vertex edit depends on rename
    const result = history.undo();
    expect(result).not.toBeNull();
    expect(result!.primary.kind).toBe('vertex_edit');
    expect(result!.cascaded.length).toBe(1);
    expect(result!.cascaded[0].kind).toBe('rename');
  });

  it('validateUndo returns OK for matching geometry', () => {
    const feature: GeoJSON.Feature = {
      type: 'Feature',
      id: 'f1',
      properties: { name: 'test' },
      geometry: { type: 'Point', coordinates: [0, 0] },
    };
    setFeature('L1', feature);

    const op = makeVertexEditOp('L1', 'f1', [0, 0], [1, 1], { type: 'Point', coordinates: [0, 0] }, { type: 'Point', coordinates: [1, 1] });
    history.push(op);

    // Mock getter that returns current feature
    const result = history.validateUndo(op, getFeature);
    expect(result.status).toBe('OK');
  });

  it('validateUndo returns STALE_GEOMETRY when geometry changed', () => {
    const originalFeature: GeoJSON.Feature = {
      type: 'Feature',
      id: 'f1',
      properties: {},
      geometry: { type: 'Point', coordinates: [0, 0] },
    };
    setFeature('L1', originalFeature);

    // Create operation expecting [0,0]
    const op = makeVertexEditOp('L1', 'f1', [0, 0], [1, 1], { type: 'Point', coordinates: [0, 0] }, { type: 'Point', coordinates: [1, 1] });
    history.push(op);

    // Now feature geometry is different ([5,5] instead of [0,0])
    const mutatedFeature: GeoJSON.Feature = {
      type: 'Feature',
      id: 'f1',
      properties: {},
      geometry: { type: 'Point', coordinates: [5, 5] },
    };
    setFeature('L1', mutatedFeature);

    const result = history.validateUndo(op, getFeature);
    expect(result.status).toBe('STALE_GEOMETRY');
  });

  it('validateUndo returns TARGET_MISSING when feature deleted', () => {
    const feature: GeoJSON.Feature = { type: 'Feature', id: 'f1', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } };
    setFeature('L1', feature);

    const op = makeDeleteOp('L1', 'f1', { type: 'Feature', id: 'f1', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } });
    history.push(op);

    // Feature is now gone
    clearFeatures();
    const result = history.validateUndo(op, getFeature);
    expect(result.status).toBe('TARGET_MISSING');
  });

  it('redo restores undone operation', () => {
    const op = makeRenameOp('L1', 'f1', 'A', 'B');
    history.push(op);
    history.undo();
    expect(history.canRedo).toBe(true);

    const redoResult = history.redo();
    expect(redoResult).not.toBeNull();
    expect(redoResult!.primary.kind).toBe('rename');
    expect(history.undoStackDepth).toBe(1);
  });

  it('respects MAX_HISTORY limit', () => {
    const smallHistory = new CommandHistory(3);
    for (let i = 0; i < 5; i++) {
      smallHistory.push(makeRenameOp('L1', `f${i}`, `A${i}`, `B${i}`));
    }
    expect(smallHistory.undoStackDepth).toBe(3);
    // Should have pruned oldest 2
  });

  it('clear resets everything', () => {
    const op = makeRenameOp('L1', 'f1', 'A', 'B');
    history.push(op);
    history.undo();
    history.clear();
    expect(history.canUndo).toBe(false);
    expect(history.canRedo).toBe(false);
    expect(history.undoStackDepth).toBe(0);
    expect(history.redoStackDepth).toBe(0);
  });

  it('validateUndo for batch operation checks all sub-operations', () => {
    const feature1: GeoJSON.Feature = { type: 'Feature', id: 'f1', properties: {}, geometry: { type: 'Point', coordinates: [0, 0] } };
    const feature2: GeoJSON.Feature = { type: 'Feature', id: 'f2', properties: {}, geometry: { type: 'Point', coordinates: [1, 1] } };
    setFeature('L1', feature1);
    setFeature('L1', feature2);

    const op1 = makeRenameOp('L1', 'f1', 'A', 'B');
    const op2 = makeRenameOp('L1', 'f2', 'C', 'D');
    const batchOp = {
      kind: 'batch',
      type: 'batch',
      meta: { timestamp: Date.now(), userId: 'u1', label: 'Batch rename' },
      operations: [op1, op2],
    } as any;

    history.push(batchOp);

    const result = history.validateUndo(batchOp, getFeature);
    expect(result.status).toBe('OK');
  });
});