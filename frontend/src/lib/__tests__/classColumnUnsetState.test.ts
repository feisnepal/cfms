// The unset state of a class cell must say something (owner decision,
// 2026-09-30: "The attribute table must not have blank which is now occuring.").
//
// Two separate failure modes are covered here, because they were confused until
// this point:
//
//  1. A READ-ONLY derived column returned '' for "not classified", so the cell
//     rendered blank -- indistinguishable from a missing field (D48) or from a
//     value that failed to load. Fixed in `NASA_QUALITY_RAW_COLUMN`.
//  2. An EDITABLE select column renders the empty-valued option that
//     `AttributeTable` injects (it must, so a value can be cleared). That option
//     used to read "-", which is not blank but says nothing: on a class column
//     "-" was ambiguous between "this source did not classify it" and "nobody has
//     chosen a value yet". `emptyLabelKey` gives it real text.
//
// The scope is deliberate: the four Auto-Block class columns get an explicit
// label, everything else keeps "-", which is right for an optional free-text
// field. And the option still saves `''`, so this is display text only -- it can
// never persist a value.
import { describe, it, expect } from 'vitest'
import {
  SLOPE_BAND_COLUMN,
  ASPECT_COLUMN,
  CANOPY_CLASS_COLUMN,
  NASA_QUALITY_COLUMN,
  NASA_QUALITY_RAW_COLUMN,
} from '../layerRegistry'

const CLASS_COLUMNS = [
  ['slope', SLOPE_BAND_COLUMN],
  ['aspect', ASPECT_COLUMN],
  ['canopy', CANOPY_CLASS_COLUMN],
  ['nasa', NASA_QUALITY_COLUMN],
] as const

describe('unset state of an Auto-Block class cell', () => {
  it('every editable class column carries an explicit unset label', () => {
    for (const [name, col] of CLASS_COLUMNS) {
      expect(col.emptyLabelKey, `${name} emptyLabelKey`).toBe('attributeTable.notSet')
    }
  })

  it('the label is an i18n key, not hardcoded English', () => {
    // The rest of these columns' option labels are still English-only (a
    // recorded gap). The unset label must not add to it: a Nepali user would
    // otherwise read one Nepali option among English ones.
    for (const [name, col] of CLASS_COLUMNS) {
      expect(col.emptyLabelKey, name).toMatch(/^[a-z][\w]*\.[\w.]+$/)
    }
  })

  it('the select options stay exactly the real choices', () => {
    // The unset state is the injected empty-valued option, NOT an entry in
    // `select` -- an entry there would render a second, duplicate blank option
    // and would risk persisting a value.
    expect(NASA_QUALITY_COLUMN.select!.map((o) => o.value)).toEqual(['1', '2', '3'])
    expect(SLOPE_BAND_COLUMN.select!.map((o) => o.value)).not.toContain('')
    expect(ASPECT_COLUMN.select!.map((o) => o.value)).not.toContain('')
    expect(CANOPY_CLASS_COLUMN.select!.map((o) => o.value)).not.toContain('')
  })

  it('the read-only derived column never returns an empty string', () => {
    const feat = (p: Record<string, unknown>) =>
      ({ type: 'Feature', geometry: null, properties: p }) as any
    const inputs: Array<Record<string, unknown>> = [
      { dominant_nasa_code: 0 },
      { dominant_nasa_code: 1 },
      { dominant_nasa_code: 2 },
      { dominant_nasa_code: 3 },
      { dominant_nasa_code: null },
      { dominant_nasa_quality: null },
      {},
    ]
    for (const p of inputs) {
      expect(NASA_QUALITY_RAW_COLUMN.getValue!(feat(p), 0), JSON.stringify(p)).not.toBe('')
    }
  })

  it('"Unclassified" and "Not determined" stay distinct', () => {
    // Code 0 means the raster classified this compartment and found it is not
    // forest. Null means the class was never worked out. Collapsing the two is
    // the exact bug D49 closed.
    const feat = (p: Record<string, unknown>) =>
      ({ type: 'Feature', geometry: null, properties: p }) as any
    expect(NASA_QUALITY_RAW_COLUMN.getValue!(feat({ dominant_nasa_code: 0 }), 0))
      .toContain('Unclassified')
    expect(NASA_QUALITY_RAW_COLUMN.getValue!(feat({ dominant_nasa_code: null }), 0))
      .not.toContain('Unclassified')
  })
})
