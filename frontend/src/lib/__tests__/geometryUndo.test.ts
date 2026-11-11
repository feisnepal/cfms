import { describe, it, expect } from 'vitest'
import type { GeoJSON } from 'geojson'
import { createSplitOperation, createMergeOperation, createVertexEditOperation } from '../operationFactories'
import { serializeOperation, deserializeOperation } from '../editOperations'
import {
  importedFeaturesAfterSplitInverse,
  importedFeaturesAfterMergeInverse,
  importedFeaturesAfterSplitForward,
  importedFeaturesAfterMergeForward,
  importedFeaturesAfterVertexInverse,
  importedFeaturesAfterVertexForward,
} from '../geometryUndo'

const USER = 'test-user'

const polygon = (dx = 0): GeoJSON.Polygon => ({
  type: 'Polygon',
  coordinates: [[[0 + dx, 0], [1 + dx, 0], [1 + dx, 1], [0 + dx, 1], [0 + dx, 0]]],
})

const line: GeoJSON.LineString = { type: 'LineString', coordinates: [[0.5, 0], [0.5, 1]] }

const feat = (featureId: string, dx = 0): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: polygon(dx),
  properties: { featureId, name: featureId },
})

describe('geometryUndo imported reducers — undo split', () => {
  it('drops the pieces and splices the source back at its original index', () => {
    const cur = [feat('imp-1'), feat('imp-2'), feat('imp-3')]
    const op = createSplitOperation('imp-1', 'imp-2', polygon(1), line, [
      { pieceId: 'imp-2-piece-1', geometry: polygon(1), properties: { name: 'p1' } },
      { pieceId: 'imp-2-piece-2', geometry: polygon(1), properties: { name: 'p2' } },
    ], USER, undefined, {
      layerType: 'imported',
      importLayerId: 7,
      sourceFeature: feat('imp-2', 1),
      sourceFeatureIndex: 1,
      pieceFeatureIds: ['imp-2-piece-1', 'imp-2-piece-2'],
    })
    const after: GeoJSON.Feature[] = [
      feat('imp-1'), feat('imp-2-piece-1'), feat('imp-2-piece-2'), feat('imp-3'),
    ]
    const next = importedFeaturesAfterSplitInverse(after, op)
    expect(next.map((f) => (f.properties as any).featureId)).toEqual(['imp-1', 'imp-2', 'imp-3'])
    expect(next[1].geometry).toEqual(op.sourceFeature!.geometry)
  })
})

describe('geometryUndo imported reducers — undo merge', () => {
  it('drops the merged feature and resplices sources at their indices', () => {
    // post-merge layer_data: sources removed, merged appended last.
    const cur: GeoJSON.Feature[] = [
      feat('imp-1-merged'), feat('imp-3'),
    ]
    const op = createMergeOperation(
      'imp-1', ['imp-1', 'imp-2'], [polygon(0), polygon(1)], [{}, {}],
      'imp-1-merged', polygon(0), {}, USER, undefined,
      {
        layerType: 'imported',
        importLayerId: 7,
        sourceFeatures: [feat('imp-1', 0), feat('imp-2', 1)],
        sourceIndices: [0, 1],
      },
    )
    const next = importedFeaturesAfterMergeInverse(cur, op)
    expect(next.map((f) => (f.properties as any).featureId)).toEqual(['imp-1', 'imp-2', 'imp-3'])
  })
})

describe('geometryUndo imported reducers — redo split/merge, vertex', () => {
  it('redo split: drops source, appends piece features with featureIds', () => {
    const cur = [feat('imp-1'), feat('imp-5')]
    const op = createSplitOperation('imp-1', 'imp-1', polygon(0), line, [
      { pieceId: 'imp-1-piece-1', geometry: polygon(0), properties: {} },
      { pieceId: 'imp-1-piece-2', geometry: polygon(0), properties: {} },
    ], USER, undefined, {
      layerType: 'imported',
      importLayerId: 7,
      pieceFeatureIds: ['imp-1-piece-1', 'imp-1-piece-2'],
    })
    const next = importedFeaturesAfterSplitForward(cur, op)
    const ids = next.map((f) => (f.properties as any).featureId)
    expect(ids).toEqual(['imp-5', 'imp-1-piece-1', 'imp-1-piece-2'])
  })

  it('redo merge: drops sources, appends merged feature', () => {
    const cur = [feat('imp-1'), feat('imp-2'), feat('imp-3')]
    const op = createMergeOperation(
      'imp-1', ['imp-1', 'imp-2'], [polygon(0), polygon(1)], [{}, {}],
      'imp-1-merged', polygon(0), {}, USER,
    )
    const next = importedFeaturesAfterMergeForward(cur, op, feat('imp-1-merged'))
    expect(next.map((f) => (f.properties as any).featureId)).toEqual(['imp-3', 'imp-1-merged'])
  })

  it('vertex inverse/forward swap geometry on the matching feature', () => {
    const cur = [feat('imp-1'), feat('imp-2')]
    const op = createVertexEditOperation(
      'imp-1', 'imp-2', 'drag', 0, [0, 0], [5, 5],
      polygon(1), polygon(2), USER, undefined,
      { layerType: 'imported', importLayerId: 7 },
    )
    const undone = importedFeaturesAfterVertexInverse(cur, op)
    expect((undone[1].geometry as any).coordinates[0][0][0]).toBe(1) // = previousGeometry
    const redone = importedFeaturesAfterVertexForward(undone, op)
    expect((redone[1].geometry as any).coordinates[0][0][0]).toBe(2) // = newGeometry
  })
})

describe('geometryUndo serialization round-trip (UE-3.2 fields survive localStorage)', () => {
  it('split keeps pieceIds + boundaryPieceBlockIds + sourceSnapshot', () => {
    const op = createSplitOperation('blocks', 'f1', polygon(0), line, [
      { pieceId: 'fa', geometry: polygon(0), properties: {} },
      { pieceId: 'fb', geometry: polygon(0), properties: {} },
    ], USER, undefined, {
      calcId: 'c1',
      layerType: 'blocks',
      pieceIds: ['fa', 'fb'],
      sourceSnapshot: { id: 'f1', name: 'orig' },
    })
    const back = deserializeOperation(serializeOperation(op))
    expect(back).toMatchObject({
      calcId: 'c1',
      layerType: 'blocks',
      pieceIds: ['fa', 'fb'],
      sourceSnapshot: { id: 'f1', name: 'orig' },
    })
  })

  it('merge keeps sourceSnapshots + mergedRowId', () => {
    const op = createMergeOperation(
      'blocks', ['f1', 'f2'], [polygon(0), polygon(1)], [{}, {}],
      'f1-merged', polygon(0), {}, USER, undefined,
      { sourceSnapshots: [{ id: 'f1' }, { id: 'f2' }], mergedRowId: 'f1-merged', layerType: 'blocks' },
    )
    const back = deserializeOperation(serializeOperation(op))
    expect(back).toMatchObject({
      sourceSnapshots: [{ id: 'f1' }, { id: 'f2' }],
      mergedRowId: 'f1-merged',
    })
  })
})