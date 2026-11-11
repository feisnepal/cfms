import { describe, it, expect, vi } from 'vitest';
import { tableToCsv, tableToTsv, tableToGeoJson, downloadText } from '../exportAttributeTable';
import type { ColumnDef } from '../layerRegistry';

const COLS: ColumnDef[] = [
  { key: '#', label: '#', width: 40, getValue: (_f, i) => i + 1 },
  { key: '__actions__', label: '', width: 34, getValue: () => '' },
  { key: 'name', label: 'Name', width: 120 },
  { key: 'area_ha', label: 'Area (ha)', width: 100, getValue: (f) => f.properties?.area_ha },
];

const FEATS: GeoJSON.Feature[] = [
  { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 2] }, properties: { name: 'Block A', area_ha: 12.5 } },
  { type: 'Feature', geometry: { type: 'Point', coordinates: [3, 4] }, properties: { name: 'Say "hi", now', area_ha: null } },
];

describe('exportAttributeTable (WORKSPACE_LAYER_STYLING_PLAN.md P2.5)', () => {
  it('tableToCsv drops row-number and action columns, keeps data columns', () => {
    const csv = tableToCsv(COLS, FEATS);
    const lines = csv.split('\r\n');
    expect(lines[0]).toBe('Name,Area (ha)');
    expect(lines[1]).toBe('Block A,12.5');
  });

  it('tableToCsv RFC-4180-quotes values with commas and quotes; null → empty', () => {
    const csv = tableToCsv(COLS, FEATS);
    const lines = csv.split('\r\n');
    // internal quotes doubled, whole field wrapped, trailing empty cell for null area
    expect(lines[2]).toBe('"Say ""hi"", now",');
  });

  it('tableToTsv is tab-separated and strips embedded tabs/newlines', () => {
    const feats: GeoJSON.Feature[] = [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { name: 'a\tb', area_ha: 1 } },
    ];
    const tsv = tableToTsv(COLS, feats);
    const lines = tsv.split('\r\n');
    expect(lines[0]).toBe('Name\tArea (ha)');
    expect(lines[1]).toBe('a b\t1');
  });

  it('tableToGeoJson keeps geometry and every in-view feature', () => {
    const out = JSON.parse(tableToGeoJson(FEATS));
    expect(out.type).toBe('FeatureCollection');
    expect(out.features).toHaveLength(2);
    expect(out.features[0].geometry.type).toBe('Point');
  });

  it('downloadText clicks an anchor with the given filename', () => {
    const click = vi.fn();
    const realCreate = document.createElement.bind(document);
    const spy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag);
      if (tag === 'a') el.click = click;
      return el;
    });
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:x';
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
    downloadText('layer.csv', 'text/csv', 'a,b');
    expect(click).toHaveBeenCalled();
    spy.mockRestore();
  });
});
