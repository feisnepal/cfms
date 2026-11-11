/**
 * autoBlocks.ts — builds an initial block set from a forest boundary.
 * Shared by the My CFOPs "Create New" flow and the workspace-based creation
 * page so the block auto-creation contract stays in one place. The workspace's
 * cut tool later divides these into named blocks.
 */
import { calculateAreaHectares } from '../utils/geometryValidation';

export interface AutoBlock {
  id: string;
  name: string;
  geometry: { type: 'Polygon'; coordinates: number[][][] };
  area: number;
}

export function buildAutoBlocks(boundary: any, forestName: string): AutoBlock[] {
  if (!boundary || !boundary.coordinates) return [];
  if (boundary.type === 'MultiPolygon') {
    return boundary.coordinates.map((coords: number[][][], index: number) => {
      const geometry = { type: 'Polygon', coordinates: coords };
      return {
        id: `block-${Date.now()}-${index}`,
        name: `B${index + 1}`, // owner 2026-10-11: B1, B2 ... (the forest is already named)
        geometry,
        area: calculateAreaHectares(geometry),
      };
    });
  }
  if (boundary.type === 'Polygon') {
    const area = calculateAreaHectares(boundary);
    return [{
      id: `block-${Date.now()}`,
      name: 'B1',
      geometry: boundary,
      area,
    }];
  }
  return [];
}
