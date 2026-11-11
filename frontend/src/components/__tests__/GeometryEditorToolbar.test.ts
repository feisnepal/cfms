import { describe, it, expect } from 'vitest'
import { toolbarModesForPurpose, geomAllow, geometryTypesForTool } from '../GeometryEditorToolbar'

describe('GeometryEditorToolbar purpose filtering (GD 2.2.1)', () => {
  it('inventory → point draw mode only', () => {
    expect(toolbarModesForPurpose('inventory')).toEqual(['draw_point'])
  })

  it('roads → line draw mode only', () => {
    expect(toolbarModesForPurpose('roads')).toEqual(['draw_line'])
  })

  it('water → line + polygon', () => {
    expect(toolbarModesForPurpose('water')).toEqual(['draw_line', 'draw_polygon'])
  })

  it('other → all three draw modes', () => {
    expect(toolbarModesForPurpose('other')).toEqual(['draw_point', 'draw_line', 'draw_polygon'])
  })

  it('sample_plot and blocks → polygon (boundary-style purpose)', () => {
    expect(toolbarModesForPurpose('sample_plot')).toEqual(['draw_point'])
    expect(toolbarModesForPurpose('blocks')).toEqual(['draw_polygon'])
  })

  it('unknown purpose → empty (no tools offered)', () => {
    expect(toolbarModesForPurpose('bogus')).toEqual([])
  })

  it('never includes split/merge/vertex/category modes', () => {
    for (const p of ['inventory', 'roads', 'water', 'other']) {
      for (const m of toolbarModesForPurpose(p)) {
        expect(['split', 'merge', 'vertex_edit', 'subarea_category']).not.toContain(m)
      }
    }
  })
})

describe('GeometryEditorToolbar geomAllow (UE-0.2 geometry-driven gate)', () => {
  it('universal tool (empty allowed types) applies on any geometry', () => {
    expect(geomAllow(['Polygon'], [])).toBe(true)
    expect(geomAllow(['Point'], [])).toBe(true)
    expect(geomAllow([], [])).toBe(true)
  })

  it('split applies to polygon + line layers, not point layers', () => {
    const split = geometryTypesForTool('split')
    expect(geomAllow(['Polygon'], split)).toBe(true)
    expect(geomAllow(['LineString'], split)).toBe(true)
    expect(geomAllow(['Point'], split)).toBe(false)
  })

  it('merge applies only to polygon layers', () => {
    const merge = geometryTypesForTool('merge')
    expect(geomAllow(['Polygon', 'MultiPolygon'], merge)).toBe(true)
    expect(geomAllow(['LineString'], merge)).toBe(false)
    expect(geomAllow(['Point'], merge)).toBe(false)
  })

  it('move applies only to point layers — never polygons or lines', () => {
    const move = geometryTypesForTool('move')
    expect(move).toEqual(['Point', 'MultiPoint'])
    expect(geomAllow(['Point'], move)).toBe(true)
    expect(geomAllow(['MultiPoint'], move)).toBe(true)
    expect(geomAllow(['Polygon', 'MultiPolygon'], move)).toBe(false)
    expect(geomAllow(['LineString', 'MultiLineString'], move)).toBe(false)
  })

  it('vertex_edit applies to polygons and lines, not points', () => {
    const vertex = geometryTypesForTool('vertex_edit')
    expect(geomAllow(['Polygon'], vertex)).toBe(true)
    expect(geomAllow(['LineString'], vertex)).toBe(true)
    expect(geomAllow(['Point'], vertex)).toBe(false)
  })

  it('draw_point only for point layers, draw_line only for lines', () => {
    expect(geomAllow(['Point'], geometryTypesForTool('draw_point'))).toBe(true)
    expect(geomAllow(['Polygon'], geometryTypesForTool('draw_point'))).toBe(false)
    expect(geomAllow(['LineString'], geometryTypesForTool('draw_line'))).toBe(true)
    expect(geomAllow(['Point'], geometryTypesForTool('draw_line'))).toBe(false)
  })
})
