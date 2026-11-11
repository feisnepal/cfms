/**
 * Field book lines: which points to join, and which to leave alone.
 *
 * Owner's rule: the OUTER points, joined in order, close into a polygon outline; the INTERNAL points are open lines
 * that are never closed -- and never joined to one another, because `I5` and `I6` can be the end of one edge and the
 * start of a different one.
 *
 * The server stores, on every point, each line it is on and its place in that line (`lines`: `{"I-2": 5, "O-1": 12}`).
 * A junction sits on every line that meets there, so every line is rebuilt end to end with its shared end points.
 * This is the browser twin of `backend/app/services/fieldbook_lines.py`.
 *
 * Line ids: `O-n` outer ring (closed) | `I-n` internal edge (open) | `L-n` a free-standing internal loop, closed
 * because it has no ends (a sub-area inside a unit).
 */
import type { Feature } from 'geojson';

export type FieldbookLineKind = 'outer' | 'internal';

export interface FieldbookLine {
  id: string;
  kind: FieldbookLineKind;
  /** true: the last point connects back to the first (drawn as a polygon outline) */
  closed: boolean;
  /** Leaflet order: [lat, lng]. A closed line repeats its first position at the end. */
  positions: [number, number][];
  /** point labels, in order */
  labels: string[];
}

export const lineKind = (id: string): FieldbookLineKind => (id.startsWith('O-') ? 'outer' : 'internal');
export const lineIsClosed = (id: string): boolean => id.startsWith('O-') || id.startsWith('L-');

const sortKey = (id: string): [number, number] => {
  const [prefix, n] = id.split('-');
  return [({ O: 0, I: 1, L: 2 } as Record<string, number>)[prefix] ?? 3, Number(n) || 0];
};

/** Group Field Book point features into their lines. Points that are on no line (an older, ungrouped book) give none. */
export function buildFieldbookLines(features: Feature[] | null | undefined): FieldbookLine[] {
  const members = new Map<string, { order: number; lat: number; lng: number; label: string }[]>();
  for (const f of features ?? []) {
    if (f.geometry?.type !== 'Point') continue;
    const memberships = (f.properties as { lines?: Record<string, number> } | null)?.lines;
    if (!memberships || typeof memberships !== 'object') continue;
    const [lng, lat] = f.geometry.coordinates as number[];
    const label = String((f.properties as { point_label?: string }).point_label ?? '');
    for (const [id, order] of Object.entries(memberships)) {
      if (!members.has(id)) members.set(id, []);
      members.get(id)!.push({ order: Number(order), lat, lng, label });
    }
  }
  return [...members.keys()]
    .sort((a, b) => {
      const [pa, na] = sortKey(a);
      const [pb, nb] = sortKey(b);
      return pa - pb || na - nb;
    })
    .map((id) => {
      const ordered = members.get(id)!.sort((a, b) => a.order - b.order);
      const positions = ordered.map((m) => [m.lat, m.lng] as [number, number]);
      const closed = lineIsClosed(id);
      if (closed && positions.length > 1) positions.push([...positions[0]] as [number, number]);
      return { id, kind: lineKind(id), closed, positions, labels: ordered.map((m) => m.label) };
    });
}

/** One line of the legend per kind of line drawn. */
export function summariseLines(lines: FieldbookLine[]) {
  return {
    outerRings: lines.filter((l) => l.kind === 'outer').length,
    internalEdges: lines.filter((l) => l.kind === 'internal' && !l.closed).length,
    loops: lines.filter((l) => l.kind === 'internal' && l.closed).length,
  };
}
