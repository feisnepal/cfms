import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import type { GeoJSON } from 'geojson'
import { GeometryHistoryManager, DEFAULT_MAX_STACK_SIZE } from '../historyManager'
import {
  createRenameOperation,
  createSplitOperation,
  createMergeOperation,
  createVertexEditOperation,
  createDeleteOperation,
  createDuplicateOperation,
  createBatchOperation,
  createDigitizeAddOperation,
  createDigitizeDeleteOperation,
  createDigitizeDeleteByIdOperation,
  createFeatureDeleteOperation,
  createAttributeEditOperation,
} from '../operationFactories'
import {
  isRenameOperation,
  isSplitOperation,
  isMergeOperation,
  isVertexEditOperation,
  isDeleteOperation,
  isDuplicateOperation,
  isBatchOperation,
  isDigitizeAddFeatureOperation,
  isDigitizeDeleteFeatureOperation,
  isDigitizeDeleteFeatureByIdOperation,
  isFeatureDeleteOperation,
  isAttributeEditOperation,
  serializeOperation,
  deserializeOperation,
  getOperationLabel,
} from '../editOperations'
import type { GeometryOperation, RenameOperation } from '../editOperations'

const USER_ID = 'test-user'
const INSTANCE_ID = 'test-forest'

const emptyPolygon: GeoJSON.Polygon = {
  type: 'Polygon',
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}

const lineString: GeoJSON.LineString = {
  type: 'LineString',
  coordinates: [[0.5, 0], [0.5, 1]],
}

const fullFeature: GeoJSON.Feature = {
  type: 'Feature',
  geometry: emptyPolygon,
  properties: { name: 'test' },
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
})

// ── Scenario 1: Basic Undo/Redo Cycle ──────────────────────────────────────

describe('Scenario 1 — Basic Undo/Redo Cycle', () => {
  it('undo/redo returns null on empty stack', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: INSTANCE_ID,
      userId: USER_ID,
      autoSave: false,
    })
    expect(mgr.undo()).toBeNull()
    expect(mgr.redo()).toBeNull()
  })

  it('push → undo → redo restores state', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: INSTANCE_ID,
      userId: USER_ID,
      autoSave: false,
    })
    const op = createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID)
    mgr.push(op)

    expect(mgr.canUndo).toBe(true)
    expect(mgr.undoDepth).toBe(1)

    const undone = mgr.undo()
    expect(undone).toEqual(op)
    expect(mgr.canUndo).toBe(false)
    expect(mgr.redoDepth).toBe(1)
    expect(mgr.canRedo).toBe(true)

    const redone = mgr.redo()
    expect(redone).toEqual(op)
    expect(mgr.canUndo).toBe(true)
    expect(mgr.redoDepth).toBe(0)
  })
})

// ── Scenario 2: MaxSize Enforcement Evicts Oldest ──────────────────────────

describe('Scenario 2 — MaxSize Enforcement Evicts Oldest', () => {
  it('evicts oldest when maxSize exceeded', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: INSTANCE_ID,
      userId: USER_ID,
      autoSave: false,
      maxSize: 3,
    })
    const ops = [1, 2, 3, 4].map((i) =>
      createRenameOperation('blocks', `f${i}`, `C${i}`, `C${i + 1}`, USER_ID),
    )
    ops.forEach((op) => mgr.push(op))

    expect(mgr.undoDepth).toBe(3)

    expect(mgr.undo()).toEqual(ops[3])
    expect(mgr.undo()).toEqual(ops[2])
    expect(mgr.undo()).toEqual(ops[1])
    expect(mgr.undo()).toBeNull()
  })
})

// ── Scenario 3: New Action Clears Redo Stack ───────────────────────────────

describe('Scenario 3 — New Action Clears Redo Stack', () => {
  it('push after undo clears redo stack', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: INSTANCE_ID,
      userId: USER_ID,
      autoSave: false,
    })
    const opA = createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID)
    const opB = createRenameOperation('blocks', 'f2', 'C2', 'C3', USER_ID)
    const opC = createRenameOperation('blocks', 'f3', 'C3', 'C4', USER_ID)

    mgr.push(opA)
    mgr.push(opB)
    expect(mgr.undoDepth).toBe(2)

    mgr.undo()
    expect(mgr.redoDepth).toBe(1)

    mgr.push(opC)
    expect(mgr.redoDepth).toBe(0)
    expect(mgr.redo()).toBeNull()
    expect(mgr.canUndo).toBe(true)
    expect(mgr.canRedo).toBe(false)
  })
})

// ── Scenario 4: localStorage Persistence ──────────────────────────────────

describe('Scenario 4 — localStorage Persistence Across Refresh', () => {
  it('survives dispose/recreate cycle', () => {
    const mgr1 = new GeometryHistoryManager({
      instanceId: 'persist-test',
      userId: USER_ID,
      autoSave: false,
    })
    const ops = [1, 2, 3].map((i) =>
      createRenameOperation('blocks', `f${i}`, `C${i}`, `C${i + 1}`, USER_ID),
    )
    ops.forEach((op) => mgr1.push(op))
    mgr1.save()

    const key = 'geom_history_persist-test'
    expect(localStorage.getItem(key)).not.toBeNull()

    mgr1.dispose()

    const mgr2 = new GeometryHistoryManager({
      instanceId: 'persist-test',
      userId: USER_ID,
      autoSave: false,
    })
    expect(mgr2.undoDepth).toBe(3)
    expect(mgr2.undo()).toEqual(ops[2])
    expect(mgr2.undo()).toEqual(ops[1])
    expect(mgr2.undo()).toEqual(ops[0])
  })

  it('handles corrupt localStorage gracefully', () => {
    const key = 'geom_history_corrupt-test'
    localStorage.setItem(key, '{invalid json')

    const mgr = new GeometryHistoryManager({
      instanceId: 'corrupt-test',
      userId: USER_ID,
      autoSave: false,
    })
    expect(mgr.undoDepth).toBe(0)
    expect(localStorage.getItem(key)).toBeNull()
  })
})

// ── Scenario 5: All Operation Types Round-Trip ─────────────────────────────

describe('Scenario 5 — All 6+1 Operation Types Round-Trip', () => {
  it('RenameOperation round-trips', () => {
    const op = createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID)
    roundTrip(op)
  })

  it('SplitOperation round-trips', () => {
    const pieces = [
      { pieceId: 'p1', geometry: emptyPolygon, properties: {} },
      { pieceId: 'p2', geometry: emptyPolygon, properties: {} },
    ]
    const op = createSplitOperation('blocks', 'f1', emptyPolygon, lineString, pieces, USER_ID)
    roundTrip(op)
  })

  it('MergeOperation round-trips', () => {
    const op = createMergeOperation(
      'blocks',
      ['f1', 'f2'],
      [emptyPolygon, emptyPolygon],
      [{ a: 1 }, { b: 2 }],
      'f3',
      emptyPolygon,
      { combined: true },
      USER_ID,
    )
    roundTrip(op)
  })

  it('VertexEditOperation round-trips', () => {
    const newPoly: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [[[0, 0], [2, 0], [1, 1], [0, 1], [0, 0]]],
    }
    const op = createVertexEditOperation(
      'blocks', 'f1', 'drag', 1,
      [1, 0], [2, 0],
      emptyPolygon, newPoly,
      USER_ID,
    )
    roundTrip(op)
  })

  it('DeleteOperation round-trips', () => {
    const op = createDeleteOperation('blocks', 'f1', fullFeature, USER_ID)
    roundTrip(op)
  })

  it('DuplicateOperation round-trips', () => {
    const op = createDuplicateOperation(
      'blocks', 'f1', 'f2', emptyPolygon, { copied: true }, USER_ID,
    )
    roundTrip(op)
  })

  it('BatchOperation round-trips', () => {
    const inner = [
      createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID),
      createDeleteOperation('blocks', 'f2', fullFeature, USER_ID),
    ]
    const op = createBatchOperation(inner)
    roundTrip(op)
  })

  it('all 7 operations survive JSON round-trip via manager', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: 'roundtrip-all',
      userId: USER_ID,
      autoSave: false,
    })
    const ops = createAllOperationTypes()
    ops.forEach((op) => mgr.push(op))

    const json = mgr.toJSON()
    const mgr2 = new GeometryHistoryManager({
      instanceId: 'roundtrip-all-2',
      userId: USER_ID,
      autoSave: false,
    })
    mgr2.fromJSON(json)

    expect(mgr2.undoDepth).toBe(ops.length)
    for (let i = ops.length - 1; i >= 0; i--) {
      expect(mgr2.undo()).toEqual(ops[i])
    }
  })

  it('DigitizeAddFeatureOperation round-trips', () => {
    const op = createDigitizeAddOperation(10, fullFeature, USER_ID)
    roundTrip(op)
  })

  it('DigitizeDeleteFeatureOperation round-trips', () => {
    const op = createDigitizeDeleteOperation(10, 'f1', USER_ID)
    roundTrip(op)
  })

  it('DigitizeDeleteFeatureByIdOperation round-trips (delete-by-id undo restore)', () => {
    const op = createDigitizeDeleteByIdOperation(10, 'f1', fullFeature, USER_ID)
    roundTrip(op)
  })

  it('digitize ops have descriptive labels', () => {
    expect(getOperationLabel(createDigitizeAddOperation(10, fullFeature, USER_ID)))
      .toBe('Draw feature on digitize layer 10')
    expect(getOperationLabel(createDigitizeDeleteByIdOperation(10, 'f1', fullFeature, USER_ID)))
      .toBe('Delete feature f1 from digitize layer 10')
  })

  it('FeatureDeleteOperation round-trips (E3 undo/redo entry)', () => {
    const op = createFeatureDeleteOperation(
      'calc-1', 'sub_compartments', 'sc-7',
      { id: 'sc-7', name: 'SC 7', geometry: { type: 'Polygon' } },
      USER_ID,
      { featureIndex: 3 },
    )
    roundTrip(op)
  })
})

// ── Type Guard Tests ────────────────────────────────────────────────────────

describe('Type Guards', () => {
  it('correctly identifies each operation type', () => {
    const ops = createAllOperationTypes()
    expect(isRenameOperation(ops[0])).toBe(true)
    expect(isSplitOperation(ops[1])).toBe(true)
    expect(isMergeOperation(ops[2])).toBe(true)
    expect(isVertexEditOperation(ops[3])).toBe(true)
    expect(isDeleteOperation(ops[4])).toBe(true)
    expect(isDuplicateOperation(ops[5])).toBe(true)
    expect(isBatchOperation(ops[6])).toBe(true)
    expect(isDigitizeAddFeatureOperation(ops[7])).toBe(true)
    expect(isDigitizeDeleteFeatureOperation(ops[8])).toBe(true)
    expect(isDigitizeDeleteFeatureByIdOperation(ops[9])).toBe(true)
    expect(isFeatureDeleteOperation(ops[10])).toBe(true)
  })
})

// ── getOperationLabel Tests ──────────────────────────────────────────────────

describe('getOperationLabel', () => {
  it('produces display labels for all operation types', () => {
    const ops = createAllOperationTypes()
    const labels = ops.map(getOperationLabel)
    expect(labels[0]).toContain('Rename')
    expect(labels[1]).toContain('Split')
    expect(labels[2]).toContain('Merge')
    expect(labels[3]).toContain('Drag vertex')
    expect(labels[4]).toContain('Delete')
    expect(labels[5]).toContain('Duplicate')
    expect(labels[6]).toContain('Batch')
    expect(getOperationLabel(createFeatureDeleteOperation(
      'calc-1', 'import_8', 'imp-f1', { feature: fullFeature }, USER_ID,
      { importLayerId: 8, featureIndex: 0 },
    ))).toContain('Delete imp-f1 from import_8')
  })
})

// ── AttributeEditOperation (WORKSPACE_LAYER_STYLING_PLAN.md P3.5) ────────────

describe('AttributeEditOperation', () => {
  const mk = () => createAttributeEditOperation(
    'calc-1', 'sub_areas', 'sa-3', 'Edit colour',
    { style: null },
    { style: { fill: '#cc3344' } },
    USER_ID,
  )

  it('is identified by its type guard and carries both payloads', () => {
    const op = mk()
    expect(isAttributeEditOperation(op)).toBe(true)
    expect(op.previousPayload).toEqual({ style: null })
    expect(op.newPayload).toEqual({ style: { fill: '#cc3344' } })
    expect(getOperationLabel(op)).toBe('Edit colour')
  })

  it('round-trips through history serialize / deserialize', () => {
    roundTrip(mk())
  })

  it('serializeOperation keeps the payload objects', () => {
    const s = serializeOperation(mk()) as Record<string, unknown>
    expect(s.kind).toBe('attribute_edit')
    expect(s.newPayload).toEqual({ style: { fill: '#cc3344' } })
    expect(deserializeOperation(s).kind).toBe('attribute_edit')
  })

  it('carries importLayerId + featureIndex for an imported-feature edit', () => {
    const op = createAttributeEditOperation(
      'calc-1', 'imported-7', 'f-2', 'Edit name',
      { properties: { name: 'old' } },
      { properties: { name: 'new' } },
      USER_ID,
      { importLayerId: 7, featureIndex: 2 },
    )
    expect(op.importLayerId).toBe(7)
    expect(op.featureIndex).toBe(2)
    roundTrip(op)
  })
})

// ── Edge Cases ──────────────────────────────────────────────────────────────

describe('Edge Cases', () => {
  it('clear empties both stacks and clears storage', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: 'clear-test',
      userId: USER_ID,
      autoSave: false,
    })
    mgr.push(createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID))
    mgr.push(createRenameOperation('blocks', 'f2', 'C2', 'C3', USER_ID))
    mgr.save()

    mgr.clear()
    expect(mgr.undoDepth).toBe(0)
    expect(mgr.redoDepth).toBe(0)
    expect(mgr.canUndo).toBe(false)
    expect(mgr.canRedo).toBe(false)
    expect(localStorage.getItem('geom_history_clear-test')).toBeNull()
  })

  it('peekUndo/peekRedo returns top without removing', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: 'peek-test',
      userId: USER_ID,
      autoSave: false,
    })
    const op = createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID)
    mgr.push(op)

    expect(mgr.peekUndo()).toEqual(op)
    expect(mgr.undoDepth).toBe(1)

    expect(mgr.peekRedo()).toBeNull()
    mgr.undo()
    expect(mgr.peekRedo()).toEqual(op)
    expect(mgr.redoDepth).toBe(1)
  })

  it('pushBatch creates a single batch operation', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: 'batch-test',
      userId: USER_ID,
      autoSave: false,
    })
    const inner = [
      createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID),
      createRenameOperation('blocks', 'f2', 'C2', 'C3', USER_ID),
    ]
    mgr.pushBatch(inner)
    expect(mgr.undoDepth).toBe(1)
    const op = mgr.peekUndo()
    expect(op).not.toBeNull()
    expect(isBatchOperation(op!)).toBe(true)
  })

  it('flush saves dirty state', () => {
    const mgr = new GeometryHistoryManager({
      instanceId: 'flush-test',
      userId: USER_ID,
      autoSave: false,
    })
    mgr.push(createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID))
    mgr.flush()
    const key = 'geom_history_flush-test'
    expect(localStorage.getItem(key)).not.toBeNull()
  })
})

// ── Helpers ─────────────────────────────────────────────────────────────────

function roundTrip(op: GeometryOperation) {
  const mgr = new GeometryHistoryManager({
    instanceId: 'roundtrip-' + op.kind,
    userId: USER_ID,
    autoSave: false,
  })
  mgr.push(op)
  const json = mgr.toJSON()
  const mgr2 = new GeometryHistoryManager({
    instanceId: 'roundtrip-2-' + op.kind,
    userId: USER_ID,
    autoSave: false,
  })
  mgr2.fromJSON(json)
  expect(mgr2.undoDepth).toBe(1)
  const restored = mgr2.undo()
  expect(restored).not.toBeNull()
  expect(restored).toEqual(op)
  expect(restored!.kind).toBe(op.kind)
}

function createAllOperationTypes(): GeometryOperation[] {
  return [
    createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID),
    createSplitOperation('blocks', 'f1', emptyPolygon, lineString, [
      { pieceId: 'p1', geometry: emptyPolygon, properties: {} },
    ], USER_ID),
    createMergeOperation('blocks', ['f1', 'f2'], [emptyPolygon, emptyPolygon],
      [{ a: 1 }, { b: 2 }], 'f3', emptyPolygon, {}, USER_ID),
    createVertexEditOperation('blocks', 'f1', 'drag', { ring: 0, index: 1 },
      [1, 0], [2, 0], emptyPolygon, emptyPolygon, USER_ID),
    createDeleteOperation('blocks', 'f1', fullFeature, USER_ID),
    createDuplicateOperation('blocks', 'f1', 'f2', emptyPolygon, {}, USER_ID),
    createBatchOperation([
      createRenameOperation('blocks', 'f1', 'C1', 'C2', USER_ID),
    ]),
    createDigitizeAddOperation(10, fullFeature, USER_ID),
    createDigitizeDeleteOperation(10, 'f1', USER_ID),
    createDigitizeDeleteByIdOperation(10, 'f1', fullFeature, USER_ID),
    createFeatureDeleteOperation(
      'calc-1', 'blocks', 'blk-1', { id: 'blk-1', name: 'Block 1' }, USER_ID,
      { importLayerId: 5, featureIndex: 2 },
    ),
  ]
}
