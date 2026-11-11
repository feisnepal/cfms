/** AccessibleForestPreview — previews forest accessibility areas on a map with GeoJSON overlays. */
import { useState, useEffect } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import { LatLngBounds } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { NumericScale } from './NumericScale';
import { useT } from '../i18n/hooks';

interface AccessibleForestPreviewProps {
  previewData: any;
}

function FitBounds({ bounds }: { bounds: LatLngBounds }) {
  const map = useMap();
  map.fitBounds(bounds);
  return null;
}

export function AccessibleForestPreview({ previewData }: AccessibleForestPreviewProps) {
  const t = useT();
  const [showStats, setShowStats] = useState(true);

  if (!previewData) {
    return null;
  }

  const { boundary, accessible_forest, protected_forest, area_statistics } = previewData;

  // Calculate bounds from boundary
  const boundaryCoords = boundary?.geometry?.coordinates || [];
  let bounds: LatLngBounds | null = null;

  if (boundaryCoords.length > 0) {
    const allCoords: [number, number][] = [];

    const extractCoords = (coords: any) => {
      if (Array.isArray(coords)) {
        if (typeof coords[0] === 'number') {
          allCoords.push([coords[1], coords[0]]);
        } else {
          coords.forEach(extractCoords);
        }
      }
    };

    extractCoords(boundaryCoords);

    if (allCoords.length > 0) {
      bounds = new LatLngBounds(allCoords);
    }
  }

  const stats = area_statistics || {};

  return (
    <div className="space-y-4">
      {/* Statistics Panel */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex justify-between items-center mb-3">
          <h4 className="text-md font-semibold text-gray-900">
            {t('sampling.forestAreaClassification')}
          </h4>
          <button
            onClick={() => setShowStats(!showStats)}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            {showStats ? t('common.hide') : t('common.show')} {t('sampling.details')}
          </button>
        </div>

        {showStats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-50 rounded p-3">
              <div className="text-xs text-gray-600 mb-1">{t('sampling.totalBoundaryArea')}</div>
              <div className="text-lg font-bold text-gray-900">
                {stats.total_boundary_area_ha?.toFixed(2) || 0} ha
              </div>
            </div>

            {stats.accessible_forest_area_ha !== undefined && (
              <div className="bg-green-50 rounded p-3 border border-green-200">
                <div className="text-xs text-green-700 mb-1">
                  ✓ {t('sampling.accessibleForestGreen')}
                </div>
                <div className="text-lg font-bold text-green-900">
                  {stats.accessible_forest_area_ha.toFixed(2)} ha
                </div>
                <div className="text-xs text-green-600 mt-1">
                  {stats.accessible_forest_percentage?.toFixed(1)}% {t('sampling.ofTotal')}
                </div>
              </div>
            )}

            {stats.inaccessible_steep_forest_ha !== undefined && stats.inaccessible_steep_forest_ha > 0 && (
              <div className="bg-red-50 rounded p-3 border border-red-200">
                <div className="text-xs text-red-700 mb-1">
                  ⚠ {t('sampling.protectedForestRed')}
                </div>
                <div className="text-lg font-bold text-red-900">
                  {stats.inaccessible_steep_forest_ha.toFixed(2)} ha
                </div>
                <div className="text-xs text-red-600 mt-1">
                  {stats.inaccessible_steep_percentage?.toFixed(1)}% {t('sampling.ofTotal')}
                </div>
              </div>
            )}

            {stats.non_forest_area_ha !== undefined && stats.non_forest_area_ha > 0 && (
              <div className="bg-gray-50 rounded p-3">
                <div className="text-xs text-gray-600 mb-1">{t('sampling.nonForestArea')}</div>
                <div className="text-lg font-bold text-gray-900">
                  {stats.non_forest_area_ha.toFixed(2)} ha
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {stats.non_forest_percentage?.toFixed(1)}% {t('sampling.ofTotal')}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Legend */}
        <div className="mt-4 pt-3 border-t border-gray-200">
          <div className="text-xs font-semibold text-gray-700 mb-2">{t('sampling.mapLegend')}:</div>
          <div className="flex flex-wrap gap-4 text-xs">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 border-2 border-blue-600 bg-transparent"></div>
              <span className="text-gray-700">{t('sampling.boundary')}</span>
            </div>
            {accessible_forest && (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 bg-green-500 opacity-40"></div>
                <span className="text-gray-700">{t('sampling.accessibleForestResourceEffective')}</span>
              </div>
            )}
            {protected_forest && (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 bg-red-500 opacity-40"></div>
                <span className="text-gray-700">{t('sampling.protectedForestSteepSlopes')}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Map */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div style={{ height: '500px', width: '100%' }}>
          <MapContainer
            style={{ height: '100%', width: '100%' }}
            center={[28.3949, 84.124]}
            zoom={13}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <NumericScale />

            {/* Accessible Forest Layer (GREEN) */}
            {accessible_forest?.geometry && (
              <GeoJSON
                key="accessible-forest"
                data={accessible_forest}
                style={{
                  fillColor: '#22c55e',
                  fillOpacity: 0.4,
                  color: '#16a34a',
                  weight: 1,
                }}
              />
            )}

            {/* Protected Forest Layer (RED) */}
            {protected_forest?.geometry && (
              <GeoJSON
                key="protected-forest"
                data={protected_forest}
                style={{
                  fillColor: '#ef4444',
                  fillOpacity: 0.4,
                  color: '#dc2626',
                  weight: 1,
                }}
              />
            )}

            {/* Boundary Layer (BLUE outline) */}
            {boundary?.geometry && (
              <GeoJSON
                key="boundary"
                data={boundary}
                style={{
                  fillColor: 'transparent',
                  fillOpacity: 0,
                  color: '#2563eb',
                  weight: 3,
                }}
              />
            )}

            {bounds && <FitBounds bounds={bounds} />}
          </MapContainer>
        </div>
      </div>

      {/* Slope Filter Note */}
      {area_statistics?.preview_note && (
        <div className="bg-orange-50 border border-orange-300 rounded-lg p-4 mb-4">
          <h5 className="text-sm font-semibold text-orange-900 mb-2">
            ⚠️ {t('sampling.slopeFilteringNoteTitle')}
          </h5>
          <p className="text-sm text-orange-800">
            {area_statistics.preview_note}
          </p>
          <p className="text-xs text-orange-700 mt-2">
            {t('sampling.slopeFilteringNoteBody')}
          </p>
        </div>
      )}

      {/* Explanation */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h5 className="text-sm font-semibold text-blue-900 mb-2">
          {t('sampling.understandingClassificationTitle')}
        </h5>
        <div className="text-sm text-blue-800 space-y-1">
          <p>
            <span className="font-semibold text-green-700">• {t('sampling.greenAreasAccessible')}</span>{' '}
            {area_statistics?.preview_note ? t('sampling.greenAreasSlopeApplied') : t('sampling.greenAreasSamplePlots')}
          </p>
          {protected_forest && (
            <p>
              <span className="font-semibold text-red-700">• {t('sampling.redAreasProtected')}</span>{' '}
              {t('sampling.redAreasExplanation')}
            </p>
          )}
          <p className="mt-2 text-xs text-blue-600">
            💡 {t('sampling.visualizationHelps')}
          </p>
        </div>
      </div>

      {/* Technical Note about Raster vs Vector Area */}
      {stats.total_boundary_area_ha > 0 && (
        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-3">
          <h6 className="text-xs font-semibold text-yellow-900 mb-1">
            📊 {t('sampling.areaCalculationsNoteTitle')}
          </h6>
          <div className="text-xs text-yellow-800">
            <p>
              {t('sampling.areaCalculationsNoteBody')}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
