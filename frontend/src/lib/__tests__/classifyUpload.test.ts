import { describe, it, expect } from 'vitest';
import JSZip from 'jszip';
import {
  classifyFile,
  matchName,
  normalizeName,
  stripExt,
  fileExt,
  isWorkbook,
  isZipBundle,
  readWorkbookSheets,
  type UploadSchema,
} from '../classifyUpload';

const SCHEMA: UploadSchema = {
  schema_version: '1.0',
  purposes: [
    {
      id: 'forest_boundary',
      label_en: 'Forest boundary',
      label_ne: '',
      kind: 'spatial',
      order: 0,
      layer_name: 'forest_boundary',
      name_aliases: ['boundary', 'forest boundary'],
      geometry_types: ['POLYGON'],
    },
    {
      id: 'blocks',
      label_en: 'Blocks',
      label_ne: '',
      kind: 'spatial',
      order: 10,
      layer_name: 'blocks',
      name_aliases: ['block'],
      geometry_types: ['POLYGON'],
    },
    {
      id: 'trees',
      label_en: 'Trees',
      label_ne: '',
      kind: 'spatial_or_tabular',
      order: 40,
      layer_name: 'trees',
      name_aliases: ['tree', 'inventory'],
      geometry_types: ['POINT'],
    },
    {
      id: 'user_group_boundary',
      label_en: 'User-group boundary',
      label_ne: '',
      kind: 'spatial',
      order: 60,
      layer_name: 'user_group_boundary',
      name_aliases: ['usergroup', 'settlement_boundary'],
      geometry_types: ['POLYGON'],
    },
    {
      id: 'households',
      label_en: 'Households',
      label_ne: '',
      kind: 'tabular',
      order: 50,
      layer_name: 'households',
      name_aliases: ['household', 'hh'],
    },
  ],
};

describe('name helpers', () => {
  it('normalizeName collapses case and separators', () => {
    expect(normalizeName('Forest Boundary')).toBe('forestboundary');
    expect(normalizeName('forest_boundary')).toBe('forestboundary');
    expect(normalizeName('forest-boundary')).toBe('forestboundary');
  });
  it('stripExt / fileExt', () => {
    expect(stripExt('brindaban-blocks.geojson')).toBe('brindaban-blocks');
    expect(fileExt('a.GPKG')).toBe('gpkg');
    expect(fileExt('noext')).toBe('');
  });
  it('isWorkbook / isZipBundle', () => {
    expect(isWorkbook('Forest_Data_Workbook.xlsx')).toBe(true);
    expect(isWorkbook('x.gpkg')).toBe(false);
    expect(isZipBundle('shp.zip')).toBe(true);
  });
});

describe('matchName', () => {
  it('matches the canonical layer name', () => {
    expect(matchName('blocks', SCHEMA.purposes)).toBe('blocks');
  });
  it('matches an alias', () => {
    expect(matchName('boundary', SCHEMA.purposes)).toBe('forest_boundary');
    expect(matchName('inventory', SCHEMA.purposes)).toBe('trees');
  });
  it('matches a prefixed token', () => {
    expect(matchName('brindaban-blocks', SCHEMA.purposes)).toBe('blocks');
    expect(matchName('2026_trees_final', SCHEMA.purposes)).toBe('trees');
  });
  it('prefers the whole-name match over an inner token', () => {
    // "boundary" token is in forest_boundary too, but the whole string is
    // user_group_boundary's layer name.
    expect(matchName('user_group_boundary', SCHEMA.purposes)).toBe(
      'user_group_boundary',
    );
    expect(matchName('settlement_boundary', SCHEMA.purposes)).toBe(
      'user_group_boundary',
    );
  });
  it('returns null when nothing matches', () => {
    expect(matchName('random-notes', SCHEMA.purposes)).toBeNull();
    expect(matchName('hh', SCHEMA.purposes)).toBe('households'); // 2-char alias still whole-matches
  });
});

function file(name: string, body = 'x'): File {
  return new File([body], name, { type: 'application/octet-stream' });
}

describe('classifyFile — loose files', () => {
  it('classifies by filename', async () => {
    expect((await classifyFile(file('blocks.geojson'), SCHEMA)).purposeId).toBe(
      'blocks',
    );
    const c = await classifyFile(file('brindaban_boundary.kml'), SCHEMA);
    expect(c.purposeId).toBe('forest_boundary');
    expect(c.via).toBe('name');
  });
  it('returns null/none for an unrecognizable name', async () => {
    const c = await classifyFile(file('export_2026.csv'), SCHEMA);
    expect(c.purposeId).toBeNull();
    expect(c.via).toBe('none');
  });
});

async function xlsxWithSheets(names: string[]): Promise<File> {
  const zip = new JSZip();
  const sheetTags = names
    .map((n, i) => `<sheet name="${n}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`)
    .join('');
  zip.file(
    'xl/workbook.xml',
    `<?xml version="1.0"?><workbook><sheets>${sheetTags}</sheets></workbook>`,
  );
  zip.file('[Content_Types].xml', '<Types/>');
  const buf = await zip.generateAsync({ type: 'arraybuffer' });
  return new File([buf], 'Forest_Data_Workbook.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}

describe('classifyFile — workbook', () => {
  it('reads sheet names and classifies each, ignoring Instructions', async () => {
    const f = await xlsxWithSheets([
      'Instructions',
      'forest_boundary',
      'blocks',
      'trees',
      'mystery',
    ]);
    expect(await readWorkbookSheets(f)).toEqual([
      'Instructions',
      'forest_boundary',
      'blocks',
      'trees',
      'mystery',
    ]);
    const c = await classifyFile(f, SCHEMA);
    expect(c.via).toBe('sheet');
    expect(c.sheets?.map((s) => s.name)).toEqual([
      'forest_boundary',
      'blocks',
      'trees',
      'mystery',
    ]);
    expect(c.sheets?.find((s) => s.name === 'blocks')?.purposeId).toBe('blocks');
    expect(c.sheets?.find((s) => s.name === 'mystery')?.purposeId).toBeNull();
    // more than one recognized sheet → no single purpose
    expect(c.purposeId).toBeNull();
  });

  it('a one-sheet workbook resolves to that purpose', async () => {
    const f = await xlsxWithSheets(['Instructions', 'households']);
    const c = await classifyFile(f, SCHEMA);
    expect(c.purposeId).toBe('households');
  });
});
