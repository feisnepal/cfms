/** The points preview: the user SEES where the file's points fall against the forest (UP-3.5). */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}${JSON.stringify(v)}` : k) }));

import { UploadPointsPreview, insideRing, type UploadPreview } from '../UploadPointsPreview';

const SQUARE = { type: 'Polygon', coordinates: [[[85.5, 27.3], [85.7, 27.3], [85.7, 27.5], [85.5, 27.5], [85.5, 27.3]]] };

describe('insideRing', () => {
  it('tells inside from outside', () => {
    const ring = SQUARE.coordinates[0] as Array<[number, number]>;
    expect(insideRing([85.6, 27.4], ring)).toBe(true);
    expect(insideRing([83.0, 27.0], ring)).toBe(false);
  });
});

describe('UploadPointsPreview', () => {
  const preview = (over: Partial<UploadPreview> = {}): UploadPreview => ({
    points: [[85.6, 27.4], [85.62, 27.41], [83.0, 27.0]], assumed: 'as_is', boundary: SQUARE, ...over,
  });

  it('draws the boundary and colours each point by whether it is inside', () => {
    render(<UploadPointsPreview preview={preview()} />);
    expect(screen.getByTestId('preview-boundary')).toBeTruthy();
    const fig = screen.getByTestId('upload-points-preview');
    expect(fig.getAttribute('data-outside')).toBe('1');
    const dots = fig.querySelectorAll('circle');
    expect(Array.from(dots).map((c) => c.getAttribute('data-inside'))).toEqual(['true', 'true', 'false']);
    expect(fig.textContent).toContain('uploadPreview.inside{"count":2}');
    expect(fig.textContent).toContain('uploadPreview.outside{"count":1}');
  });

  it('says so when the numbers were drawn as UTM metres or swapped columns, and stays quiet when read as they are', () => {
    const { rerender } = render(<UploadPointsPreview preview={preview({ assumed: 'utm_zone_45' })} />);
    expect(screen.getByTestId('preview-note').textContent).toContain('"zone":"45"');
    rerender(<UploadPointsPreview preview={preview({ assumed: 'swapped' })} />);
    expect(screen.getByTestId('preview-note').textContent).toContain('assumedSwapped');
    rerender(<UploadPointsPreview preview={preview()} />);
    expect(screen.queryByTestId('preview-note')).toBeNull();
  });

  it('still shows the points when there is no boundary, and nothing when there is nothing to draw', () => {
    const { container, rerender } = render(<UploadPointsPreview preview={preview({ boundary: null })} />);
    expect(screen.queryByTestId('preview-boundary')).toBeNull();
    expect(container.querySelectorAll('circle')).toHaveLength(3);
    rerender(<UploadPointsPreview preview={{ points: [], assumed: 'as_is', boundary: null }} />);
    expect(container.firstChild).toBeNull();
  });
});
