import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  getAllLayerConfigs,
  getLayerConfig,
  isBuiltinLayerId,
  getLabelFieldsForLayer,
  SLOPE_BAND_COLUMN,
  ASPECT_COLUMN,
  CANOPY_CLASS_COLUMN,
  MANAGEMENT_ORIENTATION_COLUMN,
  SUGGESTED_ORIENTATION_COLUMN,
  ORIENTATION_JUSTIFICATION_COLUMN,
} from '../layerRegistry'
import { STYLE_PRESETS } from '../layerStyles'

describe('user-editability of non-geometry attributes (user report, 2026-09-12)', () => {
  it('name/natural_name/compartment_code are editable on all four unit layers alike (FS-4a.16: sub_blocks joins)', () => {
    for (const layerId of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const) {
      const cols = getLayerConfig(layerId)!.columns
      const byKey = Object.fromEntries(cols.map((c) => [c.key, c]))
      expect(byKey.name?.editable, `${layerId}.name`).toBe(true)
      // Block-branch layers have no compartment code column (a block/
      // sub-block is never coded) — only compartments/sub_compartments
      // carry compartment_code.
      if (layerId !== 'blocks' && layerId !== 'sub_blocks') {
        expect(byKey.compartment_code?.editable, `${layerId}.compartment_code`).toBe(true)
      }
      expect(byKey.natural_name?.editable, `${layerId}.natural_name`).toBe(true)
    }
  })

  it('the 3 classification columns offer a select dropdown of their valid codes, everywhere they appear', () => {
    for (const col of [SLOPE_BAND_COLUMN, ASPECT_COLUMN, CANOPY_CLASS_COLUMN]) {
      expect(col.editable).toBe(true)
      expect(col.select?.length).toBeGreaterThan(0)
      // No blank option in `select` itself — AttributeTable always injects
      // one; a real code's value is a plain numeric string, and its label
      // is a human-readable one, not the bare code.
      for (const opt of col.select!) {
        expect(opt.value).toMatch(/^\d+$/)
        expect(opt.label).not.toBe(opt.value)
      }
      // getValue returns the raw code (matches a select option's value),
      // not the display label — the option's own text is what renders.
      const firstCode = col.select![0].value
      const feature = { properties: { [col.key]: Number(firstCode) } } as never
      expect(col.getValue!(feature, 0)).toBe(firstCode)
      // Unset → '' (matches AttributeTable's own injected blank option).
      expect(col.getValue!({ properties: {} } as never, 0)).toBe('')
    }
  })

  it('Management Orientation / Suggested Orientation columns appear on all 4 unit layers, scoped to slope-carved features', () => {
    for (const layerId of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const) {
      const cols = getLayerConfig(layerId)!.columns
      const byKey = Object.fromEntries(cols.map((c) => [c.key, c]))
      expect(byKey.management_orientation?.editable, `${layerId}.management_orientation`).toBe(true)
      expect(byKey.management_orientation?.select?.length).toBeGreaterThan(0)
      expect(byKey.suggested_orientation, `${layerId}.suggested_orientation`).toBeDefined()
      expect(byKey.suggested_orientation?.editable).toBeFalsy()
    }

    // Not slope-carved -> both columns report null (hidden by hideIfEmpty
    // unless another feature in the list IS slope-carved).
    const notCarved = { properties: {} } as never
    expect(MANAGEMENT_ORIENTATION_COLUMN.getValue!(notCarved, 0)).toBeNull()
    expect(SUGGESTED_ORIENTATION_COLUMN.getValue!(notCarved, 0)).toBeNull()

    // Slope-carved -> real values surface.
    const carved = {
      properties: { dominant_slope_band: 3, management_orientation: 'Production', suggested_orientation: 'Conservation' },
    } as never
    expect(MANAGEMENT_ORIENTATION_COLUMN.getValue!(carved, 0)).toBe('Production')
    expect(SUGGESTED_ORIENTATION_COLUMN.getValue!(carved, 0)).toBe('Conservation')
  })

  it('compartments/sub_compartments dataSource.fetch actually threads management_orientation/suggested_orientation into feature properties', async () => {
    // Regression: the backend compartment-tree node already carried both
    // fields, but the frontend's tree-flattening (extractCompartments/
    // extractSubCompartments) built `properties` field-by-field and had
    // never been updated to copy these two across -- so the column
    // definitions were correct in isolation (tested above) but every real
    // feature had `undefined` for them, and hideIfEmpty correctly (if
    // unhelpfully) hid the columns everywhere. `blocks` was unaffected
    // because its fetch spreads the whole response object (`...b`).
    const node = {
      id: 'c1', name: 'Compartment-1', is_compartment: true, division_level: 1,
      area_hectares: 5, geometry: { type: 'Polygon', coordinates: [] },
      dominant_slope_band: 3,
      management_orientation: 'Production',
      suggested_orientation: 'Conservation',
      children: [],
    }
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ blocks: [node] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    for (const layerId of ['compartments', 'sub_compartments'] as const) {
      const nodeAtRightLevel = { ...node, division_level: layerId === 'compartments' ? 1 : 2 }
      fetchMock.mockResolvedValue({ json: async () => ({ blocks: [nodeAtRightLevel] }) })
      const features = await getLayerConfig(layerId)!.dataSource.fetch('calc-1')
      expect(features, layerId).toHaveLength(1)
      expect(features[0].properties?.management_orientation, layerId).toBe('Production')
      expect(features[0].properties?.suggested_orientation, layerId).toBe('Conservation')
    }

    vi.unstubAllGlobals()
  })

  it('Suggested Orientation renders a mismatch warning only when it disagrees with the confirmed value', () => {
    const agree = {
      properties: { dominant_slope_band: 1, management_orientation: 'Production', suggested_orientation: 'Production' },
    } as never
    const disagree = {
      properties: { dominant_slope_band: 1, management_orientation: 'Production', suggested_orientation: 'Conservation' },
    } as never
    const agreeEl = SUGGESTED_ORIENTATION_COLUMN.render!('Production', agree) as { props: { title?: string } }
    const disagreeEl = SUGGESTED_ORIENTATION_COLUMN.render!('Conservation', disagree) as { props: { title?: string } }
    expect(agreeEl.props.title).toBeUndefined()
    expect(disagreeEl.props.title).toBeTruthy()
  })

  it('Justification column (user report, 2026-09-15) appears on all 4 unit layers, read-only, scoped to slope-carved features', () => {
    for (const layerId of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const) {
      const cols = getLayerConfig(layerId)!.columns
      const byKey = Object.fromEntries(cols.map((c) => [c.key, c]))
      expect(byKey.orientation_justification_en, `${layerId}.orientation_justification_en`).toBeDefined()
      expect(byKey.orientation_justification_en?.editable).toBeFalsy()
    }

    const notCarved = { properties: {} } as never
    expect(ORIENTATION_JUSTIFICATION_COLUMN.getValue!(notCarved, 0)).toBeNull()

    const carved = {
      properties: {
        dominant_slope_band: 3,
        orientation_justification_en: 'type 8 · slope > 45° · erosion-sensitive',
        orientation_justification_ne: 'सि.नं. 8 · > ४५° भिरालो · भू-क्षय संवेदनशील',
      },
    } as never
    expect(ORIENTATION_JUSTIFICATION_COLUMN.getValue!(carved, 0)).toBe(
      'type 8 · slope > 45° · erosion-sensitive',
    )
  })

  it('Justification renders the English text with the Nepali reason as the hover title, and "-" when empty', () => {
    const carved = {
      properties: {
        dominant_slope_band: 3,
        orientation_justification_en: 'type 8 · erosion-sensitive per अनुसूची-१',
        orientation_justification_ne: 'सि.नं. 8 · अनुसूची-१ अनुसार भू-क्षय संवेदनशील',
      },
    } as never
    const el = ORIENTATION_JUSTIFICATION_COLUMN.render!(
      'type 8 · erosion-sensitive per अनुसूची-१',
      carved,
    ) as { props: { title?: string; children?: string } }
    expect(el.props.title).toBe('सि.नं. 8 · अनुसूची-१ अनुसार भू-क्षय संवेदनशील')
    expect(el.props.children).toBe('type 8 · erosion-sensitive per अनुसूची-१')

    const notCarved = { properties: {} } as never
    const emptyEl = ORIENTATION_JUSTIFICATION_COLUMN.render!('', notCarved) as { props: { children?: string } }
    expect(emptyEl.props.children).toBe('-')
  })

  it('compartments/sub_compartments dataSource.fetch threads orientation_justification_ne/en into feature properties', async () => {
    const node = {
      id: 'c1', name: 'Compartment-1', is_compartment: true, division_level: 1,
      area_hectares: 5, geometry: { type: 'Polygon', coordinates: [] },
      dominant_slope_band: 3,
      management_orientation: 'Production',
      suggested_orientation: 'Conservation',
      orientation_justification_ne: 'सि.नं. 8 · > ४५° भिरालो · भू-क्षय संवेदनशील',
      orientation_justification_en: 'type 8 · slope > 45° · erosion-sensitive',
      children: [],
    }
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    for (const layerId of ['compartments', 'sub_compartments'] as const) {
      const nodeAtRightLevel = { ...node, division_level: layerId === 'compartments' ? 1 : 2 }
      fetchMock.mockResolvedValue({ json: async () => ({ blocks: [nodeAtRightLevel] }) })
      const features = await getLayerConfig(layerId)!.dataSource.fetch('calc-1')
      expect(features, layerId).toHaveLength(1)
      expect(features[0].properties?.orientation_justification_en, layerId).toBe(
        'type 8 · slope > 45° · erosion-sensitive',
      )
      expect(features[0].properties?.orientation_justification_ne, layerId).toBe(
        'सि.नं. 8 · > ४५° भिरालो · भू-क्षय संवेदनशील',
      )
    }

    vi.unstubAllGlobals()
  })
})

describe('sub_blocks — the block branch\'s own sub-level layer (FS-4a.16)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const node = (overrides: Record<string, unknown> = {}) => ({
    id: 'b1', name: 'Block-1-SB1', is_compartment: false, division_level: 2,
    area_hectares: 3, geometry: { type: 'Polygon', coordinates: [] },
    block_name: 'Block-1-SB1', natural_name: null,
    dominant_slope_band: null, dominant_aspect: null, dominant_canopy_class: null,
    management_orientation: null, suggested_orientation: null,
    orientation_justification_ne: null, orientation_justification_en: null,
    color: null, working_circle: 'production', style: null,
    forest_condition: null, parent_block_name: 'Block-1', parent_block_id: 'p1',
    tree_count: 0, children: [],
    ...overrides,
  })

  it('is registered right after blocks, with its own style and branch-appropriate columns', () => {
    const cfg = getLayerConfig('sub_blocks')
    expect(cfg).toBeDefined()
    expect(cfg!.order).toBe(1.5)
    expect(cfg!.styleKey).toBe('sub_blocks')
    expect(cfg!.usesPalette).toBe(true)
    const keys = cfg!.columns.map((c) => c.key)
    expect(keys).toContain('block_name')
    expect(keys).toContain('natural_name')
    expect(keys).toContain('parent')
    // No compartment_code — that's the compartment branch's own concept.
    expect(keys).not.toContain('compartment_code')
  })

  it('fetch filters the compartment-tree to the OTHER branch (!is_compartment) at sub-level depth', async () => {
    const compartmentNode = { ...node(), id: 'c1', is_compartment: true };
    const topLevelBlock = { ...node(), id: 'b0', division_level: 1 };
    const subBlock = node();
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ blocks: [{ ...topLevelBlock, children: [subBlock, compartmentNode] }] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const features = await getLayerConfig('sub_blocks')!.dataSource.fetch('calc-1')
    expect(features).toHaveLength(1)
    expect(features[0].properties?.id).toBe('b1')
    expect(features[0].properties?.parent_block_name).toBe('Block-1')
  })

  it('create is rejected: `POST .../blocks` deletes every block of the forest, and nothing calls create', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch)
    const feat = { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: {} }
    for (const id of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const) {
      await expect(getLayerConfig(id)!.dataSource.create('calc-1', feat)).rejects.toThrow(/draw \/ paste \/ divide/)
    }
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('delete routes through /api/forests/.../blocks (a sub-block is a ForestBlock row, not a compartment)', async () => {
    // Mirrors featureRowOps.ts's own routing decision (FS-4a.16): the
    // compartments delete endpoint explicitly refuses a non-compartment row.
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url)
      return { ok: true, status: 204, json: async () => ({}) }
    }) as unknown as typeof fetch)
    await getLayerConfig('sub_blocks')!.dataSource.delete('calc-1', 'b1')
    expect(calls[0]).toContain('/api/forests/calculations/calc-1/blocks/b1')
    expect(calls[0]).not.toContain('/api/compartments/')
  })
})

describe('layerRegistry labelFields', () => {
  it('every built-in layer exposes a non-empty labelFields list', () => {
    for (const config of getAllLayerConfigs()) {
      expect(config.labelFields, config.id).toBeDefined()
      expect(config.labelFields!.length, config.id).toBeGreaterThan(0)
    }
  })

  it('label fields reference real feature attributes', () => {
    const blocks = getLabelFieldsForLayer('blocks')
    expect(blocks).toContain('name')
    expect(blocks).toContain('area_hectares')

    const compartments = getLabelFieldsForLayer('compartments')
    expect(compartments).toContain('compartment_code')

    const subAreas = getLabelFieldsForLayer('sub_areas')
    expect(subAreas).toContain('category')
    expect(subAreas).toContain('block_name')

    const activity = getLabelFieldsForLayer('activity_features')
    expect(activity).toContain('year')
    expect(activity).toContain('length_m')
  })

  it('unknown layer id has no label fields', () => {
    expect(getLabelFieldsForLayer('imported-1')).toEqual([])
    expect(getLabelFieldsForLayer('nope')).toEqual([])
  })
})

describe('layerRegistry columns — one source for the attribute table (P0.4)', () => {
  it('every built-in layer exposes data columns beyond the row-number column', () => {
    for (const cfg of getAllLayerConfigs()) {
      const dataCols = cfg.columns.filter((c) => c.key !== '#' && !c.key.startsWith('geo_'));
      expect(dataCols.length, cfg.id).toBeGreaterThanOrEqual(2);
    }
  });

  it('geometry (geo_*) columns exist and are hideable via the Columns… chooser', () => {
    const geo = getLayerConfig('blocks')!.columns.filter((c) => c.key.startsWith('geo_'));
    expect(geo.length).toBeGreaterThan(0);
  });

  it('NO column anywhere carries a visibility gate (owner report, 2026-09-30)', () => {
    // Every column is visible by default; the Columns… chooser is the only way
    // to hide one. A column a user cannot see is a field they cannot set, and
    // `hideIfEmpty` made the 4 Auto-Block class columns vanish outright on a
    // forest carved by a different source. Asserted structurally because the
    // flags no longer exist on ColumnDef — this is the guard against them
    // being reintroduced to unclutter a table.
    for (const cfg of getAllLayerConfigs()) {
      for (const c of cfg.columns) {
        expect({ layer: cfg.id, key: c.key, defaultHidden: (c as never as Record<string, unknown>).defaultHidden, hideIfEmpty: (c as never as Record<string, unknown>).hideIfEmpty })
          .toEqual({ layer: cfg.id, key: c.key, defaultHidden: undefined, hideIfEmpty: undefined });
      }
    }
  });

  it('user_group and sample_plots have columns (they were missing from the old COLUMN_CONFIGS)', () => {
    expect(getLayerConfig('user_group')!.columns.some((c) => c.key === 'source')).toBe(true);
    expect(getLayerConfig('sample_plots')!.columns.some((c) => c.key === 'plot_number')).toBe(true);
  });

  it('fieldbook is a read-only Point layer with the full point/sub-area column set (fieldbook_map_layer_plan.md P1)', () => {
    const cfg = getLayerConfig('fieldbook')!;
    expect(cfg.geometryTypes).toEqual(['Point']);
    expect(cfg.alwaysReadOnly).toBe(true);
    expect(cfg.editable).toBe(false);
    expect(cfg.geomanModes).toEqual([]);
    expect(cfg.styleKey).toBe('fieldbook');
    for (const key of ['point_number', 'point_type', 'boundary_class', 'is_junction', 'remarks', 'line_id', 'sub_area_name', 'sub_area_category', 'is_excluded']) {
      expect(cfg.columns.some((c) => c.key === key), key).toBe(true);
    }
  });

  it('fieldbook has ONE column for what a point is and which units it separates (Remark), not Block + Separates + Remark', () => {
    const keys = getLayerConfig('fieldbook')!.columns.map((c) => c.key);
    expect(keys.filter((k) => k === 'remarks')).toHaveLength(1);
    expect(keys).not.toContain('block_name');
    expect(keys).not.toContain('adjacent_units');
  });

  it('boundary keeps its perimeter column and blocks its lock column (ported from COLUMN_CONFIGS)', () => {
    expect(getLayerConfig('boundary')!.columns.some((c) => c.key === 'perimeter')).toBe(true);
    expect(getLayerConfig('blocks')!.columns.some((c) => c.key === 'locked')).toBe(true);
  });

  it('sub_areas category is an editable dropdown, not a read-only label', () => {
    const cat = getLayerConfig('sub_areas')!.columns.find((c) => c.key === 'category')!;
    expect(cat.editable).toBe(true);
    expect(Array.isArray(cat.select)).toBe(true);
    expect(cat.select!.length).toBeGreaterThan(5);
  });

  it('the 4 palette layers are flagged usesPalette', () => {
    for (const id of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas']) {
      expect(getLayerConfig(id as never)!.usesPalette, id).toBe(true);
    }
    expect(getLayerConfig('boundary')!.usesPalette).toBeUndefined();
  });
});

describe('per-feature style columns (WORKSPACE_LAYER_STYLING_PLAN.md P3.4)', () => {
  it('unit + sub-area layers carry a colour and an opacity editor, shown by default', () => {
    for (const id of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas']) {
      const cols = getLayerConfig(id as never)!.columns;
      const fill = cols.find((c) => c.key === 'style_fill')!;
      const opacity = cols.find((c) => c.key === 'style_opacity')!;
      expect(fill.editControl, id).toBe('color');
      expect(opacity.editControl, id).toBe('opacity');
    }
  });

  it('boundary (no per-feature style backend) has no style columns', () => {
    const cols = getLayerConfig('boundary')!.columns;
    expect(cols.some((c) => c.key === 'style_fill')).toBe(false);
  });

  it('style_fill getValue reads properties.style.fill', () => {
    const col = getLayerConfig('blocks')!.columns.find((c) => c.key === 'style_fill')!;
    const feat = { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { style: { fill: '#abcdef' } } } as GeoJSON.Feature;
    expect(col.getValue!(feat, 0)).toBe('#abcdef');
    const bare = { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} } as GeoJSON.Feature;
    expect(col.getValue!(bare, 0)).toBeUndefined();
  });
});

describe('layerRegistry geomanModes', () => {
  it('polygon layers expose a cut (split) mode plus edit+drag', () => {
    const configs = getAllLayerConfigs()
    for (const id of ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas']) {
      const cfg = configs.find((c) => c.id === id)
      const modes = (cfg as any)?.geomanModes as Array<{ mode: string }> | undefined
      const has = (f: string) => Array.isArray(modes) && modes.some((m) => m.mode === f)
      expect(has('cut'), `${id} cut`).toBe(true)
      expect(has('edit'), `${id} edit`).toBe(true)
      expect(has('drag'), `${id} drag`).toBe(true)
    }
  })
})

describe('boundary dataSource — multipart explodes into one row per part', () => {
  afterEach(() => vi.unstubAllGlobals())

  const mockCalc = (geometry: unknown) => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({ forest_name: 'Test CF', geometry }),
    })) as unknown as typeof fetch)
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)
  }

  it('a single Polygon → 1 feature', async () => {
    mockCalc({ type: 'Polygon', coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27.01], [85, 27]]] })
    const feats = await getLayerConfig('boundary')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(1)
    expect(feats[0].geometry.type).toBe('Polygon')
    expect(feats[0].properties?.part_count).toBe(1)
  })

  it('a 3-part MultiPolygon → 3 features, each with its own geo_area_ha', async () => {
    const sq = (x: number) => [[[x, 27], [x + 0.01, 27], [x + 0.01, 27.01], [x, 27.01], [x, 27]]]
    mockCalc({ type: 'MultiPolygon', coordinates: [sq(85), sq(85.2), sq(85.4)] })
    const feats = await getLayerConfig('boundary')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(3)
    expect(feats.every((f) => f.geometry.type === 'Polygon')).toBe(true)
    expect(feats.map((f) => f.properties?.part_index)).toEqual([0, 1, 2])
    expect(feats.every((f) => typeof f.properties?.geo_area_ha === 'number' && f.properties.geo_area_ha > 0)).toBe(true)
    expect(feats[0].properties?.name).toContain('1/3')
  })
})

// BOUNDARY_PIECES_PLAN.md P4: the primary path — persistent, renamable piece
// rows from the real `forest_boundary_pieces` table — takes priority over the
// on-the-fly MultiPolygon decomposition above, which is now only a fallback
// for a boundary that somehow has zero piece rows.
describe('boundary dataSource — reads persistent named pieces when they exist', () => {
  afterEach(() => vi.unstubAllGlobals())

  const mockPieces = (pieces: unknown[]) => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/boundary-pieces')) {
        return { ok: true, json: async () => ({ pieces, total_count: pieces.length }) }
      }
      throw new Error(`unexpected fetch to ${url}`)
    }) as unknown as typeof fetch)
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)
  }

  it('one piece row → 1 feature carrying its real id and name, no fallback fetch made', async () => {
    const geometry = { type: 'Polygon', coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27.01], [85, 27]]] }
    mockPieces([{ id: 'piece-uuid-1', name: 'Main parcel', geometry, area_hectares: 12.5 }])

    const feats = await getLayerConfig('boundary')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(1)
    expect(feats[0].properties?.id).toBe('piece-uuid-1')
    expect(feats[0].properties?.name).toBe('Main parcel')
    expect(feats[0].properties?.area_hectares).toBe(12.5)
  })

  it('two disjoint piece rows → 2 features, each independently named', async () => {
    const sq = (x: number) => [[[x, 27], [x + 0.01, 27], [x + 0.01, 27.01], [x, 27.01], [x, 27]]]
    mockPieces([
      { id: 'piece-a', name: 'Piece 1', geometry: { type: 'Polygon', coordinates: sq(85) }, area_hectares: 4 },
      { id: 'piece-b', name: 'Piece 2', geometry: { type: 'Polygon', coordinates: sq(86) }, area_hectares: 6 },
    ])

    const feats = await getLayerConfig('boundary')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(2)
    expect(feats.map((f) => f.properties?.name)).toEqual(['Piece 1', 'Piece 2'])
  })

  it('rename calls the boundary-pieces PATCH endpoint with the piece id', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), init })
      return { ok: true, json: async () => ({ id: 'piece-a', name: 'Renamed', area_hectares: 4, geometry: {} }) }
    }) as unknown as typeof fetch)
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)

    await getLayerConfig('boundary')!.dataSource.update('calc-1', 'piece-a', { name: 'Renamed' } as never)

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toContain('/calculations/calc-1/boundary-pieces/piece-a')
    expect(calls[0].init?.method).toBe('PATCH')
  })
})

describe('user_group layer (USER_GROUP_BOUNDARY_PLAN.md P1)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is registered as a built-in, single-feature layer just after boundary', () => {
    const cfg = getLayerConfig('user_group')
    expect(cfg).toBeDefined()
    expect(cfg!.order).toBe(0.5)
    expect(cfg!.styleKey).toBe('user_group')
    // editable unless the structure is locked (same rule as sub-areas)
    expect(typeof cfg!.editable).toBe('function')
    expect((cfg!.editable as (c: { structure_locked: boolean }) => boolean)({ structure_locked: false })).toBe(true)
    expect((cfg!.editable as (c: { structure_locked: boolean }) => boolean)({ structure_locked: true })).toBe(false)
    // draw REPLACES the single extent; edit/split act in place on that one row.
    // No `drag` — whole-feature move is a point-only gesture.
    const modes = (cfg!.geomanModes ?? []).map((m) => m.mode)
    expect(modes).toContain('drawPolygon')
    expect(modes).toContain('edit')
    expect(modes).toContain('cut')
    expect(modes).not.toContain('drag')
    expect(isBuiltinLayerId('user_group')).toBe(true)

    const order = getAllLayerConfigs().map((c) => c.id)
    expect(order[0]).toBe('boundary')
    expect(order[1]).toBe('user_group')
  })

  it('the Source column spells out an auto-buffer distance (P5)', () => {
    const col = getLayerConfig('user_group')!.columns.find((c) => c.key === 'source')!
    const val = (props: Record<string, unknown>) =>
      col.getValue!({ type: 'Feature', geometry: null as never, properties: props }, 0)
    expect(val({ source_type: 'manual' })).toBe('manual')
    expect(val({ source_type: 'uploaded' })).toBe('uploaded')
    expect(val({ source_type: 'auto_buffer', buffer_distance_m: 1000 })).toBe('auto_buffer (1000 m)')
    expect(val({ source_type: 'auto_buffer' })).toBe('auto_buffer')
    expect(val({})).toBe('-')
  })

  // P7e: the layer reads GET .../user-group/extents, which returns one feature
  // per stored row. `mockExtent` below mocks the singular union endpoint, which
  // the analysis uses and the map layer no longer does.
  const mockExtents = (
    features: Array<{
      id: string
      source_type?: string | null
      area_hectares?: number | null
      buffer_distance_m?: number | null
      geometry: unknown
    }>,
    ok = true,
  ) => {
    // Shaped like the real endpoint, which nests the attributes under
    // `properties` and carries the row id at the top level - the registry reads
    // `f.properties`, so a flat mock would silently drop every attribute.
    const payload = features.map((f) => ({
      type: 'Feature',
      id: f.id,
      geometry: f.geometry,
      properties: {
        id: f.id,
        name: 'User Group Boundary',
        source_type: f.source_type ?? null,
        buffer_distance_m: f.buffer_distance_m ?? null,
        area_hectares: f.area_hectares ?? null,
      },
    }))
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok,
      json: async () => ({ features: payload, count: payload.length }),
    })) as unknown as typeof fetch)
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)
  }

  // P7e, inverting the old test: three islands are three ROWS, fetched as
  // three features. It used to be ONE row whose MultiPolygon the client split
  // itself, inventing part_index/part_count and `user_group#<id>#<n>` ids for
  // the server to splice back. The server already knew them as rows.
  it('three rows read as three features, one per polygon', async () => {
    mockExtents([
      { id: '11', source_type: 'manual', area_hectares: 1, geometry: { type: 'Polygon', coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27]]] } },
      { id: '12', source_type: 'manual', area_hectares: 1, geometry: { type: 'Polygon', coordinates: [[[86, 27], [86.01, 27], [86.01, 27.01], [86, 27]]] } },
      { id: '13', source_type: 'manual', area_hectares: 1, geometry: { type: 'Polygon', coordinates: [[[87, 27], [87.01, 27], [87.01, 27.01], [87, 27]]] } },
    ])
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)

    const feats = await getLayerConfig('user_group')!.dataSource.fetch('calc-1')
    // Each is independently selectable, vertex-editable and cuttable, because
    // each IS a row - and the attribute table lists one entry per row.
    expect(feats).toHaveLength(3)
    expect(feats.map((f) => f.properties?.id)).toEqual(['11', '12', '13'])
    // No part index any more: one polygon per row means nothing to index.
    expect(feats.every((f) => f.properties?.part_index === undefined)).toBe(true)
    expect(feats.every((f) => f.geometry?.type === 'Polygon')).toBe(true)
  })

  it('a single row reads as one feature whose id is the row id', async () => {
    mockExtents([
      { id: '7', source_type: 'manual', area_hectares: 1,
        geometry: { type: 'Polygon', coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27]]] } },
    ])
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)

    const feats = await getLayerConfig('user_group')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(1)
    // A plain row id - no `user_group#<id>#<part>` invented by the client.
    expect(feats[0].properties?.id).toBe('7')
  })

  // P7e: delete targets the ROW. It used to hit the id-less route, which
  // removed the whole group - correct only while one row held everything.
  it('create appends; delete targets the row', async () => {
    const calls: Array<{ url: string; method?: string; body?: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, opts?: RequestInit) => {
      calls.push({ url, method: opts?.method, body: opts?.body as string })
      return { ok: true, json: async () => ({ extent_id: 1 }) }
    }) as unknown as typeof fetch)
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)
    const ds = getLayerConfig('user_group')!.dataSource
    const feat = {
      type: 'Feature' as const,
      geometry: {
        type: 'Polygon' as const,
        coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27]]],
      },
      properties: { id: '11' },
    }

    await ds.create('c1', feat)
    await ds.delete('c1', '11')

    expect(calls[0].url).toContain('/user-group/manual')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body!)).toHaveProperty('geometry')
    expect(calls[1].url).toBe('/api/calculations/c1/user-group/11')
    expect(calls[1].method).toBe('DELETE')
  })

  it('has an indigo dashed style preset', () => {
    expect(STYLE_PRESETS.user_group.color).toBe('#4338CA')
    expect(STYLE_PRESETS.user_group.fillColor).toBe('#6366F1')
    expect(STYLE_PRESETS.user_group.dashArray).toBe('4, 4')
  })

  const mockExtent = (body: unknown, ok = true) => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok, json: async () => body })) as unknown as typeof fetch)
    vi.stubGlobal('localStorage', { getItem: () => 't' } as unknown as Storage)
  }

  it('fetch → [] when no extent exists', async () => {
    mockExtent({ extent_id: null, geometry: null, source_type: null, area_hectares: null })
    const feats = await getLayerConfig('user_group')!.dataSource.fetch('calc-1')
    expect(feats).toEqual([])
  })

  // P7e: the layer reads /extents (plural) - one feature per ROW. The
  // singular /extent is the union, which the analysis wants, not the map.
  it('fetch → one feature per row, carrying source_type + area', async () => {
    mockExtents([
      { id: '11', source_type: 'uploaded', area_hectares: 42.5,
        geometry: { type: 'Polygon', coordinates: [[[85, 27], [85.02, 27], [85.02, 27.02], [85, 27.02], [85, 27]]] } },
    ])
    const feats = await getLayerConfig('user_group')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(1)
    expect(feats[0].properties?.id).toBe('11')
    expect(feats[0].properties?.source_type).toBe('uploaded')
    expect(feats[0].properties?.area_hectares).toBe(42.5)
    expect(typeof feats[0].properties?.geo_area_ha).toBe('number')
  })

  it('fetch → [] on a non-OK response (404 = no extent yet)', async () => {
    mockExtent({}, false)
    const feats = await getLayerConfig('user_group')!.dataSource.fetch('calc-1')
    expect(feats).toEqual([])
  })
})

describe('isBuiltinLayerId', () => {
  it('returns true for all built-in TOC layers', () => {
    for (const id of ['boundary', 'user_group', 'blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas', 'activity_features']) {
      expect(isBuiltinLayerId(id), id).toBe(true)
    }
  })

  it('returns false for imported/numeric and unknown ids', () => {
    expect(isBuiltinLayerId('imported-3')).toBe(false)
    expect(isBuiltinLayerId('3')).toBe(false)
    expect(isBuiltinLayerId('')).toBe(false)
  })
})

describe('activity_features — reading the drawn-features API', () => {
  const row = (geometry: unknown, extra: Record<string, unknown> = {}) => ({
    id: 'f1',
    proposed_activity_id: 'a1',
    feature_type: 'point',
    geometry,
    properties: { name: 'Planting spot', years: [1, 2] },
    ...extra,
  })

  it('turns the API\'s GeoJSON *string* into a geometry Leaflet can draw', async () => {
    const { activityFeaturesFromApi } = await import('../layerRegistry')
    const feats = activityFeaturesFromApi([row(JSON.stringify({ type: 'Point', coordinates: [85.05, 27.44] }))])
    expect(feats).toHaveLength(1)
    expect(feats[0].geometry).toEqual({ type: 'Point', coordinates: [85.05, 27.44] })
    expect(feats[0].properties).toMatchObject({ id: 'f1', name: 'Planting spot', years: [1, 2] })
  })

  it('also accepts an already-parsed geometry object', async () => {
    const { activityFeaturesFromApi } = await import('../layerRegistry')
    const feats = activityFeaturesFromApi([row({ type: 'LineString', coordinates: [[85, 27], [85.1, 27.1]] })])
    expect(feats[0].geometry.type).toBe('LineString')
  })

  it('skips a feature whose geometry cannot be read instead of failing the whole layer', async () => {
    const { activityFeaturesFromApi } = await import('../layerRegistry')
    const good = row(JSON.stringify({ type: 'Point', coordinates: [85, 27] }), { id: 'good' })
    const feats = activityFeaturesFromApi([row('not json', { id: 'bad1' }), row(null, { id: 'bad2' }), good])
    expect(feats.map((f) => f.properties?.id)).toEqual(['good'])
  })

  it('an error body or anything that is not a list is no features, not a crash', async () => {
    const { activityFeaturesFromApi } = await import('../layerRegistry')
    expect(activityFeaturesFromApi({ detail: 'Not found' })).toEqual([])
    expect(activityFeaturesFromApi(null)).toEqual([])
  })

  it('the layer fetch raises on an HTTP error, so the problem is visible', async () => {
    const { getLayerConfig } = await import('../layerRegistry')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 }),
    )
    await expect(getLayerConfig('activity_features')!.dataSource.fetch('calc-1')).rejects.toThrow(/404/)
    fetchSpy.mockRestore()
  })

  it('the layer fetch returns drawable features on success', async () => {
    const { getLayerConfig } = await import('../layerRegistry')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([row(JSON.stringify({ type: 'Point', coordinates: [85.05, 27.44] }))]), { status: 200 }),
    )
    const feats = await getLayerConfig('activity_features')!.dataSource.fetch('calc-1')
    expect(feats).toHaveLength(1)
    expect(feats[0].geometry).toEqual({ type: 'Point', coordinates: [85.05, 27.44] })
    fetchSpy.mockRestore()
  })

  it('sub_areas: a "Yearly plan" column says whether each sub-area is tied to the plan, and the layer still loads without it', async () => {
    const sub = (id: string) => ({ id, name: id, category: 'plantation', area_hectares: 1, geometry: { type: 'Polygon', coordinates: [] } })
    const fetchMock = vi.fn(async (url: string) =>
      String(url).includes('plan-status')
        ? { ok: true, json: async () => ({ sub_areas: [{ id: 'a', state: 'planned' }, { id: 'b', state: 'needs_plan' }] }) }
        : { ok: true, json: async () => ({ sub_areas: [sub('a'), sub('b'), sub('c')] }) })
    vi.stubGlobal('fetch', fetchMock)
    const cfg = getLayerConfig('sub_areas')!
    const feats = await cfg.dataSource.fetch('calc-1')
    const col = cfg.columns.find((c) => c.key === 'plan_state')!
    expect(feats.map((f, i) => col.getValue!(f, i))).toEqual(['Planned', 'Needs a plan', '-'])

    // the plan status cannot be read: the sub-areas still come back
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('plan-status')) throw new Error('down')
      return { ok: true, json: async () => ({ sub_areas: [sub('a')] }) }
    }))
    const again = await cfg.dataSource.fetch('calc-1')
    expect(again).toHaveLength(1)
    expect(col.getValue!(again[0], 0)).toBe('-')
    vi.unstubAllGlobals()
  })
})
