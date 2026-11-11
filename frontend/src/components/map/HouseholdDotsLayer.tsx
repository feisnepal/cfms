/**
 * Household vulnerability / priority-settlement dots, drawn like the print maps: a Reds ramp over the score range, a
 * thin dark edge; settlement dots are sized by household count. Not interactive (a dot never swallows a click meant for
 * the unit under it) and never labelled (no identifiers on the map).
 */
import { CircleMarker } from 'react-leaflet';
import { sampleRamp } from '../../lib/colorRamps';
import type { HouseholdDots } from '../../hooks/useHazardHouseholds';

const STEPS = 9;
export const DOT_RAMP = (): string[] => sampleRamp('reds', STEPS);

export function dotColour(score: number, min: number, max: number, ramp: string[] = DOT_RAMP()): string {
  const t = max > min ? (score - min) / (max - min) : 1;
  return ramp[Math.max(0, Math.min(ramp.length - 1, Math.round(t * (ramp.length - 1))))];
}

export function HouseholdDotsLayer({ data, opacity }: { data: HouseholdDots | undefined; opacity: number }) {
  if (!data || data.state !== 'ready') return null;
  const ramp = DOT_RAMP();
  const maxN = Math.max(1, ...data.features.map((f) => f.properties.n ?? 1));
  return (
    <>
      {data.features.map((f, i) => {
        const [lon, lat] = f.geometry.coordinates;
        const radius = data.kind === 'settlements' ? 6 + 8 * ((f.properties.n ?? 1) / maxN) : 5;
        return (
          <CircleMarker
            key={`${data.kind}-${i}`}
            center={[lat, lon]}
            radius={radius}
            interactive={false}
            pathOptions={{
              color: '#333333',
              weight: 0.8,
              fillColor: dotColour(f.properties.score, data.min, data.max, ramp),
              fillOpacity: Math.min(0.92, opacity),
              opacity,
            }}
          />
        );
      })}
    </>
  );
}
