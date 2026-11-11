/** A fit asked for while the map is hidden must not pick the whole earth (owner report 2026-10-11). */
import { describe, expect, it, vi } from 'vitest';
import L from 'leaflet';
import {
  MIN_USEFUL_ZOOM, NEPAL_BOUNDS, fitBoundsWhenVisible, recoverFromWorldView, zoomToLayerBounds,
} from '../mapZoom';

/** A stand-in for L.Map: a size we can change, the one-shot 'resize' listeners, and a record of the fits. */
function fakeMap(initial: { x: number; y: number }, zoom = 8) {
  let size = { ...initial };
  let currentZoom = zoom;
  const listeners: Array<() => void> = [];
  const fits: Array<{ bounds: L.LatLngBounds; options?: L.FitBoundsOptions }> = [];
  const map = {
    getSize: () => ({ x: size.x, y: size.y }),
    getZoom: () => currentZoom,
    once: (_event: string, fn: () => void) => listeners.push(fn),
    fitBounds: (bounds: L.LatLngBounds, options?: L.FitBoundsOptions) => {
      fits.push({ bounds, options });
      currentZoom = 9;
    },
  };
  return {
    map: map as unknown as L.Map,
    fits,
    show: (next: { x: number; y: number }) => {
      size = next;
      listeners.splice(0).forEach((fn) => fn()); // the resize event Leaflet fires from invalidateSize
    },
    setZoom: (z: number) => {
      currentZoom = z;
    },
  };
}

const FOREST = L.latLngBounds([27.0, 84.0], [27.1, 84.1]);

describe('fitting a hidden map', () => {
  it('does not fit while the container has no size, and fits once it is shown', () => {
    const m = fakeMap({ x: 0, y: 0 });
    fitBoundsWhenVisible(m.map, FOREST, { maxZoom: 18 });
    expect(m.fits).toHaveLength(0); // fitting now would compute zoom 0 = the whole earth
    m.show({ x: 900, y: 600 });
    expect(m.fits).toHaveLength(1);
    expect(m.fits[0].bounds).toBe(FOREST);
    expect(m.fits[0].options).toEqual({ maxZoom: 18 });
  });

  it('fits straight away when the map is visible', () => {
    const m = fakeMap({ x: 900, y: 600 });
    fitBoundsWhenVisible(m.map, FOREST);
    expect(m.fits).toHaveLength(1);
  });

  it('waits again if the first resize is still not a usable size', () => {
    const m = fakeMap({ x: 0, y: 0 });
    fitBoundsWhenVisible(m.map, FOREST);
    m.show({ x: 0, y: 40 });
    expect(m.fits).toHaveLength(0);
    m.show({ x: 900, y: 600 });
    expect(m.fits).toHaveLength(1);
  });

  it('falls back to Nepal when there is nothing valid to fit to', () => {
    const m = fakeMap({ x: 900, y: 600 });
    fitBoundsWhenVisible(m.map, L.latLngBounds([]));
    expect(m.fits[0].bounds).toBe(NEPAL_BOUNDS);
  });

  it('"Zoom to layer" keeps its edge-to-edge fit with the small margin, and does nothing for empty bounds', () => {
    const m = fakeMap({ x: 900, y: 600 });
    zoomToLayerBounds(m.map, FOREST);
    expect(m.fits).toHaveLength(1);
    expect(m.fits[0].options).toEqual({ maxZoom: 18 });
    expect(m.fits[0].bounds.getNorth()).toBeGreaterThan(FOREST.getNorth()); // padded by 5%
    zoomToLayerBounds(m.map, L.latLngBounds([]));
    expect(m.fits).toHaveLength(1);
  });
});

describe('recovering from the globe', () => {
  it('sends a map that shows the whole earth to Nepal', () => {
    const m = fakeMap({ x: 900, y: 600 }, 1);
    expect(recoverFromWorldView(m.map)).toBe(true);
    expect(m.fits[0].bounds).toBe(NEPAL_BOUNDS);
  });

  it('leaves a map alone at a useful zoom, and a hidden one (nothing to judge yet)', () => {
    const ok = fakeMap({ x: 900, y: 600 }, MIN_USEFUL_ZOOM);
    expect(recoverFromWorldView(ok.map)).toBe(false);
    const hidden = fakeMap({ x: 0, y: 0 }, 0);
    expect(recoverFromWorldView(hidden.map)).toBe(false);
    expect(ok.fits.length + hidden.fits.length).toBe(0);
  });
});
