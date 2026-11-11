import { describe, it, expect, vi } from 'vitest';
import { getTouchGeomanOptions, getTouchPmDrawOptions, TOUCH_TARGET_PX, TOUCH_VERTEX_MARKER_PX, TOUCH_HIT_RADIUS_PX } from '../touchGeometry';

vi.mock('../touchDevice', () => ({
  isTouchDevice: vi.fn(),
  isCoarsePointer: vi.fn(),
}));

const mockIsTouchDevice = vi.mocked(await import('../touchDevice')).isTouchDevice;
const mockIsCoarsePointer = vi.mocked(await import('../touchDevice')).isCoarsePointer;

describe('touchGeometry', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('exports touch target constants', () => {
    expect(TOUCH_TARGET_PX).toBe(44);
    expect(TOUCH_VERTEX_MARKER_PX).toBe(44);
    expect(TOUCH_HIT_RADIUS_PX).toBe(15);
  });

  it('returns non-touch options when isTouchDevice=false and isCoarsePointer=false', () => {
    mockIsTouchDevice.mockReturnValue(false);
    mockIsCoarsePointer.mockReturnValue(false);

    const options = getTouchGeomanOptions();

    expect(options.doubleClickZoom).toBe(true);
    expect(options.containerClass).toBe('');
    expect(options.pmOptions).toEqual({});
  });

  it('returns touch options when isTouchDevice=true', () => {
    mockIsTouchDevice.mockReturnValue(true);
    mockIsCoarsePointer.mockReturnValue(false);

    const options = getTouchGeomanOptions();

    expect(options.doubleClickZoom).toBe(false);
    expect(options.containerClass).toBe('touch-device');
    expect(typeof options.pmOptions).toBe('object');
  });

  it('returns touch options when isCoarsePointer=true (even if isTouchDevice=false)', () => {
    mockIsTouchDevice.mockReturnValue(false);
    mockIsCoarsePointer.mockReturnValue(true);

    const options = getTouchGeomanOptions();

    expect(options.doubleClickZoom).toBe(false);
    expect(options.containerClass).toBe('touch-device');
  });

  it('getTouchPmDrawOptions returns pmOptions from getTouchGeomanOptions', () => {
    mockIsTouchDevice.mockReturnValue(true);
    mockIsCoarsePointer.mockReturnValue(false);

    const pmOptions = getTouchPmDrawOptions();

    expect(typeof pmOptions).toBe('object');
  });
});