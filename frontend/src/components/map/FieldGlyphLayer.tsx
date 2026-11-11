/**
 * Field-inventory charts over the map: one small chart per unit. The server sends the numbers and the colours (the print
 * placeholder's own, with the user's laid over them); this file only draws them:
 *
 *   stackbar  — height ∝ the unit's total against the forest's largest ("where is the timber?"), segments = classes, small at the bottom
 *   pie       — each class's share            waffle   — 5×5 cells filled by share
 *   sparkline — the class curve (reverse-J check)         ternary — one dot in the regen : pole : tree triangle
 *   radar     — five axes scaled over all units
 *
 * Labels are compact and appear only when there is room (the server writes them): nothing below zoom 13, the short one from 14,
 * the long one from 16. A class a forest does not have is not drawn (no hole); any class may be empty in any forest.
 */
import { useMemo, useState } from 'react';
import L from 'leaflet';
import { Marker, Tooltip, useMapEvent, useMap } from 'react-leaflet';
import type { FieldGlyphs, GlyphShape, GlyphUnit } from '../../hooks/useFieldGlyphs';
import { CATEGORICAL } from '../../lib/semanticPalettes';
import { useT } from '../../i18n/hooks';

const BAR_W = 12;
const BAR_MIN = 6;
const BAR_MAX = 46;
const PIE_D = 28;
const WAFFLE_N = 5;
const WAFFLE_CELL = 5;
const SPARK_W = 32;
const SPARK_H = 18;
const TRI_W = 30;
const TRI_H = 26;
const RADAR_D = 30;

export function glyphHeight(total: number, max: number): number {
  if (!(max > 0) || !(total > 0)) return BAR_MIN;
  return Math.max(BAR_MIN, Math.round(BAR_MAX * (total / max)));
}

/** The compact label for a zoom level: '' (none) · short · long. Uses the server's own texts when it sent them. */
export function glyphLabel(u: GlyphUnit, zoom: number): string {
  if (zoom < 14) return '';
  if (u.text_long !== undefined || u.text_short !== undefined) return zoom < 16 ? (u.text_short ?? '') : (u.text_long ?? '');
  const stock = `${Math.round(u.total_m3_per_ha)}`;
  if (zoom < 16) return stock;
  return u.ge40_pct == null ? `${stock} m³/ha` : `${stock} m³/ha · ${Math.round(u.ge40_pct)}% ≥40`;
}

/** Only a plain #rrggbb reaches the SVG: the colours come from the server, but nothing unchecked goes into markup. */
export const safeColour = (c: string): string => (/^#[0-9a-fA-F]{6}$/.test(c) ? c : '#bdbdbd');

const f1 = (n: number): string => n.toFixed(1);

interface Drawn {
  svg: string;
  w: number;
  h: number;
}

function stackbar(u: GlyphUnit, max: number): Drawn {
  const total = u.total ?? u.total_m3_per_ha;
  const h = glyphHeight(total, max);
  let y = h;
  const rects = u.segments
    .map((s) => {
      const seg = total > 0 ? (s.value / total) * h : 0;
      y -= seg;
      return `<rect x="0" y="${f1(Math.max(0, y))}" width="${BAR_W}" height="${f1(seg)}" fill="${safeColour(s.color)}" stroke="#fff" stroke-width="0.6"/>`;
    })
    .join('');
  // a unit with a summary but no data is a thin empty outline (a finding, not a gap)
  const empty = u.segments.length === 0 ? `<rect x="0.5" y="0.5" width="${BAR_W - 1}" height="${h - 1}" fill="none" stroke="#888" stroke-dasharray="2 2"/>` : '';
  return { svg: `<svg width="${BAR_W}" height="${h}">${rects}${empty}</svg>`, w: BAR_W, h };
}

const TRI_BAR_W = 8;
const TRI_BAR_GAP = 2;
/** Three bars side by side (growing stock, MAI, AAH), each stacked by class and scaled to the largest of its own kind in the forest,
 *  because MAI and AAH are a few percent of the stock and would vanish beside it. The hover card carries the real numbers. */
function triplebar(u: GlyphUnit, maxes: { gs: number; mai: number; aah: number }): Drawn {
  const bars = u.bars ?? [];
  const w = 3 * TRI_BAR_W + 2 * TRI_BAR_GAP;
  const parts = bars.map((b, bi) => {
    const h = glyphHeight(b.total, maxes[b.key]);
    let y = h;
    const x = bi * (TRI_BAR_W + TRI_BAR_GAP);
    return b.segments
      .map((s) => {
        const seg = b.total > 0 ? (s.value / b.total) * h : 0;
        y -= seg;
        return `<rect x="${x}" y="${f1(Math.max(0, y))}" width="${TRI_BAR_W}" height="${f1(seg)}" fill="${safeColour(s.color)}" stroke="#fff" stroke-width="0.5"/>`;
      })
      .join('');
  });
  return { svg: `<svg width="${w}" height="${BAR_MAX}" style="overflow:visible"><g transform="translate(0 0)">${parts.join('')}</g></svg>`, w, h: BAR_MAX };
}

function pie(u: GlyphUnit): Drawn {
  const r = PIE_D / 2;
  const total = u.segments.reduce((a, s) => a + s.value, 0);
  const live = u.segments.filter((s) => s.value > 0);
  if (total <= 0) {
    return { svg: `<svg width="${PIE_D}" height="${PIE_D}"><circle cx="${r}" cy="${r}" r="${r - 1}" fill="none" stroke="#888" stroke-dasharray="2 2"/></svg>`, w: PIE_D, h: PIE_D };
  }
  if (live.length === 1) {
    return { svg: `<svg width="${PIE_D}" height="${PIE_D}"><circle cx="${r}" cy="${r}" r="${r - 0.5}" fill="${safeColour(live[0].color)}" stroke="#fff" stroke-width="0.6"/></svg>`, w: PIE_D, h: PIE_D };
  }
  let a0 = -Math.PI / 2;
  const paths = live.map((s) => {
    const a1 = a0 + (2 * Math.PI * s.value) / total;
    const rr = r - 0.5;
    const [x0, y0, x1, y1] = [r + rr * Math.cos(a0), r + rr * Math.sin(a0), r + rr * Math.cos(a1), r + rr * Math.sin(a1)];
    const d = `M${r} ${r} L${f1(x0)} ${f1(y0)} A${rr} ${rr} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${f1(x1)} ${f1(y1)} Z`;
    a0 = a1;
    return `<path d="${d}" fill="${safeColour(s.color)}" stroke="#fff" stroke-width="0.6"/>`;
  });
  return { svg: `<svg width="${PIE_D}" height="${PIE_D}">${paths.join('')}</svg>`, w: PIE_D, h: PIE_D };
}

function waffle(u: GlyphUnit): Drawn {
  const total = u.segments.reduce((a, s) => a + s.value, 0);
  const cells: string[] = [];
  for (const s of u.segments) {
    const n = Math.max(0, Math.round((WAFFLE_N * WAFFLE_N * s.value) / (total || 1)));
    for (let i = 0; i < n; i++) cells.push(safeColour(s.color));
  }
  while (cells.length < WAFFLE_N * WAFFLE_N) cells.push('#eeeeee');
  const size = WAFFLE_N * (WAFFLE_CELL + 1);
  const rects = cells
    .slice(0, WAFFLE_N * WAFFLE_N)
    .map((c, i) => {
      const [row, col] = [Math.floor(i / WAFFLE_N), i % WAFFLE_N];
      // the first class starts at the bottom row, like the print map
      return `<rect x="${col * (WAFFLE_CELL + 1)}" y="${(WAFFLE_N - 1 - row) * (WAFFLE_CELL + 1)}" width="${WAFFLE_CELL}" height="${WAFFLE_CELL}" fill="${c}"/>`;
    })
    .join('');
  return { svg: `<svg width="${size}" height="${size}">${rects}</svg>`, w: size, h: size };
}

function sparkline(u: GlyphUnit): Drawn {
  const vals = u.segments.map((s) => s.value);
  const max = Math.max(0, ...vals);
  if (vals.length < 2 || max <= 0) {
    return { svg: `<svg width="${SPARK_W}" height="${SPARK_H}"><line x1="0" y1="${SPARK_H - 1}" x2="${SPARK_W}" y2="${SPARK_H - 1}" stroke="#888" stroke-dasharray="2 2"/></svg>`, w: SPARK_W, h: SPARK_H };
  }
  const pts = vals.map((v, i) => [(SPARK_W - 4) * (i / (vals.length - 1)) + 2, SPARK_H - 2 - (SPARK_H - 4) * (v / max)]);
  const last = pts[pts.length - 1];
  return {
    svg: `<svg width="${SPARK_W}" height="${SPARK_H}"><polyline points="${pts.map((p) => `${f1(p[0])},${f1(p[1])}`).join(' ')}" fill="none" stroke="#333" stroke-width="1.1"/><circle cx="${f1(last[0])}" cy="${f1(last[1])}" r="2" fill="#c62828"/></svg>`,
    w: SPARK_W,
    h: SPARK_H,
  };
}

function ternary(u: GlyphUnit): Drawn {
  const tri = `<polygon points="${TRI_W / 2},1 1,${TRI_H - 1} ${TRI_W - 1},${TRI_H - 1}" fill="none" stroke="#999" stroke-width="0.8"/>`;
  const v = u.segments.map((s) => s.value);
  const total = v.reduce((a, b) => a + b, 0);
  if (v.length !== 3 || total <= 0) return { svg: `<svg width="${TRI_W}" height="${TRI_H}">${tri}</svg>`, w: TRI_W, h: TRI_H };
  const [a, b, c] = v.map((x) => x / total); // regeneration (top), poles (left), trees (right)
  const x = a * (TRI_W / 2) + b * 1 + c * (TRI_W - 1);
  const y = a * 1 + b * (TRI_H - 1) + c * (TRI_H - 1);
  return { svg: `<svg width="${TRI_W}" height="${TRI_H}">${tri}<circle cx="${f1(x)}" cy="${f1(y)}" r="3" fill="#2e7d32" stroke="#fff" stroke-width="0.8"/></svg>`, w: TRI_W, h: TRI_H };
}

function radar(u: GlyphUnit): Drawn {
  const fr = u.radar ?? [];
  const r = RADAR_D / 2;
  const k = fr.length || 1;
  const pts = fr.map((f, i) => {
    const ang = Math.PI / 2 - (2 * Math.PI * i) / k;
    return `${f1(r + (r - 1) * f * Math.cos(ang))},${f1(r - (r - 1) * f * Math.sin(ang))}`;
  });
  const fill = safeColour(CATEGORICAL.condition?.Moderate ?? '#f9a825');
  return {
    svg:
      `<svg width="${RADAR_D}" height="${RADAR_D}"><circle cx="${r}" cy="${r}" r="${r - 1}" fill="#fff" fill-opacity=".55" stroke="#ccc" stroke-width=".6"/>` +
      `<circle cx="${r}" cy="${r}" r="${(r - 1) / 2}" fill="none" stroke="#ccc" stroke-width=".6"/>` +
      (pts.length ? `<polygon points="${pts.join(' ')}" fill="${fill}" fill-opacity=".45" stroke="#1b5e20" stroke-width="1"/>` : '') +
      '</svg>',
    w: RADAR_D,
    h: RADAR_D,
  };
}

export function glyphIconHtml(u: GlyphUnit, max: number, zoom: number, shape: GlyphShape = 'stackbar', maxes?: { gs: number; mai: number; aah: number }): { html: string; h: number; w: number } {
  const g =
    shape === 'triplebar' ? triplebar(u, maxes ?? { gs: max, mai: max, aah: max })
    : shape === 'pie' ? pie(u)
    : shape === 'waffle' ? waffle(u)
    : shape === 'sparkline' ? sparkline(u)
    : shape === 'ternary' ? ternary(u)
    : shape === 'radar' ? radar(u)
    : stackbar(u, max);
  const text = glyphLabel(u, zoom);
  const label = text
    ? `<span style="position:absolute;top:${g.h + 2}px;left:50%;transform:translateX(-50%);white-space:nowrap;font:600 9px/1 sans-serif;color:#111;text-shadow:0 0 2px #fff,0 0 2px #fff,0 0 3px #fff">${text}</span>`
    : '';
  return {
    h: g.h,
    w: g.w,
    html: `<div style="position:relative;width:${g.w}px;height:${g.h}px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.45))">${g.svg}${label}</div>`,
  };
}

/** The hover card. React text nodes: a unit name (user text) can never become markup. */
export function GlyphHover({ u, lang, axes }: { u: GlyphUnit; lang: string; axes?: Array<{ label_ne: string; label_en: string }> }) {
  const ne = lang.startsWith('ne');
  const t = useT();
  const total = u.total ?? u.total_m3_per_ha;
  return (
    <div style={{ fontSize: 11 }} data-testid="glyph-hover">
      <b>{u.name}</b>
      {u.radar ? null : <> — {u.text_long || `${total.toFixed(1)} m³/ha`}</>}
      {u.radar && axes
        ? u.radar.map((f, i) => (
            <div key={i}>
              {ne ? axes[i]?.label_ne : axes[i]?.label_en}: <b>{Math.round(f * 100)}%</b>
            </div>
          ))
        : u.bars
        ? u.bars.map((b) => (
            <div key={b.key} style={{ marginTop: 3 }}>
              <b>{b.key.toUpperCase()}</b> {b.total.toFixed(1)} m³/ha{b.key === 'gs' ? '' : ' *'}
              {b.segments.slice().reverse().map((s) => (
                <div key={s.key}>
                  <span style={{ display: 'inline-block', width: 9, height: 9, background: safeColour(s.color), marginRight: 5 }} />
                  {ne ? s.label_ne : s.label_en}: <b>{s.value.toFixed(2)}</b>
                </div>
              ))}
            </div>
          ))
        : u.segments.slice().reverse().map((s) => (
            <div key={s.key}>
              <span style={{ display: 'inline-block', width: 9, height: 9, background: safeColour(s.color), marginRight: 5 }} />
              {ne ? s.label_ne : s.label_en}: <b>{s.value.toFixed(1)}</b>
            </div>
          ))}
      {u.bars && <div style={{ opacity: 0.7, marginTop: 3, whiteSpace: 'pre-line' }}>{t('analysisMaps.chart.apportioned', { defaultValue: '* MAI and AAH are worked out for the whole\nblock and shared over the classes in proportion to their stock.' })}</div>}
      {u.ge40_pct != null && <div>≥40 cm: <b>{Math.round(u.ge40_pct)}%</b></div>}
      <div style={{ opacity: 0.7 }}>{u.plots} plots</div>
    </div>
  );
}

export function FieldGlyphLayer({ data, lang }: { data: FieldGlyphs | undefined; lang: string }) {
  const map = useMap();
  const [zoom, setZoom] = useState(() => map.getZoom());
  useMapEvent('zoomend', () => setZoom(map.getZoom()));
  const ready = data && data.state === 'ready' ? data : null;
  const units = ready ? ready.units : null;
  const max = ready ? ready.max_total : 0;
  const shape: GlyphShape = ready?.shape ?? 'stackbar';
  const maxes = ready?.bar_max;
  const markers = useMemo(
    () =>
      (units ?? []).map((u) => {
        const { html, h, w } = glyphIconHtml(u, max, zoom, shape, maxes);
        return { u, icon: L.divIcon({ className: 'field-glyph', html, iconSize: [w, h], iconAnchor: [w / 2, h / 2] }) };
      }),
    [units, max, zoom, shape, maxes],
  );
  if (!ready || !units) return null;
  return (
    <>
      {markers.map(({ u, icon }) => (
        <Marker key={u.name} position={[u.anchor[1], u.anchor[0]]} icon={icon} keyboard={false} zIndexOffset={600}>
          <Tooltip direction="top" offset={[0, -6]} opacity={1}>
            <GlyphHover u={u} lang={lang} axes={shape === 'radar' ? ready.legend : undefined} />
          </Tooltip>
        </Marker>
      ))}
    </>
  );
}
