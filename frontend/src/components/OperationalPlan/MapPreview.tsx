/** Leaflet-based map preview for displaying GeoJSON layers — used within the operational plan document editor. */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Select, Spin, Tag, Card, Row, Col, Statistic, Button, message, Popconfirm } from 'antd';
import { ClearOutlined } from '@ant-design/icons';
import { MapContainer, GeoJSON, useMap, TileLayer, LayersControl, Pane } from 'react-leaflet';
import { API_BASE_URL, operationalPlanApi } from '../../services/api';
import 'leaflet/dist/leaflet.css';
import { useDimensionLabels } from '../../hooks/useDimensionLabels';
import { useT } from '../../i18n/hooks';
import { useTileToken, withTileToken } from '../../hooks/useTileToken';

const { BaseLayer } = LayersControl;

interface MapPreviewProps {
  planId: string;
  calculationId?: string;
}

interface GeoJsonFeature {
  type: string;
  properties: {
    name: string;
    type: string;
    area_hectares?: number;
    color: string;
  };
  geometry: any;
}

interface MapData {
  type: string;
  features: GeoJsonFeature[];
  forest_name: string;
}

interface MapOption {
  /** i18n key; module scope, so resolved at render (rule 4). */
  value: string;
  labelKey: string;
  category: string;
}

const MAP_OPTIONS: MapOption[] = [
  { value: 'boundary', labelKey: 'maps.boundary', category: 'Base' },
  { value: 'forest_type', labelKey: 'maps.forestType', category: 'Raster' },
  { value: 'forest_health', labelKey: 'maps.forestHealth', category: 'Raster' },
  { value: 'slope', labelKey: 'maps.slope', category: 'Raster' },
  { value: 'biomass', labelKey: 'maps.biomass', category: 'Raster' },
  { value: 'landcover', labelKey: 'maps.landCover', category: 'Raster' },
  { value: 'soil_texture', labelKey: 'maps.soilTexture', category: 'Raster' },
  { value: 'dem', labelKey: 'maps.elevation', category: 'Raster' },
  { value: 'aspect', labelKey: 'maps.aspect', category: 'Raster' },
  { value: 'canopy', labelKey: 'maps.canopyCover', category: 'Raster' },
];

const LAYER_LABELS: Record<string, string> = {
  boundary: 'maps.boundary',
  forest_type: 'maps.forestType',
  forest_health: 'maps.forestHealth',
  slope: 'maps.slope',
  biomass: 'maps.biomass',
  landcover: 'maps.landCover',
  soil_texture: 'maps.soilTexture',
  dem: 'maps.elevation',
  aspect: 'maps.aspect',
  canopy: 'maps.canopyCover',
};

const BLOCK_STYLE = (feature: any) => ({
  color: feature?.properties?.color || '#2ecc71',
  weight: 1,
  fillOpacity: 0.15,
  fillColor: feature?.properties?.color || '#2ecc71',
});

const BOUNDARY_STYLE = {
  color: '#27ae60',
  weight: 2,
  fillOpacity: 0,
  fillColor: '#27ae60',
  dashArray: '8 4',
};

function MapController({ mapData }: { mapData: MapData | null }) {
  const map = useMap();
  const fitted = useRef(false);

  useEffect(() => {
    if (!mapData || fitted.current) return;
    try {
      const geoLayer = (window as any).L?.geoJSON ? (window as any).L.geoJSON(mapData) : null;
      if (geoLayer) {
        const bounds = geoLayer.getBounds();
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [30, 30] });
          fitted.current = true;
        }
      }
    } catch {
      map.setView([28.3949, 84.124], 7);
    }
  }, [mapData, map]);

  return null;
}

const MapPreview: React.FC<MapPreviewProps> = ({ planId, calculationId }) => {

  const t = useT();  const [selectedType, setSelectedType] = useState<string>('boundary');
  const tileToken = useTileToken(calculationId);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const labels = useDimensionLabels({ hasCompartments: false });

  const loadBoundaryMap = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await operationalPlanApi.getMapGeojson(planId);
      if (!data.features || data.features.length === 0) {
        setError(t('operationalPlan.map.noData'));
      } else {
        setMapData(data);
      }
    } catch {
      setError(t('operationalPlan.map.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [planId]);

  useEffect(() => {
    loadBoundaryMap();
  }, [loadBoundaryMap]);

  const clearCache = useCallback(async () => {
    setClearing(true);
    try {
      const layer = selectedType === 'boundary' ? undefined : selectedType;
      await operationalPlanApi.clearMapCache(planId, layer);
      message.success(`Cache cleared for ${layer || 'all layers'}. Reloading...`);
      loadBoundaryMap();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err.message || t('operationalPlan.map.clearCacheFailed'));
    } finally {
      setClearing(false);
    }
  }, [planId, selectedType, loadBoundaryMap]);

  const boundaryFeatures = mapData?.features?.filter(f => f.properties.type === 'boundary') || [];
  const blockFeatures = mapData?.features?.filter(f => f.properties.type === 'block') || [];

  const selectedOption = MAP_OPTIONS.find(o => o.value === selectedType);
  const isRaster = selectedOption?.category === 'Raster';
  // H2.4 / S1-04: null until the tile token arrives, which holds the layer
  // back rather than firing a screenful of 401s.
  const rasterTileUrl = calculationId && selectedType !== 'boundary'
    ? withTileToken(
        `${API_BASE_URL}/api/calculations/${calculationId}/tiles/${selectedType}/{z}/{x}/{y}.png?alpha=200`,
        tileToken,
      )
    : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Select
          style={{ width: 320 }}
          value={selectedType}
          onChange={setSelectedType}
          options={[
            { label: t('operationalPlan.map.groupBase'), value: '', disabled: true },
            ...MAP_OPTIONS.filter(o => o.category === 'Base').map(o => ({ value: o.value, label: t(o.labelKey) })),
            { label: t('operationalPlan.map.groupRaster'), value: '', disabled: true },
            ...MAP_OPTIONS.filter(o => o.category === 'Raster').map(o => ({ value: o.value, label: t(o.labelKey) })),
          ]}
        />
        {selectedOption && (
          <Tag color={isRaster ? 'green' : 'blue'}>{isRaster ? t('operationalPlan.map.raster') : t('operationalPlan.map.vector')}</Tag>
        )}
        <Popconfirm
          title={t('operationalPlan.map.confirmClear')}
          description={t('operationalPlan.map.confirmClearHint')}
          onConfirm={clearCache}
          okText={t('operationalPlan.map.clear')}
          cancelText={t('operationalPlan.map.cancel')}
        >
          <Button icon={<ClearOutlined />} size="small" loading={clearing}>
            {t('operationalPlan.map.clearCache')}
          </Button>
        </Popconfirm>
        {!loading && !error && selectedType === 'boundary' && mapData && (
          <Statistic
            title={labels.unitLabelPlural}
            value={blockFeatures.length}
            suffix={`of ${mapData.features.length} total features`}
            valueStyle={{ fontSize: 14 }}
          />
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
        {error ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>{'\uD83D\uDDFA\uFE0F'}</div>
            <div style={{ fontSize: 16, fontWeight: 500, marginBottom: 8 }}>{error}</div>
            <div style={{ fontSize: 13 }}>
              {selectedType === 'boundary'
                ? t('operationalPlan.map.emptyBoundaryHint')
                : t('operationalPlan.map.emptyRasterHint')}
            </div>
          </div>
        ) : selectedType === 'boundary' && mapData ? (
          <Row gutter={16} style={{ width: '100%', height: '100%', minHeight: 500 }}>
            <Col xs={24} lg={18}>
              <div style={{ height: '100%', minHeight: 500, borderRadius: 8, overflow: 'hidden', border: '1px solid #f0f0f0' }}>
                <MapContainer center={[28.3949, 84.124]} zoom={7} style={{ height: '100%', width: '100%' }}>
                  <LayersControl position="topright">
                    <BaseLayer name="Street Map" checked>
                      <TileLayer
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                        maxZoom={19}
                      />
                    </BaseLayer>
                    <BaseLayer name="Satellite Imagery">
                      <TileLayer
                        url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                        maxZoom={19}
                      />
                    </BaseLayer>
                    <BaseLayer name="Topographic Map">
                      <TileLayer
                        url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
                        maxZoom={17}
                      />
                    </BaseLayer>
                  </LayersControl>
                  <MapController mapData={mapData} />
                  {boundaryFeatures.map((f, i) => (
                    <GeoJSON
                      key={`boundary-${i}`}
                      data={f as any}
                      style={BOUNDARY_STYLE}
                      onEachFeature={(feature, layer) => {
                        layer.bindPopup(
                          `<div style="font-size:13px"><strong>${feature.properties.name}</strong></div>`
                        );
                      }}
                    />
                  ))}
                  {blockFeatures.map((f, i) => (
                    <GeoJSON
                      key={`block-${i}`}
                      data={f as any}
                      style={BLOCK_STYLE}
                      onEachFeature={(feature, layer) => {
                        const p = feature.properties;
                        const area = p.area_hectares ? `<br/>Area: ${p.area_hectares.toFixed(2)} ha` : '';
                        layer.bindPopup(
                          `<div style="font-size:13px"><strong>${p.name}</strong>${area}</div>`
                        );
                        const color = p.color || '#2ecc71';
                        layer.bindTooltip(p.name, {
                          permanent: false,
                          direction: 'center',
                          className: 'block-tooltip',
                        });
                        (layer as any).setStyle({
                          fillColor: color,
                          color: color,
                          fillOpacity: 0.15,
                          weight: 1,
                        });
                      }}
                    />
                  ))}
                </MapContainer>
                {loading && (
                  <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.6)', zIndex: 1000 }}>
                    <div style={{ textAlign: 'center' }}>
                  <Spin size="large" />
                  <div style={{ marginTop: 12 }}>{t('operationalPlan.map.loading')}</div>
                </div>
                  </div>
                )}
              </div>
            </Col>
            <Col xs={24} lg={6}>
              <Card title={labels.unitLabelPlural} size="small" style={{ maxHeight: 500, overflow: 'auto' }}>
                {blockFeatures.length > 0 ? (
                  <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '2px solid #f0f0f0' }}>
                        <th style={{ textAlign: 'left', padding: '4px 6px' }}>{labels.unitLabel}</th>
                        <th style={{ textAlign: 'right', padding: '4px 6px' }}>{t('operationalPlan.map.areaHa')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {blockFeatures.map((f, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid #f5f5f5' }}>
                          <td style={{ padding: '4px 6px' }}>
                            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: f.properties.color, marginRight: 6 }} />
                            {f.properties.name}
                          </td>
                          <td style={{ textAlign: 'right', padding: '4px 6px' }}>
                            {f.properties.area_hectares?.toFixed(2) ?? '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div style={{ color: '#999', textAlign: 'center', padding: 20 }}>{t('operationalPlan.map.noBlocks')}</div>
                )}
              </Card>
            </Col>
          </Row>
        ) : (
          <div style={{ width: '100%', height: '100%', minHeight: 500, borderRadius: 8, overflow: 'hidden', border: '1px solid #f0f0f0' }}>
            <MapContainer center={[28.3949, 84.124]} zoom={7} style={{ height: '100%', width: '100%' }}>
              <LayersControl position="topright">
                <BaseLayer name="Street Map" checked>
                  <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    maxZoom={19}
                  />
                </BaseLayer>
                <BaseLayer name="Satellite Imagery">
                  <TileLayer
                    url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    maxZoom={19}
                  />
                </BaseLayer>
                <BaseLayer name="Topographic Map">
                  <TileLayer
                    url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
                    maxZoom={17}
                  />
                </BaseLayer>
              </LayersControl>
              <MapController mapData={mapData} />
              {boundaryFeatures.map((f, i) => (
                <GeoJSON
                  key={`boundary-${i}`}
                  data={f as any}
                  style={BOUNDARY_STYLE}
                  onEachFeature={(feature, layer) => {
                    layer.bindPopup(
                      `<div style="font-size:13px"><strong>${feature.properties.name}</strong></div>`
                    );
                  }}
                />
              ))}
              {rasterTileUrl && (
                <Pane name="raster-tiles" style={{ zIndex: 500 }}>
                  <TileLayer url={rasterTileUrl} maxZoom={18} minZoom={5} />
                </Pane>
              )}
            </MapContainer>
            {loading && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.6)', zIndex: 1000 }}>
                <div style={{ textAlign: 'center' }}>
                  <Spin size="large" />
                  <div style={{ marginTop: 12 }}>{t('operationalPlan.map.loading')}</div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default MapPreview;
