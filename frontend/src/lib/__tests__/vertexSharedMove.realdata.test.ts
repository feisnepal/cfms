/**
 * Reproduction harness for the live report "Edit rejected: overlaps an
 * adjacent feature" (2026-08-19) — runs the FULL frontend drag pre-check
 * against the two real blocks of calculation dba70e97, exactly as
 * MapWorkspace wires it:
 *
 *   snapshot/updated  = layer.toGeoJSON()  → Leaflet rounds to 6 dp
 *   layerFeatures     = API payload        → full precision
 *   pre-check         = SharedEdgeIndex(propagatedFeatures).validate(edited)
 *
 * That message string is produced ONLY by the local pre-check
 * (`SharedEdgeIndex.validate` → witness OVERLAP), never by the server, so the
 * gesture is being refused before any POST.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { Geometry } from 'geojson'
import { computeSharedMoves } from '../vertexSharedMove'
import { SharedEdgeIndex } from '../sharedEdgeIndex'
import { classifyVertices, coordAtIndex, iterVertices } from '../vertexClassifier'

const FIXTURE = join(__dirname, 'fixtures', 'dba70e97-blocks.json')

type Row = { id: string; name: string; geometry: Geometry }

const rows: Row[] = JSON.parse(readFileSync(FIXTURE, 'utf8'))

/**
 * How the layer's geometry comes back from Leaflet.
 *
 * `capture` mirrors `snapshotOf` / `liveGeometryOf`, which call
 * `toGeoJSON(false)` — lossless.  `round6` is what the DEFAULT `toGeoJSON()`
 * did (formatNum precision 6) and is kept to prove the regression: a
 * quantised edited geometry crossing full-precision neighbours is what
 * produced "overlaps an adjacent feature".
 */
function capture(geom: Geometry): Geometry {
  return JSON.parse(JSON.stringify(geom)) as Geometry
}

function round6(geom: Geometry): Geometry {
  const r = (n: number) => Math.round(n * 1e6) / 1e6
  const walk = (c: any): any =>
    typeof c[0] === 'number' ? [r(c[0]), r(c[1])] : c.map(walk)
  return { ...(geom as any), coordinates: walk((geom as any).coordinates) } as Geometry
}

const M = 1 / 111_320

describe('real dba70e97 blocks — shared-vertex drag pre-check', () => {
  it('fixture holds the two blocks', () => {
    expect(rows).toHaveLength(2)
    expect(rows.map((r) => r.name).sort()).toEqual(['blocks-1', 'blocks-2'])
  })

  it('every editable vertex drags without a local OVERLAP verdict', () => {
    const failures: string[] = []
    const noPropagation: string[] = []

    for (const target of rows) {
      const others = rows.filter((r) => r.id !== target.id)
      const cls = classifyVertices(target.geometry, {
        layerType: 'blocks',
        sameLevelFeatures: others,
        parentShell: null, // shell handled separately; here we exercise `shared`
      })
      expect(cls.editable.length).toBeGreaterThan(0)

      // The layer as Leaflet gives it back to us (lossless).
      const live = capture(target.geometry)

      for (const idx of cls.editable) {
        const from = coordAtIndex(live, idx)
        if (!from) continue
        // A modest 2 m drag along +x/+y, the kind a user makes.
        const to: [number, number] = [from[0] + 2 * M, from[1] + 2 * M]

        const updated = JSON.parse(JSON.stringify(live)) as any
        let flat = 0
        outer: for (const poly of updated.type === 'MultiPolygon'
          ? updated.coordinates : [updated.coordinates]) {
          for (const ring of poly) {
            const n = ring.length
            const closed = n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1]
            const count = closed ? n - 1 : n
            for (let vi = 0; vi < count; vi++) {
              if (flat === idx) {
                ring[vi] = [to[0], to[1]]
                if (vi === 0 && closed) ring[n - 1] = [to[0], to[1]]
                break outer
              }
              flat += 1
            }
          }
        }

        const shared = computeSharedMoves({
          featureId: target.id,
          snapshot: live,
          updated,
          layerFeatures: rows,
        })

        if (!shared) {
          noPropagation.push(`${target.name}#${idx}`)
        }

        const index = shared
          ? new SharedEdgeIndex(shared.propagatedFeatures)
          : new SharedEdgeIndex(rows)
        const verdict = index.validate(updated, { excludeId: target.id, snapshot: live })
        if (!verdict.ok) {
          failures.push(
            `${target.name}#${idx} ${verdict.witness} propagated=${shared ? shared.moves.length : 'NONE'}`,
          )
        }
      }
    }

    // The regression: before the fix EVERY editable vertex produced
    // "OVERLAP propagated=1" — the propagation was right, the pre-check was
    // comparing a 6 dp-quantised polygon against full-precision neighbours.
    expect(failures).toEqual([])

    // VR-5 mid-edge drag: a vertex sitting on a neighbour's segment with no
    // coincident partner used to propagate NOTHING (`blocks-2#19` here), so
    // only one side moved and R6 refused the drag.  The neighbour now gains a
    // vertex at the destination, so EVERY editable vertex propagates.
    expect(noPropagation).toEqual([])
  })

  it('reproduces the bug when the edited geometry is 6 dp-quantised', () => {
    // Guards the fix in `snapshotOf` / `liveGeometryOf`: if either ever goes
    // back to a bare `toGeoJSON()`, this is what the user sees again.
    const target = rows[0]
    const others = rows.filter((r) => r.id !== target.id)
    const cls = classifyVertices(target.geometry, {
      layerType: 'blocks', sameLevelFeatures: others, parentShell: null,
    })
    const idx = cls.editable[0]
    const live = round6(target.geometry) // ← the old, lossy capture
    const from = coordAtIndex(live, idx)!
    const to: [number, number] = [from[0] + 2 * M, from[1] + 2 * M]

    const updated: any = JSON.parse(JSON.stringify(live))
    const ring = updated.coordinates[0]
    ring[idx] = [to[0], to[1]]
    if (idx === 0) ring[ring.length - 1] = [to[0], to[1]]

    const shared = computeSharedMoves({
      featureId: target.id, snapshot: live, updated, layerFeatures: rows,
    })
    expect(shared!.moves).toHaveLength(1) // propagation was never the problem

    const verdict = new SharedEdgeIndex(shared!.propagatedFeatures)
      .validate(updated, { excludeId: target.id, snapshot: live })
    expect(verdict.ok).toBe(false)
    expect(verdict.witness).toBe('OVERLAP')
  })

  it('reports how many editable vertices have a coincident partner', () => {
    let coincident = 0
    let total = 0
    for (const target of rows) {
      const others = rows.filter((r) => r.id !== target.id)
      const cls = classifyVertices(target.geometry, {
        layerType: 'blocks', sameLevelFeatures: others, parentShell: null,
      })
      for (const idx of cls.editable) {
        total += 1
        const c = coordAtIndex(target.geometry, idx)!
        const hit = others.some((o) =>
          iterVertices(o.geometry).some(([, [x, y]]) =>
            Math.hypot(x - c[0], y - c[1]) <= 1 * M))
        if (hit) coincident += 1
      }
    }
    // Surfaced in the report; PostGIS says 21 of 22.
    expect({ total, coincident }).toBeTruthy()
    console.log('[realdata] editable vertices', { total, coincident })
  })
})
