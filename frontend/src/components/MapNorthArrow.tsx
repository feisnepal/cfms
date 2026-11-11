import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { useEffect, useRef } from 'react';

export function MapNorthArrow() {
  const map = useMap();
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = L.DomUtil.create('div', 'map-north-arrow');
    el.innerHTML = `<svg viewBox="0 0 24 32" width="24" height="32">
      <defs>
        <filter id="na-shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="1" dy="1" stdDeviation="2" flood-color="#fff" flood-opacity="0.9"/>
        </filter>
      </defs>
      <line x1="12" y1="28" x2="12" y2="6" stroke="#444" stroke-width="1.5" filter="url(#na-shadow)"/>
      <polygon points="12,2 5,11 19,11" fill="#444" filter="url(#na-shadow)"/>
      <text x="12" y="31" text-anchor="middle" font-size="8" font-weight="700"
        stroke="#fff" stroke-width="3" stroke-linejoin="round" fill="#444">N</text>
      <text x="12" y="31" text-anchor="middle" font-size="8" font-weight="700" fill="#444">N</text>
    </svg>`;
    map.getContainer().appendChild(el);
    ref.current = el;
    return () => { if (el.parentNode) el.parentNode.removeChild(el); };
  }, [map]);

  return null;
}