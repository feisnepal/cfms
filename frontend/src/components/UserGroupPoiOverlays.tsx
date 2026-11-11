import { useEffect, useState } from 'react';
import { Marker, GeoJSON, Popup, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import api from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';

interface PoiPoint {
  name?: string;
  type?: string;
  lat: number;
  lon: number;
}

interface PoiRiver {
  name?: string;
  geometry: any;
}

interface UserGroupPoiData {
  poi: PoiPoint[];
  education: PoiPoint[];
  health: PoiPoint[];
  rivers: PoiRiver[];
}

const poiIcon = L.divIcon({
  html: `<div style="font-size: 16px; filter: hue-rotate(200deg);">📍</div>`,
  className: 'poi-marker',
  iconSize: [20, 20],
  iconAnchor: [10, 20],
});

const educationIcon = L.divIcon({
  html: `<div style="font-size: 16px;">🏫</div>`,
  className: 'education-marker',
  iconSize: [20, 20],
  iconAnchor: [10, 20],
});

const healthIcon = L.divIcon({
  html: `<div style="font-size: 16px;">🏥</div>`,
  className: 'health-marker',
  iconSize: [20, 20],
  iconAnchor: [10, 20],
});

/**
 * POI overlays in the workspace (BG-3). Fetches `GET /user-group/poi` once the
 * results section turns any category on, and shows exactly the categories the
 * section has enabled — mirroring the icons/data/colours of the legacy tab
 * (`UserGroupMapVisualization.tsx:323-426`).
 */
export function UserGroupPoiOverlays({ calculationId }: { calculationId: string }) {
  const vis = useWorkspaceStore((s) => s.userGroupPoiVisible);
  const anyVisible = !!vis.education || !!vis.health || !!vis.poi || !!vis.rivers;
  const [poiData, setPoiData] = useState<UserGroupPoiData | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!anyVisible) {
      setPoiData(null);
      return;
    }
    api
      .get(`/api/calculations/${calculationId}/user-group/poi`, { params: { layer_type: 'all' } })
      .then((res) => { if (!cancelled) setPoiData(res.data); })
      .catch(() => { if (!cancelled) setPoiData(null); });
    return () => { cancelled = true; };
  }, [calculationId, anyVisible]);

  if (!poiData) return null;

  return (
    <>
      {vis.poi && poiData.poi?.length > 0 && poiData.poi.map((p, idx) => (
        <Marker key={`poi-${idx}`} position={[p.lat, p.lon]} icon={poiIcon}>
          <Tooltip direction="top"><div style={{ fontSize: '11px', fontWeight: 'bold' }}>{p.name}</div></Tooltip>
          <Popup>
            <div>
              <strong>{p.name}</strong><br />
              Type: {p.type || 'N/A'}
            </div>
          </Popup>
        </Marker>
      ))}
      {vis.education && poiData.education?.length > 0 && poiData.education.map((p, idx) => (
        <Marker key={`edu-${idx}`} position={[p.lat, p.lon]} icon={educationIcon}>
          <Tooltip direction="top"><div style={{ fontSize: '11px', fontWeight: 'bold' }}>{p.name}</div></Tooltip>
          <Popup>
            <div><strong>{p.name}</strong></div>
          </Popup>
        </Marker>
      ))}
      {vis.health && poiData.health?.length > 0 && poiData.health.map((p, idx) => (
        <Marker key={`health-${idx}`} position={[p.lat, p.lon]} icon={healthIcon}>
          <Tooltip direction="top"><div style={{ fontSize: '11px', fontWeight: 'bold' }}>{p.name}</div></Tooltip>
          <Popup>
            <div><strong>{p.name}</strong></div>
          </Popup>
        </Marker>
      ))}
      {vis.rivers && poiData.rivers?.length > 0 && poiData.rivers.map((r, idx) => (
        <GeoJSON
          key={`river-${idx}`}
          data={r.geometry}
          style={{ color: '#0066ff', weight: 2, opacity: 0.8 }}
        >
          <Tooltip direction="top"><div style={{ fontSize: '11px', fontWeight: 'bold' }}>{r.name}</div></Tooltip>
          <Popup>
            <div><strong>{r.name}</strong></div>
          </Popup>
        </GeoJSON>
      ))}
    </>
  );
}