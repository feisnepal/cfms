/** Manager for sub-areas within a forest block – create, edit, and delete sub-polygons on the map. */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import * as turf from '@turf/turf';
import HelpTooltip from '../HelpTooltip';
import { NumericScale } from '../NumericScale';

import {
  validateSubAreasNoOverlap,
  validateSubAreaSum,
  detectBlockForSubArea,
  calculateAreaHectares,
  formatArea,
  calculateSubAreaByBlock,
} from '../../utils/geometryValidation';
import { getGeometryCenter } from '../../utils/geometryHelpers';
import BaseMapSelector from './BaseMapSelector';
import { SUB_AREA_CATEGORIES } from '../../lib/subAreaCategories';
import { useTileToken, withTileToken } from '../../hooks/useTileToken';
import { useT } from '../../i18n/hooks';
import { formatDecimal } from '../../i18n/numberFormat';

interface Block {
  id: string;
  name: string;
  geometry: any;
  area: number;
}

interface SubArea {
  id: string;
  name: string;
  category: string;
  geometry: any;
  area: number;
  blockId?: string;
  blockName?: string;
  blockBreakdown?: Array<{ blockId: string; blockName: string; area: number; percentage: number }>;
  isExcluded?: boolean;  // True for private land excluded from forest calculations
}

interface SubAreaManagerProps {
  blocks: Block[];
  outerBoundary: any;
  onSubAreasChange: (subAreas: SubArea[]) => void;
  initialSubAreas?: SubArea[];
  calculationId?: string;
}

const formatLiveArea = (
  sqMeters: number,
  t: (k: string, opts?: Record<string, unknown>) => string,
): string => {
  const hectares = sqMeters / 10000;
  return `${formatDecimal(sqMeters, 1)} ${t('units.sqM')}`
    + ` (${formatDecimal(hectares)} ${t('units.hectare')})`;
};

// Predefined sub-area categories — single source is `../../lib/subAreaCategories` (D1).

// Map component with drawing controls for sub-areas
const SubAreaDrawingControls: React.FC<{
  blocks: Block[];
  outerBoundary: any;
  selectedCategory: string;
  onSubAreaCreated: (geometry: any, removeTempLayer: () => void) => void;
  subAreas: SubArea[];
  selectedSubAreaId: string | null;
  onSubAreaEdit: (subAreaId: string, geometry: any) => void;
  onSubAreaDelete: (subAreaId: string) => void;
  onLiveAreaChange?: (area: number) => void;
  onSubAreaSelect?: (subAreaId: string | null) => void;
}> = ({
  blocks,
  outerBoundary,
  selectedCategory,
  onSubAreaCreated,
  subAreas,
  selectedSubAreaId,
  onSubAreaEdit,
  onSubAreaDelete,
  onLiveAreaChange,
  onSubAreaSelect,
}) => {
  const t = useT();
  const map = useMap();
  const layersRef = useRef<Map<string, L.Layer>>(new Map());
  const pendingLayersRef = useRef<L.Layer[]>([]);
  const boundaryLayerRef = useRef<L.Layer | null>(null);
  const [liveArea, setLiveArea] = useState<number>(0);

  // Stabilize callbacks to prevent effect re-triggering
  const callbacksRef = useRef({ onSubAreaCreated, onSubAreaEdit, onSubAreaDelete, onSubAreaSelect });
  useEffect(() => {
    callbacksRef.current = { onSubAreaCreated, onSubAreaEdit, onSubAreaDelete, onSubAreaSelect };
  }, [onSubAreaCreated, onSubAreaEdit, onSubAreaDelete, onSubAreaSelect]);

  // Propagate live area to parent
  useEffect(() => {
    if (onLiveAreaChange) {
      onLiveAreaChange(liveArea);
    }
  }, [liveArea, onLiveAreaChange]);

  // FIRST useEffect: STRICTLY Leaflet-Geoman Setup
  useEffect(() => {
    // Get the category color
    const category = SUB_AREA_CATEGORIES.find(c => c.value === selectedCategory);
    const categoryColor = category?.color || '#3b82f6';

    // Add outer boundary as a snapping guide layer
    if (outerBoundary && !boundaryLayerRef.current) {
      const boundaryLayer = L.geoJSON(outerBoundary, {
        style: {
          color: '#1d4ed8',
          weight: 3,
          fillOpacity: 0,
          opacity: 0.7,
        },
        pmIgnore: true, // Don't let geoman edit this layer
      }).addTo(map);
      boundaryLayerRef.current = boundaryLayer;
      
      // Set snapping options to snap to boundary edges
      map.pm.setGlobalOptions({
        snapDistance: 25,
        snapSegment: true,
      });
      
      // Add boundary layer to geoman's snap list
      boundaryLayer.eachLayer((layer: any) => {
        if (layer.pm) {
          layer.pm.set({
            snappable: true,
          });
        }
      });
    }

    // Enable Leaflet-Geoman controls
    map.pm.addControls({
      position: 'topleft',
      drawPolygon: true,
      drawMarker: false,
      drawCircle: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawRectangle: true,
      editMode: true,
      dragMode: false,
      cutPolygon: false,
      removalMode: true,
    });

    // Apply category color to drawing
    const handleDrawStart = (e: any) => {
      const layer = e.workingLayer;
      if (layer) {
        layer.setStyle({
          color: categoryColor,
          fillColor: categoryColor,
          fillOpacity: 0.3,
          weight: 3,
        });
        setTimeout(() => {
          const el = map.getContainer().querySelector<HTMLElement>('.leaflet-pm-touch-hint');
          if (el) el.style.opacity = '0.05';
        }, 50);
      }
    };

    // Helper to check if polygon is within boundary
    const isWithinBoundary = (polygon: any): boolean => {
      if (!outerBoundary) return true;
      try {
        const poly = turf.polygon(polygon.coordinates);
        const boundary = turf.polygon(outerBoundary.coordinates);
        const intersection = turf.intersect(turf.featureCollection([poly, boundary]));
        if (!intersection) return false;
        const polyArea = turf.area(poly);
        const intersectionArea = turf.area(intersection);
        return intersectionArea >= polyArea * 0.99; // 99% tolerance
      } catch (e) {
        return false;
      }
    };

    // Helper to update layer style based on boundary containment
    const updateLayerBoundaryStatus = (layer: any, isValid: boolean) => {
      if (isValid) {
        layer.setStyle({
          color: categoryColor,
          fillColor: categoryColor,
          fillOpacity: 0.3,
          weight: 3,
        });
      } else {
        layer.setStyle({
          color: '#ef4444',
          fillColor: '#ef4444',
          fillOpacity: 0.2,
          weight: 3,
          dashArray: '5, 5',
        });
      }
    };

    // Handle vertex added - check boundary containment
    const handleVertexAdded = (e: any) => {
      const layer = e.workingLayer;
      if (layer && outerBoundary) {
        try {
          const geoJSON = layer.toGeoJSON();
          if (geoJSON.geometry && geoJSON.geometry.type === 'Polygon') {
            const valid = isWithinBoundary(geoJSON.geometry);
            updateLayerBoundaryStatus(layer, valid);
          }
        } catch (err) {
          // Ignore errors during drawing
        }
      }
      // Calculate live area during drawing
      if (layer) {
        try {
          const gj = layer.toGeoJSON();
          if (gj.geometry && gj.geometry.type === 'Polygon' && gj.geometry.coordinates.length > 0) {
            const coords = gj.geometry.coordinates[0];
            if (coords.length >= 3) {
              const closedCoords = [...coords];
              const first = closedCoords[0];
              const last = closedCoords[closedCoords.length - 1];
              if (first[0] !== last[0] || first[1] !== last[1]) {
                closedCoords.push([...first]);
              }
              const poly = turf.polygon([closedCoords]);
              const area = turf.area(poly);
              setLiveArea(area);
            }
          }
        } catch (err) {
          setLiveArea(0);
        }
      }
    };

    // Handle polygon creation
    const handleCreate = (e: any) => {
      console.log('[SubAreaDrawingControls] handleCreate triggered');
      setLiveArea(0);  // Clear live area after polygon is created
      const layer = e.layer;
      const geoJSON = layer.toGeoJSON();

      // Check if polygon is within boundary
      if (outerBoundary && geoJSON.geometry) {
        const valid = isWithinBoundary(geoJSON.geometry);
        if (!valid) {
          console.log('[SubAreaDrawingControls] Rejected: polygon outside boundary');
          // Remove the layer immediately
          map.removeLayer(layer);
          // Show a brief error indicator on the map
          L.popup()
            .setLatLng(map.getCenter())
            .setContent(`<div style="color: red; font-weight: bold;">${t('digitize.subArea.errOutsideBoundary')}</div>`)
            .openOn(map);
          setTimeout(() => {
            try { map.closePopup(); } catch (e) {}
          }, 3000);
          return;
        }
      }

      // Style the layer immediately so it's visible
      layer.setStyle({
        color: categoryColor,
        fillColor: categoryColor,
        fillOpacity: 0.3,
        weight: 3,
      });
      console.log('[SubAreaDrawingControls] Layer styled with color:', categoryColor);

      // Disable editing on this temporary layer
      if (layer.pm) {
        layer.pm.disable();
        console.log('[SubAreaDrawingControls] Disabled PM on temp layer');
      }

      // Add to pending layers list
      pendingLayersRef.current.push(layer);
      console.log('[SubAreaDrawingControls] Added to pending layers, total pending:', pendingLayersRef.current.length);

      // Call the parent handler with callback to remove this temp layer on validation failure
      callbacksRef.current.onSubAreaCreated(geoJSON.geometry, () => {
        console.log('[SubAreaDrawingControls] Remove temp layer callback called (validation failed)');
        // Remove from pending and from map on validation failure
        const index = pendingLayersRef.current.indexOf(layer);
        if (index > -1) {
          pendingLayersRef.current.splice(index, 1);
        }
        map.removeLayer(layer);
      });
      console.log('[SubAreaDrawingControls] onSubAreaCreated called, waiting for validation...');
    };

    // Handle polygon editing
    const handleEdit = (e: any) => {
      const layers = e.layers;
      layers.eachLayer((layer: any) => {
        const geoJSON = layer.toGeoJSON();

        layersRef.current.forEach((storedLayer, subAreaId) => {
          if (storedLayer === layer) {
            callbacksRef.current.onSubAreaEdit(subAreaId, geoJSON.geometry);
          }
        });
      });
    };

    // Handle polygon removal
    const handleRemove = (e: any) => {
      const layer = e.layer;

      layersRef.current.forEach((storedLayer, subAreaId) => {
        if (storedLayer === layer) {
          callbacksRef.current.onSubAreaDelete(subAreaId);
          layersRef.current.delete(subAreaId);
        }
      });
    };

    map.on('pm:drawstart', handleDrawStart);
    map.on('pm:vertexadded', handleVertexAdded);
    map.on('pm:create', handleCreate);
    map.on('pm:edit', handleEdit);
    map.on('pm:remove', handleRemove);

    return () => {
      map.pm.removeControls();
      map.off('pm:drawstart', handleDrawStart);
      map.off('pm:vertexadded', handleVertexAdded);
      map.off('pm:create', handleCreate);
      map.off('pm:edit', handleEdit);
      map.off('pm:remove', handleRemove);

      // Clean up boundary layer
      if (boundaryLayerRef.current) {
        map.removeLayer(boundaryLayerRef.current);
        boundaryLayerRef.current = null;
      }

      // Reset global geoman options
      map.pm.setGlobalOptions({
        snapDistance: 0,
        snappable: false,
      });

      // Clean up pending layers only (removed layersRef cleanup from here)
      pendingLayersRef.current.forEach((layer) => {
        try {
          map.removeLayer(layer);
        } catch (e) {
          // Layer might already be removed
        }
      });
      pendingLayersRef.current = [];
    };
  }, [map, selectedCategory, outerBoundary]); // Dependency array minimized - removed callback dependencies

  // SECOND useEffect: STRICTLY State to Map Rendering
  useEffect(() => {
    console.log('[SubAreaManager] useEffect triggered - subAreas:', subAreas.length);
    console.log('[SubAreaManager] Pending layers to remove:', pendingLayersRef.current.length);
    console.log('[SubAreaManager] Old managed layers to remove:', layersRef.current.size);

    // Clean up temporary layers once state updates
    pendingLayersRef.current.forEach((layer) => {
      try {
        map.removeLayer(layer);
        console.log('[SubAreaManager] Removed pending layer');
      } catch (e) {
        console.log('[SubAreaManager] Error removing pending layer:', e);
      }
    });
    pendingLayersRef.current = [];

    // Clear existing managed layers to prevent duplicates
    layersRef.current.forEach((layer) => {
      map.removeLayer(layer);
    });
    layersRef.current.clear();

    // Add new layers for each sub-area
    subAreas.forEach((subArea) => {
      const category = SUB_AREA_CATEGORIES.find(c => c.value === subArea.category);
      const color = category?.color || '#6b7280';
      const isSelected = subArea.id === selectedSubAreaId;
      const isExcluded = subArea.isExcluded || false;

      const geoJsonLayer = L.geoJSON(subArea.geometry, {
        style: {
          color: isSelected ? '#000000' : color,
          weight: isSelected ? 4 : 2,
          fillOpacity: isExcluded ? 0.5 : 0.3,  // Higher opacity for excluded areas
          fillColor: isExcluded ? '#dc2626' : color,  // Red fill for excluded areas
          dashArray: isExcluded ? '10, 10' : undefined,  // Dashed border for excluded areas
        },
        pmIgnore: false,
      });

      // Add click handler to select sub-area
      geoJsonLayer.on('click', () => {
        if (callbacksRef.current.onSubAreaSelect) {
          callbacksRef.current.onSubAreaSelect(subArea.id);
        }
      });

      // Add to map
      geoJsonLayer.addTo(map);
      console.log(`[SubAreaManager] Added managed layer for ${subArea.name}, id: ${subArea.id}, excluded: ${isExcluded}`);

      layersRef.current.set(subArea.id, geoJsonLayer);
    });

    console.log('[SubAreaManager] Finished adding all managed layers, total:', layersRef.current.size);

    // Force map to invalidate size and re-render
    setTimeout(() => {
      map.invalidateSize();
      console.log('[SubAreaManager] Map invalidated');
    }, 0);
  }, [subAreas, selectedSubAreaId, map]);

  return null;
};

const SubAreaManager: React.FC<SubAreaManagerProps> = ({
  blocks,
  outerBoundary,
  onSubAreasChange,
  initialSubAreas = [],
  calculationId,
}) => {
  const t = useT();
  const [subAreas, setSubAreas] = useState<SubArea[]>(initialSubAreas);
  const [selectedCategory, setSelectedCategory] = useState<string>(SUB_AREA_CATEGORIES[0].value);
  const [selectedSubAreaId, setSelectedSubAreaId] = useState<string | null>(null);
  const [selectedBlockFilter, setSelectedBlockFilter] = useState<string>('all');
  const [error, setError] = useState<string>('');
  const [showSteepSlopeMask, setShowSteepSlopeMask] = useState<boolean>(false);
  const tileToken = useTileToken(calculationId);
  const [slopeMinClass, setSlopeMinClass] = useState<number>(4);
  const [showCanopyMask, setShowCanopyMask] = useState<boolean>(false);
  const [canopyShowRed, setCanopyShowRed] = useState<boolean>(true);
  const [canopyShowBlue, setCanopyShowBlue] = useState<boolean>(true);
  const [canopyShowGreen, setCanopyShowGreen] = useState<boolean>(true);
  const [liveArea, setLiveArea] = useState<number>(0);

  // Validate sub-areas whenever they change
  useEffect(() => {
    if (subAreas.length > 0) {
      // Validate no overlap
      const overlapResult = validateSubAreasNoOverlap(subAreas);
      if (!overlapResult.valid) {
        setError(overlapResult.error || '');
      } else {
        setError('');
      }
    }

    // Update parent
    onSubAreasChange(subAreas);
  }, [subAreas, onSubAreasChange]);

  // Handle sub-area creation (wrapped in useCallback to prevent unnecessary re-renders)
  const handleSubAreaCreated = useCallback((geometry: any, removeTempLayer: () => void) => {
    console.log('[SubAreaManager] handleSubAreaCreated called');
    setError('');

    try {
      const area = calculateAreaHectares(geometry);
      console.log('[SubAreaManager] Area calculated:', area);

      // Detect which block this sub-area belongs to
      const detection = detectBlockForSubArea(geometry, blocks);
      console.log('[SubAreaManager] Block detection:', detection);

      if (!detection.blockId) {
        console.log('[SubAreaManager] Validation failed: no block detected');
        setError(t('digitize.subArea.errOutsideBlock'));
        removeTempLayer(); // Remove temp layer on validation failure
        return;
      }

      if (detection.confidence < 0.9) {
        console.log('[SubAreaManager] Warning: low confidence', detection.confidence);
        setError(`Warning: Sub-area partially outside block (${(detection.confidence * 100).toFixed(0)}% inside)`);
      }

      const category = SUB_AREA_CATEGORIES.find(c => c.value === selectedCategory);

      // Calculate block-wise breakdown for cross-block sub-areas
      const blockBreakdown = calculateSubAreaByBlock(geometry, blocks);
      console.log('[SubAreaManager] Block breakdown:', blockBreakdown);

      const newSubArea: SubArea = {
        id: `subarea-${Date.now()}`,
        name: `${category?.label || 'Sub-area'} ${subAreas.filter(s => s.category === selectedCategory).length + 1}`,
        category: selectedCategory,
        geometry,
        area,
        blockId: detection.blockId,
        blockName: detection.blockName,
        blockBreakdown: blockBreakdown.length > 0 ? blockBreakdown : undefined,
        isExcluded: category?.isExcluded || false,  // Set excluded flag for private land
      };

      // Check if adding this sub-area would exceed block area
      const block = blocks.find(b => b.id === detection.blockId);
      if (block) {
        const blockSubAreas = [...subAreas.filter(s => s.blockId === block.id), newSubArea];
        const sumResult = validateSubAreaSum(block.geometry, blockSubAreas, 5);

        if (!sumResult.valid) {
          console.log('[SubAreaManager] Validation failed: exceeds block area');
          setError(sumResult.error || t('digitize.subArea.exceedsBlock'));
          removeTempLayer(); // Remove temp layer on validation failure
          return;
        }
      }

      console.log('[SubAreaManager] Validation passed! Updating state...');
      console.log('[SubAreaManager] Current subAreas count:', subAreas.length);
      console.log('[SubAreaManager] New subArea:', newSubArea);
      setSubAreas(prev => [...prev, newSubArea]);
      console.log('[SubAreaManager] State update called (will trigger useEffect)');
      // Temp layer will be removed and replaced by state-managed layer in useEffect
    } catch (err) {
      console.log('[SubAreaManager] Error during creation:', err);
      setError(t('digitize.subArea.createFailed'));
      removeTempLayer(); // Remove temp layer on error
    }
  }, [blocks, selectedCategory, subAreas]);

  // Handle sub-area edit (wrapped in useCallback to prevent unnecessary re-renders)
  const handleSubAreaEdit = useCallback((subAreaId: string, geometry: any) => {
    try {
      const area = calculateAreaHectares(geometry);

      // Re-detect block
      const detection = detectBlockForSubArea(geometry, blocks);

      // Calculate block-wise breakdown
      const blockBreakdown = calculateSubAreaByBlock(geometry, blocks);

      setSubAreas(prev =>
        prev.map((subArea) =>
          subArea.id === subAreaId
            ? {
                ...subArea,
                geometry,
                area,
                blockId: detection.blockId,
                blockName: detection.blockName,
                blockBreakdown: blockBreakdown.length > 0 ? blockBreakdown : undefined,
              }
            : subArea
        )
      );
    } catch (err) {
      setError('Failed to update sub-area');
    }
  }, [blocks]);

  // Handle sub-area delete (wrapped in useCallback to prevent unnecessary re-renders)
  const handleSubAreaDelete = useCallback((subAreaId: string) => {
    setSubAreas(prev => prev.filter((s) => s.id !== subAreaId));
    if (selectedSubAreaId === subAreaId) {
      setSelectedSubAreaId(null);
    }
  }, [selectedSubAreaId]);

  // Handle sub-area name change
  const handleSubAreaNameChange = (subAreaId: string, newName: string) => {
    setSubAreas(
      subAreas.map((subArea) =>
        subArea.id === subAreaId ? { ...subArea, name: newName } : subArea
      )
    );
  };

  // Delete selected sub-area
  const handleDeleteSelected = () => {
    if (selectedSubAreaId) {
      handleSubAreaDelete(selectedSubAreaId);
    }
  };

  // Clear all sub-areas
  const handleClearAll = () => {
    if (confirm('Are you sure you want to delete all sub-areas?')) {
      setSubAreas([]);
      setSelectedSubAreaId(null);
    }
  };

  // Filter sub-areas by block
  const filteredSubAreas =
    selectedBlockFilter === 'all'
      ? subAreas
      : subAreas.filter((s) => s.blockId === selectedBlockFilter);

  // Group sub-areas by block
  const subAreasByBlock: Record<string, SubArea[]> = {};
  subAreas.forEach((subArea) => {
    const blockId = subArea.blockId || 'unknown';
    if (!subAreasByBlock[blockId]) {
      subAreasByBlock[blockId] = [];
    }
    subAreasByBlock[blockId].push(subArea);
  });

  // Use helper function that works for both Polygon and MultiPolygon
  const mapCenter = getGeometryCenter(outerBoundary, [27.7172, 85.3240]);

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-bold mb-4">{t('digitize.subArea.title')}</h2>

        <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-md">
          <p className="text-sm text-blue-800">
            <strong>{t('digitize.subArea.instructions')}</strong>
            <br />
            • {t('digitize.subArea.step1')}
            <br />
            • {t('digitize.subArea.step2')}
            <br />
            • {t('digitize.subArea.step3')}
            <br />
            • {t('digitize.subArea.step4')}
            <br />• {t('digitize.subArea.step5')}
          </p>
        </div>

        {/* Category Selection */}
        <div className="mb-4">
          <div className="flex items-center mb-2">
            <label className="block text-sm font-medium text-gray-700">
              {t('digitize.subArea.categoryLabel')}
            </label>
            <HelpTooltip tKey="tooltips.subAreas" position="right" />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {SUB_AREA_CATEGORIES.map((category) => (
              <div key={category.value} className="relative">
                <button
                  onClick={() => setSelectedCategory(category.value)}
                  className={`w-full px-4 py-3 rounded-lg border-2 transition-colors text-left ${
                    selectedCategory === category.value
                      ? 'border-gray-800 bg-gray-100'
                      : 'border-gray-300 hover:border-gray-400'
                  }`}
                  style={{
                    borderLeftWidth: '4px',
                    borderLeftColor: category.color,
                  }}
                >
                  <div className="font-semibold text-sm">{t(category.labelKey)}</div>
                </button>
                {category.value === 'protected' && (
                  <HelpTooltip tKey="tooltips.protectedZone" position="top" />
                )}
                {category.value === 'plantation' && (
                  <HelpTooltip tKey="tooltips.plantationArea" position="top" />
                )}
                {category.value === 'private_land' && (
                  <HelpTooltip tKey="tooltips.privateLand" position="top" />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Slope Regulation Mask Control */}
        <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center">
              <input
                type="checkbox"
                id="showSteepSlope"
                checked={showSteepSlopeMask}
                onChange={(e) => setShowSteepSlopeMask(e.target.checked)}
                className="w-4 h-4 text-amber-600 border-gray-300 rounded focus:ring-amber-500 mr-2"
              />
              <label htmlFor="showSteepSlope" className="text-sm font-medium text-gray-800">
                {t('digitize.subArea.showSlopeMask')}
              </label>
            </div>
            <HelpTooltip 
              helpText={t('digitize.subArea.slopeMaskHelp')}

              position="top" 
            />
          </div>
          
          {showSteepSlopeMask && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-4">
                <label className="text-sm text-gray-700">
                  {t('digitize.subArea.sensitivity')}
                </label>
                <select
                  value={slopeMinClass}
                  onChange={(e) => setSlopeMinClass(Number(e.target.value))}
                  className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:ring-amber-500 focus:border-amber-500"
                >
<option value={4}>{t('digitize.subArea.slope4')}</option>
                <option value={3}>{t('digitize.subArea.slope3')}</option>
                <option value={2}>{t('digitize.subArea.slope2')}</option>
                <option value={1}>{t('digitize.subArea.slope1')}</option>
                </select>
              </div>
              <div className="text-sm text-red-600 font-medium">
                → Displaying: Class {slopeMinClass === 4 ? '4' : `${slopeMinClass}-4`} (and above)
              </div>
            </div>
          )}
        </div>

        {/* Canopy Mask Control */}
        <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <input
                type="checkbox"
                id="showCanopy"
                checked={showCanopyMask}
                onChange={(e) => setShowCanopyMask(e.target.checked)}
                className="w-4 h-4 text-green-600 border-gray-300 rounded focus:ring-green-500 mr-2"
              />
              <label htmlFor="showCanopy" className="text-sm font-medium text-gray-800">
                {t('digitize.subArea.showCanopyMask')}
              </label>
            </div>
            <HelpTooltip 
              helpText={t('digitize.subArea.canopyMaskHelp')}

              position="top" 
            />
          </div>
          {showCanopyMask && (
            <div className="mt-3 space-y-2 pl-1">
              <div className="text-xs font-semibold text-gray-600 mb-1">Legend &amp; Filters:</div>
              <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                <input type="checkbox" checked={canopyShowRed} onChange={(e) => setCanopyShowRed(e.target.checked)} className="w-3 h-3 rounded border-gray-300" />
                <span className="inline-block w-4 h-4 rounded-sm" style={{backgroundColor: 'rgba(255,0,0,0.8)'}}></span>
                <span><strong>Red</strong> — No Canopy (bare ground, water)</span>
              </label>
              <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                <input type="checkbox" checked={canopyShowBlue} onChange={(e) => setCanopyShowBlue(e.target.checked)} className="w-3 h-3 rounded border-gray-300" />
                <span className="inline-block w-4 h-4 rounded-sm" style={{backgroundColor: 'rgba(0,0,255,0.8)'}}></span>
                <span><strong>Blue</strong> — Low Canopy (1-15m)</span>
              </label>
              <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                <input type="checkbox" checked={canopyShowGreen} onChange={(e) => setCanopyShowGreen(e.target.checked)} className="w-3 h-3 rounded border-gray-300" />
                <span className="inline-block w-4 h-4 rounded-sm" style={{backgroundColor: 'rgba(0,255,0,0.8)'}}></span>
                <span><strong>{t('digitize.subArea.legendGreen')}</strong> — {t('digitize.subArea.legendTallCanopy')}</span>
              </label>
            </div>
          )}
        </div>

        {/* Error Messages */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md">
            {error}
          </div>
        )}

        {/* Excluded Area Summary (Private Land) */}
        {subAreas.some(s => s.isExcluded) && (
          <div className="mb-4 p-4 bg-red-50 border-2 border-red-300 rounded-lg">
            <h3 className="font-semibold text-red-900 mb-2">{t('digitize.subArea.privateLandTitle')}</h3>
            <div className="text-sm text-red-800">
              <p className="mb-2">
                These areas are <strong>NOT part of the community forest</strong> and will be excluded from all calculations,
                sampling, and forest management activities.
              </p>
              <p className="font-semibold">
                Total Excluded Area: {formatArea(subAreas.filter(s => s.isExcluded).reduce((sum, s) => sum + s.area, 0))}
              </p>
            </div>
          </div>
        )}

        {/* Sub-areas Summary by Block */}
        {Object.keys(subAreasByBlock).length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold mb-2">{t('digitize.subArea.byBlock')}</h3>
            <div className="space-y-2">
              {Object.entries(subAreasByBlock).map(([blockId, blockSubAreas]) => {
                const block = blocks.find((b) => b.id === blockId);
                const blockName = block?.name || t('digitize.subArea.unknownBlock');
                const blockArea = block?.area || 0;
                // Only count non-excluded sub-areas
                const includedSubAreas = blockSubAreas.filter(s => !s.isExcluded);
                const excludedSubAreas = blockSubAreas.filter(s => s.isExcluded);
                const subAreasTotal = includedSubAreas.reduce((sum, s) => sum + s.area, 0);
                const excludedTotal = excludedSubAreas.reduce((sum, s) => sum + s.area, 0);
                const percentage = blockArea > 0 ? (subAreasTotal / blockArea) * 100 : 0;

                return (
                  <div key={blockId} className="p-3 bg-gray-50 border border-gray-200 rounded">
                    <div className="flex justify-between items-center">
                      <div>
                        <strong>{blockName}</strong>
                        <span className="ml-2 text-sm text-gray-600">
                          ({includedSubAreas.length} sub-areas
                          {excludedSubAreas.length > 0 && `, ${excludedSubAreas.length} excluded`})
                        </span>
                      </div>
                      <div className="text-sm">
                        <div>
                          <span className={percentage > 100 ? 'text-red-600 font-semibold' : 'text-gray-700'}>
                            {formatArea(subAreasTotal)} / {formatArea(blockArea)}
                          </span>
                          <span className="ml-2 text-gray-500">({percentage.toFixed(1)}%)</span>
                        </div>
                        {excludedTotal > 0 && (
                          <div className="text-xs text-red-600 mt-1">
                            Excluded: -{formatArea(excludedTotal)}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Sub-areas List */}
        {subAreas.length > 0 && (
          <div className="mb-4">
            <div className="flex justify-between items-center mb-2">
              <h3 className="font-semibold">Sub-areas ({subAreas.length})</h3>
              <div className="flex gap-2">
                <select
                  value={selectedBlockFilter}
                  onChange={(e) => setSelectedBlockFilter(e.target.value)}
                  className="px-3 py-1 text-sm border border-gray-300 rounded"
                >
                  <option value="all">{t('digitize.subArea.allBlocks')}</option>
                  {blocks.map((block) => (
                    <option key={block.id} value={block.id}>
                      {block.name}
                    </option>
                  ))}
                </select>
                {selectedSubAreaId && (
                  <button
                    onClick={handleDeleteSelected}
                    className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                  >
                    {t('digitize.subArea.deleteSelected')}
                  </button>
                )}
                <button
                  onClick={handleClearAll}
                  className="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700"
                >
                  {t('digitize.subArea.clearAll')}
                </button>
              </div>
            </div>

            <div className="max-h-96 overflow-y-auto border border-gray-200 rounded">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.subArea.colName')}</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.subArea.colCategory')}</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.subArea.colBlock')}</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.subArea.colArea')}</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.subArea.colActions')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {filteredSubAreas.map((subArea) => {
                    const category = SUB_AREA_CATEGORIES.find(c => c.value === subArea.category);
                    return (
                      <tr
                        key={subArea.id}
                        className={`hover:bg-gray-50 cursor-pointer ${
                          selectedSubAreaId === subArea.id ? 'bg-blue-50' : ''
                        }`}
                        onClick={() => setSelectedSubAreaId(subArea.id)}
                      >
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            value={subArea.name}
                            onChange={(e) =>
                              handleSubAreaNameChange(subArea.id, e.target.value)
                            }
                            onClick={(e) => e.stopPropagation()}
                            className="w-full px-2 py-1 border border-gray-300 rounded text-sm"
                          />
                        </td>
                        <td className="px-3 py-2 text-sm">
                          <div className="flex items-center">
                            <div
                              className="w-3 h-3 rounded-full mr-2"
                              style={{ backgroundColor: category?.color }}
                            />
                            {category ? t(category.labelKey) : subArea.category}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-sm">
                          {subArea.blockBreakdown && subArea.blockBreakdown.length > 1 ? (
                            <div className="text-xs">
                              <div className="font-medium text-orange-600 mb-1">Spans {subArea.blockBreakdown.length} blocks:</div>
                              {subArea.blockBreakdown.map((bd, idx) => (
                                <div key={idx} className="text-gray-700">
                                  • {bd.blockName}: {formatArea(bd.area)} ({bd.percentage.toFixed(0)}%)
                                </div>
                              ))}
                            </div>
                          ) : (
                            subArea.blockName || t('digitize.subArea.unknown')
                          )}
                        </td>
                        <td className="px-3 py-2 text-sm">
                          {formatArea(subArea.area)}
                          {subArea.blockBreakdown && subArea.blockBreakdown.length > 1 && (
                            <span className="text-xs text-gray-500 block">{t('digitize.subArea.total')}</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSubAreaDelete(subArea.id);
                            }}
                            className="text-red-600 hover:text-red-800 text-sm"
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Map */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">{t('digitize.subArea.map')}</h3>

        {/* Legend */}
        <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded">
          <div className="text-sm font-semibold mb-2">{t('digitize.subArea.legend')}</div>
          <div className="flex flex-wrap gap-3">
            {SUB_AREA_CATEGORIES.map((category) => (
              <div key={category.value} className="flex items-center">
                <div
                  className="w-4 h-4 rounded mr-2"
                  style={{ backgroundColor: category.color }}
                />
                <span className="text-sm">{t(category.labelKey)}</span>
              </div>
            ))}
            <div className="flex items-center ml-4 pl-4 border-l border-gray-300">
              <div
                className="w-4 h-4 rounded mr-2 border-2"
                style={{ 
                  backgroundColor: 'transparent',
                  borderColor: '#1d4ed8',
                  borderStyle: 'solid',
                }}
              />
              <span className="text-sm text-blue-700">{t('digitize.subArea.legendBoundary')}</span>
            </div>
            {showSteepSlopeMask && (
              <div className="flex items-center ml-4 pl-4 border-l border-gray-300">
                <div
                  className="w-4 h-4 rounded mr-2"
                  style={{ backgroundColor: '#e74c3c' }}
                />
                <span className="text-sm text-red-700">Steep Slope (&gt;{slopeMinClass}°)</span>
              </div>
            )}
          </div>
        </div>

        <div className="h-[600px] rounded overflow-hidden border border-gray-300 relative">
          <MapContainer
            center={mapCenter as [number, number]}
            zoom={14}
            style={{ height: '100%', width: '100%' }}
          >
            <BaseMapSelector />
            <NumericScale />

            {/* Slope Regulation Mask Layer - shows sensitive areas in red */}
            {/* H2.4 / S1-04: tiles are owner-gated; the token rides in the URL
                because Leaflet fetches them as <img>, which sends no headers. */}
            {showSteepSlopeMask && calculationId && tileToken && (
              <TileLayer
                url={withTileToken(`/api/calculations/${calculationId}/steep-slope-mask/{z}/{x}/{y}.png?threshold=${slopeMinClass}&alpha=150`, tileToken)!}
                opacity={0.7}
                zIndex={5}
                minZoom={13}
                maxZoom={20}
              />
            )}

            {/* Canopy Mask Layer - clipped to forest boundary with color filters */}
            {showCanopyMask && calculationId && tileToken && (
              <TileLayer
                url={withTileToken(`/api/calculations/${calculationId}/canopy-mask/{z}/{x}/{y}.png?alpha=150&red=${canopyShowRed}&blue=${canopyShowBlue}&green=${canopyShowGreen}`, tileToken)!}
                opacity={0.7}
                zIndex={5}
                minZoom={13}
                maxZoom={20}
              />
            )}

            {/* Blocks */}
            {blocks.map((block) => (
              <GeoJSON
                key={block.id}
                data={block.geometry}
                style={{
                  color: '#3b82f6',
                  weight: 2,
                  fillOpacity: 0.05,
                  dashArray: '5, 5',
                }}
              />
            ))}

            {/* Drawing controls */}
            <SubAreaDrawingControls
              blocks={blocks}
              outerBoundary={outerBoundary}
              selectedCategory={selectedCategory}
              onSubAreaCreated={handleSubAreaCreated}
              subAreas={subAreas}
              selectedSubAreaId={selectedSubAreaId}
              onSubAreaEdit={handleSubAreaEdit}
              onSubAreaDelete={handleSubAreaDelete}
              onLiveAreaChange={setLiveArea}
              onSubAreaSelect={setSelectedSubAreaId}
            />
          </MapContainer>

            {/* Live Area Label - shown during polygon drawing */}
            {liveArea > 0 && (
              <div
                style={{
                  position: 'absolute',
                  top: 10,
                  right: 10,
                  zIndex: 1000,
                  backgroundColor: 'rgba(255, 255, 255, 0.95)',
                  padding: '8px 12px',
                  borderRadius: 4,
                  boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
                  fontSize: '14px',
                  fontWeight: 600,
                  color: '#1f2937',
                  border: '2px solid #3b82f6',
                }}
              >
                {formatLiveArea(liveArea, t)}
              </div>
            )}
        </div>

        {/* Status Bar */}
        {selectedSubAreaId && (() => {
          const sa = subAreas.find(s => s.id === selectedSubAreaId);
          if (!sa) return null;
          const category = SUB_AREA_CATEGORIES.find(c => c.value === sa.category);
          const isExcluded = sa.isExcluded || false;
          return (
            <div style={{
              backgroundColor: 'rgba(31, 41, 55, 0.85)',
              color: '#e5e7eb',
              padding: '6px 16px',
              fontSize: '13px',
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
              minHeight: '32px',
              borderRadius: '0 0 8px 8px',
              backdropFilter: 'blur(4px)',
              marginTop: '4px',
            }}>
              <span style={{ fontWeight: 600, color: '#ffffff' }}>{sa.name}</span>
              <span style={{ color: category?.color || '#9ca3af' }}>●</span>
              <span>{category ? t(category.labelKey) : sa.category}</span>
              <span style={{ color: '#9ca3af' }}>|</span>
              <span>Area: {formatArea(sa.area)}</span>
              <span style={{ color: '#9ca3af' }}>|</span>
              <span>{t('digitize.subArea.blockLabel')} {sa.blockName || t('digitize.subArea.unknown')}</span>
              {isExcluded && (
                <span style={{ color: '#f87171', fontWeight: 600 }}>EXCLUDED FROM FOREST</span>
              )}
            </div>
          );
        })()}
      </div>
    </div>
  );
};

export default SubAreaManager;
