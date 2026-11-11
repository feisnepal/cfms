/** Activity map view — Leaflet map displaying yearly-activity geometries (blocks, sub-areas, operations). */
import React, { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, GeoJSON, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { Card, Select, Spin, Empty, Tag, message, Radio, Space, Button, List } from 'antd';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';
import { subAreaCategoryLabelKey } from '../../lib/subAreaCategories';
const Option = Select.Option;
import { yearlyActivitiesApi, forestApi } from '../../services/api';
import DrawingCanvas from './DrawingCanvas';
import { NumericScale } from '../NumericScale';

interface ActivityMapViewProps {
  calculationId: string;
  selectedActivityId?: string | null;
  onActivitySelect?: (activityId: string) => void;
}

const BASE_MAPS = {
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri',
    labelKey: 'yearlyActivities.map.baseSatellite'
  },
  osm: {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap',
    labelKey: 'yearlyActivities.map.baseStreet'
  },
  topo: {
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenTopoMap',
    labelKey: 'yearlyActivities.map.baseTopo'
  }
};

// Sub-area category colors (match your existing SUB_AREA_CATEGORIES)
const CATEGORY_COLORS: Record<string, string> = {
  'protected': '#ef4444',
  'plantation': '#10b981',
  'pro-poor': '#f59e0b',
  'religious': '#8b5cf6',
  'biodiversity': '#06b6d4',
  'tourist': '#ec4899',
  'office': '#6b7280',
  'private_land': '#dc2626',
  'encroached': '#78350f'
};

const ActivityMapView: React.FC<ActivityMapViewProps> = ({ calculationId, selectedActivityId: externalActivityId, onActivitySelect }) => {
  const t = useT();
  const [loading, setLoading] = useState(false);
  const [activityGeoData, setActivityGeoData] = useState<any>(null);
  const [blocksWithSubAreas, setBlocksWithSubAreas] = useState<any[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | undefined>();
  const [mapMode, setMapMode] = useState<'view' | 'assign' | 'draw'>('view');
  const [selectedActivityId, setSelectedActivityId] = useState<string | null>(null);
  const [drawnFeatures, setDrawnFeatures] = useState<any[]>([]);
  
  // Forest layers state
  const [boundaryGeometry, setBoundaryGeometry] = useState<any>(null);
  const [blockLayers, setBlockLayers] = useState<any[]>([]);
  const [subAreaLayers, setSubAreaLayers] = useState<any[]>([]);
  const [baseMap, setBaseMap] = useState<'satellite' | 'osm' | 'topo'>('satellite');
  const [layersLoading, setLayersLoading] = useState(false);

  useEffect(() => {
    loadActivityGeoData();
    loadBlocksWithSubAreas();
    loadForestLayers();
  }, [calculationId]);

  const loadForestLayers = async () => {
    setLayersLoading(true);
    try {
      // Load boundary and blocks from calculation
      const calcData = await forestApi.getCalculation(calculationId);
      console.log('[ActivityMapView] Calculation data:', calcData);
      
      // Use geometry as boundary (old format) or check result_data
      if (calcData.geometry) {
        setBoundaryGeometry(calcData.geometry);
      } else if ((calcData.result_data as any)?.boundary) {
        setBoundaryGeometry((calcData.result_data as any).boundary);
      }
      
      // Load blocks from result_data
      if (calcData.result_data?.blocks && calcData.result_data.blocks.length > 0) {
        console.log('[ActivityMapView] Blocks from result_data:', calcData.result_data.blocks.length);
        setBlockLayers(calcData.result_data.blocks);
      }
      
      // Load sub-areas
      const subAreasData = await forestApi.listSubAreas(calculationId);
      console.log('[ActivityMapView] Sub-areas:', subAreasData.sub_areas?.length || 0);
      if (subAreasData.sub_areas && subAreasData.sub_areas.length > 0) {
        setSubAreaLayers(subAreasData.sub_areas);
      }
    } catch (err) {
      console.error('Failed to load forest layers:', err);
    } finally {
      setLayersLoading(false);
    }
  };

  useEffect(() => {
    if (externalActivityId) {
      setSelectedActivityId(externalActivityId);
      loadDrawnFeatures(externalActivityId);
    }
  }, [externalActivityId]);

  const loadBlocksWithSubAreas = async () => {
    try {
      const data = await yearlyActivitiesApi.getBlocksWithSubareas(calculationId);
      setBlocksWithSubAreas(data);
    } catch (err) {
      console.error('Failed to load blocks', err);
    }
  };

  const loadActivityGeoData = async () => {
    setLoading(true);
    try {
      const data = await yearlyActivitiesApi.getActivitiesWithGeometry(calculationId);
      setActivityGeoData(data);
    } catch (error: any) {
      console.error('Failed to load activity geometry', error);
      message.error(t('yearlyActivities.map.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const loadDrawnFeatures = async (activityId: string) => {
    try {
      const features = await yearlyActivitiesApi.getDrawnFeatures(activityId);
      setDrawnFeatures(features);
    } catch (error: any) {
      setDrawnFeatures([]);
    }
  };

  const handleActivitySelect = async (activityId: string) => {
    setSelectedActivityId(activityId);
    await loadDrawnFeatures(activityId);
    if (onActivitySelect) {
      onActivitySelect(activityId);
    }
  };

  // Filter features based on selected filters
  const filteredFeatures = activityGeoData?.features?.filter((feature: any) => {
    const props = feature.properties;

    if (selectedCategory && props.sub_area_category !== selectedCategory) {
      return false;
    }

    return true;
  }) || [];

  // Get unique values for filters
  const uniqueCategories = Array.from(
    new Set(activityGeoData?.features?.map((f: any) => f.properties.sub_area_category) || [])
  );

  // Style function based on sub-area category
  const styleFeature = (feature: any) => {
    const category = feature.properties.sub_area_category;
    const color = CATEGORY_COLORS[category] || '#3b82f6';

    return {
      fillColor: color,
      weight: 2,
      opacity: 0.8,
      color: color,
      fillOpacity: 0.4
    };
  };

  // Popup content
  const onEachFeature = (feature: any, layer: L.Layer) => {
    const props = feature.properties;

    const popupContent = `
      <div style="min-width: 250px;">
        <h3 style="margin: 0 0 8px 0; font-size: 14px; font-weight: bold;">
          ${props.activity_name}
        </h3>
        <div style="font-size: 12px; line-height: 1.6;">
          <div><strong>${t('yearlyActivities.map.location')}</strong> ${props.sub_area_name} (${props.sub_area_category})</div>
          <div><strong>${t('yearlyActivities.map.block')}</strong> ${props.block_name || t('common.notAvailable')}</div>
          <div><strong>${t('yearlyActivities.map.project')}</strong> ${props.project_name || t('common.notAvailable')}</div>
          <div><strong>${t('yearlyActivities.map.program')}</strong> ${props.program || t('common.notAvailable')}</div>
          <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #ddd;">
            <strong>${t('yearlyActivities.map.quantity')}</strong> ${t('yearlyActivities.map.perYear', {
              value: `${formatNumber(Number(props.quantity))} ${props.unit}`,
            })}
          </div>
          <div><strong>${t('yearlyActivities.map.budget')}</strong> ${t('yearlyActivities.map.perYear', {
            value: t('units.npr', { value: formatNumber(Number(props.yearly_budget)) }),
          })}</div>
          <div><strong>${t('yearlyActivities.map.totalTenYears')}</strong> ${t('units.npr', {
            value: formatNumber(Number(props.total_budget_10_years)),
          })}</div>
          <div style="margin-top: 8px;">
            <span style="display: inline-block; padding: 2px 8px; background: #1890ff; color: white; border-radius: 4px; font-size: 11px;">
              ${props.status}
            </span>
          </div>
        </div>
      </div>
    `;

    layer.bindPopup(popupContent);
  };

  // Auto-fit map to show all layers (boundary, blocks, sub-areas, activities)
  const MapBoundsUpdater: React.FC = () => {
    const map = useMap();

    useEffect(() => {
      const bounds = L.latLngBounds([]);
      let hasBounds = false;
      
      // Add boundary
      if (boundaryGeometry) {
        try {
          const layer = L.geoJSON(boundaryGeometry);
          bounds.extend(layer.getBounds());
          hasBounds = true;
        } catch (e) { console.warn('Boundary bounds error', e); }
      }
      
      // Add blocks
      blockLayers.forEach((block: any) => {
        if (block.geometry) {
          try {
            const layer = L.geoJSON(block.geometry);
            bounds.extend(layer.getBounds());
            hasBounds = true;
          } catch (e) { console.warn('Block bounds error', e); }
        }
      });
      
      // Add sub-areas
      subAreaLayers.forEach((subArea: any) => {
        if (subArea.geometry) {
          try {
            const layer = L.geoJSON(subArea.geometry);
            bounds.extend(layer.getBounds());
            hasBounds = true;
          } catch (e) { console.warn('SubArea bounds error', e); }
        }
      });
      
      // Add activity features
      if (filteredFeatures.length > 0) {
        const geojsonLayer = L.geoJSON({
          type: 'FeatureCollection',
          features: filteredFeatures
        } as any);
        bounds.extend(geojsonLayer.getBounds());
        hasBounds = true;
      }

      if (hasBounds && bounds.isValid()) {
        map.fitBounds(bounds, { padding: [50, 50] });
      }
    }, [boundaryGeometry, blockLayers, subAreaLayers, filteredFeatures, map]);

    return null;
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 24 }}>
        <Spin />
        <div style={{ marginTop: 8 }}>{t('yearlyActivities.map.loading')}</div>
      </div>
    );
  }

  if (!activityGeoData || filteredFeatures.length === 0) {
    return (
      <Empty
        description={t('yearlyActivities.map.empty')}
      />
    );
  }

  const uniqueActivities = Array.from(
    new Set(activityGeoData?.features?.map((f: any) => ({
      id: f.properties.proposed_activity_id,
      name: f.properties.activity_name
    })) || [])
  ).filter(Boolean);

  // ===== ASSIGN MODE =====
  if (mapMode === 'assign') {
    return (
      <div>
        <div style={{ marginBottom: '16px' }}>
          <Space>
            <Radio.Group
              value={mapMode}
              onChange={(e) => setMapMode(e.target.value)}
              buttonStyle="solid"
            >
              <Radio.Button value="view">{t('yearlyActivities.map.modeView')}</Radio.Button>
              <Radio.Button value="assign">{t('yearlyActivities.map.modeAssign')}</Radio.Button>
              <Radio.Button value="draw">{t('yearlyActivities.map.modeDraw')}</Radio.Button>
            </Radio.Group>
          </Space>
        </div>
        
        <Card title={t('yearlyActivities.map.selectActivity')} size="small" style={{ marginBottom: '16px' }}>
          <Select
            placeholder={t('yearlyActivities.map.phAssignActivity')}
            style={{ width: '100%' }}
            value={selectedActivityId}
            onChange={handleActivitySelect}
            options={uniqueActivities.map((a: any) => ({
              label: a.name,
              value: a.id
            }))}
          />
        </Card>

        {selectedActivityId && blocksWithSubAreas.length > 0 && (
          <Card title={t('yearlyActivities.map.assignmentTitle')} size="small">
            <p style={{ marginBottom: '12px', color: '#666' }}>
              {t('yearlyActivities.map.assignmentHint')}
            </p>
            <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
              <List
                size="small"
                dataSource={blocksWithSubAreas}
                renderItem={(block: any) => (
                  <List.Item>
                    <div style={{ width: '100%' }}>
                      <strong>{block.block_name}</strong>
                      {block.sub_areas?.length > 0 && (
                        <List
                          size="small"
                          style={{ marginLeft: '16px', marginTop: '4px' }}
                          dataSource={block.sub_areas}
                          renderItem={(subArea: any) => (
                            <List.Item style={{ padding: '4px 0' }}>
                              <span>📍 {subArea.name} ({subArea.category})</span>
                            </List.Item>
                          )}
                        />
                      )}
                    </div>
                  </List.Item>
                )}
              />
            </div>
          </Card>
        )}

        <div style={{ height: '400px', marginTop: '16px', border: '1px solid #ddd', borderRadius: '4px' }}>
          <MapContainer
            center={[28.3949, 84.1240]}
            zoom={10}
            style={{ height: '100%', width: '100%' }}
          >
            <TileLayer
              attribution={BASE_MAPS[baseMap].attribution}
              url={BASE_MAPS[baseMap].url}
            />
<NumericScale />
            
            {/* Forest Boundary Layer */}
            {boundaryGeometry && (
              <GeoJSON
                data={boundaryGeometry}
                style={{
                  color: '#666666',
                  weight: 2,
                  fillColor: '#cccccc',
                  fillOpacity: 0.1
                }}
              />
            )}

            {/* Block Layers */}
            {blockLayers.map((block: any, index: number) => (
              block.geometry && (
                <GeoJSON
                  key={`block-${index}`}
                  data={block.geometry}
                  style={{
                    color: '#2563eb',
                    weight: 2,
                    fillColor: '#2563eb',
                    fillOpacity: 0.15
                  }}
                />
              )
            ))}

            {/* Sub-Area Layers */}
            {subAreaLayers.map((subArea: any, index: number) => (
              subArea.geometry && (
                <GeoJSON
                  key={`subarea-${index}`}
                  data={subArea.geometry}
                  style={{
                    color: CATEGORY_COLORS[subArea.category] || '#059669',
                    weight: 2,
                    fillColor: CATEGORY_COLORS[subArea.category] || '#059669',
                    fillOpacity: 0.3
                  }}
                />
              )
            ))}
            
            <MapBoundsUpdater />
          </MapContainer>
        </div>
      </div>
    );
  }

  // ===== DRAW MODE =====
  if (mapMode === 'draw') {
    return (
      <div>
        <div style={{ marginBottom: '16px' }}>
          <Space>
            <Radio.Group
              value={mapMode}
              onChange={(e) => setMapMode(e.target.value)}
              buttonStyle="solid"
            >
              <Radio.Button value="view">{t('yearlyActivities.map.modeView')}</Radio.Button>
              <Radio.Button value="assign">{t('yearlyActivities.map.modeAssign')}</Radio.Button>
              <Radio.Button value="draw">{t('yearlyActivities.map.modeDraw')}</Radio.Button>
            </Radio.Group>
          </Space>
        </div>
        <Select
          placeholder={t('yearlyActivities.map.phDrawActivity')}
          style={{ width: 300, marginBottom: '16px' }}
          value={selectedActivityId}
          onChange={handleActivitySelect}
          options={uniqueActivities.map((a: any) => ({
            label: a.name,
            value: a.id
          }))}
        />
        {selectedActivityId ? (
          <div style={{ height: '400px' }}>
            <DrawingCanvas
              calculationId={calculationId}
              activityId={selectedActivityId}
              featureType="point"
              onFeatureTypeChange={() => {}}
              drawnFeatures={drawnFeatures}
              onFeaturesChange={() => loadDrawnFeatures(selectedActivityId)}
              baseMap={baseMap}
              boundaryGeometry={boundaryGeometry}
              blockLayers={blockLayers}
              subAreaLayers={subAreaLayers}
            />
          </div>
        ) : (
          <Empty description={t('yearlyActivities.map.emptyDraw')} />
        )}
      </div>
    );
  }

  // ===== VIEW MODE =====
  return (
    <div>
      {/* Filter Controls */}
      <div style={{ marginBottom: '16px', display: 'flex', gap: '16px' }}>
        <Radio.Group
          value={mapMode}
          onChange={(e) => setMapMode(e.target.value)}
          buttonStyle="solid"
        >
          <Radio.Button value="view">{t('yearlyActivities.map.modeView')}</Radio.Button>
          <Radio.Button value="assign">{t('yearlyActivities.map.modeAssign')}</Radio.Button>
          <Radio.Button value="draw">{t('yearlyActivities.map.modeDraw')}</Radio.Button>
        </Radio.Group>
        
        <Select
          placeholder={t('yearlyActivities.map.filterCategory')}
          allowClear
          style={{ width: 200 }}
          value={selectedCategory}
          onChange={setSelectedCategory}
          options={uniqueCategories.map(cat => ({
            label: cat,
            value: cat
          }))}
        />
        
        {/* Base Map Selector */}
        <Select
          value={baseMap}
          onChange={setBaseMap}
          style={{ width: 140 }}
        >
          <Option value="satellite">{t('yearlyActivities.map.baseSatellite')}</Option>
          <Option value="osm">{t('yearlyActivities.map.baseStreet')}</Option>
          <Option value="topo">{t('yearlyActivities.map.baseTopo')}</Option>
        </Select>
        
        <div style={{ flex: 1, textAlign: 'right' }}>
          <Tag color="blue">{t('yearlyActivities.map.activityCount', { count: formatNumber(filteredFeatures.length) })}</Tag>
        </div>
      </div>

      {/* Map */}
      <div style={{ height: '500px', border: '1px solid #ddd', borderRadius: '4px', overflow: 'hidden' }}>
        <MapContainer
          center={[28.3949, 84.1240]}  // Nepal center
          zoom={10}
          style={{ height: '100%', width: '100%' }}
        >
          <TileLayer
            attribution={BASE_MAPS[baseMap].attribution}
            url={BASE_MAPS[baseMap].url}
          />
          <NumericScale />

          {/* Forest Boundary Layer */}
          {boundaryGeometry && (
            <GeoJSON
              data={boundaryGeometry}
              style={{
                color: '#666666',
                weight: 2,
                fillColor: '#cccccc',
                fillOpacity: 0.1
              }}
            />
          )}

          {/* Block Layers */}
          {blockLayers.map((block: any, index: number) => (
            block.geometry && (
              <GeoJSON
                key={`block-${index}`}
                data={block.geometry}
                style={{
                  color: '#2563eb',
                  weight: 2,
                  fillColor: '#2563eb',
                  fillOpacity: 0.15
                }}
              />
            )
          ))}

          {/* Sub-Area Layers */}
          {subAreaLayers.map((subArea: any, index: number) => (
            subArea.geometry && (
              <GeoJSON
                key={`subarea-${index}`}
                data={subArea.geometry}
                style={{
                  color: CATEGORY_COLORS[subArea.category] || '#059669',
                  weight: 2,
                  fillColor: CATEGORY_COLORS[subArea.category] || '#059669',
                  fillOpacity: 0.3
                }}
              />
            )
          ))}

          {/* Activity Features */}
          <GeoJSON
            key={JSON.stringify(filteredFeatures)}  // Force re-render on filter change
            data={{
              type: 'FeatureCollection',
              features: filteredFeatures
            } as any}
            style={styleFeature}
            onEachFeature={onEachFeature}
          />

          <MapBoundsUpdater />
        </MapContainer>
      </div>

      {/* Legend */}
      <Card size="small" style={{ marginTop: '16px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
          <strong style={{ width: '100%' }}>{t('yearlyActivities.map.categoriesLegend')}</strong>
          {Object.entries(CATEGORY_COLORS).map(([category, color]) => (
            <div key={category} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{
                width: '16px',
                height: '16px',
                backgroundColor: color,
                border: '1px solid #ddd',
                borderRadius: '2px'
              }} />
              <span style={{ fontSize: '12px' }}>
                {subAreaCategoryLabelKey(category)
                  ? t(subAreaCategoryLabelKey(category))
                  : category.replace('_', ' ')}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

export default ActivityMapView;
