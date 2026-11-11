import { describe, it, expect, vi, afterEach } from 'vitest';
import { getLayerConfig, isUndividedNode } from '../layerRegistry';

// SL-2 / SL-3 (SUBCOMPARTMENT_LAYER_TRACKER.md). The Sub-compartment and Sub-block
// layers show EVERY unit of their branch that is not divided further, so the layer
// tiles the forest exactly once: sum(layer area) == sum(top-level area) == forest.
// Fixture = the owner's परिक्षण forest: C-1 (68.76) divided into 5, C-2/3/4 undivided.

const sq = (x: number) => ({
  type: 'Polygon',
  coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]],
});

function node(id: string, area: number, isCompartment: boolean, level: number, children: any[] = [], x = 0) {
  return {
    id, name: id, area_hectares: area, is_compartment: isCompartment,
    division_level: level, geometry: sq(x), children, child_count: children.length,
  };
}

function tree(isCompartment: boolean, divideSecond = false) {
  const kids = [16.0, 15.18, 14.28, 11.73, 11.57].map((a, i) =>
    node(`SC${i + 1}`, a, isCompartment, 2, [], i));
  const second = divideSecond
    ? node('C-2', 35.67, isCompartment, 1, [20, 10, 5.67].map((a, i) => node(`C-2-SC${i + 1}`, a, isCompartment, 2, [], 10 + i)), 10)
    : node('C-2', 35.67, isCompartment, 1, [], 10);
  return {
    blocks: [
      node('C-1', 68.76, isCompartment, 1, kids, 0),
      second,
      node('C-3', 13.09, isCompartment, 1, [], 20),
      node('C-4', 12.23, isCompartment, 1, [], 30),
    ],
  };
}

function stubTree(t: unknown) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => t })));
}

const sum = (fs: any[]) => fs.reduce((a, f) => a + f.properties.area_hectares, 0);

afterEach(() => vi.unstubAllGlobals());

describe('isUndividedNode', () => {
  it('is true only when the node has no children', () => {
    expect(isUndividedNode({})).toBe(true);
    expect(isUndividedNode({ children: [] })).toBe(true);
    expect(isUndividedNode({ children: [{}] })).toBe(false);
  });
});

describe.each([
  ['sub_compartments', true],
  ['sub_blocks', false],
] as const)('%s layer shows every undivided unit of its branch', (layerId, isCompartment) => {
  it('परिक्षण: 3 undivided + 5 children = 8 rows covering the forest once', async () => {
    stubTree(tree(isCompartment));
    const feats: any[] = await getLayerConfig(layerId)!.dataSource.fetch('c');
    expect(feats).toHaveLength(8);
    expect(new Set(feats.map((f) => f.properties.id)).size).toBe(8);
    // the divided parent is replaced by its children, never listed with them
    expect(feats.map((f) => f.properties.id)).not.toContain('C-1');
    expect(sum(feats)).toBeCloseTo(68.76 + 35.67 + 13.09 + 12.23, 2);
  });

  it('dividing an undivided unit changes the count but never the total area', async () => {
    stubTree(tree(isCompartment));
    const before: any[] = await getLayerConfig(layerId)!.dataSource.fetch('c');
    stubTree(tree(isCompartment, true));
    const after: any[] = await getLayerConfig(layerId)!.dataSource.fetch('c');
    expect(before).toHaveLength(8);
    expect(after).toHaveLength(10); // C-2 replaced by its 3 children
    expect(sum(after)).toBeCloseTo(sum(before), 2);
  });

  it("ignores the other branch's units", async () => {
    stubTree(tree(!isCompartment));
    const feats: any[] = await getLayerConfig(layerId)!.dataSource.fetch('c');
    expect(feats).toHaveLength(0);
  });
});
