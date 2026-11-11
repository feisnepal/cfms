/**
 * NumericEntryPanel.tsx — Precision numeric entry panel during drawing (Task 3.3.1).
 *
 * Allows entering absolute lat,lng or bearing + distance from last vertex
 * using great-circle calculation via coordinateMath.destinationPoint.
 */
import { useState } from 'react';
import { message } from 'antd';
import { destinationPoint } from '../lib/coordinateMath';
import { parseCoords } from '../lib/displayCrs';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';

interface NumericEntryPanelProps {
  visible: boolean;
  lastVertex?: { lat: number; lng: number } | null;
  onInsertVertex: (point: { lat: number; lng: number }) => void;
  onClose: () => void;
}

export function NumericEntryPanel({ visible, lastVertex, onInsertVertex, onClose }: NumericEntryPanelProps) {
  const t = useT();
  const [mode, setMode] = useState<'absolute' | 'offset'>('absolute');
  const [absText, setAbsText] = useState('');
  const [bearing, setBearing] = useState('0');
  const [distance, setDistance] = useState('10');

  if (!visible) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === 'absolute') {
      const pt = parseCoords(absText);
      if (!pt) {
        message.error(t('editing.numeric.invalidCoords'));
        return;
      }
      onInsertVertex(pt);
      message.success(t('editing.numeric.insertedVertex', {
        lat: formatNumber(pt.lat, { minimumFractionDigits: 5, maximumFractionDigits: 5 }),
        lng: formatNumber(pt.lng, { minimumFractionDigits: 5, maximumFractionDigits: 5 }),
      }));
      setAbsText('');
    } else {
      if (!lastVertex) {
        message.error(t('editing.numeric.noPreviousVertex'));
        return;
      }
      const b = parseFloat(bearing);
      const d = parseFloat(distance);
      if (Number.isNaN(b) || Number.isNaN(d)) {
        message.error(t('editing.numeric.invalidBearingDistance'));
        return;
      }
      const dest = destinationPoint(
        { lat: lastVertex.lat, lng: lastVertex.lng },
        b,
        d
      );
      const pt = { lat: dest.lat, lng: dest.lng };
      onInsertVertex(pt);
      message.success(t('editing.numeric.insertedOffset', {
        bearing: formatNumber(b),
        distance: formatNumber(d),
        meter: t('units.meter'),
      }));
    }
    onClose();
  };

  return (
    <div className="numeric-entry-panel" role="dialog" aria-label={t('editing.numeric.title')} style={{
      position: 'absolute', bottom: 60, right: 20, zIndex: 1000,
      background: '#fff', padding: '16px', borderRadius: '8px',
      boxShadow: '0 4px 12px rgba(0,0.5,0.15,0.2)', width: '300px', border: '1px solid #e5e7eb'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
        <strong>📐 {t('editing.numeric.title')}</strong>
        <button onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '16px' }}>&times;</button>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
        <button
          type="button"
          onClick={() => setMode('absolute')}
          style={{ flex: 1, padding: '4px', background: mode === 'absolute' ? '#2563eb' : '#f3f4f6', color: mode === 'absolute' ? '#fff' : '#374151', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
        >
          {t('editing.numeric.absolute')}
        </button>
        <button
          type="button"
          onClick={() => setMode('offset')}
          style={{ flex: 1, padding: '4px', background: mode === 'offset' ? '#2563eb' : '#f3f4f6', color: mode === 'offset' ? '#fff' : '#374151', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
        >
          {t('editing.numeric.offset')}
        </button>
      </div>

      <form onSubmit={handleSubmit}>
        {mode === 'absolute' ? (
          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: '#4b5563' }}>{t('editing.numeric.coordinatesLabel')}</label>
            <input
              type="text"
              value={absText}
              onChange={(e) => setAbsText(e.target.value)}
              placeholder={t('editing.numeric.coordsPlaceholder')}
              style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid #d1d5db', boxSizing: 'border-box' }}
              autoFocus
            />
          </div>
        ) : (
          <>
            <div style={{ marginBottom: '8px' }}>
              <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: '#4b5563' }}>{t('editing.numeric.bearingLabel')}</label>
              <input
                type="text" inputMode="decimal"
                value={bearing}
                onChange={(e) => setBearing(e.target.value)}
                placeholder={t('editing.numeric.bearingPlaceholder')}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid #d1d5db', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'block', fontSize: '12px', marginBottom: '4px', color: '#4b5563' }}>{t('editing.numeric.distanceLabel')}</label>
              <input
                type="text" inputMode="decimal"
                value={distance}
                onChange={(e) => setDistance(e.target.value)}
                placeholder={t('editing.numeric.distancePlaceholder')}
                style={{ width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid #d1d5db', boxSizing: 'border-box' }}
              />
            </div>
          </>
        )}
        <button
          type="submit"
          style={{ width: '100%', padding: '8px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}
        >
          {t('editing.numeric.insertVertex')}
        </button>
      </form>
    </div>
  );
}
