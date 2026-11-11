import { describe, it, expect } from 'vitest';
import { createFreshPointIcon, FRESH_POINT_FILL, FRESH_POINT_RING } from '../pointIcons';

describe('createFreshPointIcon', () => {
  it('renders the index number in the icon html', () => {
    const icon = createFreshPointIcon(3);
    const compact = ((icon.options as any).html as string).replace(/\s+/g, '');
    expect(compact).toContain('>3<');
  });

  it('renders blank for a null index', () => {
    const icon = createFreshPointIcon(null);
    const compact = ((icon.options as any).html as string).replace(/\s+/g, '');
    // no stray digits between the closing div-open and the number slot
    expect(compact).not.toMatch(/>\d+</);
  });

  it('uses the fuchsia palette, not the Sample Plot amber/orange', () => {
    const icon = createFreshPointIcon(1);
    const html = (icon.options as any).html as string;
    expect(html).toContain(FRESH_POINT_FILL);
    expect(html).toContain(FRESH_POINT_RING);
    expect(html).not.toContain('#fbbf24');
    expect(html).not.toContain('#FF8C00');
  });

  it('is sized to match Sample Plot\'s icon (18px, numbered divIcon)', () => {
    const icon = createFreshPointIcon(1);
    expect(icon.options.iconSize).toEqual([18, 18]);
  });
});
