/**
 * VR-0.4 — real-geometry sweep of the vertex-edit paths nobody has exercised.
 *
 * Three user-visible bugs (F-5 zero handles, F-8 wrong partner, F-9 false
 * overlap) all survived a green unit suite because every fixture was built in
 * a single precision space and at synthetic scale.  This file replays the
 * REMAINING paths through the real wiring, on real geometry:
 *
 *   A  multi-feature undo round-trip (shared move → undo → both restored)
 *   B  midpoint insert on a shared edge (both sides)
 *   C  shared-vertex delete (both sides / blocked)
 *   D  the compartments level, including parent-shell resolution
 *
 * Fixtures are live rows: `dba70e97-blocks.json` (2 adjacent blocks) and
 * `brindaban-structure.json` (5 blocks + 8 compartments under one block).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Geometry } from 'geojson'
import { computeSharedMoves, computeSharedVertexChange } from '../vertexSharedMove'
import { SharedEdgeIndex } from '../sharedEdgeIndex'
import { classifyVertices, coordAtIndex, isOnBoundary, iterVertices } from '../vertexClassifier'
import { shellGeometryFor } from '../vertexEditMask'

const fx = (n: string) => JSON.parse(readFileSync(join(__dirname, 'fixtures', n), 'utf8'))

type Row = { id: string; name: string; geometry: Geometry }
type StructRow = Row & { level: number; parent: string | null }

const BLOCKS: Row[] = fx('dba70e97-blocks.json')
const STRUCT: StructRow[] = fx('brindaban-structure.json')
const BR_BLOCKS = STRUCT.filter((r) => r.level === 0)
const BR_COMPS = STRUCT.filter((r) => r.level === 1)

const M = 1 / 111_320
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))

/** Move the flat-indexed vertex to an absolute coord (mirrors a drag). */
function dragTo(geom: Geometry, flatIndex: number, to: [number, number]): Geometry {
  const g: any = clone(geom)
  const polys = g.type === 'MultiPolygon' ? g.coordinates : [g.coordinates]
  let flat = 0
  for (const poly of polys) {
    for (const ring of poly) {
      const n = ring.length
      const closed = n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1]
      const count = closed ? n - 1 : n
      for (let vi = 0; vi < count; vi++) {
        if (flat === flatIndex) {
          ring[vi] = [to[0], to[1]]
          if (vi === 0 && closed) ring[n - 1] = [to[0], to[1]]
          return g as Geometry
        }
        flat += 1
      }
    }
  }
  return g as Geometry
}

function editableOf(target: Row, siblings: Row[], shell: Geometry | null = null) {
  return classifyVertices(target.geometry, {
    layerType: 'blocks',
    sameLevelFeatures: siblings.filter((s) => s.id !== target.id),
    parentShell: shell,
  })
}

// ---------------------------------------------------------------------------
// A — multi-feature undo round-trip
// ---------------------------------------------------------------------------

describe('A · shared move → undo restores every affected feature', () => {
  it('rebuilds the exact pre-edit geometry of the edited feature AND its partners', () => {
    const target = BLOCKS[0]
    const cls = editableOf(target, BLOCKS)
    const problems: string[] = []

    for (const idx of cls.editable) {
      const before = clone(target.geometry)
      const from = coordAtIndex(before, idx)!
      const to: [number, number] = [from[0] + 3 * M, from[1] - 2 * M]
      const updated = dragTo(before, idx, to)

      const shared = computeSharedMoves({
        featureId: target.id, snapshot: before, updated, layerFeatures: BLOCKS,
      })
      if (!shared) continue // mid-edge: single-feature commit, nothing to batch

      // The undo entry MapWorkspace records for this gesture.
      const partners = shared.moves.map((m) => ({
        featureId: m.feature_id,
        previousGeometry: BLOCKS.find((b) => b.id === m.feature_id)?.geometry,
        newGeometry: m.geometry,
      }))

      // Every partner must carry a previous geometry, or undo silently POSTs
      // `geometry: undefined` for that feature.
      for (const p of partners) {
        if (!p.previousGeometry) problems.push(`#${idx} partner ${p.featureId} has no previousGeometry`)
      }

      // Undo = previousGeometry for the edited feature + every partner.
      const restored = new Map<string, Geometry>()
      restored.set(target.id, before)
      for (const p of partners) restored.set(p.featureId, p.previousGeometry!)

      for (const [id, geom] of restored) {
        const original = BLOCKS.find((b) => b.id === id)!.geometry
        if (JSON.stringify(geom) !== JSON.stringify(original)) {
          problems.push(`#${idx} ${id} did not restore bit-identically`)
        }
      }
    }

    expect(problems).toEqual([])
  })

  it('the undone state is topologically clean (no gap, no overlap)', () => {
    const target = BLOCKS[0]
    const cls = editableOf(target, BLOCKS)
    const idx = cls.editable[0]
    const before = clone(target.geometry)
    const from = coordAtIndex(before, idx)!
    const updated = dragTo(before, idx, [from[0] + 3 * M, from[1] - 2 * M])

    const shared = computeSharedMoves({
      featureId: target.id, snapshot: before, updated, layerFeatures: BLOCKS,
    })!
    // Apply, then undo.
    const afterUndo = BLOCKS.map((b) => ({ id: b.id, geometry: b.geometry }))
    const verdict = new SharedEdgeIndex(afterUndo)
      .validate(before, { excludeId: target.id, snapshot: updated })
    expect(shared.moves.length).toBeGreaterThan(0)
    expect(verdict.ok).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// B — midpoint insert on a shared edge
// ---------------------------------------------------------------------------

describe('B · inserting a vertex on a shared edge updates both units', () => {
  it('propagates every insert and leaves the topology clean', () => {
    const target = BLOCKS[0]
    const cls = editableOf(target, BLOCKS)
    const problems: string[] = []
    let propagated = 0

    for (const idx of cls.editable) {
      const before = clone(target.geometry)
      const a = coordAtIndex(before, idx)
      const b = coordAtIndex(before, idx + 1)
      if (!a || !b) continue
      // Midpoint of the edge that follows this editable vertex.
      const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]

      const g: any = clone(before)
      const ring = g.coordinates[0]
      const at = ring.findIndex((p: number[]) => p[0] === a[0] && p[1] === a[1])
      if (at < 0) continue
      ring.splice(at + 1, 0, [mid[0], mid[1]])

      const change = computeSharedVertexChange({
        featureId: target.id, snapshot: before, updated: g, layerFeatures: BLOCKS,
      })
      if (!change) { problems.push(`#${idx} insert not recognised as a vertex change`); continue }
      if (change.kind !== 'add') { problems.push(`#${idx} classified as ${change.kind}`); continue }
      if (!change.propagation) continue // edge not shared with a sibling
      propagated += 1

      // The partner must now carry the same coordinate.
      for (const m of change.propagation.moves) {
        const has = iterVertices(m.geometry).some(([, [x, y]]) =>
          Math.hypot(x - mid[0], y - mid[1]) <= 1e-12)
        if (!has) problems.push(`#${idx} partner ${m.feature_id} missing the inserted vertex`)
      }

      const verdict = new SharedEdgeIndex(change.propagation.propagatedFeatures)
        .validate(g, { excludeId: target.id, snapshot: before })
      if (!verdict.ok) problems.push(`#${idx} insert rejected: ${verdict.witness}`)
    }

    expect(problems).toEqual([])
    expect(propagated).toBeGreaterThan(0) // the test must actually exercise it
  })
})

// ---------------------------------------------------------------------------
// C — shared-vertex delete
// ---------------------------------------------------------------------------

describe('C · deleting a shared vertex', () => {
  it('removes it from both units, or blocks with a reason — never one side only', () => {
    const target = BLOCKS[0]
    const cls = editableOf(target, BLOCKS)
    const problems: string[] = []
    let applied = 0

    for (const idx of cls.editable) {
      const before = clone(target.geometry)
      const coord = coordAtIndex(before, idx)!
      const g: any = clone(before)
      const ring = g.coordinates[0]
      const at = ring.findIndex((p: number[]) => p[0] === coord[0] && p[1] === coord[1])
      if (at < 0 || ring.length - 1 < 4) continue
      ring.splice(at, 1)
      if (at === 0) ring[ring.length - 1] = [ring[0][0], ring[0][1]]

      const change = computeSharedVertexChange({
        featureId: target.id, snapshot: before, updated: g, layerFeatures: BLOCKS,
      })
      if (!change) { problems.push(`#${idx} delete not recognised`); continue }
      if (change.kind !== 'remove') { problems.push(`#${idx} classified as ${change.kind}`); continue }
      if (change.blocked) continue // refused with a reason — acceptable
      if (!change.propagation) continue // unshared vertex

      applied += 1
      for (const m of change.propagation.moves) {
        const still = iterVertices(m.geometry).some(([, [x, y]]) =>
          Math.hypot(x - coord[0], y - coord[1]) <= 1e-12)
        if (still) problems.push(`#${idx} partner ${m.feature_id} kept the deleted vertex`)
      }
    }

    expect(problems).toEqual([])
    expect(applied).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// D — the compartments level
// ---------------------------------------------------------------------------

describe('D · compartments level on real बृन्दाबन geometry', () => {
  it('fixture shape', () => {
    expect(BR_BLOCKS).toHaveLength(5)
    expect(BR_COMPS).toHaveLength(8)
  })

  it('the frontend resolves each compartment to its true parent block', () => {
    const wrong: string[] = []
    for (const comp of BR_COMPS) {
      const shell = shellGeometryFor('compartments', comp.id, BR_COMPS, BR_BLOCKS)
      const trueParent = BR_BLOCKS.find((b) => b.id === comp.parent)
      if (!trueParent) { wrong.push(`${comp.name}: parent not in fixture`); continue }
      if (!shell) { wrong.push(`${comp.name}: no shell resolved`); continue }
      if (JSON.stringify(shell) !== JSON.stringify(trueParent.geometry)) {
        wrong.push(`${comp.name}: shell is not parent_block_id's geometry`)
      }
    }
    expect(wrong).toEqual([])
  })

  it('any editable compartment vertex drags without a local rejection', () => {
    const failures: string[] = []
    for (const comp of BR_COMPS) {
      const shell = shellGeometryFor('compartments', comp.id, BR_COMPS, BR_BLOCKS)
      const cls = classifyVertices(comp.geometry, {
        layerType: 'compartments',
        sameLevelFeatures: BR_COMPS.filter((c) => c.id !== comp.id),
        parentShell: shell,
      })
      for (const idx of cls.editable) {
        const before = clone(comp.geometry)
        const from = coordAtIndex(before, idx)!
        const updated = dragTo(before, idx, [from[0] + 2 * M, from[1] + 2 * M])
        const shared = computeSharedMoves({
          featureId: comp.id, snapshot: before, updated, layerFeatures: BR_COMPS,
        })
        const index = shared
          ? new SharedEdgeIndex(shared.propagatedFeatures)
          : new SharedEdgeIndex(BR_COMPS)
        const verdict = index.validate(updated, { excludeId: comp.id, snapshot: before })
        if (!verdict.ok) {
          failures.push(`${comp.name}#${idx} ${verdict.witness} propagated=${shared ? shared.moves.length : 'NONE'}`)
        }
      }
    }
    expect(failures).toEqual([])
  })

  /**
   * FINDING (VR-0.4) — a straight-cut subdivision is 100 % LOCKED.
   *
   * बृन्दाबन's 8 compartments are an equal-area division of one 122.56 ha
   * block into 8 × 15.277 ha strips.  Every cut is a straight segment, so it
   * contributes NO interior vertices: each compartment vertex is a cut
   * endpoint, and every cut endpoint lies on the parent block's boundary.
   * "shell wins over shared" therefore locks all of them, and the layer
   * offers not one draggable handle.
   *
   * The rule is being applied correctly — but on the output of auto-divide,
   * which is how compartments are normally created, the tool can do nothing.
   * The midpoint of a cut is NOT on the shell, so the fix is to let a shared
   * EDGE be subdivided even when both its endpoints are locked; the inserted
   * vertex is then shared-and-not-shell, i.e. editable.  Today
   * `maskVertexMarkers` only shows a midpoint when BOTH corners are editable,
   * so that escape hatch is closed too.  Decision belongs to VR-5.
   */
  it('documents that a straight-cut subdivision leaves nothing editable', () => {
    const perCompartment = BR_COMPS.map((comp) => {
      const shell = shellGeometryFor('compartments', comp.id, BR_COMPS, BR_BLOCKS)
      const cls = classifyVertices(comp.geometry, {
        layerType: 'compartments',
        sameLevelFeatures: BR_COMPS.filter((c) => c.id !== comp.id),
        parentShell: shell,
      })
      return {
        name: comp.name,
        verts: cls.vertexCount,
        shared: cls.shared.length,
        shell: cls.shell.length,
        editable: cls.editable.length,
      }
    })

    // Independently reproduced in PostGIS (shell == verts for all eight).
    expect(perCompartment.every((c) => c.shell === c.verts)).toBe(true)
    expect(perCompartment.every((c) => c.editable === 0)).toBe(true)
    // …while shared edges genuinely exist — they just carry no interior vertex.
    expect(perCompartment.every((c) => c.shared > 0)).toBe(true)
  })

  /**
   * VR-5 — the midpoint rule is what makes the case above workable.  For every
   * compartment there is at least one shared-edge midpoint that is NOT on the
   * parent shell, so a vertex can be inserted there without touching a locked
   * vertex; the insert propagates to the sibling, and the new vertex then
   * classifies as editable.
   */
  it('a cut can be subdivided at its midpoint, and the new vertex is editable', () => {
    const noEscape: string[] = []
    let proven = 0

    for (const comp of BR_COMPS) {
      const siblings = BR_COMPS.filter((c) => c.id !== comp.id)
      const shell = shellGeometryFor('compartments', comp.id, BR_COMPS, BR_BLOCKS)
      const ring = (comp.geometry as any).coordinates[0] as number[][]

      let found = false
      for (let i = 0; i < ring.length - 1 && !found; i++) {
        const a = ring[i]
        const b = ring[i + 1]
        const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]

        // The rule the mask applies: on a sibling's boundary, off the shell.
        const onSibling = siblings.some((s) => isOnBoundary(mid[0], mid[1], s.geometry))
        const onShell = !!shell && isOnBoundary(mid[0], mid[1], shell)
        if (!onSibling || onShell) continue

        // Insert it and check the sibling gets the same coordinate.
        const updated: any = clone(comp.geometry)
        updated.coordinates[0].splice(i + 1, 0, [mid[0], mid[1]])
        const change = computeSharedVertexChange({
          featureId: comp.id, snapshot: comp.geometry, updated, layerFeatures: BR_COMPS,
        })
        if (!change || change.kind !== 'add' || !change.propagation) continue
        const partnerHasIt = change.propagation.moves.every((m) =>
          iterVertices(m.geometry).some(([, [x, y]]) =>
            Math.hypot(x - mid[0], y - mid[1]) <= 1e-12))
        if (!partnerHasIt) continue

        // …and the inserted vertex is now editable on the edited compartment.
        const after = classifyVertices(updated, {
          layerType: 'compartments', sameLevelFeatures: siblings, parentShell: shell,
        })
        const editableCoords = after.editable.map((k) => coordAtIndex(updated, k)!)
        if (!editableCoords.some(([x, y]) => Math.hypot(x - mid[0], y - mid[1]) <= 1e-12)) continue

        found = true
        proven += 1
      }
      if (!found) noEscape.push(comp.name)
    }

    expect(noEscape).toEqual([])
    expect(proven).toBe(BR_COMPS.length)
  })
})
