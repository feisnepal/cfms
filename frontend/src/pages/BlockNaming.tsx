/** BlockNaming — interactive block naming on Leaflet map with Turf.js geometry operations. */
import React, { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { notification } from 'antd';
import { MapContainer, TileLayer, GeoJSON, Popup, Marker, useMap } from 'react-leaflet';
import L from 'leaflet';
import * as turf from '@turf/turf';
import { forestApi } from '../services/api';
import { Tooltip } from '../components/Tooltip';
import GuideModal from '../components/GuideModal';
import i18n from '../i18n';
import { useT } from '../i18n/hooks';
import { formatDecimal, formatNumber } from '../i18n/numberFormat';
import '../styles/compact.css';
import { NumericScale } from '../components/NumericScale';
import { useDimensionLabels } from '../hooks/useDimensionLabels';

const WORKSPACE_FEATURE_FLAG = 'workspaceRedirect';

function useBlockNamingRedirect(calculationId: string) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const t = useT();

  const workspaceEnabled = true;

  const isLegacyMode = searchParams.get('legacy') === 'true';

  const { data: calc, isLoading, isError } = useQuery({
    queryKey: ['calculation-status', calculationId],
    queryFn: async () => {
      const resp = await fetch(`/api/calculations/${calculationId}?fields=id,status,forest_name,structure_locked`);
      if (!resp.ok) throw new Error(t('blockNaming.fetchFailed'));
      return resp.json();
    },
    enabled: workspaceEnabled && !isLegacyMode,
    staleTime: 60_000,
  });

  const targetUrl = useMemo(() => {
    if (!calculationId) return '';
    const preservedParams = new URLSearchParams();
    const preserveList = ['tab', 'mode', 'referrer', 'dimension'];
    for (const key of preserveList) {
      const val = searchParams.get(key);
      if (val) preservedParams.set(key, val);
    }
    preservedParams.set('context', 'block_naming');
    const qs = preservedParams.toString();
    return `/workspace/${calculationId}${qs ? `?${qs}` : ''}`;
  }, [calculationId, searchParams]);

  React.useEffect(() => {
    if (!isLoading && calc && !isLegacyMode && workspaceEnabled) {
      if (calc.status === 'archived') return;

      notification.info({
        message: t('workspace.redirect.title'),
        description: t('workspace.redirect.description'),
        placement: 'topRight',
        duration: 5,
        key: 'workspace-redirect',
      });

      const timer = setTimeout(() => {
        navigate(targetUrl, { replace: true });
      }, 1500);

      return () => clearTimeout(timer);
    }
  }, [isLoading, calc, isLegacyMode, workspaceEnabled, targetUrl, navigate, t]);

  return {
    shouldRedirect: workspaceEnabled && !isLegacyMode && !!calc && calc.status !== 'archived',
    targetUrl,
    reason: workspaceEnabled && calc && calc.status !== 'archived' ? 'workspace_available' : null,
  };
}

interface BlockPolygon {
  index: number;
  geometry: any;
  area_hectares: number;
  current_name: string;
}

interface Calculation {
  id: string;
  forest_name: string;
  geometry: any; // GeoJSON geometry from API
}

type BlockMode = 'single' | 'multiple';

const COLORS = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4'];

// Component to fit map bounds to show boundary geometry
const FitBoundaryBounds: React.FC<{ geometry: any }> = ({ geometry }) => {
  const map = useMap();

  useEffect(() => {
    if (!geometry) return;
    
    try {
      const allCoords: [number, number][] = [];
      
      if (geometry.type === 'Polygon') {
        geometry.coordinates[0].forEach((coord: number[]) => {
          allCoords.push([coord[1], coord[0]]);
        });
      } else if (geometry.type === 'MultiPolygon') {
        geometry.coordinates.forEach((polygon: any) => {
          polygon[0].forEach((coord: number[]) => {
            allCoords.push([coord[1], coord[0]]);
          });
        });
      }

      if (allCoords.length > 0) {
        const bounds = L.latLngBounds(allCoords);
        map.fitBounds(bounds, { padding: [50, 50] });
      }
    } catch (e) {
      console.error('Error fitting bounds:', e);
    }
  }, [geometry, map]);

  return null;
};

// Component to fit map bounds to show all polygons
const FitBounds: React.FC<{ polygons: BlockPolygon[] }> = ({ polygons }) => {
  const map = useMap();

  useEffect(() => {
    if (polygons.length > 0) {
      const allCoords: [number, number][] = [];

      polygons.forEach(poly => {
        if (poly.geometry.type === 'Polygon') {
          poly.geometry.coordinates[0].forEach((coord: number[]) => {
            allCoords.push([coord[1], coord[0]]);
          });
        } else if (poly.geometry.type === 'MultiPolygon') {
          poly.geometry.coordinates.forEach((polygon: any) => {
            polygon[0].forEach((coord: number[]) => {
              allCoords.push([coord[1], coord[0]]);
            });
          });
        }
      });

      if (allCoords.length > 0) {
        const bounds = L.latLngBounds(allCoords);
        map.fitBounds(bounds, { padding: [50, 50] });
      }
    }
  }, [polygons, map]);

  return null;
};

function LegacyBlockNaming({ calculationId }: { calculationId: string }) {
  const t = useT();
  const labels = useDimensionLabels({ hasCompartments: false });
  const isNe = i18n.language === 'ne';
  const unitNoun = isNe ? labels.unitLabelNp : labels.unitLabel;
  const unitNounLower = isNe ? labels.unitLabelNp : labels.unitLabelLower;
  const unitNounPlural = isNe ? labels.unitLabelPluralNp : labels.unitLabelPlural;
  const unitNounPluralLower = isNe ? labels.unitLabelPluralNp : labels.unitLabelPluralLower;
  const navigate = useNavigate();

  // State
  const [calculation, setCalculation] = useState<Calculation | null>(null);
  const [blockMode, setBlockMode] = useState<BlockMode>('multiple');
  const [singleBlockName, setSingleBlockName] = useState('');
  const [polygons, setPolygons] = useState<BlockPolygon[]>([]);
  const [namedPolygons, setNamedPolygons] = useState<Map<number, string>>(new Map());
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [baseMap, setBaseMap] = useState<'satellite' | 'street'>('satellite');
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showGuide, setShowGuide] = useState(false);

  // Load calculation and polygons
  useEffect(() => {
    if (calculationId) {
      loadData();
    }
  }, [calculationId]);

  const loadData = async () => {
    try {
      setLoading(true);

      // Fetch calculation details
      const calc = await forestApi.getCalculation(calculationId);
      setCalculation(calc as any);

      // Set default block name
      setSingleBlockName(`${calc.forest_name} - Block 1`);

      // Fetch polygons for multi-block mode
      const response = await forestApi.getPolygons(calculationId);
      if (response.polygons && response.polygons.length > 0) {
        setPolygons(response.polygons);

        // Initialize named polygons with default names
        const initialNames = new Map<number, string>();
        response.polygons.forEach((p: BlockPolygon) => {
          initialNames.set(p.index, p.current_name || `Block ${p.index + 1}`);
        });
        setNamedPolygons(initialNames);
      }
    } catch (error: any) {
      console.error('Failed to load data:', error);
      alert(`Failed to load: ${error.response?.data?.detail || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!calculationId) return;

    try {
      setSaving(true);

      if (blockMode === 'single') {
        await forestApi.createSingleBlock(calculationId, singleBlockName);
      } else {
        const blocksInput = Array.from(namedPolygons.entries()).map(([index, name]) => ({
          polygon_index: index,
          name: name
        }));
        await forestApi.createBlocks(calculationId, blocksInput);
      }

      navigate(`/calculations/${calculationId}`);
    } catch (error: any) {
      console.error('Failed to save blocks:', error);
      alert(`Failed to save: ${error.response?.data?.detail || error.message}`);
      setSaving(false);
    }
  };

  const handleBlockNameChange = (index: number, newName: string) => {
    setNamedPolygons(new Map(namedPolygons.set(index, newName.trim())));
  };

  const handleRowClick = (index: number) => {
    setSelectedIndex(index);
    setEditingIndex(null);
  };

  const handleEditClick = (index: number, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingIndex(index);
    setSelectedIndex(index);
  };

  const getColorForIndex = (index: number): string => {
    return COLORS[index % COLORS.length];
  };

  const geoJsonStyle = (feature: any, index: number) => {
    const isSelected = selectedIndex === index;
    return {
      color: getColorForIndex(index),
      weight: isSelected ? 3 : 2,
      fillColor: getColorForIndex(index),
      fillOpacity: blockMode === 'multiple' ? (isSelected ? 0.5 : 0.3) : 0.2
    };
  };

  // Calculate centroid for a polygon
  const getPolygonCentroid = (geometry: any): [number, number] | null => {
    try {
      let turfPoly;
      if (geometry.type === 'MultiPolygon') {
        const areas = geometry.coordinates.map((ring: any) => {
          try {
            return turf.area(turf.polygon(ring));
          } catch {
            return 0;
          }
        });
        const maxIdx = areas.indexOf(Math.max(...areas));
        turfPoly = turf.polygon(geometry.coordinates[maxIdx]);
      } else if (geometry.type === 'Polygon') {
        turfPoly = turf.polygon(geometry.coordinates);
      }

      if (turfPoly) {
        const center = turf.centroid(turfPoly);
        return [center.geometry.coordinates[1], center.geometry.coordinates[0]];
      }
    } catch (e) {
      console.error('Error calculating centroid:', e);
    }
    return null;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{t('common.loading')}</p>
        </div>
      </div>
    );
  }

  // Debug info
  console.log('[BlockNaming] State:', {
    hasCalculation: !!calculation,
    hasGeometry: !!calculation?.geometry,
    geometryType: calculation?.geometry?.type,
    polygonsCount: polygons.length,
    blockMode,
    singleBlockName
  });

  return (
    <>
      <div className="compact-page">
      {/* Header */}
      <div className="compact-header flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-800">
          {t('blockNaming.title', { unit: unitNoun, name: calculation?.forest_name ?? '' })}
        </h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowGuide(true)}
            className="text-gray-500 hover:text-gray-700 p-1 rounded"
            title={t('blockNaming.openGuide')}
          >
            ❓
          </button>
          <button
            onClick={() => navigate(`/calculations/${calculationId}`)}
            className="text-gray-500 hover:text-gray-700 text-xl font-bold"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar - Fixed width, full height */}
        <div className="w-72 bg-white border-r border-gray-200 flex flex-col" style={{ minHeight: 0 }}>
          {/* Block Mode Selection */}
          <div className="p-4 border-b border-gray-200">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">{t('blockNaming.mode', { unit: unitNoun })}</h2>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  value="single"
                  checked={blockMode === 'single'}
                  onChange={() => setBlockMode('single')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="font-medium text-sm">{t('blockNaming.single', { unit: unitNoun })}</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  value="multiple"
                  checked={blockMode === 'multiple'}
                  onChange={() => setBlockMode('multiple')}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="font-medium text-sm">{t('blockNaming.multiple', { unit: unitNounPlural })}</span>
              </label>
            </div>
          </div>

          {/* Single Block Name Input */}
          {blockMode === 'single' && (
<div className="p-4 border-b border-gray-200">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-gray-700 mb-2">{t('blockNaming.name', { unit: unitNoun })}</h3>
            </div>
            <input
                type="text"
                value={singleBlockName}
                onChange={(e) => setSingleBlockName(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder={t('blockNaming.phName', { unit: unitNoun })}
              />
            </div>
          )}

          {/* Multiple Blocks List - Scrollable */}
          {blockMode === 'multiple' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="p-4 border-b border-gray-200 bg-gray-50">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                    {unitNounPlural} ({formatNumber(polygons.length)})
                  </h3>
                </div>
                <p className="text-xs text-gray-500 mt-1">{t('blockNaming.rowHint')}</p>
              </div>
              <div className="flex-1 overflow-y-auto">
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-gray-100">
                    {polygons.map((poly, idx) => (
                      <tr
                        key={idx}
                        onClick={() => handleRowClick(idx)}
                        className={`cursor-pointer transition-colors ${
                          selectedIndex === idx 
                            ? 'bg-blue-600 text-white' 
                            : 'hover:bg-gray-100'
                        }`}
                      >
                        <td className="px-3 py-2.5 w-8">
                          <div
                            className="w-6 h-6 rounded border-2"
                            style={{
                              backgroundColor: getColorForIndex(idx),
                              borderColor: getColorForIndex(idx)
                            }}
                          ></div>
                        </td>
                        <td className="px-2 py-2.5">
                          {editingIndex === idx ? (
                            <input
                              type="text"
                              value={namedPolygons.get(idx) || ''}
                              onChange={(e) => handleBlockNameChange(idx, e.target.value)}
                              onBlur={() => setEditingIndex(null)}
                              onKeyPress={(e) => {
                                if (e.key === 'Enter') setEditingIndex(null);
                              }}
                              autoFocus
                              className="w-full px-2 py-1 text-sm border border-blue-500 rounded focus:outline-none"
                              onClick={(e) => e.stopPropagation()}
                            />
                          ) : (
                            <div className="flex items-center justify-between">
                              <span className={`font-medium ${selectedIndex === idx ? 'text-white' : 'text-gray-900'}`}>
                                {namedPolygons.get(idx) || `Block ${idx + 1}`}
                              </span>
                              <button
                                onClick={(e) => handleEditClick(idx, e)}
                                className={selectedIndex === idx ? 'text-white opacity-70 hover:opacity-100' : 'text-gray-400 hover:text-blue-600'}
                              >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                                </svg>
                              </button>
                            </div>
                          )}
                        </td>
                        <td className={`px-3 py-2.5 whitespace-nowrap ${selectedIndex === idx ? 'text-white opacity-80' : 'text-gray-600'}`}>
                          {formatDecimal(poly.area_hectares)} {t('units.hectare')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="p-4 border-t border-gray-200 bg-gray-50">
            <button
              onClick={handleSave}
              disabled={saving || (blockMode === 'multiple' && namedPolygons.size !== polygons.length)}
              className="w-full px-4 py-2.5 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed font-medium transition-colors"
            >
              {saving ? t('common.saving') : t('blockNaming.saveContinue')}
            </button>
            <p className="text-xs text-gray-500 text-center mt-2">
              {blockMode === 'multiple'
                ? t('blockNaming.namedCount', {
                    done: formatNumber(namedPolygons.size),
                    total: formatNumber(polygons.length),
                    unit: unitNounPluralLower,
                  })
                : t('blockNaming.singleSaveHint', { unit: unitNounLower })}
            </p>
          </div>
        </div>

        {/* Map Area */}
        <div className="flex-1 relative">
          <MapContainer
            center={[27.7, 85.3]}
            zoom={13}
            style={{ height: '100%', width: '100%' }}
            className="z-0"
          >
            {/* Satellite imagery as default */}
            <TileLayer
              attribution='&copy; <a href="https://www.esri.com/">Esri</a>'
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              maxZoom={19}
              opacity={baseMap === 'satellite' ? 1 : 0}
              zIndex={1}
            />
            {/* Street map option */}
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
              opacity={baseMap === 'street' ? 1 : 0}
              zIndex={1}
            />

            {/* Show boundary */}
            {calculation?.geometry && (
              <GeoJSON
                data={calculation.geometry}
                style={{
                  color: '#10b981',
                  weight: 3,
                  fillColor: '#10b981',
                  fillOpacity: 0.15
                }}
              />
            )}

            {/* Auto-fit bounds to boundary */}
            <FitBoundaryBounds geometry={calculation?.geometry} />
            <NumericScale />

            {/* Show polygons for multi-block mode */}
            {blockMode === 'multiple' && polygons.map((poly, idx) => {
              const centroid = getPolygonCentroid(poly.geometry);
              const blockName = namedPolygons.get(idx) || `Block ${idx + 1}`;

              return (
                <React.Fragment key={`polygon-${idx}`}>
                  <GeoJSON
                    data={poly.geometry}
                    style={geoJsonStyle(poly.geometry, idx)}
                    eventHandlers={{ click: () => handleRowClick(idx) }}
                  >
                    <Popup>
                      <div className="text-sm">
                        <strong>{blockName}</strong><br />
                        {t('blockNaming.area', { value: formatDecimal(poly.area_hectares), unit: t('units.hectare') })}
                      </div>
                    </Popup>
                  </GeoJSON>
                </React.Fragment>
              );
            })}

            {blockMode === 'multiple' && polygons.length > 0 && (
              <FitBounds polygons={polygons} />
            )}
            
            {/* Block Labels */}
            {blockMode === 'multiple' && polygons.map((poly, idx) => {
              const centroid = getPolygonCentroid(poly.geometry);
              const blockName = namedPolygons.get(idx) || `Block ${idx + 1}`;
              if (!centroid) return null;
              return (
                <Marker
                  key={`label-${idx}`}
                  position={centroid}
                  zIndexOffset={1000}
                  icon={L.divIcon({
                    className: 'block-label',
                    html: `<div style="
                      background: ${getColorForIndex(idx)};
                      color: white;
                      padding: 2px 6px;
                      border-radius: 3px;
                      font-size: 11px;
                      font-weight: bold;
                      white-space: nowrap;
                      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    ">${blockName}</div>`,
                    iconSize: [0, 0],
                    iconAnchor: [0, 0]
                  })}
                />
              );
            })}
          </MapContainer>
          
          {/* Base Map Toggle */}
          <div className="absolute top-3 right-3 z-[1000] bg-white rounded-lg shadow-md p-1 flex gap-1">
            <button
              onClick={() => setBaseMap('satellite')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                baseMap === 'satellite' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {t('blockNaming.satellite')}
            </button>
            <button
              onClick={() => setBaseMap('street')}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                baseMap === 'street' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {t('blockNaming.street')}
            </button>
          </div>
        </div>
      </div>
    </div>
      <GuideModal
        visible={showGuide}
        onClose={() => setShowGuide(false)}
        initialGuide="blocks-compartments"
      />
    </>
  );
};

export default function BlockNaming() {
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const calculationId = id!;
  const { shouldRedirect, targetUrl } = useBlockNamingRedirect(calculationId);

  if (shouldRedirect) {
    return (
      <div className="block-naming-redirect" role="status" aria-live="polite">
        <div className="redirect-banner">
          <span className="redirect-icon">🗺️</span>
          <h2>{t('blockNaming.redirecting')}</h2>
          <p className="redirect-subtitle">
            {t('blockNaming.redirectBody')}
          </p>
          <a
            href={targetUrl}
            className="redirect-link"
            onClick={(e) => {
              e.preventDefault();
              window.location.href = targetUrl;
            }}
          >
            {t('blockNaming.redirectLink')}
          </a>
          <p className="redirect-legacy">
            <a href={`${window.location.pathname}?legacy=true`}>{t('blockNaming.legacyLink')}</a>
          </p>
        </div>
      </div>
    );
  }

  return <LegacyBlockNaming calculationId={calculationId} />;
}
