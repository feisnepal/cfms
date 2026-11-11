import { describe, it, expect } from 'vitest';
import { createFieldbookIcon, FIELDBOOK_INTERNAL_COLOR, FIELDBOOK_JUNCTION_COLOR } from '../fieldbookIcon';
import { FIELDBOOK_COLOR } from '../layerStyles';

const html = (icon: ReturnType<typeof createFieldbookIcon>) => String(icon.options.html);
const size = (icon: ReturnType<typeof createFieldbookIcon>) => icon.options.iconSize as [number, number];

describe('createFieldbookIcon', () => {
  it('prints the label people read and quote (O1 / I7), not a bare running number', () => {
    expect(html(createFieldbookIcon('O1', 'vertex', false, 'outer'))).toContain('O1');
    expect(html(createFieldbookIcon('I7', 'vertex', false, 'internal'))).toContain('I7');
  });

  it('outer is sky blue and internal is violet, so the two can be told apart on the map', () => {
    expect(html(createFieldbookIcon('O1', 'vertex', false, 'outer'))).toContain(FIELDBOOK_COLOR);
    const internal = html(createFieldbookIcon('I1', 'vertex', false, 'internal'));
    expect(internal).toContain(FIELDBOOK_INTERNAL_COLOR);
    expect(internal).not.toContain(`background-color: ${FIELDBOOK_COLOR}`);
  });

  it('a junction gets an amber ring; an ordinary point does not', () => {
    expect(html(createFieldbookIcon('O6', 'vertex', false, 'outer', true))).toContain(FIELDBOOK_JUNCTION_COLOR);
    expect(html(createFieldbookIcon('O6', 'vertex', false, 'outer', false))).not.toContain(FIELDBOOK_JUNCTION_COLOR);
  });

  it('a longer label widens the marker into a pill instead of overflowing it', () => {
    const short = size(createFieldbookIcon('5', 'vertex'))[0];
    const long = size(createFieldbookIcon('O173', 'vertex'))[0];
    expect(short).toBe(18);
    expect(long).toBeGreaterThan(short);
    expect(size(createFieldbookIcon('O173', 'vertex'))[1]).toBe(18);        // height unchanged
    expect(html(createFieldbookIcon('O173', 'vertex'))).toContain(`width: ${long}px`);
  });

  it('an interpolated point is the small hollow ring with no text', () => {
    const icon = createFieldbookIcon('I12', 'interpolated', false, 'internal');
    expect(size(icon)).toEqual([13, 13]);
    expect(html(icon)).not.toContain('I12');
    expect(html(icon)).toContain('background-color: transparent');
  });

  it('a selected point is orange whatever its kind', () => {
    expect(html(createFieldbookIcon('I1', 'vertex', true, 'internal'))).toContain('#FF8C00');
  });

  it('still accepts a plain number (older field books)', () => {
    expect(html(createFieldbookIcon(12, 'vertex'))).toContain('12');
    expect(html(createFieldbookIcon(null, 'vertex'))).not.toContain('null');
  });
});
