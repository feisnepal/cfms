/**
 * Undoing a user_group cut deletes the CREATED rows, then restores the source.
 *
 * P7e, inverting this file's original contract. It used to read "undo must
 * restore the extent, never delete it", because back then a cut REWROTE the one
 * stored row: the server created no piece rows, the piece ids were synthetic, and
 * the user_group delete route took no feature id - so deleting a "piece" would
 * have destroyed the whole extent. That reasoning was right for that model and is
 * why the dedicated branch existed.
 *
 * The owner's model (2026-09-28) makes each polygon its own row, so a cut now
 * DELETES the source row and INSERTS one row per piece - exactly like a block
 * cut. Undo is therefore the ordinary shape: delete what the cut created, restore
 * what it replaced. Keeping the old branch would have left the created rows behind
 * and shown the cut twice after an undo.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { GeoJSON } from 'geojson'
import { deleteFeatureRow, restoreFeatureRow } from '../featureRowOps'
import { createSplitOperation } from '../operationFactories'
import { undoCutServer } from '../geometryUndo'

vi.mock('../featureRowOps', () => ({
  deleteFeatureRow: vi.fn(async () => ({})),
  restoreFeatureRow: vi.fn(async () => {}),
}))

const polygon: GeoJSON.Polygon = {
  type: 'Polygon',
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}
const line: GeoJSON.LineString = { type: 'LineString', coordinates: [[0.5, 0], [0.5, 1]] }

const CALC = 'calc-1'
const SOURCE_ID = '7'
const SNAPSHOT = { id: SOURCE_ID, name: 'User Group', geometry: polygon, area_hectares: 12.5 }

const userGroupCut = () =>
  createSplitOperation(
    'user_group',
    SOURCE_ID,
    polygon,
    line,
    [
      { pieceId: '11', geometry: polygon, properties: {} },
      { pieceId: '12', geometry: polygon, properties: {} },
    ],
    'tester',
    undefined,
    {
      calcId: CALC,
      layerType: 'user_group',
      // The rows the cut really created - plain row ids, no part index.
      pieceIds: ['11', '12'],
      sourceSnapshot: SNAPSHOT,
    },
  )

describe('undoCutServer — user_group', () => {
  beforeEach(() => {
    vi.mocked(deleteFeatureRow).mockClear()
    vi.mocked(restoreFeatureRow).mockClear()
  })

  it('deletes the rows the cut created and restores the source', async () => {
    await undoCutServer(userGroupCut())

    // A cut CREATES rows, so undo has to remove them - otherwise they survive and
    // the cut appears not to have been undone.
    expect(deleteFeatureRow).toHaveBeenCalledTimes(2)
    for (const [ctx] of vi.mocked(deleteFeatureRow).mock.calls) {
      expect(ctx).toMatchObject({ calcId: CALC, layerType: 'user_group' })
    }
    expect(vi.mocked(deleteFeatureRow).mock.calls.map((c) => c[0].featureId)).toEqual([
      '11',
      '12',
    ])

    expect(restoreFeatureRow).toHaveBeenCalledTimes(1)
    const [ctx, snapshot] = vi.mocked(restoreFeatureRow).mock.calls[0]
    expect(ctx).toMatchObject({ calcId: CALC, layerType: 'user_group', featureId: SOURCE_ID })
    expect(snapshot).toBe(SNAPSHOT)
  })

  it('deletes only what the cut created, and still restores the source', async () => {
    // The failure this replaces: a cut that created rows but an undo that skipped
    // deleting them, leaving the layer showing both the cut and the original.
    const op = userGroupCut()
    vi.mocked(deleteFeatureRow).mockClear()
    vi.mocked(restoreFeatureRow).mockClear()

    await undoCutServer(op)

    const deleted = vi.mocked(deleteFeatureRow).mock.calls.map((c) => c[0].featureId)
    expect(deleted).not.toContain(SOURCE_ID)
    expect(restoreFeatureRow).toHaveBeenCalledTimes(1)
  })

  it('still deletes the created rows when no source snapshot was captured', async () => {
    // The old "never a delete" case. Deleting the created rows is correct either
    // way; what is lost without a snapshot is only the ability to put the source
    // back, which the test states rather than hides.
    const op = createSplitOperation(
      'user_group', SOURCE_ID, polygon, line,
      [{ pieceId: '11', geometry: polygon, properties: {} }],
      'tester', undefined,
      { calcId: CALC, layerType: 'user_group', pieceIds: ['11'] },
    )
    await undoCutServer(op)

    expect(deleteFeatureRow).toHaveBeenCalledTimes(1)
    expect(restoreFeatureRow).not.toHaveBeenCalled()
  })
})
