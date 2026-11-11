/** Interactive polygon drawing tool with vertex markers, polyline preview, and ref-exposed API. */
import React, { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import HelpTooltip from '../HelpTooltip';
import { GPSPoint, gpsPointsToPolygon } from '../../utils/gpsUtils';
import { NumericScale } from '../NumericScale';

import {
  validatePolygonGeometry,
  calculateAreaHectares,
  simplifyPolygon,
  formatArea,
} from '../../utils/geometryValidation';
import BaseMapSelector from './BaseMapSelector';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';

interface PolygonCreatorProps {
  gpsPoints?: GPSPoint[];
  onPolygonChange: (polygon: any) => void;
  initialPolygon?: any;
}

export interface PolygonCreatorHandle {
  zoomToBounds: (bounds: [number, number, number, number]) => void;
  setWardBoundary: (geometry: any) => void;
}

interface Island {
  id: string;
  geometry: any;
  area: number;
  layer?: L.Layer;
}

const ISLAND_COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];

// Component to capture map reference
const MapRefCapture: React.FC<{ onMapReady: (map: L.Map) => void }> = ({ onMapReady }) => {
  const map = useMap();

  useEffect(() => {
    if (map) {
      onMapReady(map);
    }
  }, [map, onMapReady]);

  return null;
};

// Map component with Leaflet-Geoman drawing controls for multiple islands
const MultiIslandDrawingControls: React.FC<{
  mode: 'auto' | 'manual';
  onPolygonCreated: (polygon: any) => void;
  islands: Island[];
  activeIslandId: string | null;
  onIslandLayerCreated: (islandId: string, layer: L.Layer) => void;
}> = ({ mode, onPolygonCreated, islands, activeIslandId, onIslandLayerCreated }) => {
  const map = useMap();
  const layersRef = useRef<Map<string, L.Layer>>(new Map());

  useEffect(() => {
    if (mode === 'manual') {
      // Enable Leaflet-Geoman controls (polygon disabled by default until Add Island is clicked)
      map.pm.addControls({
        position: 'topleft',
        drawPolygon: false,  // Disabled until Add Island is clicked
        drawMarker: false,
        drawCircle: false,
        drawCircleMarker: false,
        drawPolyline: false,
        drawRectangle: false,  // Also disable rectangle
        editMode: true,
        dragMode: false,
        cutPolygon: false,
        removalMode: true,
      });

      // Listen for polygon creation
      const handleCreate = (e: any) => {
        const layer = e.layer;
        const geoJSON = layer.toGeoJSON();

        // Store layer reference for the active island
        if (activeIslandId) {
          layersRef.current.set(activeIslandId, layer);
          onIslandLayerCreated(activeIslandId, layer);
        }

        onPolygonCreated(geoJSON.geometry);
        
        // Disable polygon drawing after completion
        map.pm.disableDraw('Polygon');
      };

      // Listen for polygon editing
      const handleEdit = (e: any) => {
        const layers = e.layers;
        layers.eachLayer((layer: any) => {
          const geoJSON = layer.toGeoJSON();
          onPolygonCreated(geoJSON.geometry);
        });
      };

      // Listen for polygon removal
      const handleRemove = (e: any) => {
        const layer = e.layer;
        // Find and remove from layersRef
        for (const [id, storedLayer] of layersRef.current.entries()) {
          if (storedLayer === layer) {
            layersRef.current.delete(id);
            break;
          }
        }
      };

      map.on('pm:create', handleCreate);
      map.on('pm:edit', handleEdit);
      map.on('pm:remove', handleRemove);

      return () => {
        map.pm.removeControls();
        map.off('pm:create', handleCreate);
        map.off('pm:edit', handleEdit);
        map.off('pm:remove', handleRemove);

        // DON'T remove layers here - they're managed by the islands display useEffect
        // Only cleanup event listeners
      };
    }
  }, [mode, map, onPolygonCreated]);

  // Control polygon tool based on activeIslandId
  useEffect(() => {
    if (mode === 'manual' && map) {
      if (activeIslandId) {
        // Enable polygon drawing when an island is being added
        map.pm.enableDraw('Polygon', {
          snappable: true,
          snapDistance: 20,
        });
      } else {
        // Disable polygon drawing when no island is being added
        map.pm.disableDraw('Polygon');
      }
    }
  }, [mode, activeIslandId, map]);

  // Display existing islands on map
  useEffect(() => {
    if (mode === 'manual') {
      // Remove old layers that are not in current islands
      const currentIslandIds = new Set(islands.map(i => i.id));
      for (const [id, layer] of layersRef.current.entries()) {
        if (!currentIslandIds.has(id) && map.hasLayer(layer)) {
          map.removeLayer(layer);
          layersRef.current.delete(id);
        }
      }

      // Add islands that don't have layers yet
      islands.forEach((island, index) => {
        if (!layersRef.current.has(island.id) && island.geometry) {
          const color = ISLAND_COLORS[index % ISLAND_COLORS.length];
          const geoJsonLayer = L.geoJSON(island.geometry, {
            pmIgnore: false,
            style: {
              color: color,
              weight: 3,
              fillOpacity: 0.2,
              fillColor: color,
            }
          });
          geoJsonLayer.addTo(map);
          layersRef.current.set(island.id, geoJsonLayer);
        }
      });

      // Fit bounds to show all islands
      if (islands.length > 0) {
        const allBounds: L.LatLngBounds[] = [];
        islands.forEach(island => {
          const layer = layersRef.current.get(island.id);
          if (layer && (layer as any).getBounds) {
            allBounds.push((layer as any).getBounds());
          }
        });

        if (allBounds.length > 0) {
          const combinedBounds = allBounds.reduce((acc, bounds) => acc.extend(bounds), allBounds[0]);
          map.fitBounds(combinedBounds, { padding: [50, 50] });
        }
      }
    }
  }, [islands, map, mode]);

  return null;
};

const DRAFT_STORAGE_KEY = 'polygon_creator_draft';

const PolygonCreator = forwardRef<PolygonCreatorHandle, PolygonCreatorProps>(({
  gpsPoints = [],
  onPolygonChange,
  initialPolygon,
}, ref) => {
  const t = useT();
  const [mode, setMode] = useState<'auto' | 'manual'>('auto');
  const [islands, setIslands] = useState<Island[]>([]);
  const [activeIslandId, setActiveIslandId] = useState<string | null>(null);
  const [error, setError] = useState<string>('');
  const [validation, setValidation] = useState<{
    valid: boolean;
    error?: string;
    warnings?: string[];
  } | null>(null);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [showSaveIndicator, setShowSaveIndicator] = useState(false);

  // Refs for map control
  const mapRef = useRef<L.Map | null>(null);
  const wardBoundaryLayerRef = useRef<L.GeoJSON | null>(null);

  // Load from initialPolygon on mount
  useEffect(() => {
    if (initialPolygon) {
      // Check if it's a MultiPolygon
      if (initialPolygon.type === 'MultiPolygon') {
        const loadedIslands: Island[] = initialPolygon.coordinates.map((coords: any, index: number) => {
          const polygonGeom = {
            type: 'Polygon',
            coordinates: coords
          };
          return {
            id: `island-${Date.now()}-${index}`,
            geometry: polygonGeom,
            area: calculateAreaHectares(polygonGeom),
          };
        });
        setIslands(loadedIslands);
        // Notify parent with MultiPolygon
        onPolygonChange(initialPolygon);
      } else if (initialPolygon.type === 'Polygon') {
        // Single polygon
        const newIsland = {
          id: `island-${Date.now()}-0`,
          geometry: initialPolygon,
          area: calculateAreaHectares(initialPolygon),
        };
        setIslands([newIsland]);
        // Notify parent with the polygon
        onPolygonChange(initialPolygon);
      }
    }
  }, [initialPolygon]);

  // Manual save draft (called by user clicking Save Draft button)
  const saveDraft = () => {
    try {
      const draft = {
        islands: islands,
        mode,
        activeIslandId: activeIslandId,
        timestamp: new Date().toISOString(),
      };
      localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      setLastSaved(new Date());
      setShowSaveIndicator(true);
      setTimeout(() => setShowSaveIndicator(false), 2000);
    } catch (error) {
      console.error('[PolygonCreator] Error saving draft:', error);
    }
  };

  // Clear draft when completing (passing polygon to parent)
  const clearDraft = () => {
    try {
      localStorage.removeItem(DRAFT_STORAGE_KEY);
      setLastSaved(null);
    } catch (error) {
      console.error('[PolygonCreator] Error clearing draft:', error);
    }
  };

  // Expose saveDraft method to parent
  useImperativeHandle(ref, () => ({
    zoomToBounds: (bounds: [number, number, number, number]) => {
      console.log('[PolygonCreator] zoomToBounds called:', bounds);
      if (mapRef.current) {
        try {
          mapRef.current.fitBounds([
            [bounds[1], bounds[0]],  // Southwest corner
            [bounds[3], bounds[2]]   // Northeast corner
          ], {
            padding: [50, 50],
            maxZoom: 16
          });
          console.log('[PolygonCreator] Map zoomed to bounds');
        } catch (error) {
          console.error('[PolygonCreator] Error zooming to bounds:', error);
        }
      } else {
        console.warn('[PolygonCreator] Map ref not available yet');
      }
    },
    setWardBoundary: (geometry: any) => {
      console.log('[PolygonCreator] setWardBoundary called:', geometry ? 'show' : 'hide');
      if (!mapRef.current) {
        console.warn('[PolygonCreator] Map ref not available');
        return;
      }

      // Remove existing ward boundary
      if (wardBoundaryLayerRef.current) {
        mapRef.current.removeLayer(wardBoundaryLayerRef.current);
        wardBoundaryLayerRef.current = null;
        console.log('[PolygonCreator] Removed existing ward boundary');
      }

      // Add new ward boundary if geometry provided
      if (geometry) {
        try {
          const layer = L.geoJSON(geometry, {
            style: {
              color: '#fbbf24',      // Yellow
              weight: 2,
              fillOpacity: 0.05,
              fillColor: '#fbbf24',
              dashArray: '8, 4'      // Dashed line
            }
          });
          layer.addTo(mapRef.current);
          wardBoundaryLayerRef.current = layer;
          console.log('[PolygonCreator] Added ward boundary to map');
        } catch (error) {
          console.error('[PolygonCreator] Error adding ward boundary:', error);
        }
      }
    }
  }));

  // Capture map reference when ready
  const handleMapReady = (map: L.Map) => {
    console.log('[PolygonCreator] Map ready');
    mapRef.current = map;
  };

  // Handle mode change
  const handleModeChange = (newMode: 'auto' | 'manual') => {
    setMode(newMode);
    setError('');
    setActiveIslandId(null);

    if (newMode === 'auto' && gpsPoints.length < 3) {
      setError(t('digitize.polygon.need3Auto'));
    }
  };

  // Auto-create polygon from GPS points (single island only)
  const handleAutoCreate = () => {
    setError('');

    if (gpsPoints.length < 3) {
      setError(t('digitize.polygon.need3Manual'));
      return;
    }

    try {
      const autoPolygon = gpsPointsToPolygon(gpsPoints);
      const geometry = autoPolygon.geometry;

      // Validate
      const validationResult = validatePolygonGeometry(geometry);
      setValidation(validationResult);

      if (!validationResult.valid) {
        setError(validationResult.error || t('digitize.polygon.invalidPolygon'));
        return;
      }

      // Create single island from GPS points
      const newIsland: Island = {
        id: `island-${Date.now()}`,
        geometry: geometry,
        area: calculateAreaHectares(geometry),
      };

      setIslands([newIsland]);
      updateParentWithCombinedGeometry([newIsland]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('digitize.polygon.createFailed'));
    }
  };

  // Add new island for manual drawing
  const handleAddIsland = () => {
    const newIslandId = `island-${Date.now()}`;
    setActiveIslandId(newIslandId);
    setError('');

    // Add placeholder island (will be updated when drawn)
    const newIsland: Island = {
      id: newIslandId,
      geometry: null,
      area: 0,
    };

    setIslands(prev => [...prev, newIsland]);
  };

  // Remove island
  const handleRemoveIsland = (islandId: string) => {
    // Compute new value first
    const updatedIslands = islands.filter(i => i.id !== islandId);
    
    // Update state and parent geometry separately
    setIslands(updatedIslands);
    updateParentWithCombinedGeometry(updatedIslands);

    if (activeIslandId === islandId) {
      setActiveIslandId(null);
    }
  };

  // Handle manually drawn polygon
  const handleManualPolygon = (geometry: any) => {
    setError('');

    // Validate
    const validationResult = validatePolygonGeometry(geometry);
    setValidation(validationResult);

    if (!validationResult.valid) {
      setError(validationResult.error || t('digitize.polygon.invalidPolygon'));
      return;
    }

    if (activeIslandId) {
      // Update the active island - compute new value first
      const updatedIslands = islands.map(island =>
        island.id === activeIslandId
          ? { ...island, geometry, area: calculateAreaHectares(geometry) }
          : island
      );
      
      // Update state and parent geometry separately to avoid setState during render warning
      setIslands(updatedIslands);
      updateParentWithCombinedGeometry(updatedIslands);
      setActiveIslandId(null); // Clear active island after drawing
    }
  };

  // Update layer reference for island
  const handleIslandLayerCreated = (islandId: string, layer: L.Layer) => {
    setIslands(prev =>
      prev.map(island =>
        island.id === islandId ? { ...island, layer } : island
      )
    );
  };

  // Combine all islands into single geometry (Polygon or MultiPolygon)
  const updateParentWithCombinedGeometry = (islandList: Island[]) => {
    const validIslands = islandList.filter(i => i.geometry);

    if (validIslands.length === 0) {
      onPolygonChange(null);
    } else if (validIslands.length === 1) {
      // Single polygon
      onPolygonChange(validIslands[0].geometry);
    } else {
      // MultiPolygon
      const multiPolygon = {
        type: 'MultiPolygon',
        coordinates: validIslands.map(i => i.geometry.coordinates)
      };
      onPolygonChange(multiPolygon);
    }
  };

  // Calculate total area
  const totalArea = islands.reduce((sum, island) => sum + island.area, 0);
  const validIslandsCount = islands.filter(i => i.geometry).length;

  // Prepare map data
  const mapCenter: [number, number] =
    gpsPoints.length > 0
      ? [gpsPoints[0].latitude, gpsPoints[0].longitude]
      : [27.7172, 85.3240];

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold">{t('digitize.polygon.title')}</h2>

          {/* Auto-save indicator */}
          <div className="flex items-center gap-2">
            {showSaveIndicator && (
              <span className="text-sm text-green-600 flex items-center gap-1">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                {t('digitize.polygon.saved')}
              </span>
            )}
            {lastSaved && !showSaveIndicator && (
              <span className="text-xs text-gray-500">
                Last saved: {lastSaved.toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>

        {/* Mode Selection */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('digitize.polygon.creationMethod')}
          </label>
          <div className="flex gap-4">
            <button
              onClick={() => handleModeChange('auto')}
              className={`flex-1 px-4 py-3 rounded-lg border-2 transition-colors ${
                mode === 'auto'
                  ? 'border-green-600 bg-green-50 text-green-700'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              <div className="font-semibold">{t('digitize.polygon.methodAuto')}</div>
              <div className="text-sm text-gray-600 mt-1">
                {t('digitize.polygon.methodAutoHint')}
              </div>
            </button>
            <button
              onClick={() => handleModeChange('manual')}
              className={`flex-1 px-4 py-3 rounded-lg border-2 transition-colors ${
                mode === 'manual'
                  ? 'border-green-600 bg-green-50 text-green-700'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              <div className="font-semibold">{t('digitize.polygon.methodManual')}</div>
              <div className="text-sm text-gray-600 mt-1">
                {t('digitize.polygon.methodManualHint')}
              </div>
            </button>
          </div>
        </div>

        {/* Auto-create Mode */}
        {mode === 'auto' && (
          <div className="space-y-4">
            <div className="p-4 bg-blue-50 border border-blue-200 rounded-md">
              <p className="text-sm text-blue-800">
                <strong>{gpsPoints.length}</strong> GPS points loaded.{' '}
                {gpsPoints.length >= 3
                  ? 'Click "Create Polygon" to connect points in order.'
                  : `Need ${3 - gpsPoints.length} more points.`}
              </p>
            </div>

            <button
              onClick={handleAutoCreate}
              disabled={gpsPoints.length < 3}
              className="px-6 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {t('digitize.polygon.createFromGps')}
            </button>
          </div>
        )}

        {/* Manual Mode - Island Management */}
        {mode === 'manual' && (
          <div className="space-y-4">
            <div className="p-4 bg-blue-50 border border-blue-200 rounded-md">
              <div className="flex items-start">
                <p className="text-sm text-blue-800 flex-1">
                  <strong>{t('digitize.polygon.instructions')}</strong>
                  <br />
                  {t('digitize.polygon.step1', { button: t('digitize.polygon.addIsland') })}
                  <br />
                  {t('digitize.polygon.step2')}
                  <br />
                  {t('digitize.polygon.step3')}
                </p>
                <HelpTooltip tKey="tooltips.addIsland" position="left" />
              </div>
            </div>

            {/* Island List - Only show completed islands */}
            {validIslandsCount > 0 && (
              <div className="border border-gray-300 rounded-lg p-4">
                {/* Drawing indicator */}
                {activeIslandId && (
                  <div className="mb-3 p-2 bg-green-50 border border-green-200 rounded text-sm text-green-700">
                    <span className="font-semibold">{t('digitize.polygon.drawingActive')}</span> {t('digitize.polygon.drawingActiveHint')}
                  </div>
                )}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center">
                    <h3 className="font-semibold text-gray-800">
                      Islands: {validIslandsCount}
                    </h3>
                    <HelpTooltip tKey="tooltips.islands" position="right" />
                  </div>
                  <div className="flex items-center gap-2">
                    <HelpTooltip tKey="tooltips.addIsland" position="top">
                      <button
                        onClick={handleAddIsland}
                        disabled={activeIslandId !== null}
                        className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
                      >
                        + {t('digitize.polygon.addIsland')}
                      </button>
                    </HelpTooltip>
                  </div>
                </div>

                <div className="space-y-2">
                  {islands.filter(i => i.geometry).map((island, index) => (
                    <div
                      key={island.id}
                      className="flex items-center gap-3 p-3 rounded border-2 border-gray-200 bg-gray-50"
                    >
                      {/* Color indicator */}
                      <div
                        className="w-8 h-8 rounded border-2"
                        style={{
                          backgroundColor: ISLAND_COLORS[index % ISLAND_COLORS.length],
                          borderColor: ISLAND_COLORS[index % ISLAND_COLORS.length],
                        }}
                      ></div>

                      {/* Island info */}
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">
                          {t('digitize.polygon.islandN', { n: formatNumber(index + 1) })}
                        </div>
                        <div className="text-sm text-gray-600">
                          {t('digitize.polygon.areaLabel')} {formatArea(island.area)}
                        </div>
                      </div>

                      {/* Remove button */}
                      <button
                        onClick={() => handleRemoveIsland(island.id)}
                        className="p-2 text-red-600 hover:bg-red-50 rounded transition-colors"
                        title={t('digitize.polygon.removeIsland')}
                      >
                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Add First Island Button */}
            {islands.length === 0 && (
              <button
                onClick={handleAddIsland}
                className="w-full px-6 py-3 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
              >
                + Add First Island
              </button>
            )}
          </div>
        )}

        {/* Drawing Mode Indicator */}
        {activeIslandId && (
          <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-md flex items-center gap-2">
            <div className="animate-pulse w-3 h-3 bg-blue-500 rounded-full"></div>
            <span className="text-blue-800 font-medium">{t('digitize.polygon.drawModeActive')}</span>
            <button
              onClick={() => setActiveIslandId(null)}
              className="ml-auto text-blue-600 hover:text-blue-800 text-sm"
            >
              Cancel
            </button>
          </div>
        )}

        {/* Error Messages */}
        {error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md">
            {error}
          </div>
        )}

        {/* Validation Messages */}
        {validation && validation.warnings && validation.warnings.length > 0 && (
          <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 text-yellow-700 rounded-md">
            <strong>{t('digitize.polygon.warnings')}</strong>
            <ul className="list-disc list-inside mt-1">
              {validation.warnings.map((warning, i) => (
                <li key={i}>{warning}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Total Info */}
        {validIslandsCount > 0 && (
          <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-md">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <h3 className="font-semibold text-green-800 mb-2">
                  {validIslandsCount === 1
                    ? t('digitize.polygon.polygonCreated')
                    : t('digitize.polygon.islandsCreated', { count: formatNumber(validIslandsCount) })}
                </h3>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-gray-600">{t('digitize.polygon.totalArea')}</span>
                    <span className="ml-2 font-semibold">{formatArea(totalArea)}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">{t('digitize.polygon.type')}</span>
                    <span className="ml-2 font-semibold">
                      {validIslandsCount === 1 ? 'Polygon' : 'MultiPolygon'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Clear Draft Button */}
              {lastSaved && (
                <button
                  onClick={() => {
                    if (window.confirm(t('digitize.polygon.confirmClearDraft'))) {
                      clearDraft();
                      setIslands([]);
                      setActiveIslandId(null);
                      onPolygonChange(null);
                    }
                  }}
                  className="ml-4 px-3 py-1 text-sm text-red-600 hover:bg-red-50 rounded border border-red-300 transition-colors"
                  title={t('digitize.polygon.clearDraftHint')}
                >
                  {t('digitize.polygon.clearDraft')}
                </button>
              )}
            </div>

            <div className="mt-3 p-2 bg-blue-50 border border-blue-200 rounded text-xs text-blue-800">
              {t('digitize.polygon.clickNextHint', { button: t('digitize.polygon.next') })}
            </div>
          </div>
        )}
      </div>

      {/* Map */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">{t('digitize.polygon.map')}</h3>
        <div className="h-[600px] rounded overflow-hidden border border-gray-300">
          <MapContainer
            center={mapCenter}
            zoom={13}
            style={{ height: '100%', width: '100%' }}
          >
            <MapRefCapture onMapReady={handleMapReady} />
            <BaseMapSelector />
            <NumericScale />

            {/* Show GPS points if in auto mode */}
            {mode === 'auto' && gpsPoints.length > 0 && (
              <>
                {/* GPS point markers */}
                {gpsPoints.map((point) => (
                  <Marker key={point.id} position={[point.latitude, point.longitude]} />
                ))}

                {/* Line connecting GPS points */}
                <Polyline
                  positions={gpsPoints.map((p) => [p.latitude, p.longitude])}
                  color="blue"
                  weight={2}
                  dashArray="5, 5"
                />
              </>
            )}

            {/* Show created polygon in auto mode */}
            {mode === 'auto' && islands.length > 0 && islands[0].geometry && (
              <GeoJSON
                data={islands[0].geometry}
                style={{
                  color: '#10b981',
                  weight: 3,
                  fillOpacity: 0.2,
                }}
              />
            )}

            {/* Drawing controls for manual mode with multi-island support */}
            <MultiIslandDrawingControls
              mode={mode}
              onPolygonCreated={handleManualPolygon}
              islands={islands}
              activeIslandId={activeIslandId}
              onIslandLayerCreated={handleIslandLayerCreated}
            />
          </MapContainer>
        </div>
      </div>
    </div>
  );
});

export default PolygonCreator;
