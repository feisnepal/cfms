import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { useEffect, useRef } from 'react';

export function MapGrid() {
  const map = useMap();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = L.DomUtil.create('div', 'map-grid-overlay');
    container.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:500;overflow:hidden;';
    map.getContainer().appendChild(container);
    containerRef.current = container;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.style.cssText = 'width:100%;height:100%;position:absolute;top:0;left:0;';
    svg.setAttribute('overflow', 'visible');
    container.appendChild(svg);
    svgRef.current = svg;

    function drawGrid() {
      if (!svg) return;
      const bounds = map.getBounds();
      const zoom = map.getZoom();
      const size = map.getSize();

      svg.setAttribute('viewBox', `0 0 ${size.x} ${size.y}`);

      if (zoom < 6) { svg.innerHTML = ''; return; }

      const latRange = bounds.getNorth() - bounds.getSouth();
      const lngRange = bounds.getEast() - bounds.getWest();
      const precision = getPrecision(zoom);
      const latInterval = niceInterval(latRange, precision);
      const lngInterval = niceInterval(lngRange, precision);

      const latMin = Math.floor(bounds.getSouth() / latInterval) * latInterval;
      const latMax = Math.ceil(bounds.getNorth() / latInterval) * latInterval;
      const lngMin = Math.floor(bounds.getWest() / lngInterval) * lngInterval;
      const lngMax = Math.ceil(bounds.getEast() / lngInterval) * lngInterval;

      const decPlaces = Math.max(0, Math.ceil(-Math.log10(latInterval)));

      let html = '';

      for (let lat = latMin; lat <= latMax; lat += latInterval) {
        if (lat < bounds.getSouth() - latInterval * 0.1 || lat > bounds.getNorth() + latInterval * 0.1) continue;
        const pt = map.latLngToContainerPoint([lat, 0]);
        html += `<line x1="0" y1="${pt.y}" x2="${size.x}" y2="${pt.y}" stroke="white" stroke-width="2.5" opacity="0.5"/>`;
        html += `<line x1="0" y1="${pt.y}" x2="${size.x}" y2="${pt.y}" stroke="#555" stroke-width="0.5" opacity="0.6"/>`;
        html += `<text x="${size.x - 8}" y="${pt.y - 4}" text-anchor="end" font-size="10" font-weight="600"
          stroke="#fff" stroke-width="3" stroke-linejoin="round" fill="#222">${lat.toFixed(decPlaces)}°</text>`;
        html += `<text x="${size.x - 8}" y="${pt.y - 4}" text-anchor="end" font-size="10" font-weight="600"
          fill="#222">${lat.toFixed(decPlaces)}°</text>`;
      }

      for (let lng = lngMin; lng <= lngMax; lng += lngInterval) {
        if (lng < bounds.getWest() - lngInterval * 0.1 || lng > bounds.getEast() + lngInterval * 0.1) continue;
        const pt = map.latLngToContainerPoint([0, lng]);
        html += `<line x1="${pt.x}" y1="0" x2="${pt.x}" y2="${size.y}" stroke="white" stroke-width="2.5" opacity="0.5"/>`;
        html += `<line x1="${pt.x}" y1="0" x2="${pt.x}" y2="${size.y}" stroke="#555" stroke-width="0.5" opacity="0.6"/>`;
        html += `<text x="${pt.x + 4}" y="14" text-anchor="start" font-size="10" font-weight="600"
          stroke="#fff" stroke-width="3" stroke-linejoin="round" fill="#222">${lng.toFixed(decPlaces)}°</text>`;
        html += `<text x="${pt.x + 4}" y="14" text-anchor="start" font-size="10" font-weight="600"
          fill="#222">${lng.toFixed(decPlaces)}°</text>`;
      }

      svg.innerHTML = html;
    }

    function getPrecision(zoom: number): number {
      if (zoom <= 7) return 1;
      if (zoom <= 9) return 0.5;
      if (zoom <= 10) return 0.2;
      if (zoom <= 11) return 0.1;
      if (zoom <= 12) return 0.05;
      if (zoom <= 13) return 0.02;
      return 0.01;
    }

    function niceInterval(range: number, precision: number): number {
      const raw = range / 6;
      const n = Math.pow(10, Math.floor(Math.log10(raw)));
      const candidates = [n, n * 2, n * 5, n * 10];
      let best = candidates[0];
      for (const c of candidates) {
        if (Math.abs(c - raw) < Math.abs(best - raw)) best = c;
      }
      return Math.max(best, precision);
    }

    map.on('moveend zoomend', drawGrid);
    drawGrid();

    return () => {
      map.off('moveend zoomend', drawGrid);
      if (container && container.parentNode) container.parentNode.removeChild(container);
    };
  }, [map]);

  return null;
}