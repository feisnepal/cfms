/**
 * AnalysisTab -- the "analysis" context of a calculation.
 *
 * Charts / key-metrics / whole-forest & block edit forms come from <AnalysisTabContent>;
 * this wrapper adds the detailed block-wise tables, additional-info block, geometry
 * warning, the A5 boundary map and the partitioned-processing banner.
 *
 * Extracted verbatim from pages/CalculationDetail.tsx (Single Workspace A2) so the
 * tabbed shell can render forest-data > analysis directly. Accepts a `calculation`
 * from a parent that already has it (legacy page); self-fetches when given only an id
 * (tabbed shell). Mutations are optimistic; `onDataChanged` lets the parent refetch.
 */
import { useEffect, useState, useCallback } from 'react';
import { forestApi } from '../../services/api';
import { EditableCell } from '../EditableCell';
import AnalysisTabContent from '../AnalysisTabContent';
import FertilityBadge from '../FertilityBadge';
import { RasterLayerControl } from '../RasterLayerControl';
import { RasterClickInfo } from '../RasterClickInfo';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useDimensionLabels, hasCompartmentsFromResultData, analysisUnitKey } from '../../hooks/useDimensionLabels';

// Validate GeoJSON geometry structure
function isValidGeoJSON(geometry: any): boolean {
  if (!geometry || typeof geometry !== 'object') {
    if (import.meta.env.DEV) console.error('Geometry validation failed: not an object', geometry);
    return false;
  }

  if (!geometry.type) {
    if (import.meta.env.DEV) console.error('Geometry validation failed: missing type', geometry);
    return false;
  }

  const validTypes = ['Point', 'LineString', 'Polygon', 'MultiPoint', 'MultiLineString', 'MultiPolygon', 'GeometryCollection', 'Feature', 'FeatureCollection'];
  if (!validTypes.includes(geometry.type)) {
    if (import.meta.env.DEV) console.error('Geometry validation failed: invalid type', geometry.type);
    return false;
  }

  if (!geometry.coordinates && geometry.type !== 'GeometryCollection' && geometry.type !== 'Feature' && geometry.type !== 'FeatureCollection') {
    if (import.meta.env.DEV) console.error('Geometry validation failed: missing coordinates', geometry);
    return false;
  }

  return true;
}

// Component to handle auto-zoom to layer and add scale control
function ZoomToLayer({
  geometry,
  setMapInstance,
  orientation
}: {
  geometry: any;
  setMapInstance: (map: L.Map) => void;
  orientation: 'portrait' | 'landscape';
}) {
  const map = useMap();

  useEffect(() => {
    // Store map instance for external use
    setMapInstance(map);

    // Remove any existing scale controls first
    map.eachLayer((layer: any) => {
      if (layer instanceof L.Control.Scale) {
        map.removeControl(layer);
      }
    });

    // Add single scale control (bottom-left)
    const scaleControl = L.control.scale({
      position: 'bottomleft',
      metric: true,
      imperial: false,
      maxWidth: 150
    });
    scaleControl.addTo(map);

    // Auto-zoom to layer on initial load - same behavior for both orientations
    if (geometry && isValidGeoJSON(geometry)) {
      try {
        const geoJsonLayer = L.geoJSON(geometry);
        const bounds = geoJsonLayer.getBounds();
        if (bounds.isValid()) {
          // Use same padding for both portrait and landscape for consistent zoom behavior
          const padding = [50, 50] as [number, number];

          map.fitBounds(bounds, { padding });
        }
      } catch (error) {
        if (import.meta.env.DEV) console.error('Error creating GeoJSON layer for zoom:', error);
      }
    }

    // Cleanup function
    return () => {
      if (map && scaleControl) {
        map.removeControl(scaleControl);
      }
    };
  }, [geometry, map, setMapInstance, orientation]);

  return null;
}

// North Arrow Component - Points upward (North)
function NorthArrow() {
  return (
    <div className="absolute top-4 right-4 z-[1000] bg-white rounded-lg shadow-lg p-2 border border-gray-300">
      <div className="flex flex-col items-center">
        <div className="text-sm font-bold text-gray-800 mb-1">N</div>
        <svg width="30" height="50" viewBox="0 0 30 60">
          {/* Arrow shaft */}
          <line x1="15" y1="10" x2="15" y2="50" stroke="#333" strokeWidth="2"/>
          {/* North half (dark/filled) pointing UP */}
          <polygon points="15,5 10,20 15,18 20,20" fill="#1a1a1a" stroke="#000" strokeWidth="1"/>
          {/* South half (white/outline) pointing DOWN */}
          <polygon points="15,18 10,20 15,50 20,20" fill="#ffffff" stroke="#000" strokeWidth="1"/>
        </svg>
      </div>
    </div>
  );
}

interface AnalysisTabProps {
  calculationId: string;
  /** supplied by the legacy page which already holds the calculation */
  calculation?: any;
  /** called after a successful mutation so a parent can refetch */
  onDataChanged?: () => void;
}

export default function AnalysisTab({ calculationId, calculation: calcProp, onDataChanged }: AnalysisTabProps) {
  const [calc, setCalc] = useState<any>(calcProp ?? null);
  const [subAreas, setSubAreas] = useState<any[]>([]);
  const [loading, setLoading] = useState(!calcProp);
  const [geometryError, setGeometryError] = useState<string | null>(null);
  const [mapInstance, setMapInstance] = useState<L.Map | null>(null);
  const [mapOrientation, setMapOrientation] = useState<'portrait' | 'landscape'>('portrait');
  const [boundaryVisible, setBoundaryVisible] = useState(true);
  const [basemap, setBasemap] = useState<'satellite' | 'osm' | 'terrain' | 'none'>('satellite');
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set());
  const [renamingBlockId, setRenamingBlockId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  // keep local copy in sync when the parent hands down a fresh calculation
  useEffect(() => { if (calcProp) setCalc(calcProp); }, [calcProp]);

  // self-fetch when only an id was supplied (tabbed shell path)
  useEffect(() => {
    if (calcProp || !calculationId) return;
    let cancelled = false;
    setLoading(true);
    forestApi.getCalculation(calculationId)
      .then((data: any) => { if (!cancelled) setCalc(data); })
      .catch(() => { if (!cancelled) setCalc(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [calculationId, calcProp]);

  // sub-areas power AnalysisTabContent + the block-rename sync
  useEffect(() => {
    if (!calculationId) return;
    let cancelled = false;
    forestApi.listSubAreas(calculationId)
      .then((data: any) => { if (!cancelled) setSubAreas(data.sub_areas || []); })
      .catch(() => { if (!cancelled) setSubAreas([]); });
    return () => { cancelled = true; };
  }, [calculationId]);

  const refresh = useCallback(() => {
    onDataChanged?.();
    if (!calcProp && calculationId) {
      forestApi.getCalculation(calculationId).then((d: any) => setCalc(d)).catch(() => {});
      forestApi.listSubAreas(calculationId).then((d: any) => setSubAreas(d.sub_areas || [])).catch(() => {});
    }
  }, [onDataChanged, calcProp, calculationId]);

  const hasCompartments = hasCompartmentsFromResultData(calc?.result_data as Record<string, unknown> | null | undefined);
  const labels = useDimensionLabels({ hasCompartments });

  // optimal map orientation + geometry validity (moved from CalculationDetail)
  // Calculate optimal map orientation based on geometry extent
  useEffect(() => {
    if (calc?.geometry) {
      // First validate the geometry structure
      if (!isValidGeoJSON(calc.geometry)) {
        const errorMsg = 'The boundary geometry data is in an invalid format. The map may not display correctly.';
        if (import.meta.env.DEV) console.error('Invalid GeoJSON structure detected for calc:', calc.id);
        if (import.meta.env.DEV) console.error('Geometry data:', calc.geometry);
        setGeometryError(errorMsg);
        setMapOrientation('portrait');
        return;
      }

      try {
        const geoJsonLayer = L.geoJSON(calc.geometry);
        const bounds = geoJsonLayer.getBounds();

        if (bounds.isValid()) {
          const width = bounds.getEast() - bounds.getWest();
          const height = bounds.getNorth() - bounds.getSouth();

          // If width > height, use landscape; otherwise portrait
          const orientation = width > height ? 'landscape' : 'portrait';
          setMapOrientation(orientation);
          setGeometryError(null); // Clear any previous errors
          if (import.meta.env.DEV) console.log('Geometry loaded successfully, orientation:', orientation);
        } else {
          if (import.meta.env.DEV) console.warn('Invalid geometry bounds for calc');
          setGeometryError('The boundary has invalid geographic bounds.');
          setMapOrientation('portrait');
        }
      } catch (error) {
        const errorMsg = `Error processing boundary geometry: ${error instanceof Error ? error.message : 'Unknown error'}`;
        if (import.meta.env.DEV) console.error('Error processing geometry:', error);
        if (import.meta.env.DEV) console.error('Problematic geometry:', JSON.stringify(calc.geometry));
        setGeometryError(errorMsg);
        setMapOrientation('portrait');
      }
    }
  }, [calc]);

  if (loading) {
    return <div className="p-6 text-gray-500">Loading analysis...</div>;
  }
  if (!calc) {
    return <div className="p-6 text-red-600">Analysis data is not available for this calculation.</div>;
  }

  // Compartment-mode forests analyse per compartment; the backend writes those
  // to result_data.compartments (PolygonSource). Show the SAME units here.
  const unitKey = analysisUnitKey(calc.result_data as Record<string, unknown> | null | undefined);
  const blocks = calc.result_data?.[unitKey] || [];
  const totalBlocks =
    calc.result_data?.[unitKey === 'compartments' ? 'total_compartments' : 'total_blocks'] ||
    blocks.length ||
    1;
  const processingInfo: any = calc.result_data?.processing_info || {};

  const getStatusBadge = (status: string) => {
    const styles = {
      processing: 'bg-yellow-100 text-yellow-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
    };
    return styles[status as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  const formatDate = (dateString: string) => new Date(dateString).toLocaleString();

  const handleZoomToLayer = () => {
    if (calc?.geometry && mapInstance) {
      const geoJsonLayer = L.geoJSON(calc.geometry);
      const bounds = geoJsonLayer.getBounds();
      if (bounds.isValid()) {
        mapInstance.fitBounds(bounds, { padding: [50, 50] as [number, number] });
      }
    }
  };

  // Handler to save a whole-forest field
  const handleSaveWholeForest = async (key: string, newValue: string) => {
    const numericKeys = [
      'elevation_mean_m', 'elevation_min_m', 'elevation_max_m',
      'temperature_mean_c', 'temperature_min_c',
      'precipitation_mean_mm',
      'agb_total_mg', 'agb_mean_mg_ha', 'carbon_stock_mg',
      'forest_loss_hectares', 'forest_gain_hectares', 'fire_loss_hectares',
      'canopy_mean_m', 'area_hectares', 'area_sqm'
    ];
    const val: any = numericKeys.includes(key) ? parseFloat(newValue) : newValue;
    await forestApi.updateResultData(calc.id, { [key]: val });
    setCalc((prev: any) => prev ? {
      ...prev,
      result_data: { ...prev.result_data, [key]: val }
    } : prev);
    onDataChanged?.();
  };

  // Handler to save a block-level field
  const handleSaveBlock = async (blockIndex: number, key: string, newValue: string) => {
    const numericKeys = [
      'elevation_mean_m', 'elevation_min_m', 'elevation_max_m',
      'temperature_mean_c', 'temperature_min_c',
      'precipitation_mean_mm',
      'agb_total_mg', 'agb_mean_mg_ha', 'carbon_stock_mg',
      'forest_loss_hectares', 'forest_gain_hectares', 'fire_loss_hectares',
      'canopy_mean_m', 'area_hectares', 'area_sqm'
    ];
    const val: any = numericKeys.includes(key) ? parseFloat(newValue) : newValue;
    const updatedBlocks = [...(calc.result_data?.[unitKey] || [])];
    updatedBlocks[blockIndex] = { ...updatedBlocks[blockIndex], [key]: val };
    await forestApi.updateResultData(calc.id, { [unitKey]: updatedBlocks });
    setCalc((prev: any) => prev ? {
      ...prev,
      result_data: { ...prev.result_data, [unitKey]: updatedBlocks }
    } : prev);
    onDataChanged?.();
  };

  // Handler to save a block extent field
  const handleSaveBlockExtent = async (blockIndex: number, direction: string, newValue: string) => {
    const val = parseFloat(newValue);
    const updatedBlocks = [...(calc.result_data?.[unitKey] || [])];
    updatedBlocks[blockIndex] = {
      ...updatedBlocks[blockIndex],
      extent: { ...updatedBlocks[blockIndex].extent!, [direction]: val }
    };
    await forestApi.updateResultData(calc.id, { [unitKey]: updatedBlocks });
    setCalc((prev: any) => prev ? {
      ...prev,
      result_data: { ...prev.result_data, [unitKey]: updatedBlocks }
    } : prev);
    onDataChanged?.();
  };

  // Handler to save whole forest extent field
  const handleSaveWholeExtent = async (direction: string, newValue: string) => {
    const val = parseFloat(newValue);
    const updatedExtent = { ...(calc.result_data?.whole_forest_extent ?? {}), [direction]: val } as { N: number; S: number; E: number; W: number };
    await forestApi.updateResultData(calc.id, { whole_forest_extent: updatedExtent });
    setCalc((prev: any) => prev ? {
      ...prev,
      result_data: { ...prev.result_data, whole_forest_extent: updatedExtent }
    } : prev);
    onDataChanged?.();
  };

  // Handler to save whole forest percentages
  const handleSaveWholePercentages = async (key: string, className: string, newValue: string) => {
    const val = parseFloat(newValue);
    const updatedPercentages = { ...(calc.result_data as Record<string, unknown> | undefined)?.[key] as Record<string, number> | undefined, [className]: val };
    await forestApi.updateResultData(calc.id, { [key]: updatedPercentages });
    setCalc((prev: any) => prev ? {
      ...prev,
      result_data: { ...prev.result_data, [key]: updatedPercentages }
    } : prev);
    onDataChanged?.();
  };

  // Handler to save block percentages
  const handleSaveBlockPercentages = async (blockIndex: number, key: string, className: string, newValue: string) => {
    const val = parseFloat(newValue);
    const updatedBlocks = [...(calc.result_data?.[unitKey] || [])];
    updatedBlocks[blockIndex] = {
      ...updatedBlocks[blockIndex],
      [key]: { ...updatedBlocks[blockIndex][key as keyof typeof updatedBlocks[number]], [className]: val }
    };
    await forestApi.updateResultData(calc.id, { [unitKey]: updatedBlocks });
    setCalc((prev: any) => prev ? {
      ...prev,
      result_data: { ...prev.result_data, [unitKey]: updatedBlocks }
    } : prev);
    onDataChanged?.();
  };

  // Handle block rename
  const handleRenameBlock = async (block: any) => {
    if (!renameValue.trim() || !renamingBlockId) return;
    const newName = renameValue.trim();
    const oldName = block.block_name;
    const blockId = block.block_id;
    try {
      if (blockId) {
        await forestApi.updateBlock(calc.id, blockId, newName);
      }
      // Update local blocks array
      const updatedBlocks = [...blocks];
      const idx = updatedBlocks.findIndex((b: any) =>
        b.block_id ? b.block_id === renamingBlockId : b.block_name === renamingBlockId
      );
      if (idx >= 0) {
        updatedBlocks[idx] = { ...updatedBlocks[idx], block_name: newName };
      }
      // Sync sub-areas that reference this block (match by ID or name)
      const renameInSubArea = (sa: any) => {
        const updated = { ...sa };
        const matchBlock = (ref: any) =>
          (blockId && ref.blockId === blockId) || ref.blockName === oldName || ref.block_name === oldName;
        if (matchBlock(sa)) {
          if (sa.blockId === blockId || sa.blockName === oldName) updated.blockName = newName;
          if (sa.block_name === oldName) updated.block_name = newName;
        }
        if (sa.blockBreakdown) {
          updated.blockBreakdown = sa.blockBreakdown.map((bb: any) =>
            matchBlock(bb) ? { ...bb, blockName: newName, block_name: newName } : bb
          );
        }
        return updated;
      };
      setCalc((prev: any) => {
        if (!prev) return prev;
        const rd = { ...prev.result_data, [unitKey]: updatedBlocks };
        if (rd.sub_areas) rd.sub_areas = rd.sub_areas.map(renameInSubArea);
        return { ...prev, result_data: rd };
      });
      setSubAreas(prev => prev.map(renameInSubArea));
      onDataChanged?.();
    } catch (err: any) {
      if (import.meta.env.DEV) console.error('Failed to rename block:', err);
    }
    setRenamingBlockId(null);
    setRenameValue('');
  };

  return (
    <div className="analysis-tab">
      <AnalysisTabContent
        calculation={calc}
        blocks={blocks}
        subAreas={subAreas}
        totalBlocks={totalBlocks}
        handleSaveWholeForest={handleSaveWholeForest}
        handleSaveWholeExtent={handleSaveWholeExtent}
        handleSaveWholePercentages={handleSaveWholePercentages}
        handleSaveBlockExtent={handleSaveBlockExtent}
        handleSaveBlockField={handleSaveBlock}
        handleSaveBlockPercentages={handleSaveBlockPercentages}
        onRefresh={refresh}
      />

        {/* Detailed Block-wise Analysis */}
        {blocks.length > 0 && (
          <div className="p-6 border-t border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900 mb-6">Detailed {labels.unitLabel}-wise Analysis</h2>
            <div className="space-y-6">
              {blocks.map((block: any, index: number) => (
                <div key={index} className="border border-gray-300 rounded-lg bg-white shadow-sm">
                  {/* Block Header */}
                  <div className="bg-gradient-to-r from-green-50 to-green-100 px-6 py-4 border-b border-gray-200">
                    <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                      <span>{labels.unitLabel} #{index + 1}:</span>
                      {renamingBlockId === (block.block_id || `detail-${index}`) ? (
                        <input
                          type="text"
                          value={renameValue}
                          onChange={e => setRenameValue(e.target.value)}
                          onBlur={() => handleRenameBlock(block)}
                          onKeyDown={e => { if (e.key === 'Enter') handleRenameBlock(block); if (e.key === 'Escape') { setRenamingBlockId(null); setRenameValue(''); } }}
                          className="w-48 px-2 py-0.5 text-base border border-green-400 rounded focus:outline-none focus:ring-1 focus:ring-green-500"
                          autoFocus
                          onClick={e => e.stopPropagation()}
                        />
                      ) : (
                        <>
                          <span>{block.block_name}</span>
                          <button
                            onClick={() => { setRenamingBlockId(block.block_id || `detail-${index}`); setRenameValue(block.block_name); }}
                            className="p-1 text-gray-400 hover:text-green-600 transition-colors"
                            title="Rename block"
                          >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                            </svg>
                          </button>
                        </>
                      )}
                    </h3>
                    <p className="text-sm text-gray-600 mt-1">
                      Area: {parseFloat(block.area_hectares || 0).toFixed(2)} hectares
                      {block.excluded_area_hectares > 0 && (
                        <span className="text-red-600">
                          {' '}(Net: {parseFloat(block.effective_area_hectares || 0).toFixed(2)} ha, Excluded: {parseFloat(block.excluded_area_hectares || 0).toFixed(2)} ha)
                        </span>
                      )}
                    </p>
                  </div>

                  {/* Block Analysis Table */}
                  <div className="p-6">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Parameter</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Value</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Details</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {/* Extent */}
                        {block.extent && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Extent</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono" colSpan={2}>
                              <EditableCell value={block.extent.N} displayValue={"N: " + block.extent.N.toFixed(7)} onSave={(v) => handleSaveBlockExtent(index, 'N', v)} className="font-mono" />{", "}
                              <EditableCell value={block.extent.S} displayValue={"S: " + block.extent.S.toFixed(7)} onSave={(v) => handleSaveBlockExtent(index, 'S', v)} className="font-mono" />{", "}
                              <EditableCell value={block.extent.E} displayValue={"E: " + block.extent.E.toFixed(7)} onSave={(v) => handleSaveBlockExtent(index, 'E', v)} className="font-mono" />{", "}
                              <EditableCell value={block.extent.W} displayValue={"W: " + block.extent.W.toFixed(7)} onSave={(v) => handleSaveBlockExtent(index, 'W', v)} className="font-mono" />
                            </td>
                          </tr>
                        )}

                        {/* Elevation */}
                        {block.elevation_mean_m !== undefined && block.elevation_mean_m !== null && block.elevation_mean_m > -32000 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Elevation</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.elevation_mean_m} displayValue={block.elevation_mean_m.toFixed(1) + " m (mean)"} onSave={(v) => handleSaveBlock(index, 'elevation_mean_m', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              Min: <EditableCell value={block.elevation_min_m} displayValue={block.elevation_min_m?.toFixed(0)} onSave={(v) => handleSaveBlock(index, 'elevation_min_m', v)} />{" m, Max: "}
                              <EditableCell value={block.elevation_max_m} displayValue={block.elevation_max_m?.toFixed(0)} onSave={(v) => handleSaveBlock(index, 'elevation_max_m', v)} />{" m"}
                            </td>
                          </tr>
                        )}

                        {/* Slope */}
                        {block.slope_dominant_class && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Slope</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.slope_dominant_class} onSave={(v) => handleSaveBlock(index, 'slope_dominant_class', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.slope_percentages &&
                                Object.entries(block.slope_percentages).map(([cls, pct]: [string, any], idx: number) => (
                                  <span key={cls}>
                                    {cls}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'slope_percentages', cls, v)} className="inline" />
                                    {idx < Object.keys(block.slope_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Aspect */}
                        {block.aspect_dominant && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Aspect</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize font-semibold">
                              <EditableCell value={block.aspect_dominant} onSave={(v) => handleSaveBlock(index, 'aspect_dominant', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.aspect_percentages &&
                                Object.entries(block.aspect_percentages).map(([dir, pct]: [string, any], idx: number) => (
                                  <span key={dir}>
                                    {dir}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'aspect_percentages', dir, v)} className="inline" />
                                    {idx < Object.keys(block.aspect_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Canopy Height */}
                        {block.canopy_dominant_class && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Canopy Structure</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.canopy_dominant_class} onSave={(v) => handleSaveBlock(index, 'canopy_dominant_class', v)} />
                              {block.canopy_mean_m !== undefined && (
                                <span className="text-xs text-gray-500 ml-2">
                                  (<EditableCell value={block.canopy_mean_m} displayValue={block.canopy_mean_m.toFixed(1)} onSave={(v) => handleSaveBlock(index, 'canopy_mean_m', v)} />m avg)
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.canopy_percentages &&
                                Object.entries(block.canopy_percentages).map(([cls, pct]: [string, any], idx: number) => (
                                  <span key={cls}>
                                    {cls.replace('_', ' ')}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'canopy_percentages', cls, v)} className="inline" />
                                    {idx < Object.keys(block.canopy_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Above Ground Biomass */}
                        {block.agb_total_mg !== undefined && block.agb_total_mg !== null && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Above Ground Biomass</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.agb_total_mg} displayValue={block.agb_total_mg.toLocaleString() + " Mg"} onSave={(v) => handleSaveBlock(index, 'agb_total_mg', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              <EditableCell value={block.agb_mean_mg_ha} displayValue={block.agb_mean_mg_ha?.toFixed(2)} onSave={(v) => handleSaveBlock(index, 'agb_mean_mg_ha', v)} /> Mg/ha (mean per hectare)
                            </td>
                          </tr>
                        )}

                        {/* Carbon Stock */}
                        {block.carbon_stock_mg !== undefined && block.carbon_stock_mg !== null && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Carbon Stock</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.carbon_stock_mg} displayValue={block.carbon_stock_mg.toLocaleString() + " Mg"} onSave={(v) => handleSaveBlock(index, 'carbon_stock_mg', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              50% of total biomass
                            </td>
                          </tr>
                        )}

                        {/* Forest Health */}
                        {block.forest_health_dominant && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Forest Health</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.forest_health_dominant} onSave={(v) => handleSaveBlock(index, 'forest_health_dominant', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.forest_health_percentages &&
                                Object.entries(block.forest_health_percentages).map(([cls, pct]: [string, any], idx: number) => (
                                  <span key={cls}>
                                    {cls}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'forest_health_percentages', cls, v)} className="inline" />
                                    {idx < Object.keys(block.forest_health_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Forest Type */}
                        {block.forest_type_dominant && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Forest Type</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.forest_type_dominant} onSave={(v) => handleSaveBlock(index, 'forest_type_dominant', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.forest_type_percentages &&
                                Object.entries(block.forest_type_percentages).map(([type, pct]: [string, any], idx: number) => (
                                  <span key={type}>
                                    {type}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'forest_type_percentages', type, v)} className="inline" />
                                    {idx < Object.keys(block.forest_type_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Potential Tree Species */}
                        {block.potential_species && block.potential_species.length > 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Potential Tree Species</td>
                            <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                              <div className="flex flex-wrap gap-2">
                                {(() => {
                                  const blockKey = `block-${index}`;
                                  const isExpanded = expandedBlocks.has(blockKey);
                                  const speciesToShow = isExpanded ? block.potential_species : block.potential_species.slice(0, 8);

                                  return (
                                    <>
                                      {speciesToShow.map((species: any, speciesIdx: number) => (
                                        <div
                                          key={speciesIdx}
                                          className="inline-flex items-center rounded-md px-2 py-1 text-xs bg-green-50 border border-green-300 transition-all"
                                        >
                                          <span className="font-semibold text-green-900">{species.local_name}</span>
                                          <span className="ml-1 text-gray-500 italic">
                                            ({species.scientific_name})
                                          </span>
                                          {species.economic_value === 'High' && (
                                            <span className="ml-1 px-1 py-0.5 bg-green-200 text-green-800 rounded text-xs">$$</span>
                                          )}
                                          {species.economic_value === 'Medium' && (
                                            <span className="ml-1 px-1 py-0.5 bg-yellow-200 text-yellow-800 rounded text-xs">$</span>
                                          )}
                                        </div>
                                      ))}
                                      {block.potential_species.length > 8 && (
                                        <button
                                          onClick={(e) => {
                                            e.stopPropagation();
                                            setExpandedBlocks(prev => {
                                              const newSet = new Set(prev);
                                              if (isExpanded) {
                                                newSet.delete(blockKey);
                                              } else {
                                                newSet.add(blockKey);
                                              }
                                              return newSet;
                                            });
                                          }}
                                          className="text-xs text-blue-600 hover:text-blue-800 underline cursor-pointer italic"
                                        >
                                          {isExpanded
                                            ? '▲ Show less'
                                            : `▼ +${block.potential_species.length - 8} more species`}
                                        </button>
                                      )}
                                    </>
                                  );
                                })()}
                              </div>
                            </td>
                          </tr>
                        )}

                        {/* Land Cover 1984 (Historical) */}
                        {block.landcover_1984_dominant && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Land Cover (1984)</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.landcover_1984_dominant} onSave={(v) => handleSaveBlock(index, 'landcover_1984_dominant', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.landcover_1984_percentages &&
                                Object.entries(block.landcover_1984_percentages).map(([cover, pct]: [string, any], idx: number) => (
                                  <span key={cover}>
                                    {cover}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'landcover_1984_percentages', cover, v)} className="inline" />
                                    {idx < Object.keys(block.landcover_1984_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Hansen 2000 Forest Classification */}
                        {block.hansen2000_dominant && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Forest Status (2000)</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.hansen2000_dominant} onSave={(v) => handleSaveBlock(index, 'hansen2000_dominant', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.hansen2000_percentages &&
                                Object.entries(block.hansen2000_percentages).map(([forestClass, pct]: [string, any], idx: number) => (
                                  <span key={forestClass}>
                                    {forestClass}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'hansen2000_percentages', forestClass, v)} className="inline" />
                                    {idx < Object.keys(block.hansen2000_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Land Cover (Current) */}
                        {block.landcover_dominant && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Land Cover (Current)</td>
                            <td className="px-4 py-3 text-sm text-gray-900 capitalize">
                              <EditableCell value={block.landcover_dominant} onSave={(v) => handleSaveBlock(index, 'landcover_dominant', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.landcover_percentages &&
                                Object.entries(block.landcover_percentages).map(([cover, pct]: [string, any], idx: number) => (
                                  <span key={cover}>
                                    {cover}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'landcover_percentages', cover, v)} className="inline" />
                                    {idx < Object.keys(block.landcover_percentages).length - 1 && ', '}
                                  </span>
                                ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Forest Loss */}
                        {block.forest_loss_hectares !== undefined && block.forest_loss_hectares !== null && block.forest_loss_hectares >= 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Forest Loss (2001-2023)</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.forest_loss_hectares} displayValue={block.forest_loss_hectares.toFixed(2) + " ha"} onSave={(v) => handleSaveBlock(index, 'forest_loss_hectares', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.forest_loss_by_year &&
                                Object.entries(block.forest_loss_by_year)
                                  .sort(([yearA], [yearB]) => parseInt(yearA) - parseInt(yearB))
                                  .map(([year, ha]: [string, any], idx: number, arr: any[]) => (
                                    <span key={year}>
                                      {year}: <EditableCell value={ha} displayValue={ha.toFixed(2) + " ha"} onSave={(v) => handleSaveBlockPercentages(index, 'forest_loss_by_year', year, v)} className="inline" />
                                      {idx < arr.length - 1 && ', '}
                                    </span>
                                  ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Forest Gain */}
                        {block.forest_gain_hectares !== undefined && block.forest_gain_hectares !== null && block.forest_gain_hectares >= 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Forest Gain (2000-2012)</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.forest_gain_hectares} displayValue={block.forest_gain_hectares.toFixed(2) + " ha"} onSave={(v) => handleSaveBlock(index, 'forest_gain_hectares', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              Net forest gain over 12-year period
                            </td>
                          </tr>
                        )}

                        {/* Fire Loss */}
                        {block.fire_loss_hectares !== undefined && block.fire_loss_hectares !== null && block.fire_loss_hectares >= 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Fire Loss (2001-2023)</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.fire_loss_hectares} displayValue={block.fire_loss_hectares.toFixed(2) + " ha"} onSave={(v) => handleSaveBlock(index, 'fire_loss_hectares', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              {block.fire_loss_by_year &&
                                Object.entries(block.fire_loss_by_year)
                                  .sort(([yearA], [yearB]) => parseInt(yearA) - parseInt(yearB))
                                  .map(([year, ha]: [string, any], idx: number, arr: any[]) => (
                                    <span key={year}>
                                      {year}: <EditableCell value={ha} displayValue={ha.toFixed(2) + " ha"} onSave={(v) => handleSaveBlockPercentages(index, 'fire_loss_by_year', year, v)} className="inline" />
                                      {idx < arr.length - 1 && ', '}
                                    </span>
                                  ))
                              }
                            </td>
                          </tr>
                        )}

                        {/* Temperature */}
                        {block.temperature_mean_c !== undefined && block.temperature_mean_c !== null && block.temperature_mean_c > -100 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Temperature</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.temperature_mean_c} displayValue={block.temperature_mean_c.toFixed(1) + " °C (mean)"} onSave={(v) => handleSaveBlock(index, 'temperature_mean_c', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              Min (coldest month): <EditableCell value={block.temperature_min_c} displayValue={block.temperature_min_c?.toFixed(1)} onSave={(v) => handleSaveBlock(index, 'temperature_min_c', v)} />{" °C"}
                            </td>
                          </tr>
                        )}

                        {/* Precipitation */}
                        {block.precipitation_mean_mm !== undefined && block.precipitation_mean_mm !== null && block.precipitation_mean_mm >= 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Precipitation</td>
                            <td className="px-4 py-3 text-sm text-gray-900 font-mono">
                              <EditableCell value={block.precipitation_mean_mm} displayValue={block.precipitation_mean_mm.toFixed(0) + " mm/year"} onSave={(v) => handleSaveBlock(index, 'precipitation_mean_mm', v)} />
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600">
                              Annual total precipitation
                            </td>
                          </tr>
                        )}

                        {/* Soil Analysis */}
                        {block.soil_texture && (
                          <>
                            <tr className="hover:bg-gray-50">
                              <td className="px-4 py-3 text-sm font-medium text-gray-900">Soil Texture</td>
                              <td className="px-4 py-3 text-sm text-gray-900">
                                <EditableCell value={block.soil_texture} onSave={(v) => handleSaveBlock(index, 'soil_texture', v)} />
                                {block.soil_texture_system && (
                                  <span className="text-xs text-gray-500 ml-2">({block.soil_texture_system})</span>
                                )}
                              </td>
                              <td className="px-4 py-3 text-sm text-gray-600">
                                {block.soil_properties &&
                                  Object.entries(block.soil_properties)
                                    .map(([prop, val]: [string, any]) => `${prop}: ${val}`)
                                    .join(', ')
                                }
                              </td>
                            </tr>
                            {block.carbon_stock_t_ha && (
                              <tr className="hover:bg-gray-50">
                                <td className="px-4 py-3 text-sm font-medium text-gray-900">Carbon Stock</td>
                                <td className="px-4 py-3 text-sm text-gray-900">
                                  <EditableCell
                                    value={block.carbon_stock_t_ha}
                                    displayValue={`${block.carbon_stock_t_ha} t/ha`}
                                    onSave={(v) => handleSaveBlock(index, 'carbon_stock_t_ha', v)}
                                  />
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-600">
                                  Topsoil (0-30cm) organic carbon stock
                                </td>
                              </tr>
                            )}
                            {block.fertility_class && (
                              <tr className="hover:bg-gray-50">
                                <td className="px-4 py-3 text-sm font-medium text-gray-900">Soil Fertility</td>
                                <td className="px-4 py-3 text-sm text-gray-900">
                                  <FertilityBadge
                                    value={block.fertility_class}
                                    className="inline-flex px-2 py-1 text-xs font-semibold rounded"
                                  />
                                  {block.fertility_score && (
                                    <span className="text-xs text-gray-500 ml-2">(Score: {block.fertility_score}/100)</span>
                                  )}
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-600">
                                  {block.limiting_factors && block.limiting_factors.length > 0 &&
                                    block.limiting_factors.join('; ')}
                                </td>
                              </tr>
                            )}
                            {block.compaction_status && (
                              <tr className="hover:bg-gray-50">
                                <td className="px-4 py-3 text-sm font-medium text-gray-900">Compaction Status</td>
                                <td className="px-4 py-3 text-sm text-gray-900">
                                  <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded ${
                                    block.compaction_status === 'Not compacted' ? 'bg-green-100 text-green-800' :
                                    block.compaction_status === 'Slight compaction' ? 'bg-yellow-100 text-yellow-800' :
                                    block.compaction_status === 'Moderate compaction' ? 'bg-orange-100 text-orange-800' :
                                    'bg-red-100 text-red-800'
                                  }`}>
                                    {block.compaction_status}
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-600">
                                  {block.compaction_alert || 'No action needed'}
                                </td>
                              </tr>
                            )}
                          </>
                        )}

                        {/* Administrative Location */}
                        <tr className="bg-gray-100">
                          <td colSpan={3} className="px-4 py-3 text-sm font-semibold text-gray-900">
                            Administrative Location
                          </td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Province</td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <EditableCell value={block.province} onSave={(v) => handleSaveBlock(index, 'province', v)} />
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600"></td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">District</td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <EditableCell value={block.district} onSave={(v) => handleSaveBlock(index, 'district', v)} />
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600"></td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Municipality</td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <EditableCell value={block.municipality} onSave={(v) => handleSaveBlock(index, 'municipality', v)} />
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600"></td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Ward</td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <EditableCell value={block.ward} onSave={(v) => handleSaveBlock(index, 'ward', v)} />
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600"></td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Watershed</td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <EditableCell value={block.watershed} onSave={(v) => handleSaveBlock(index, 'watershed', v)} />
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600"></td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Major River Basin</td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            <EditableCell value={block.major_river_basin} onSave={(v) => handleSaveBlock(index, 'major_river_basin', v)} />
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600"></td>
                        </tr>

                        {/* Geology */}
                        {block.geology_percentages && Object.keys(block.geology_percentages).length > 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Geology</td>
                            <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                              {Object.entries(block.geology_percentages).map(([cls, pct]: [string, any], idx: number) => (
                                <span key={cls}>
                                  {cls}: <EditableCell value={pct} displayValue={pct.toFixed(1) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'geology_percentages', cls, v)} className="inline" />
                                  {idx < Object.keys(block.geology_percentages).length - 1 && ', '}
                                </span>
                              ))}
                            </td>
                          </tr>
                        )}

                        {/* Physiography */}
                        {block.physiography_percentages && Object.keys(block.physiography_percentages).length > 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Physiography</td>
                            <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                              {Object.entries(block.physiography_percentages).map(([zone, pct]: [string, any], idx: number) => (
                                <span key={zone}>
                                  {zone}: <EditableCell value={pct} displayValue={pct.toFixed(2) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'physiography_percentages', zone, v)} className="inline" />
                                  {idx < Object.keys(block.physiography_percentages).length - 1 && ', '}
                                </span>
                              ))}
                            </td>
                          </tr>
                        )}

                        {/* Ecoregion */}
                        {block.ecoregion_percentages && Object.keys(block.ecoregion_percentages).length > 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Ecoregion</td>
                            <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                              {Object.entries(block.ecoregion_percentages).map(([eco, pct]: [string, any], idx: number) => (
                                <span key={eco}>
                                  {eco}: <EditableCell value={pct} displayValue={pct.toFixed(2) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'ecoregion_percentages', eco, v)} className="inline" />
                                  {idx < Object.keys(block.ecoregion_percentages).length - 1 && ', '}
                                </span>
                              ))}
                            </td>
                          </tr>
                        )}

                        {/* NASA Forest 2020 */}
                        {block.nasa_forest_2020_percentages && Object.keys(block.nasa_forest_2020_percentages).length > 0 && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">NASA Forest 2020</td>
                            <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                              {Object.entries(block.nasa_forest_2020_percentages).map(([type, pct]: [string, any], idx: number) => (
                                <span key={type}>
                                  <span className="capitalize">{type.replace(/_/g, ' ')}</span>: <EditableCell value={pct} displayValue={pct.toFixed(2) + "%"} onSave={(v) => handleSaveBlockPercentages(index, 'nasa_forest_2020_percentages', type, v)} className="inline" />
                                  {idx < Object.keys(block.nasa_forest_2020_percentages).length - 1 && ', '}
                                </span>
                              ))}
                            </td>
                          </tr>
                        )}

                        {/* Access */}
                        {block.access_info && (
                          <tr className="hover:bg-gray-50">
                            <td className="px-4 py-3 text-sm font-medium text-gray-900">Access</td>
                            <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                              <EditableCell value={block.access_info} onSave={(v) => handleSaveBlock(index, 'access_info', v)} />
                            </td>
                          </tr>
                        )}

                        {/* Nearby Features */}
                        <tr className="bg-gray-100">
                          <td colSpan={3} className="px-4 py-3 text-sm font-semibold text-gray-900">
                            Natural Features (within 100m)
                          </td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Features North</td>
                          <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                            <EditableCell value={block.features_north || ''} onSave={(v) => handleSaveBlock(index, 'features_north', v)} />
                          </td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Features East</td>
                          <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                            <EditableCell value={block.features_east || ''} onSave={(v) => handleSaveBlock(index, 'features_east', v)} />
                          </td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Features South</td>
                          <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                            <EditableCell value={block.features_south || ''} onSave={(v) => handleSaveBlock(index, 'features_south', v)} />
                          </td>
                        </tr>

                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">Features West</td>
                          <td className="px-4 py-3 text-sm text-gray-900" colSpan={2}>
                            <EditableCell value={block.features_west || ''} onSave={(v) => handleSaveBlock(index, 'features_west', v)} />
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Additional Information */}
        {(
          <div className="px-6 pb-6">
          <dl className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">Status</dt>
              <dd className="mt-1">
                <span
                  className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${getStatusBadge(
                    calc.status
                  )}`}
                >
                  {calc.status}
                </span>
              </dd>
            </div>

            {calc.processing_time_seconds && (
              <div>
                <dt className="text-sm font-medium text-gray-500">Processing Time</dt>
                <dd className="mt-1 text-sm text-gray-900">
                  {calc.processing_time_seconds} seconds
                </dd>
              </div>
            )}

            {calc.completed_at && (
              <div>
                <dt className="text-sm font-medium text-gray-500">Completed At</dt>
                <dd className="mt-1 text-sm text-gray-900">
                  {formatDate(calc.completed_at)}
                </dd>
              </div>
            )}

            {calc.error_message && (
              <div className="sm:col-span-3">
                <dt className="text-sm font-medium text-gray-500">Error Message</dt>
                <dd className="mt-1 text-sm text-red-600">{calc.error_message}</dd>
              </div>
            )}
          </dl>
          </div>
        )}

        {/* Geometry Error Warning */}
        {geometryError && (
          <div className="px-6 pb-4">
            <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg className="h-5 w-5 text-yellow-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                </div>
                <div className="ml-3">
                  <p className="text-sm text-yellow-700">
                    <strong>Map Display Issue:</strong> {geometryError}
                  </p>
                  <p className="text-xs text-yellow-600 mt-1">
                    The analysis data is still available above, but the boundary map cannot be displayed. This can happen with certain KML file formats. All other features (sampling, fieldbook, tree models) will work normally.
                  </p>
                  <p className="text-xs text-yellow-600 mt-2">
                    <strong>Recommendation:</strong> If you need the map, try re-uploading the boundary as a GeoJSON or Shapefile format instead.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Map Section */}
        {calc.geometry && !geometryError && (
          <div className="px-6 pb-6">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold text-gray-900">
                Boundary Map (A5 - {mapOrientation === 'portrait' ? 'Portrait' : 'Landscape'})
              </h2>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-700">Base Map:</span>
                  <select
                    value={basemap}
                    onChange={(e) => setBasemap(e.target.value as 'satellite' | 'osm' | 'terrain' | 'none')}
                    className="px-3 py-1.5 border border-gray-300 rounded-md bg-white text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                  >
                    <option value="satellite">Satellite</option>
                    <option value="osm">OpenStreetMap</option>
                    <option value="terrain">Terrain</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={boundaryVisible}
                    onChange={(e) => setBoundaryVisible(e.target.checked)}
                    className="h-4 w-4 text-green-600 focus:ring-green-500 border-gray-300 rounded"
                  />
                  <span className="text-sm font-medium text-gray-700">Show Forest Boundary</span>
                </label>
                <button
                  onClick={handleZoomToLayer}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors shadow-sm"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                  </svg>
                  Zoom to Layer
                </button>
              </div>
            </div>
            <div
              className="rounded-lg overflow-hidden border-2 border-gray-400 shadow-lg mx-auto relative"
              style={{
                width: mapOrientation === 'portrait' ? '900px' : '1200px',
                height: mapOrientation === 'portrait' ? '1200px' : '900px'
              }}
            >
              <MapContainer
                center={[27.7, 85.3]}
                zoom={7}
                style={{ height: '100%', width: '100%' }}
                zoomControl={true}
                attributionControl={true}
              >
                {basemap === 'satellite' && (
                  <TileLayer
                    attribution='&copy; <a href="https://www.esri.com/">Esri</a> &mdash; Source: Esri, Maxar, Earthstar Geographics'
                    url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                    maxZoom={19}
                  />
                )}
                {basemap === 'osm' && (
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    maxZoom={19}
                  />
                )}
                {basemap === 'terrain' && (
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'
                    url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
                    maxZoom={17}
                  />
                )}
                {boundaryVisible && calc.geometry && isValidGeoJSON(calc.geometry) && (
                  <GeoJSON
                    key={JSON.stringify(calc.geometry)}
                    data={calc.geometry}
                    style={{
                      color: '#059669',
                      weight: 3,
                      fillColor: '#34d399',
                      fillOpacity: 0
                    }}
                  />
                )}
                {/* Render blocks from result_data */}
                {blocks.length > 0 && blocks.map((block: any, index: number) => (
                  block.geometry && (
                    <GeoJSON
                      key={`block-${index}-${block.block_name || index}`}
                      data={block.geometry}
                      style={{
                        color: '#2563eb',
                        weight: 2,
                        fillColor: '#3b82f6',
                        fillOpacity: 0.1
                      }}
                    />
                  )
                ))}
                {/* Render sub-areas from result_data */}
                {calc.result_data?.sub_areas && calc.result_data.sub_areas.map((subArea: any, index: number) => (
                  subArea.geometry && (
                    <GeoJSON
                      key={`subarea-${index}-${subArea.name || index}`}
                      data={subArea.geometry}
                      style={{
                        color: subArea.isExcluded ? '#dc2626' : '#7c3aed',
                        weight: 2,
                        fillColor: subArea.isExcluded ? '#fca5a5' : '#c4b5fd',
                        fillOpacity: 0.3
                      }}
                    />
                  )
                ))}
                <ZoomToLayer
                  geometry={calc.geometry}
                  setMapInstance={setMapInstance}
                  orientation={mapOrientation}
                />
                <RasterLayerControl calculationId={calc.id} calculation={calc} />
                <RasterClickInfo calculationId={calc.id} boundaryGeometry={calc.geometry} />
              </MapContainer>
              <NorthArrow />
            </div>
            <div className="mt-3 text-center">
              <p className="text-sm text-gray-500">
                A5 Map Size: {mapOrientation === 'portrait' ? '560px × 794px (148mm × 210mm)' : '794px × 560px (210mm × 148mm)'} at 96 DPI
                {totalBlocks > 1 && (
                  <span className="block mt-1 italic">
                    Map shows all {totalBlocks} blocks combined
                  </span>
                )}
              </p>
            </div>
          </div>
        )}

        {/* Processing Info Section - Only show if partitioned */}
        {processingInfo.partitioned && (
          <div className="px-6 pb-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">Processing Information</h2>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-start">
                <svg className="w-5 h-5 text-blue-600 mt-0.5 mr-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                </svg>
                <div className="flex-1">
                  <p className="text-sm text-blue-800 font-medium">{labels.unitLabel} Boundary Partitioning Applied</p>
                  <p className="mt-1 text-sm text-blue-700">
                    The outer boundary was partitioned using {processingInfo.partition_info?.division_lines_used || 0} division lines,
                    creating {processingInfo.partition_info?.blocks_created || 0} separate {labels.unitLabelPluralLower}.
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
    </div>
  );
}
