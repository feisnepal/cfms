import { describe, it, expect } from 'vitest';
import { mergeUnitProps, type UnitMapData } from '../unitMapProps';

const f = (name: string) => ({ type: 'Feature', geometry: null, properties: { name } }) as never;
const ready: UnitMapData = {
  state: 'ready', token: 'thememap:unit__growing_stock', custom_colours: false,
  units: { A: { color: '#112233', value: 80.1, text: '80 m³/ha' } }, legend: [],
};

describe('mergeUnitProps', () => {
  it('puts the server colour, the label text and the raw numbers on the matching unit only', () => {
    const out = mergeUnitProps([f('A'), f('B')], ready, { A: { fi_stock: 80.1, fi_condition: 'Weak' }, B: { fi_stock: 5 } })!;
    expect(out[0].properties).toMatchObject({ um_color: '#112233', um_text: '80 m³/ha', um_value: 80.1, fi_stock: 80.1, fi_condition: 'Weak' });
    expect(out[1].properties).toMatchObject({ fi_stock: 5 });
    expect(out[1].properties).not.toHaveProperty('um_color'); // B has no entry in the active map: it reads grey, never a stale colour
  });
  it('the raw numbers alone still reach the table when no map is active', () => {
    const out = mergeUnitProps([f('A')], null, { A: { fi_stock: 80.1 } })!;
    expect(out[0].properties).toMatchObject({ fi_stock: 80.1 });
    expect(out[0].properties).not.toHaveProperty('um_color');
  });
  it('is the very same array when there is nothing to merge, or the map is not ready', () => {
    const list = [f('A')];
    expect(mergeUnitProps(list, null, {})).toBe(list);
    expect(mergeUnitProps(list, { state: 'not_computed' }, undefined)).toBe(list);
    expect(mergeUnitProps(null, ready, {})).toBeNull();
  });
});
