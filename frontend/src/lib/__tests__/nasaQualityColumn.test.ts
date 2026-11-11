// Owner report, 2026-09-30: "NASA is working fine but no value in attribute
// name and value."
//
// The carving, the persistence and the tile were all correct. The attribute
// table showed neither a column header nor any value, because
// `dominant_nasa_quality` was never registered as a ColumnDef and the three
// compartment-tree property mappers dropped the field on the way into
// `feature.properties` -- so even the JSON the backend correctly returned
// (compartments.py, blocks.py) never reached the cell.
//
// The backend half was already covered (test_feature_editing.py asserts the
// PATCH persists and the 1-3 bounds reject 4). Nothing asserted the FRONTEND
// half -- that a field the backend returns is actually rendered. Same failure
// shape as RS-2.10, one layer over: a value that is correct everywhere except
// the last hop, and untested at that hop.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  getLayerConfig,
  getLabelFieldsForLayer,
  NASA_QUALITY_COLUMN,
  NASA_QUALITY_LABEL,
  NASA_QUALITY_RAW_COLUMN,
  SLOPE_BAND_COLUMN,
  ASPECT_COLUMN,
  CANOPY_CLASS_COLUMN,
} from '../layerRegistry'

const CLASS_LAYERS = ['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const

describe('NASA forest-quality attribute column (owner report, 2026-09-30)', () => {
  it('is registered on every block/compartment layer, and only there', () => {
    for (const layerId of CLASS_LAYERS) {
      const cols = getLayerConfig(layerId)!.columns
      const byKey = Object.fromEntries(cols.map((c) => [c.key, c]))
      const col = byKey[NASA_QUALITY_COLUMN.key]
      expect(col, `${layerId} is missing the dominant_nasa_quality column`).toBeDefined()
      expect(col, `${layerId} must not share one column object across layers`).toBeDefined()
    }
  })

  it('is editable, like the other class columns', () => {
    // Every class column must stay hand-editable: P2's gate is that a user can
    // overrule the raster, and that is only possible from a dropdown in the
    // cell (AttributeTable's generic `editable` + `select` path).
    for (const c of [SLOPE_BAND_COLUMN, ASPECT_COLUMN, CANOPY_CLASS_COLUMN, NASA_QUALITY_COLUMN]) {
      expect(c.editable, `${c.key} must stay hand-editable (P2 gate: accept a hand edit)`).toBe(true);
      expect(c.select?.length, `${c.key} must offer its choices`).toBeGreaterThan(0);
    }
  })

  it('carries no visibility gate, so it is visible even when every block is unclassified', () => {
    // The owner's complaint: "NASA is working fine but no value in attribute
    // name and value." The column was `hideIfEmpty`, so on a forest where no
    // block carries a class the HEADER disappeared too -- the field looked
    // nonexistent and its dropdown was unreachable. See layerRegistry.test.ts
    // for the same guard across every layer.
    for (const c of [SLOPE_BAND_COLUMN, ASPECT_COLUMN, CANOPY_CLASS_COLUMN, NASA_QUALITY_COLUMN]) {
      const raw = c as unknown as Record<string, unknown>
      expect(raw.hideIfEmpty, `${c.key} must not be gated`).toBeUndefined()
      expect(raw.defaultHidden, `${c.key} must not be gated`).toBeUndefined()
    }
  })

  it('offers exactly the 1-3 classes the backend vocabulary defines, by RAW code', () => {
    // The select's `value` is the raw numeric code so it binds to
    // <option value=...>; the option's own label text is what renders in the
    // closed select. getValue must therefore return the code, not the label.
    expect(Object.keys(NASA_QUALITY_LABEL)).toEqual(['1', '2', '3'])
    expect(NASA_QUALITY_COLUMN.select!.map((o) => o.value)).toEqual(['1', '2', '3'])
    // Backend `forest_types.NASA_FOREST_QUALITY` is the authority. If a
    // backend rename lands, this fails and the pair is reconciled by hand.
    expect(NASA_QUALITY_LABEL).toEqual({
      1: 'Primary Forest',
      2: 'Young Secondary Forest',
      3: 'Old Secondary Forest',
    })
  })

  it('getValue renders a stored code and stays blank for an unclassified block', () => {
    const feat = (p: Record<string, unknown>) =>
      ({ type: 'Feature', geometry: null, properties: p }) as any
    expect(NASA_QUALITY_COLUMN.getValue!(feat({ dominant_nasa_quality: 2 }), 0)).toBe('2')
    // null (block not carved via NASA) and absent must BOTH be blank, never
    // the string "null" and never a misleading 0.
    expect(NASA_QUALITY_COLUMN.getValue!(feat({ dominant_nasa_quality: null }), 0)).toBe('')
    expect(NASA_QUALITY_COLUMN.getValue!(feat({}), 0)).toBe('')
  })

  it('every class column is a labelField, so map labels can use it', () => {
    for (const layerId of CLASS_LAYERS) {
      const fields = getLabelFieldsForLayer(layerId)
      expect(fields, `${layerId} labelFields`).toContain('dominant_nasa_quality')
    }
  })

  // -----------------------------------------------------------------------
  // RS-2.14 -- "why other polygon data is missing in preview?"
  // -----------------------------------------------------------------------
  describe('raw raster class (code 0 included)', () => {
    const feat = (p: Record<string, unknown>) =>
      ({ type: 'Feature', geometry: null, properties: p }) as any
    const raw = (p: Record<string, unknown>) => NASA_QUALITY_RAW_COLUMN.getValue!(feat(p), 0)

    it('is registered beside the class column on every class layer', () => {
      for (const layerId of CLASS_LAYERS) {
        const keys = getLayerConfig(layerId)!.columns.map((c) => c.key)
        expect(keys, `${layerId} columns`).toContain('dominant_nasa_code')
        expect(keys, `${layerId} columns`).toContain('dominant_nasa_quality')
      }
    })

    it('is read-only: the raw class is what the raster said, not a user choice', () => {
      expect(NASA_QUALITY_RAW_COLUMN.editable).toBeFalsy()
      expect(NASA_QUALITY_RAW_COLUMN.select).toBeUndefined()
      expect(NASA_QUALITY_COLUMN.editable).toBe(true)
    })

    it('says "Unclassified" for code 0 instead of leaving a blank cell', () => {
      // THE REPORTED BUG. A 0-dominated compartment used to render exactly like
      // an uncovered one, so "this is not forest" was unreadable.
      expect(raw({ dominant_nasa_code: 0 })).toBe('0 · Unclassified')
    })

    it('never renders a blank cell, for any input', () => {
      // Owner decision, 2026-09-30: "The attribute table must not have blank
      // which is now occuring." An empty cell reads as a missing field (D48) or
      // as a value that failed to load; all three states must be visible.
      for (const p of [
        { dominant_nasa_code: 0 },
        { dominant_nasa_code: 1 },
        { dominant_nasa_code: 2 },
        { dominant_nasa_code: 3 },
        { dominant_nasa_code: null, dominant_nasa_quality: null },
        { dominant_nasa_code: null },
        { dominant_nasa_quality: 2 },
        {},
        { dominant_nasa_code: undefined },
      ]) {
        const v = raw(p)
        expect(v, `input ${JSON.stringify(p)}`).not.toBe('')
        expect(v, `input ${JSON.stringify(p)}`).not.toBeNull()
        expect(v, `input ${JSON.stringify(p)}`).toBeTypeOf('string')
      }
    })

    it('the never-determined case says so, rather than implying no data', () => {
      // Code 0 is "Unclassified" -- data present, class present. The null case is
      // the only one where the class was never worked out, and it must not reuse
      // the same wording, or the two collapse back into one.
      expect(raw({ dominant_nasa_code: null })).toBe('Not determined')
      expect(raw({ dominant_nasa_code: null })).not.toContain('Unclassified')
    })

    it('labels the reported classes too, and never invents a 0', () => {
      expect(raw({ dominant_nasa_code: 1 })).toContain('Primary Forest')
      expect(raw({ dominant_nasa_code: 3 })).toContain('Old Secondary Forest')
      // A raw 0 must not be coerced into a false "no data".
      expect(raw({ dominant_nasa_code: 0 })).not.toBe('')
    })

    it('falls back to the reported column when only it is present', () => {
      expect(raw({ dominant_nasa_quality: 2 })).toContain('Young Secondary Forest')
    })

    it('prefers the raw column, which is the one that carries the 0', () => {
      // A block carved by an older build has no raw code; a block carved now has
      // both. The raw one is authoritative because it can say "Unclassified".
      expect(raw({ dominant_nasa_code: 0, dominant_nasa_quality: null })).toBe('0 · Unclassified')
    })

    it('an unknown code shows the raw number rather than blanking out', () => {
      expect(raw({ dominant_nasa_code: 9 })).toBe('9')
    })

    it('every class layer maps it out of the compartment tree', () => {
      const src = readFileSync(join(__dirname, '..', 'layerRegistry.ts'), 'utf8')
      const hits = [...src.matchAll(/dominant_nasa_code:\s*node\.dominant_nasa_code\s*\?\?\s*null,/g)]
      expect(hits.length, 'expected 3 tree-backed property mappers').toBe(3)
      for (const layerId of CLASS_LAYERS) {
        expect(getLabelFieldsForLayer(layerId), `${layerId} labelFields`)
          .toContain('dominant_nasa_code')
      }
    })
  })

  it('the compartment-tree mappers carry the field into feature.properties', () => {
    // The actual defect, guarded at the line that caused it. The three
    // tree-backed layers build `properties` from an explicit mapper rather
    // than a spread, so a field the backend returns still has to be listed.
    // `blocks` is absent here because it spreads `...b` and cannot drop it.
    const src = readFileSync(join(__dirname, '..', 'layerRegistry.ts'), 'utf8')
    const hits = [...src.matchAll(/dominant_slope_band:\s*node\.dominant_slope_band\s*\?\?\s*null,/g)]
    expect(hits.length, 'expected 3 tree-backed property mappers').toBe(3)
    hits.forEach((h, i) => {
      // Bound the window at the NEXT mapper's start, so a mapper missing the
      // line can never be masked by the following mapper having it.
      const end = i + 1 < hits.length ? hits[i + 1].index! : src.length
      const window = src.slice(h.index!, end)
      expect(window, `mapper missing dominant_nasa_quality: ${h[0]}`).toContain(
        'dominant_nasa_quality: node.dominant_nasa_quality ?? null,',
      )
    })
  })
})
