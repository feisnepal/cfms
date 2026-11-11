/**
 * VR-2 — frontend half of the vertex-classification CONTRACT.
 *
 * Reads `tests/fixtures/vertex_contract.json` at the repo root — the SAME file
 * `backend/tests/services/test_vertex_classification_contract.py` reads — and
 * asserts this mirror produces exactly the recorded index sets.
 *
 * Why: every bug in this feature so far was two components disagreeing about
 * the same coordinate (F-5 marker keys, F-8 partner radius, F-9 capture
 * precision, F-10 shell anchor).  `vertexClassifier.ts` is a hand-written
 * mirror of a Python engine and nothing forced the two to agree; before VR-2
 * they indexed holes differently (D-3).  Changing one side without the other
 * now fails CI on BOTH sides rather than in the browser.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Geometry } from 'geojson'
import { classifyVertices, iterVertices, type ClassifiableLayerType } from '../vertexClassifier'

// frontend/src/lib/__tests__/… → repo root
const FIXTURE = join(__dirname, '..', '..', '..', '..', 'tests', 'fixtures', 'vertex_contract.json')

interface ContractCase {
  name: string
  why: string
  layer_type: ClassifiableLayerType
  geometry: Geometry
  same_level_features?: Array<{ id: string; geometry: Geometry }>
  parent_shell?: Geometry | null
  expected: { shared: number[]; shell: number[]; editable: number[]; vertex_count: number }
}

const cases: ContractCase[] = JSON.parse(readFileSync(FIXTURE, 'utf8')).cases

describe('vertexClassifier — backend contract', () => {
  it('reads the shared fixture the backend suite reads', () => {
    expect(cases.length).toBeGreaterThanOrEqual(8)
    for (const c of cases) {
      expect(c.name, 'every case is named').toBeTruthy()
      expect(c.why, `${c.name} explains what it pins`).toBeTruthy()
    }
  })

  it.each(cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    const result = classifyVertices(c.geometry, {
      layerType: c.layer_type,
      sameLevelFeatures: c.same_level_features ?? [],
      parentShell: c.parent_shell ?? null,
    })
    expect(result.shared).toEqual(c.expected.shared)
    expect(result.shell).toEqual(c.expected.shell)
    expect(result.editable).toEqual(c.expected.editable)
    expect(result.vertexCount).toEqual(c.expected.vertex_count)
  })

  it('holes contribute no indices (D-3)', () => {
    const c = cases.find((x) => x.name === 'polygon_with_hole')!
    expect((c.geometry as any).coordinates).toHaveLength(2) // fixture really has a hole
    // 4 exterior corners only — the pre-VR-2 mirror walked all rings and got 8.
    expect(iterVertices(c.geometry)).toHaveLength(4)
    expect(classifyVertices(c.geometry, {
      layerType: c.layer_type,
      sameLevelFeatures: c.same_level_features ?? [],
      parentShell: c.parent_shell ?? null,
    }).vertexCount).toBe(4)
  })

  it('MultiPolygon indices run across parts in order', () => {
    const c = cases.find((x) => x.name === 'multipolygon_two_parts')!
    const verts = iterVertices(c.geometry)
    expect(verts).toHaveLength(8)
    expect(verts.map(([i]) => i)).toEqual([0, 1, 2, 3, 4, 5, 6, 7])
    // Only the second part touches the neighbour.
    const result = classifyVertices(c.geometry, {
      layerType: c.layer_type,
      sameLevelFeatures: c.same_level_features ?? [],
      parentShell: c.parent_shell ?? null,
    })
    expect(result.shared.every((i) => i >= 4)).toBe(true)
  })
})
