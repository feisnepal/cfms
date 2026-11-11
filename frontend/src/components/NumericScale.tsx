/** NumericScale — Leaflet control overlay displaying a numeric scale bar. */
import { useMap } from 'react-leaflet';
import { useEffect, useState, useRef } from 'react';
import L from 'leaflet';
import { parseLocaleNumber } from '../i18n/numberFormat';

function getScaleFromZoom(zoom: number, lat: number): number {
  const c = 156412;
  const latRad = lat * Math.PI / 180;
  const metersPerPixel = c / Math.pow(2, zoom) / Math.cos(latRad);
  const dpi = 96;
  const inchesPerMeter = 39.37;
  const scale = Math.round(metersPerPixel * inchesPerMeter / dpi * 1000);
  return scale;
}

function getZoomFromScale(targetScale: number, lat: number): number {
  const c = 156412;
  const latRad = lat * Math.PI / 180;
  const dpi = 96;
  const inchesPerMeter = 39.37;
  
  const metersPerPixel = targetScale / 1000 / inchesPerMeter * dpi;
  const zoom = Math.log2((c / metersPerPixel) * Math.cos(latRad));
  
  return Math.round(zoom);
}

export function NumericScale() {
  const map = useMap();
  const [currentScale, setCurrentScale] = useState(10000);
  const [displayScale, setDisplayScale] = useState(10000);
  const [isEditing, setIsEditing] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const initialScaleRef = useRef<number | null>(null);

  useEffect(() => {
    const updateScale = () => {
      const center = map.getCenter();
      const zoom = map.getZoom();
      const newScale = getScaleFromZoom(zoom, center.lat);
      setCurrentScale(newScale);
      setDisplayScale(newScale);
    };

    updateScale();
    
    map.on('zoomend', updateScale);
    map.on('moveend', updateScale);

    return () => {
      map.off('zoomend', updateScale);
      map.off('moveend', updateScale);
    };
  }, [map]);

  const handleClick = () => {
    initialScaleRef.current = displayScale;
    setIsEditing(true);
    setInputValue(String(displayScale));
    setTimeout(() => inputRef.current?.select(), 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      const newScale = Math.trunc(parseLocaleNumber(inputValue));
      if (!isNaN(newScale) && newScale > 0) {
        const center = map.getCenter();
        const zoom = getZoomFromScale(newScale, center.lat);
        const clampedZoom = Math.max(1, Math.min(18, zoom));
        map.setZoom(clampedZoom, { animate: true });
        setDisplayScale(newScale);
      }
      setIsEditing(false);
    } else if (e.key === 'Escape') {
      if (initialScaleRef.current) {
        setDisplayScale(initialScaleRef.current);
      }
      setIsEditing(false);
    }
  };

  const handleBlur = () => {
    const newScale = Math.trunc(parseLocaleNumber(inputValue));
    if (!isNaN(newScale) && newScale > 0) {
      const center = map.getCenter();
      const zoom = getZoomFromScale(newScale, center.lat);
      const clampedZoom = Math.max(1, Math.min(18, zoom));
      map.setZoom(clampedZoom, { animate: true });
      setDisplayScale(newScale);
    }
    setIsEditing(false);
  };

  return (
    <div
      style={{
        position: 'absolute',
        bottom: '10px',
        left: '55px',
        zIndex: 1000,
        background: 'rgba(255, 255, 255, 0.9)',
        padding: '4px 8px',
        borderRadius: '4px',
        fontSize: '14px',
        fontWeight: 'bold',
        color: '#333',
        border: '1px solid #ccc',
        boxShadow: '0 1px 3px rgba(0,0,0,0.2)'
      }}
    >
      {isEditing ? (
        <input
          ref={inputRef}
          type="text" inputMode="decimal"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          autoFocus
          style={{
            width: '70px',
            fontSize: '14px',
            fontWeight: 'bold',
            border: '1px solid #2563eb',
            borderRadius: '3px',
            padding: '2px 4px',
            textAlign: 'center'
          }}
        />
      ) : (
        <span
          onClick={handleClick}
          title="Click to edit scale"
          style={{
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '2px'
          }}
        >
          1:{displayScale}
        </span>
      )}
    </div>
  );
}