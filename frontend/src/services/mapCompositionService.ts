import { MapComposition, defaultComposition } from '../lib/mapComposition';
import { forestApi } from '../services/api';

/**
 * MapCompositionService - manages map compositions for a calculation.
 * Persists to calculation.result_data via existing /result-data endpoint.
 */
export class MapCompositionService {
  private calculationId: string;
  private cache: { compositions: MapComposition[]; activeId: string | null } | null = null;

  constructor(calculationId: string) {
    this.calculationId = calculationId;
  }

  /**
   * Load compositions from calculation.result_data
   */
  async load(): Promise<{ compositions: MapComposition[]; activeCompositionId: string | null }> {
    try {
      const calculation = await forestApi.getCalculation(this.calculationId);
      const resultData = calculation.result_data || {};
      const compositions = (resultData.mapCompositions as MapComposition[]) || [];
      const activeId = resultData.activeCompositionId as string | null;

      this.cache = { compositions, activeId: activeId || null };
      return { compositions, activeCompositionId: activeId || null };
    } catch (error) {
      console.warn('Failed to load map compositions:', error);
      const fallback = defaultComposition();
      this.cache = { compositions: [fallback], activeId: fallback.id };
      return { compositions: [fallback], activeCompositionId: fallback.id };
    }
  }

  /**
   * Save compositions to calculation.result_data
   */
  async save(compositions: MapComposition[], activeId: string | null): Promise<void> {
    this.cache = { compositions, activeId };
    await forestApi.updateResultData(this.calculationId, {
      mapCompositions: compositions,
      activeCompositionId: activeId,
    });
  }

  /**
   * Create a new composition
   */
  async createComposition(partial?: Partial<MapComposition>): Promise<MapComposition> {
    const newComp: MapComposition = {
      ...defaultComposition(),
      ...partial,
      id: crypto.randomUUID(),
      version: 1,
    };

    const comps = this.cache ? [...this.cache.compositions, newComp] : [newComp];
    await this.save(comps, newComp.id);
    return newComp;
  }

  /**
   * Update an existing composition
   */
  async updateComposition(id: string, updates: Partial<MapComposition>): Promise<void> {
    if (!this.cache) return;
    const comps = this.cache.compositions.map(c =>
      c.id === id ? { ...c, ...updates, version: c.version + 1 } : c
    );
    await this.save(comps, this.cache.activeId);
  }

  /**
   * Delete a composition
   */
  async deleteComposition(id: string): Promise<void> {
    if (!this.cache) return;
    const comps = this.cache.compositions.filter(c => c.id !== id);
    const newActive = this.cache.activeId === id ? (comps[0]?.id || null) : this.cache.activeId;
    await this.save(comps, newActive);
  }

  /**
   * Set active composition
   */
  async setActive(id: string): Promise<void> {
    if (!this.cache) return;
    await this.save(this.cache.compositions, id);
  }

  /**
   * Get cached data without fetching
   */
  getCached(): { compositions: MapComposition[]; activeId: string | null } | null {
    return this.cache;
  }
}