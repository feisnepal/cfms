import { describe, it, expect, vi, beforeEach } from 'vitest';

// E-0 spike: registry lookup (E0.1) + event wiring (E0.2) + throttle (E0.3).
// Geoman's DOM interaction is tested via a mockable event/layer surface; real
// Geoman rendering is E2E-only (planned E8).

interface MockLayer {
  on: ReturnType<typeof vi.fn>;
  off: ReturnType<typeof vi.fn>;
  toGeoJSON: ReturnType<typeof vi.fn>;
  pm: {
    enable: ReturnType<typeof vi.fn>;
    disable: ReturnType<typeof vi.fn>;
    enabled: ReturnType<typeof vi.fn>;
  };
}

function makeLayer(): MockLayer {
  return {
    on: vi.fn(),
    off: vi.fn(),
    toGeoJSON: vi.fn().mockReturnValue({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [] },
      properties: { id: 'f1' },
    }),
    pm: {
      enable: vi.fn(),
      disable: vi.fn(),
      enabled: vi.fn().mockReturnValue(true),
    },
  };
}

function makeMap() {
  const handlers = new Map<string, Set<(...args: any[]) => void>>();
  return {
    on: vi.fn((evt: string, cb: (...args: any[]) => void) => {
      if (!handlers.has(evt)) handlers.set(evt, new Set());
      handlers.get(evt)!.add(cb);
    }),
    off: vi.fn((evt: string, cb: (...args: any[]) => void) => {
      handlers.get(evt)?.delete(cb);
    }),
    emit(evt: string, ...args: any[]) {
      handlers.get(evt)?.forEach((cb) => cb(...args));
    },
  };
}

function layerListener(layer: MockLayer, evt: string): (...args: any[]) => void {
  const cb = layer.on.mock.calls.find(([e]) => e === evt)?.[1];
  expect(cb, `${evt} listener`).toBeTruthy();
  return cb!;
}

describe('featureLayerRegistry (E0.1)', () => {
  let registryModule: typeof import('../featureLayerRegistry');
  beforeEach(async () => {
    vi.resetModules();
    registryModule = await import('../featureLayerRegistry');
    registryModule.getFeatureLayerRegistry().clear();
  });

  it('resolves the live layer for a feature id', () => {
    const layer = makeLayer();
    registryModule.registerFeatureLayer(
      { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { id: 'blk-42' } },
      layer as any,
    );
    const registry = registryModule.getFeatureLayerRegistry();
    expect(registry.has('blk-42')).toBe(true);
    expect(registry.get('blk-42')).toBe(layer);
  });

  it('ignores features without a usable id', () => {
    registryModule.registerFeatureLayer(
      { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: {} },
      makeLayer() as any,
    );
    expect(registryModule.getFeatureLayerRegistry().size).toBe(0);
  });

  it('drops the mapping when the leaflet layer is removed', () => {
    const layer = makeLayer();
    registryModule.registerFeatureLayer(
      { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { id: 'f1' } },
      layer as any,
    );
    layerListener(layer, 'remove')();
    expect(registryModule.getFeatureLayerRegistry().has('f1')).toBe(false);
  });
});

describe('geomanSpikeEdit (E0.2/E0.3)', () => {
  let spike: typeof import('../geomanSpikeEdit');
  beforeEach(async () => {
    spike = await import('../geomanSpikeEdit');
  });

  it('enables edit+drag on the registry layer (E0.1 lookup-or-enable gate)', () => {
    const layer = makeLayer();
    const map = makeMap();
    const cleanup = spike.enableRegistryLayerGeoman(
      map as any,
      { get: () => layer as any },
      'f1',
      { onSave: vi.fn() },
    );
    expect(layer.pm.enable).toHaveBeenCalledWith(
      expect.objectContaining({ edit: true, drag: true, allowSelfIntersection: false }),
    );
    cleanup();
    expect(layer.pm.disable).toHaveBeenCalled();
  });

  it('saves exactly once per drag-release (pm: markerdragend → onSave)', () => {
    const layer = makeLayer();
    const map = makeMap();
    const onSave = vi.fn();
    spike.enableRegistryLayerGeoman(
      map as any,
      { get: () => layer as any },
      'f1',
      { onSave },
    );

    // many continuous drag-moves, then ONE release
    for (let i = 0; i < 20; i++) map.emit('pm:edit', {});
    layerListener(layer, 'pm:markerdragend')({});

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0].properties.id).toBe('f1');
  });

  it('continuous pm:edit NEVER triggers a save (E0.3 throttle gate)', () => {
    const layer = makeLayer();
    const map = makeMap();
    const onSave = vi.fn();
    const onDragMove = vi.fn();
    spike.enableRegistryLayerGeoman(
      map as any,
      { get: () => layer as any },
      'f1',
      { onSave, onDragMove },
    );

    map.emit('pm:edit', {});
    map.emit('pm:edit', {});
    map.emit('pm:edit', {});

    expect(onSave).not.toHaveBeenCalled();
    expect(onDragMove).toHaveBeenCalledTimes(3);
  });

  it('saves on vertex add and vertex remove (immediate commit points)', () => {
    const layer = makeLayer();
    const map = makeMap();
    const onSave = vi.fn();
    spike.enableRegistryLayerGeoman(
      map as any,
      { get: () => layer as any },
      'f1',
      { onSave },
    );

    layerListener(layer, 'pm:vertexadded')({});
    layerListener(layer, 'pm:vertexremoved')({});
    expect(onSave).toHaveBeenCalledTimes(2);
  });

  it('returns a noop when the registry cannot resolve the layer', () => {
    const map = makeMap();
    const cleanup = spike.enableRegistryLayerGeoman(
      map as any,
      { get: () => undefined },
      'missing',
      { onSave: vi.fn() },
    );
    expect(typeof cleanup).toBe('function');
    cleanup();
  });
});