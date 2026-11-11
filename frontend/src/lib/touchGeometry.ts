import { isTouchDevice, isCoarsePointer } from './touchDevice';

export const TOUCH_TARGET_PX = 44;
export const TOUCH_VERTEX_MARKER_PX = 44;
export const TOUCH_HIT_RADIUS_PX = 15;

export interface TouchGeomanOptions {
  /** Map option: disable double-click zoom when true (touch devices). */
  doubleClickZoom: boolean;
  /** CSS class to add to map container for touch-specific styles. */
  containerClass: string;
  /** Extra options passed to layer.pm.enable() for draw/edit modes. */
  pmOptions: Record<string, unknown>;
}

/**
 * Returns touch-aware Geoman options and container class.
 * Call once on component mount (uses cached touch detection).
 */
export function getTouchGeomanOptions(): TouchGeomanOptions {
  const touch = isTouchDevice();
  const coarse = isCoarsePointer();

  // On any touch or coarse pointer device, apply touch optimizations
  const applyTouch = touch || coarse;

  return {
    doubleClickZoom: !applyTouch,
    containerClass: applyTouch ? 'touch-device' : '',
    pmOptions: applyTouch
      ? {
          // Note: Geoman 2.19 doesn't expose touchRadius; vertex marker size
          // is controlled via CSS (.touch-device .marker-icon).
          // We only set draw-mode options here if needed.
        }
      : {},
  };
}

/**
 * Get Geoman draw options merged with touch options.
 * For use in layer.pm.enable({ ...drawOptions, ...getTouchPmDrawOptions() })
 */
export function getTouchPmDrawOptions(): Record<string, unknown> {
  return getTouchGeomanOptions().pmOptions;
}