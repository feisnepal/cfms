/**
 * Where a file's points fall against the forest (UPLOAD_EXPERIENCE_PLAN.md, UP-3.5): the forest boundary, the points inside it in green and
 * the ones outside in red, so a wrong projection or swapped columns is something the user SEES, not something we describe.
 *
 * Plain SVG (no map tiles): it must work offline and on a slow connection, and it is a sketch, not a map. When the numbers were UTM metres or
 * swapped columns the server draws them as they WOULD be if read correctly (`assumed`), and the caption says so.
 */
import { useMemo } from 'react';
import { useT } from '../i18n/hooks';

export interface UploadPreview {
  points: Array<[number, number]>;
  /** how the numbers were read: as_is | utm_zone_44 | utm_zone_45 | swapped */
  assumed: string;
  boundary: { type: string; coordinates: unknown } | null;
}

const W = 320;
const H = 220;
const PAD = 12;

type Ring = Array<[number, number]>;

function rings(boundary: UploadPreview['boundary']): Ring[] {
  if (!boundary) return [];
  const c = boundary.coordinates as any;
  if (boundary.type === 'Polygon') return [c[0] as Ring];
  if (boundary.type === 'MultiPolygon') return (c as any[]).map((p) => p[0] as Ring);
  return [];
}

/** ray casting: is the point inside the ring? */
export function insideRing(p: [number, number], ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function UploadPointsPreview({ preview }: { preview: UploadPreview }) {
  const t = useT();
  const view = useMemo(() => {
    const rs = rings(preview.boundary);
    const all: Array<[number, number]> = [...rs.flat(), ...preview.points];
    if (!all.length) return null;
    const xs = all.map((p) => p[0]);
    const ys = all.map((p) => p[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const k = Math.min((W - 2 * PAD) / (x1 - x0 || 1e-6), (H - 2 * PAD) / (y1 - y0 || 1e-6));
    const sx = (x: number) => PAD + (x - x0) * k;
    const sy = (y: number) => H - PAD - (y - y0) * k; // north is up
    const paths = rs.map((r) => 'M' + r.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join('L') + 'Z').join(' ');
    const pts = preview.points.map((p) => ({ cx: sx(p[0]), cy: sy(p[1]), inside: rs.length ? rs.some((r) => insideRing(p, r)) : true }));
    return { paths, pts };
  }, [preview]);

  if (!view) return null;
  const outside = view.pts.filter((p) => !p.inside).length;
  const note =
    preview.assumed === 'as_is'
      ? null
      : preview.assumed === 'swapped'
        ? t('uploadPreview.assumedSwapped')
        : t('uploadPreview.assumedUtm', { zone: preview.assumed.replace('utm_zone_', '') });

  return (
    <figure className="my-2" data-testid="upload-points-preview" data-outside={outside}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: 420, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 4 }} role="img" aria-label={t('uploadPreview.title')}>
        {view.paths && <path d={view.paths} fill="rgba(34,197,94,0.12)" stroke="#16a34a" strokeWidth={1.5} data-testid="preview-boundary" />}
        {view.pts.map((p, i) => (
          <circle key={i} cx={p.cx} cy={p.cy} r={2.5} fill={p.inside ? '#16a34a' : '#dc2626'} data-inside={p.inside ? 'true' : 'false'} />
        ))}
      </svg>
      <figcaption className="text-xs text-gray-600">
        <span style={{ color: '#16a34a' }}>●</span> {t('uploadPreview.inside', { count: view.pts.length - outside })}{' '}
        <span style={{ color: '#dc2626' }}>●</span> {t('uploadPreview.outside', { count: outside })}
        {note && <div className="text-amber-700" data-testid="preview-note">{note}</div>}
      </figcaption>
    </figure>
  );
}

export default UploadPointsPreview;
