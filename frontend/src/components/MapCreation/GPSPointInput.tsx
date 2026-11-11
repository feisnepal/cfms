/** GPS coordinate point input with interactive map marker placement and popup details. */
import React, { useState, useCallback } from 'react';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import HelpTooltip from '../HelpTooltip';
import { NumericScale } from '../NumericScale';
import { useTranslation } from 'react-i18next';

import {
  parseCSVCoordinates,
  parsePastedCoordinates,
  parseGPXFile,
  transformCoordinates,
  validateGPSPoint,
  gpsPointsToGeoJSON,
  detectEPSG,
  GPSPoint,
} from '../../utils/gpsUtils';

// Fix Leaflet default marker icon
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

interface GPSPointInputProps {
  onPointsChange: (points: GPSPoint[]) => void;
  initialPoints?: GPSPoint[];
}

// Component to auto-fit map to markers
const FitBoundsToMarkers: React.FC<{ points: GPSPoint[] }> = ({ points }) => {
  const map = useMap();

  React.useEffect(() => {
    if (points.length > 0) {
      const bounds = L.latLngBounds(points.map(p => [p.latitude, p.longitude]));
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [points, map]);

  return null;
};

const GPSPointInput: React.FC<GPSPointInputProps> = ({ onPointsChange, initialPoints = [] }) => {
  const { t } = useTranslation();
  const [points, setPoints] = useState<GPSPoint[]>(initialPoints);
  const [inputMethod, setInputMethod] = useState<'csv' | 'manual' | 'paste' | 'gpx'>('csv');
  const [epsgCode, setEpsgCode] = useState<string>('EPSG:4326');
  const [customEPSG, setCustomEPSG] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [success, setSuccess] = useState<string>('');

  // Manual entry form state
  const [manualLat, setManualLat] = useState<string>('');
  const [manualLon, setManualLon] = useState<string>('');
  const [manualName, setManualName] = useState<string>('');
  const [manualElev, setManualElev] = useState<string>('');

  // Paste coordinates state
  const [pasteText, setPasteText] = useState<string>('');

  // Update parent when points change
  const updatePoints = useCallback(
    (newPoints: GPSPoint[]) => {
      setPoints(newPoints);
      onPointsChange(newPoints);
    },
    [onPointsChange]
  );

  // Handle CSV upload
  const handleCSVUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError('');
    setSuccess('');

    try {
      const parsedPoints = await parseCSVCoordinates(file);

      // Transform if needed
      const actualEPSG = epsgCode === 'custom' ? customEPSG : epsgCode;
      const transformedPoints = transformCoordinates(parsedPoints, {
        fromEPSG: actualEPSG,
        toEPSG: 'EPSG:4326',
      });

      // Validate all points
      for (const point of transformedPoints) {
        const validation = validateGPSPoint(point);
        if (!validation.valid) {
          setError(`${point.name}: ${validation.error}`);
          return;
        }
      }

      updatePoints(transformedPoints);
      setSuccess(`Successfully loaded ${transformedPoints.length} GPS points from CSV`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('digitize.gps.csvParseFailed'));
    }

    // Reset file input
    e.target.value = '';
  };

  // Handle GPX upload
  const handleGPXUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError('');
    setSuccess('');

    try {
      const parsedPoints = await parseGPXFile(file);

      // GPX files are always in WGS84 (EPSG:4326), no transformation needed
      for (const point of parsedPoints) {
        const validation = validateGPSPoint(point);
        if (!validation.valid) {
          setError(`${point.name}: ${validation.error}`);
          return;
        }
      }

      updatePoints(parsedPoints);
      setSuccess(`Successfully loaded ${parsedPoints.length} GPS points from GPX file`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('digitize.gps.gpxParseFailed'));
    }

    // Reset file input
    e.target.value = '';
  };

  // Handle manual point entry
  const handleManualAdd = () => {
    setError('');
    setSuccess('');

    const lat = parseFloat(manualLat);
    const lon = parseFloat(manualLon);

    if (isNaN(lat) || isNaN(lon)) {
      setError(t('digitize.gps.invalidCoords'));
      return;
    }

    const newPoint: GPSPoint = {
      id: `manual-${Date.now()}`,
      latitude: lat,
      longitude: lon,
      name: manualName.trim() || `Point ${points.length + 1}`,
      elevation: manualElev ? parseFloat(manualElev) : undefined,
      order: points.length,
    };

    // Transform if needed
    const actualEPSG = epsgCode === 'custom' ? customEPSG : epsgCode;
    const [transformed] = transformCoordinates([newPoint], {
      fromEPSG: actualEPSG,
      toEPSG: 'EPSG:4326',
    });

    const validation = validateGPSPoint(transformed);
    if (!validation.valid) {
      setError(validation.error || t('digitize.gps.invalidPoint'));
      return;
    }

    updatePoints([...points, transformed]);
    setSuccess(`Added ${transformed.name}`);

    // Clear form
    setManualLat('');
    setManualLon('');
    setManualName('');
    setManualElev('');
  };

  // Handle paste coordinates
  const handlePasteCoordinates = () => {
    setError('');
    setSuccess('');

    if (!pasteText.trim()) {
      setError(t('digitize.gps.pasteFirst'));
      return;
    }

    try {
      const parsedPoints = parsePastedCoordinates(pasteText);

      // Transform if needed
      const actualEPSG = epsgCode === 'custom' ? customEPSG : epsgCode;
      const transformedPoints = transformCoordinates(parsedPoints, {
        fromEPSG: actualEPSG,
        toEPSG: 'EPSG:4326',
      });

      // Validate all points
      for (const point of transformedPoints) {
        const validation = validateGPSPoint(point);
        if (!validation.valid) {
          setError(`${point.name}: ${validation.error}`);
          return;
        }
      }

      updatePoints(transformedPoints);
      setSuccess(`Successfully parsed ${transformedPoints.length} GPS points`);
      setPasteText('');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('digitize.gps.coordParseFailed'));
    }
  };

  // Delete a point
  const handleDeletePoint = (pointId: string) => {
    const newPoints = points.filter(p => p.id !== pointId);
    // Update order
    newPoints.forEach((p, i) => {
      p.order = i;
    });
    updatePoints(newPoints);
  };

  // Clear all points
  const handleClearAll = () => {
    updatePoints([]);
    setError('');
    setSuccess('');
  };

  // Auto-detect EPSG when points are loaded
  React.useEffect(() => {
    if (points.length > 0 && epsgCode === 'EPSG:4326') {
      const detected = detectEPSG(points);
      if (detected !== 'EPSG:4326') {
        setEpsgCode(detected);
      }
    }
  }, [points, epsgCode]);

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-bold mb-4">{t('digitize.gps.title')}</h2>

        {/* EPSG Code Selector */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Coordinate System (EPSG Code) <span className="text-red-500">*</span>
          </label>
          <div className="flex gap-4">
            <select
              value={epsgCode}
              onChange={(e) => setEpsgCode(e.target.value)}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
            >
              <option value="EPSG:4326">{t('digitize.gps.epsg4326')}</option>
              <option value="EPSG:32644">{t('digitize.gps.epsg32644')}</option>
              <option value="EPSG:32645">{t('digitize.gps.epsg32645')}</option>
              <option value="custom">{t('digitize.gps.customEpsg')}</option>
            </select>

            {epsgCode === 'custom' && (
              <input
                type="text"
                value={customEPSG}
                onChange={(e) => setCustomEPSG(e.target.value)}
                placeholder={t('digitize.gps.phCustomEpsg')}
                className="w-48 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
              />
            )}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Specify the coordinate system of your GPS data. System will auto-detect if possible.
          </p>
        </div>

        {/* Input Method Tabs */}
        <div className="border-b border-gray-200 mb-4">
          <div className="flex space-x-4">
            {['csv', 'gpx', 'manual', 'paste'].map((method) => (
              <button
                key={method}
                onClick={() => setInputMethod(method as any)}
                className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  inputMethod === method
                    ? 'border-green-600 text-green-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {method === 'csv' && t('digitize.gps.tabCsv')}
                {method === 'gpx' && t('digitize.gps.tabGpx')}
                {method === 'manual' && t('digitize.gps.tabManual')}
                {method === 'paste' && t('digitize.gps.tabPaste')}
              </button>
            ))}
          </div>
        </div>

        {/* Input Methods */}
        <div className="space-y-4">
          {/* CSV Upload */}
          {inputMethod === 'csv' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('digitize.gps.uploadCsv')}
              </label>
              <input
                type="file"
                accept=".csv"
                onChange={handleCSVUpload}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
              />
              <p className="text-xs text-gray-500 mt-2">
                {t('digitize.gps.csvHint')}
              </p>
            </div>
          )}

          {/* GPX Upload */}
          {inputMethod === 'gpx' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('digitize.gps.uploadGpx')}
              </label>
              <input
                type="file"
                accept=".gpx"
                onChange={handleGPXUpload}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
              />
              <p className="text-xs text-gray-500 mt-2">
                {t('digitize.gps.gpxHint')}
              </p>
            </div>
          )}

          {/* Manual Entry */}
          {inputMethod === 'manual' && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Latitude / Northing
                </label>
                <input
                  type="text"
                  value={manualLat}
                  onChange={(e) => setManualLat(e.target.value)}
                  placeholder="27.7172"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Longitude / Easting
                </label>
                <input
                  type="text"
                  value={manualLon}
                  onChange={(e) => setManualLon(e.target.value)}
                  placeholder="85.3240"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Point Name (Optional)
                </label>
                <input
                  type="text"
                  value={manualName}
                  onChange={(e) => setManualName(e.target.value)}
                  placeholder={t('digitize.gps.phPointName')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Elevation (Optional)
                </label>
                <input
                  type="text"
                  value={manualElev}
                  onChange={(e) => setManualElev(e.target.value)}
                  placeholder="1200"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div className="col-span-2">
                <button
                  onClick={handleManualAdd}
                  className="w-full px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
                >
                  Add Point
                </button>
              </div>
            </div>
          )}

          {/* Paste Coordinates */}
          {inputMethod === 'paste' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('digitize.gps.pasteLabel')}
              </label>
              <textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder="27.7172, 85.3240&#10;27.7180, 85.3250&#10;27.7165, 85.3255"
                rows={6}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-green-500 font-mono text-sm"
              />
              <p className="text-xs text-gray-500 mt-2">
                {t('digitize.gps.pasteHint')}
              </p>
              <button
                onClick={handlePasteCoordinates}
                className="mt-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
              >
                {t('digitize.gps.parseCoords')}
              </button>
            </div>
          )}
        </div>

        {/* Messages */}
        {error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md">
            {error}
          </div>
        )}
        {success && (
          <div className="mt-4 p-3 bg-green-50 border border-green-200 text-green-700 rounded-md">
            {success}
          </div>
        )}
      </div>

      {/* GPS Points List */}
      {points.length > 0 && (
        <div className="bg-white p-6 rounded-lg shadow">
          <div className="flex justify-between items-center mb-4">
            <div className="flex items-center">
              <h3 className="text-lg font-semibold">
                GPS Points ({points.length})
              </h3>
              <HelpTooltip tKey="tooltips.gpsPoints" position="right" />
            </div>
            <button
              onClick={handleClearAll}
              className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
            >
              Clear All
            </button>
          </div>

          <div className="max-h-64 overflow-y-auto border border-gray-200 rounded">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">#</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.gps.colName')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.gps.colLat')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.gps.colLon')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.gps.colElevation')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.gps.colAction')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {points.map((point, index) => (
                  <tr key={point.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-sm">{index + 1}</td>
                    <td className="px-3 py-2 text-sm">{point.name}</td>
                    <td className="px-3 py-2 text-sm font-mono">{formatDecimal(point.latitude, 6)}</td>
                    <td className="px-3 py-2 text-sm font-mono">{formatDecimal(point.longitude, 6)}</td>
                    <td className="px-3 py-2 text-sm">
                      {point.elevation ? `${formatNumber(Math.round(point.elevation))} ${t('units.meter')}` : '-'}
                    </td>
                    <td className="px-3 py-2 text-sm">
                      <button
                        onClick={() => handleDeletePoint(point.id)}
                        className="text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Map Preview */}
      {points.length > 0 && (
        <div className="bg-white p-6 rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-4">{t('digitize.gps.mapPreview')}</h3>
          <div className="h-96 rounded overflow-hidden border border-gray-300">
            <MapContainer
              center={[27.7172, 85.3240]}
              zoom={13}
              style={{ height: '100%', width: '100%' }}
            >
              <TileLayer
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              />
              <NumericScale />
              {points.map((point) => (
                <Marker key={point.id} position={[point.latitude, point.longitude]}>
                  <Popup>
                    <div>
                      <strong>{point.name}</strong>
                      <br />
                      {t('digitize.gps.latShort')} {formatDecimal(point.latitude, 6)}
                      <br />
                      {t('digitize.gps.lonShort')} {formatDecimal(point.longitude, 6)}
                      {point.elevation && (
                        <>
                          <br />
                          {t('digitize.gps.elevShort')} {formatNumber(Math.round(point.elevation))} {t('units.meter')}
                        </>
                      )}
                    </div>
                  </Popup>
                </Marker>
              ))}
              <FitBoundsToMarkers points={points} />
            </MapContainer>
          </div>
        </div>
      )}
    </div>
  );
};

export default GPSPointInput;
