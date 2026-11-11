import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { useEffect, useRef } from 'react';

export function MapScaleBar() {
  const map = useMap();
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = L.DomUtil.create('div', 'map-scale-bar');
    el.style.cssText = 'position:absolute;bottom:8px;left:60px;z-index:501;pointer-events:none;';
    map.getContainer().appendChild(el);
    ref.current = el;

    function update() {
      const center = map.getCenter();
      const zoom = map.getZoom();
      const size = map.getSize();
      if (!center || !size) return;

      const p1 = map.containerPointToLatLng([0, 0]);
      const p2 = map.containerPointToLatLng([100, 0]);
      const metersPer100px = p1.distanceTo(p2);
      const scaleKm = metersPer100px / 1000;

      const niceKm = niceScaleValue(scaleKm);
      const pxWidth = (niceKm * 100) / scaleKm;

      const rf = Math.round(getScaleDenominator(center.lat, zoom));

      el.innerHTML = `
        <div class="msb-bar" style="position:relative;width:${pxWidth}px;">
          <div style="position:absolute;top:0;left:0;right:0;height:0;border-top:2px solid #444;box-shadow:0 0 3px #fff;"></div>
          <div style="position:absolute;top:-3px;left:0;width:1px;height:6px;background:#444;box-shadow:0 0 3px #fff;"></div>
          <div style="position:absolute;top:-3px;right:0;width:1px;height:6px;background:#444;box-shadow:0 0 3px #fff;"></div>
          <div style="position:absolute;top:-3px;left:25%;width:1px;height:4px;background:#444;box-shadow:0 0 3px #fff;"></div>
          <div style="position:absolute;top:-3px;left:50%;width:1px;height:4px;background:#444;box-shadow:0 0 3px #fff;"></div>
          <div style="position:absolute;top:-3px;left:75%;width:1px;height:4px;background:#444;box-shadow:0 0 3px #fff;"></div>
          <div style="position:absolute;top:6px;left:0;font-size:10px;font-weight:600;color:#1a1a2e;text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,0 0 4px #fff;white-space:nowrap;">0</div>
          <div style="position:absolute;top:6px;left:50%;font-size:10px;font-weight:600;color:#1a1a2e;text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,0 0 4px #fff;transform:translateX(-50%);white-space:nowrap;">${(niceKm / 2).toFixed(2)}</div>
          <div style="position:absolute;top:6px;right:0;font-size:10px;font-weight:600;color:#1a1a2e;text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,0 0 4px #fff;white-space:nowrap;">${niceKm.toFixed(2)} km</div>
          <div style="position:absolute;top:22px;left:0;font-size:9px;font-weight:600;color:#1a1a2e;text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,0 0 4px #fff;white-space:nowrap;">1:${rf.toLocaleString()}</div>
        </div>`;
    }

    map.on('moveend zoomend', update);
    update();

    return () => {
      map.off('moveend zoomend', update);
      if (el.parentNode) el.parentNode.removeChild(el);
    };
  }, [map]);

  return null;
}

function niceScaleValue(rawKm: number): number {
  const n = Math.pow(10, Math.floor(Math.log10(rawKm)));
  const candidates = [n, n * 2, n * 5, n * 10];
  let best = candidates[0];
  for (const c of candidates) {
    if (Math.abs(c - rawKm) < Math.abs(best - rawKm)) best = c;
  }
  return best;
}

function getScaleDenominator(lat: number, zoom: number): number {
  const metersPerPixel = 156543.03392 * Math.cos((lat * Math.PI) / 180) / Math.pow(2, zoom);
  const dpi = 96;
  const metersPerInch = 0.0254;
  return Math.round(metersPerPixel * dpi / metersPerInch);
}