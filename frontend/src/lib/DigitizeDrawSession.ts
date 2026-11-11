/**
 * DigitizeDrawSession.ts — Manages single-active-draw sessions (Gap 4.2).
 *
 * Controls start, commit, abort, pause, and resume states for Geoman draw sessions.
 */
import type L from 'leaflet';

export type DrawSessionState = 'idle' | 'drawing' | 'paused';

export class DigitizeDrawSession {
  private state: DrawSessionState = 'idle';
  private activeLayer: L.Layer | null = null;
  private map: L.Map | null = null;

  public start(map: L.Map, layer: L.Layer): void {
    this.map = map;
    this.activeLayer = layer;
    this.state = 'drawing';
  }

  public pause(): void {
    if (this.state !== 'drawing') return;
    this.state = 'paused';
    if (this.map && this.activeLayer) {
      try {
        (this.map as any).pm?.disableDraw?.();
      } catch {
        /* ignore */
      }
    }
  }

  public resume(): void {
    if (this.state !== 'paused') return;
    this.state = 'drawing';
  }

  public abort(): void {
    if (this.map && this.activeLayer) {
      try {
        if (this.map.hasLayer(this.activeLayer)) {
          this.map.removeLayer(this.activeLayer);
        }
      } catch {
        /* ignore */
      }
    }
    this.activeLayer = null;
    this.map = null;
    this.state = 'idle';
  }

  public commit(): L.Layer | null {
    const layer = this.activeLayer;
    this.activeLayer = null;
    this.map = null;
    this.state = 'idle';
    return layer;
  }

  public getState(): DrawSessionState {
    return this.state;
  }
}
