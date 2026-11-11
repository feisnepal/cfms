/** RasterClickInfo — popup showing raster band value at the clicked map point. */
import React, { useState } from 'react';
import { useMapEvents, Popup } from 'react-leaflet';
import { LatLng } from 'leaflet';
import * as turf from '@turf/turf';
import api from '../services/api';
import { useT } from '../i18n/hooks';

interface RasterData {
  location: {
    lat: number;
    lon: number;
  };
  elevation_m: number | null;
  slope_class: number | null;
  slope_class_label: string | null;
  slope_class_range: string | null;
  slope_is_nodata: boolean;
  aspect_class: number | null;
  aspect_direction: string | null;
  canopy_height_m: number | null;
  biomass_mg_ha: number | null;
  forest_type_class: number | null;
  temperature_c: number | null;
  precipitation_mm: number | null;
}

interface RasterClickInfoProps {
  calculationId: string;
  boundaryGeometry: any;
}

export const RasterClickInfo: React.FC<RasterClickInfoProps> = ({ calculationId, boundaryGeometry }) => {
  const [clickedData, setClickedData] = useState<RasterData | null>(null);
  const [clickPosition, setClickPosition] = useState<LatLng | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = useT();

  useMapEvents({
    click: async (e) => {
      const { lat, lng } = e.latlng;

      // Check if click is inside boundary geometry
      if (boundaryGeometry) {
        const clickPoint = turf.point([lng, lat]);
        let isInside = false;

        try {
          // Handle both single polygon and multi-polygon geometries
          if (boundaryGeometry.type === 'FeatureCollection') {
            isInside = boundaryGeometry.features.some((feature: any) => {
              try {
                return turf.booleanPointInPolygon(clickPoint, feature);
              } catch {
                return false;
              }
            });
          } else if (boundaryGeometry.type === 'Feature') {
            isInside = turf.booleanPointInPolygon(clickPoint, boundaryGeometry);
          } else if (boundaryGeometry.type === 'Polygon' || boundaryGeometry.type === 'MultiPolygon') {
            isInside = turf.booleanPointInPolygon(clickPoint, turf.feature(boundaryGeometry));
          }
        } catch (err) {
          console.error('Error checking point in polygon:', err);
          isInside = false;
        }

        if (!isInside) {
          // Click is outside the boundary, don't show popup
          setClickPosition(null);
          setClickedData(null);
          return;
        }
      }

      setClickPosition(e.latlng);
      setLoading(true);
      setError(null);

      try {
        // Query all raster values at this point.
        //
        // H2.4 / S1-04: this route is owner-gated now. It was a bare fetch(),
        // which sends no credentials — routed through the shared axios client
        // so the interceptor attaches the session token like everywhere else.
        const response = await api.get(
          `/api/calculations/${calculationId}/query?lat=${lat}&lon=${lng}`
        );

        setClickedData(response.data as RasterData);
      } catch (err) {
        console.error('Error fetching raster data:', err);
        setError(t('raster.clickInfo.noData'));
        setClickedData(null);
      } finally {
        setLoading(false);
      }
    }
  });

  if (!clickPosition) {
    return null;
  }

  return (
    <Popup {...{ position: clickPosition, onClose: () => setClickPosition(null) } as any}>
      <div style={{
        minWidth: '250px',
        maxWidth: '300px',
        fontFamily: 'Arial, sans-serif'
      }}>
        <h4 style={{
          margin: '0 0 10px 0',
          fontSize: '16px',
          fontWeight: 'bold',
          borderBottom: '2px solid #4caf50',
          paddingBottom: '5px'
        }}>
          {t('raster.clickInfo.locationTitle')}
        </h4>

        {loading && (
          <div style={{ padding: '10px', textAlign: 'center', color: '#666' }}>
            {t('raster.clickInfo.loading')}
          </div>
        )}

        {error && (
          <div style={{ padding: '10px', color: '#d32f2f', fontSize: '14px' }}>
            {error}
          </div>
        )}

        {clickedData && !loading && (
          <table style={{
            width: '100%',
            fontSize: '13px',
            borderCollapse: 'collapse'
          }}>
            <tbody>
              <tr style={{ backgroundColor: '#f5f5f5' }}>
                <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.coordinates')}:</td>
                <td style={{ padding: '6px' }}>
                  {clickedData.location.lat.toFixed(5)}°, {clickedData.location.lon.toFixed(5)}°
                </td>
              </tr>

              {clickedData.elevation_m !== null && (
                <tr>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.elevation')}:</td>
                  <td style={{ padding: '6px' }}>{clickedData.elevation_m} m</td>
                </tr>
              )}

              {clickedData.slope_class !== null && (
                <tr style={{ backgroundColor: '#f5f5f5' }}>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.slope')}:</td>
                  <td style={{ padding: '6px' }}>
                    {/* class from rasters.slope_regulation, never a degree value */}
                    {clickedData.slope_is_nodata
                      ? t('common.na')
                      : `${clickedData.slope_class_label} (${clickedData.slope_class_range})`}
                  </td>
                </tr>
              )}

              {clickedData.aspect_direction && (
                <tr>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.aspect')}:</td>
                  <td style={{ padding: '6px' }}>{clickedData.aspect_direction}</td>
                </tr>
              )}

              {clickedData.canopy_height_m !== null && (
                <tr style={{ backgroundColor: '#f5f5f5' }}>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.canopyHeight')}:</td>
                  <td style={{ padding: '6px' }}>{clickedData.canopy_height_m} m</td>
                </tr>
              )}

              {clickedData.biomass_mg_ha !== null && (
                <tr>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.biomass')}:</td>
                  <td style={{ padding: '6px' }}>{clickedData.biomass_mg_ha} Mg/ha</td>
                </tr>
              )}

              {clickedData.temperature_c !== null && (
                <tr style={{ backgroundColor: '#f5f5f5' }}>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.temperature')}:</td>
                  <td style={{ padding: '6px' }}>{clickedData.temperature_c}°C</td>
                </tr>
              )}

              {clickedData.precipitation_mm !== null && (
                <tr>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.precipitation')}:</td>
                  <td style={{ padding: '6px' }}>{clickedData.precipitation_mm} mm/year</td>
                </tr>
              )}

              {clickedData.forest_type_class !== null && (
                <tr style={{ backgroundColor: '#f5f5f5' }}>
                  <td style={{ padding: '6px', fontWeight: '600' }}>{t('raster.clickInfo.forestType')}:</td>
                  <td style={{ padding: '6px' }}>{t('raster.clickInfo.class', { class: clickedData.forest_type_class })}</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </Popup>
  );
};