/**
 * VertexTable.tsx — Vertex coordinate table & editing panel (Task 3.3.2).
 *
 * Lists vertices of the active feature with CRS precision formatting,
 * allowing coordinate edits, vertex deletion, and insertion.
 */
import { useState } from 'react';
import type { Feature } from 'geojson';
import { useT } from '../i18n/hooks';

interface VertexTableProps {
  feature: Feature | null;
  onUpdateGeometry: (newCoords: number[][] | number[][][]) => void;
  onClose: () => void;
}

export function VertexTable({ feature, onUpdateGeometry, onClose }: VertexTableProps) {
  const t = useT();
  if (!feature || !feature.geometry) return null;

  const geom = feature.geometry;
  const coordinates: any = (geom as any).coordinates;
  const isPolygon = geom.type === 'Polygon';
  const rawVertices: number[][] = isPolygon ? coordinates[0] : coordinates;

  const [vertices, setVertices] = useState<number[][]>(rawVertices || []);

  const handleCoordinateChange = (index: number, axis: 0 | 1, val: string) => {
    const num = parseFloat(val);
    if (Number.isNaN(num)) return;
    const next = vertices.map((v, i) => {
      if (i !== index) return v;
      const copy = [...v];
      copy[axis] = num;
      return copy;
    });
    setVertices(next);
    commitChanges(next);
  };

  const handleDeleteVertex = (index: number) => {
    if (vertices.length <= 2 && isPolygon) return;
    const next = vertices.filter((_, i) => i !== index);
    setVertices(next);
    commitChanges(next);
  };

  const commitChanges = (nextVerts: number[][]) => {
    if (isPolygon) {
      // ensure closed ring
      const closed = [...nextVerts];
      if (closed.length > 0 && (closed[0][0] !== closed[closed.length - 1][0] || closed[0][1] !== closed[closed.length - 1][1])) {
        closed.push([...closed[0]]);
      }
      onUpdateGeometry([closed]);
    } else {
      onUpdateGeometry(nextVerts);
    }
  };

  return (
    <div className="vertex-table-panel" role="dialog" aria-label={t('layerPanel.vertexTableAria')} style={{
      position: 'absolute', bottom: 60, right: 20, zIndex: 1000,
      background: '#fff', padding: '16px', borderRadius: '8px',
      boxShadow: '0 4px 12px rgba(0,0,0,0.15)', width: '340px', maxHeight: '400px',
      overflowY: 'auto', border: '1px solid #e5e7eb'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
        <strong>📍 {t('layerPanel.vertexEditorTitle', { count: vertices.length }) }</strong>
        <button onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '16px' }}>&times;</button>
      </div>

      <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #e5e7eb', textAlign: 'left', color: '#6b7280' }}>
            <th style={{ padding: '4px' }}>#</th>
            <th style={{ padding: '4px' }}>{t('layerPanel.vertexLongitude')}</th>
            <th style={{ padding: '4px' }}>{t('layerPanel.vertexLatitude')}</th>
            <th style={{ padding: '4px' }}>{t('attributeTable.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {vertices.map((v, idx) => (
            <tr key={idx} style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '4px', color: '#9ca3af' }}>{idx}</td>
              <td style={{ padding: '4px' }}>
                <input
                  type="text" inputMode="decimal"
                  step="0.000001"
                  value={v[0]}
                  onChange={(e) => handleCoordinateChange(idx, 0, e.target.value)}
                  style={{ width: '90px', padding: '2px', fontSize: '11px', border: '1px solid #d1d5db', borderRadius: '4px' }}
                />
              </td>
              <td style={{ padding: '4px' }}>
                <input
                  type="text" inputMode="decimal"
                  step="0.000001"
                  value={v[1]}
                  onChange={(e) => handleCoordinateChange(idx, 1, e.target.value)}
                  style={{ width: '90px', padding: '2px', fontSize: '11px', border: '1px solid #d1d5db', borderRadius: '4px' }}
                />
              </td>
              <td style={{ padding: '4px' }}>
                <button
                  type="button"
                  onClick={() => handleDeleteVertex(idx)}
                  style={{ background: '#fee2e2', color: '#b91c1c', border: 'none', borderRadius: '4px', padding: '2px 6px', cursor: 'pointer', fontSize: '11px' }}
                >
                  {t('layerPanel.vertexDelete')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}