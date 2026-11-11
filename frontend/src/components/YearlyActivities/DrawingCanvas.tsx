/** Drawing canvas — Leaflet + Geoman drawing tools for sketching activity boundaries, polylines, and markers. */
import React, { useRef, useState, useEffect, useImperativeHandle, forwardRef } from 'react';
import { MapContainer, TileLayer, useMap, useMapEvents, Marker, Polyline, Polygon, GeoJSON, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import * as turf from '@turf/turf';
import { Button, Radio, Space, List, Card, message, Popconfirm, Input, InputRef, Divider, Checkbox } from 'antd';
import { yearlyActivitiesApi } from '../../services/api';
import { NumericScale } from '../NumericScale';
import { useT } from '../../i18n/hooks';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';

interface BlockSubArea {
  id: string;
  name: string;
  type: 'boundary' | 'block' | 'sub_area';
  category?: string;
  geometry?: any;
}

interface YearData {
  year: number;
}

const EditableTag: React.FC<{
  text: string;
  onSave: (newText: string) => void;
}> = ({ text, onSave }) => {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(text);
  const inputRef = useRef<InputRef>(null);

  useEffect(() => {
    setValue(text);
  }, [text]);

  const handleEdit = () => {
    setEditing(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const handleSave = () => {
    if (value.trim() && value !== text) {
      onSave(value.trim());
    } else {
      setValue(text);
    }
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave();
    } else if (e.key === 'Escape') {
      setValue(text);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <Input
        ref={inputRef}
        size="small"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        style={{ width: 120 }}
      />
    );
  }

  return (
    <span 
      onClick={handleEdit} 
      style={{ cursor: 'pointer', padding: '2px 6px', borderRadius: 4 }}
      title={t('yearlyActivities.draw.clickToRename')}
    >
      {text} ✎
    </span>
  );
};

interface DrawingCanvasProps {
  calculationId: string;
  activityId: string;
  featureType: 'point' | 'line' | 'polygon';
  onFeatureTypeChange: (type: 'point' | 'line' | 'polygon') => void;
  drawnFeatures: any[];
  onFeaturesChange: () => void;
  blocksWithSubAreas?: BlockSubArea[];
  availableYears?: YearData[];
  baseMap?: 'satellite' | 'osm' | 'topo';
  boundaryGeometry?: any;
  blockLayers?: any[];
  subAreaLayers?: any[];
}

const BASE_MAPS = {
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri'
  },
  osm: {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap'
  },
  topo: {
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenTopoMap'
  }
};

const DrawingCanvas: React.FC<DrawingCanvasProps> = ({
  calculationId,
  activityId,
  featureType: _propFeatureType,  // ignored - using internal state
  onFeatureTypeChange,
  drawnFeatures,
  onFeaturesChange,
  blocksWithSubAreas = [],
  availableYears = [],
  baseMap = 'satellite',
}) => {
  const t = useT();
  const mapRef = useRef<L.Map | null>(null);
  const nameInputRef = useRef<InputRef>(null);
  const [drawingMode, setDrawingMode] = useState(true);
  const [currentPoints, setCurrentPoints] = useState<L.LatLng[]>([]);
  const [tempLayer, setTempLayer] = useState<L.Polyline | L.Polygon | L.Marker | null>(null);
  const [featureName, setFeatureName] = useState('');
  const [selectedYears, setSelectedYears] = useState<number[]>([]);
  const [featureType, setFeatureType] = useState<'point' | 'line' | 'polygon'>('polygon');
  const [isDrawing, setIsDrawing] = useState(false);
  
  // Live measurements state
  const [currentLength, setCurrentLength] = useState(0);
  const [currentArea, setCurrentArea] = useState(0);
  const [measurementUnit, setMeasurementUnit] = useState<'metric' | 'imperial'>('metric');
  const [editMode, setEditMode] = useState<'draw' | 'edit'>('draw');
  
  // Feature selection for editing
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [editingFeature, setEditingFeature] = useState<any | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editingFeatureId, setEditingFeatureId] = useState<string | null>(null);
  const [editingLayers, setEditingLayers] = useState<Map<string, any>>(new Map());
  const featureLayersRef = useRef<Map<string, L.Layer>>(new Map());
  
  // Vertex editing state (for draggable vertices)
  const [editingVertices, setEditingVertices] = useState<L.LatLng[]>([]);
  const [vertexBeingDragged, setVertexBeingDragged] = useState<number | null>(null);
  
  // Layer visibility toggles
  const [showBoundary, setShowBoundary] = useState(true);
  const [showBlocks, setShowBlocks] = useState(true);
  const [showSubAreas, setShowSubAreas] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  
  // Auto-select first year when availableYears is provided
  useEffect(() => {
    if (availableYears && availableYears.length > 0 && selectedYears.length === 0) {
      setSelectedYears([availableYears[0].year]);
    }
  }, [availableYears]);
  
  // Calculate live geodesic measurements using turf.js
  const calculateMeasurements = (points: L.LatLng[], type: string) => {
    if (points.length < 2) {
      setCurrentLength(0);
      setCurrentArea(0);
      return;
    }
    
    if (type === 'line' && points.length >= 2) {
      // Use turf.js for geodesic length
      const coords = points.map(p => [p.lng, p.lng] as [number, number]);
      const lineCoords = points.map(p => [p.lng, p.lat] as [number, number]);
      const lineFeature = turf.lineString(lineCoords);
      const length = turf.length(lineFeature, { units: 'meters' });
      setCurrentLength(length);
    } else if (type === 'polygon' && points.length >= 3) {
      // Use turf.js for geodesic area (spherical)
      const polyCoords = [...points.map(p => [p.lng, p.lat] as [number, number])];
      // Close the polygon if needed
      if (polyCoords.length > 0) {
        const first = polyCoords[0];
        const last = polyCoords[polyCoords.length - 1];
        if (first[0] !== last[0] || first[1] !== last[1]) {
          polyCoords.push([...first]);
        }
      }
      const polygonFeature = turf.polygon([polyCoords]);
      const area = turf.area(polygonFeature); // Returns area in square meters
      setCurrentArea(area);
    }
  };
  
  const formatLength = (meters: number) => {
    if (measurementUnit === 'imperial') {
      return `${formatDecimal(meters * 3.28084, 1)} ${t('yearlyActivities.draw.unitFt')}`;
    }
    return `${formatDecimal(meters, 1)} ${t('units.meter')}`;
  };
  
  const formatArea = (sqMeters: number) => {
    const sqMetersDisplay = sqMeters;
    const hectaresDisplay = sqMeters / 10000;
    const acresDisplay = sqMeters * 0.000247105;
    
    if (measurementUnit === 'imperial') {
      return `${formatDecimal(acresDisplay)} ${t('yearlyActivities.draw.unitAcres')}`;
    }
    return `${formatDecimal(sqMetersDisplay, 1)} ${t('yearlyActivities.draw.unitSqM')}`
      + ` (${formatDecimal(hectaresDisplay)} ${t('units.hectare')})`;
  };

  const handleMapClick = (e: L.LeafletMouseEvent) => {
    // Handle edit mode clicks
    if (editingFeatureId) {
      handleMapClickForEdit(e);
      return;
    }
    
    if (!selectedYears.length || !drawingMode) return;
    const latlng = e.latlng;
    const newPoints = [...currentPoints, latlng];
    setCurrentPoints(newPoints);
    
    // Calculate live measurements
    calculateMeasurements(newPoints, featureType);

    if (featureType === 'point') {
      createPoint(latlng);
    }
  };

  const createPoint = async (latlng: L.LatLng) => {
    try {
      const geometry = JSON.stringify({
        type: 'Point',
        coordinates: [latlng.lng, latlng.lat]
      });
      
      const name = featureName.trim();  // empty: the server names it after the activity

      await yearlyActivitiesApi.createDrawnFeature(activityId, {
        feature_type: 'point',
        geometry,
        properties: { ...(name ? { label: name, name } : {}), years: selectedYears }
      });

      message.success(t('yearlyActivities.draw.msgPointAdded'));
      onFeaturesChange();
      setCurrentPoints([]);
      setFeatureName('');
      setSelectedYears([availableYears[0]?.year].filter(Boolean));
    } catch (error: any) {
      message.error(t('yearlyActivities.draw.addPointFailed'));
    }
  };

  const handleDoubleClick = async (e: any) => {
    // Stop editing when double-clicking (for line/polygon vertices)
    if (editingFeatureId) {
      handleStopEdit();
      return;
    }
    
    if (!selectedYears.length || currentPoints.length < 2) return;
    e.originalEvent?.preventDefault();

    if (featureType === 'line') {
      await createLine();
    } else if (featureType === 'polygon') {
      await createPolygon();
    }
  };

  const createLine = async () => {
    try {
      const geometry = JSON.stringify({
        type: 'LineString',
        coordinates: currentPoints.map(p => [p.lng, p.lat])
      });

      const length = currentPoints.reduce((acc, p, i) => {
        if (i === 0) return 0;
        return acc + currentPoints[i - 1].distanceTo(p);
      }, 0);

      const name = featureName.trim();  // empty: the server names it after the activity
      
      await yearlyActivitiesApi.createDrawnFeature(activityId, {
        feature_type: 'line',
        geometry,
        properties: { length_m: Math.round(length), ...(name ? { name } : {}), years: selectedYears }
      });

      message.success(t('yearlyActivities.draw.msgLineAdded'));
      onFeaturesChange();
      setCurrentPoints([]);
      setFeatureName('');
      setSelectedYears([availableYears[0]?.year].filter(Boolean));
    } catch (error: any) {
      message.error(t('yearlyActivities.draw.addLineFailed'));
    }
  };

  const createPolygon = async () => {
    try {
      const coords = currentPoints.map(p => [p.lng, p.lat]);
      const firstPoint = currentPoints[0];
      const lastPoint = currentPoints[currentPoints.length - 1];
      if (firstPoint.distanceTo(lastPoint) > 1) {
        coords.push([firstPoint.lng, firstPoint.lat]);
      }

      const polygon = L.polygon(currentPoints.map(p => [p.lat, p.lng]));
      const bounds = polygon.getBounds();
      const latSpan = bounds.getNorthEast().lat - bounds.getSouthWest().lat;
      const lngSpan = bounds.getNorthEast().lng - bounds.getSouthWest().lng;
      const centerLat = bounds.getSouthWest().lat + latSpan / 2;
      const metersPerDegreeLat = 111320;
      const metersPerDegreeLng = 111320 * Math.cos(centerLat * Math.PI / 180);
      const areaSqM = Math.abs(latSpan * metersPerDegreeLat) * Math.abs(lngSpan * metersPerDegreeLng);

      const geometry = JSON.stringify({
        type: 'Polygon',
        coordinates: [coords]
      });

      console.log('[createPolygon] saving geometry:', geometry);
      
      const name = featureName.trim();  // empty: the server names it after the activity

      await yearlyActivitiesApi.createDrawnFeature(activityId, {
        feature_type: 'polygon',
        geometry,
        properties: { area_sqm: Math.round(areaSqM), ...(name ? { name } : {}), years: selectedYears }
      });

      message.success(t('yearlyActivities.draw.msgPolygonAdded'));
      onFeaturesChange();
      setCurrentPoints([]);
      setFeatureName('');
      setSelectedYears([availableYears[0]?.year].filter(Boolean));
    } catch (error: any) {
      console.error('[createPolygon] error:', error);
      message.error(t('yearlyActivities.draw.addPolygonFailed'));
    }
  };

  const handleDeleteFeature = async (featureId: string) => {
    try {
      await yearlyActivitiesApi.deleteDrawnFeature(activityId, featureId);
      message.success(t('yearlyActivities.draw.msgFeatureDeleted'));
      onFeaturesChange();
    } catch (error: any) {
      message.error(t('yearlyActivities.draw.deleteFeatureFailed'));
    }
  };

  const handleCopyFeature = async (targetYear: number) => {
    if (!editingFeature) return;
    
    // Get base feature name (without year suffixes)
    const baseName = (editingFeature?.properties?.name || editingFeature?.feature_type || '')
      .replace(/\s*\(Y\d+\)\s*/g, '')
      .trim();
    
    // Get the geometry to compare
    const sourceGeometry = editingFeature.geometry;
    
    // Check if any feature with the same geometry already exists for this year
    // This prevents duplicate geometries assigned to the same year
    const isDuplicate = drawnFeatures.some(f => 
      f.id !== editingFeature.id &&  // Not the same feature
      f.properties?.year === targetYear &&  // Same year
      f.geometry === sourceGeometry  // Same geometry
    );
    
    if (isDuplicate) {
      message.warning(`This feature is already assigned to Year ${targetYear}`);
      return;
    }
    
    // Check if this feature already has the year assigned
    const currentYear = editingFeature.properties?.year;
    const existingYears = (editingFeature.properties?.name || '').match(/\(Y(\d+)\)/g) || [];
    const hasYearAlready = existingYears.some((y: string) => y.includes(`(Y${targetYear})`));
    
    if (currentYear === targetYear || hasYearAlready) {
      message.warning(`Year ${targetYear} is already assigned to this feature`);
      return;
    }
    
    try {
      // Preserve the area/length from source feature
      const sourceArea = editingFeature.properties?.area_sqm;
      const sourceLength = editingFeature.properties?.length_m;
      
      console.log('[handleCopyFeature] editingFeature:', JSON.stringify(editingFeature, null, 2));
      
      await yearlyActivitiesApi.createDrawnFeature(activityId, {
        feature_type: editingFeature.feature_type,
        geometry: editingFeature.geometry,
        properties: { 
          name: `${baseName} (Y${targetYear})`,
          year: targetYear,
          area_sqm: sourceArea,
          length_m: sourceLength
        }
      });
      message.success(`Assigned to Year ${targetYear}`);
      onFeaturesChange();
    } catch (error: any) {
      console.error('[handleCopyFeature] error:', error);
      message.error(t('yearlyActivities.draw.assignFailed'));
    }
  };

  const handleStartEdit = (feature: any) => {
    const map = mapRef.current;
    if (!map) return;
    
    // Stop editing previous feature first if any
    if (editingFeatureId && editingFeatureId !== feature.id) {
      const prevLayer = featureLayersRef.current.get(editingFeatureId);
      if (prevLayer) {
        (prevLayer as any).pm.disable();
        map.removeLayer(prevLayer);
        featureLayersRef.current.delete(editingFeatureId);
      }
    }
    
    setSelectedFeatureId(feature.id);
    setEditingFeatureId(feature.id);
    setEditingFeature(feature);
    
    const coords = parseGeometry(feature.geometry, feature.feature_type);
    if (!coords) return;
    
    const latlngs = coords.map(c => [c[0], c[1]] as [number, number]);
    
    let layer: L.Polyline | L.Polygon;
    if (feature.feature_type === 'polygon') {
      layer = L.polygon(latlngs, {
        color: '#ff9900',
        weight: 3,
        fillOpacity: 0.3,
        dashArray: '5, 5'
      });
    } else {
      layer = L.polyline(latlngs, {
        color: '#ff9900',
        weight: 4,
        dashArray: '5, 5'
      }) as any;
    }
    
    layer.addTo(map);
    featureLayersRef.current.set(feature.id, layer);
    (layer as any).pm.enable();
    
    layer.on('pm:edit', async () => {
      const geoJson = (layer as any).toGeoJSON();
      const newGeometry = JSON.stringify(geoJson.geometry);
      console.log('[Geoman] Saving:', { featureId: feature.id, featureType: feature.feature_type, geometry: newGeometry });
      try {
        await yearlyActivitiesApi.updateDrawnFeature(activityId, feature.id, {
          geometry: newGeometry,
          feature_type: feature.feature_type
        });
        message.success(t('yearlyActivities.draw.msgChangesSaved'));
        onFeaturesChange();
      } catch (err: any) {
        const errorDetail = err?.response?.data?.detail;
        console.error('[Geoman] Save failed:', errorDetail || err);
        message.error(errorDetail?.[0]?.msg || t('yearlyActivities.draw.saveFailed'));
      }
    });
    
    message.info(t('yearlyActivities.draw.editHint'));
  };

  const handleStopEdit = async () => {
    const map = mapRef.current;
    if (map && editingFeatureId) {
      const layer = featureLayersRef.current.get(editingFeatureId);
      if (layer) {
        const geoJson = (layer as any).toGeoJSON();
        const finalGeometry = JSON.stringify(geoJson.geometry);
        
        // Recalculate length/area after editing
        let newProperties: any = {};
        const geom = geoJson.geometry;
        
        if (geom.type === 'LineString' && geom.coordinates) {
          const lineFeature = turf.lineString(geom.coordinates);
          const length = turf.length(lineFeature, { units: 'meters' });
          newProperties.length_m = Math.round(length);
        } else if (geom.type === 'Polygon' && geom.coordinates) {
          // Use outer ring for area calculation
          const polyCoords = geom.coordinates[0].map((c: number[]) => [c[0], c[1]] as [number, number]);
          const polygonFeature = turf.polygon([polyCoords]);
          const area = turf.area(polygonFeature);
          newProperties.area_sqm = Math.round(area);
        }
        
        try {
          await yearlyActivitiesApi.updateDrawnFeature(activityId, editingFeatureId, {
            geometry: finalGeometry,
            feature_type: editingFeature?.feature_type || featureType,
            properties: { ...editingFeature?.properties, ...newProperties }
          });
        } catch (err) {
          console.error('[Geoman] Final save failed:', err);
        }
        (layer as any).pm.disable();
        map.removeLayer(layer);
        featureLayersRef.current.delete(editingFeatureId);
      }
    }
    setEditingFeatureId(null);
    setEditingFeature(null);
    setEditingVertices([]);
    onFeaturesChange();
    message.success(t('yearlyActivities.draw.msgEditComplete'));
  };

  // Handle vertex drag during drawing (draggable markers)
  const handleVertexDrag = (index: number, e: L.DragEndEvent) => {
    const newLatLng = e.target.getLatLng();
    const newPoints = [...currentPoints];
    newPoints[index] = newLatLng;
    setCurrentPoints(newPoints);
    calculateMeasurements(newPoints, featureType);
  };

  // Handle right-click on vertex to delete it
  const handleVertexDelete = (index: number) => {
    // Prevent breaking shapes - minimum points
    if (featureType === 'polygon' && currentPoints.length <= 3) {
      message.warning(t('yearlyActivities.draw.errPolygonVertices'));
      return;
    }
    if (featureType === 'line' && currentPoints.length <= 2) {
      message.warning(t('yearlyActivities.draw.errLineVertices'));
      return;
    }
    
    const newPoints = currentPoints.filter((_, i) => i !== index);
    setCurrentPoints(newPoints);
    calculateMeasurements(newPoints, featureType);
    message.success(t('yearlyActivities.draw.msgVertexDeleted'));
  };

  // Handle vertex drag for editing existing features
  const handleEditingVertexDrag = async (index: number, e: L.DragEndEvent) => {
    const newLatLng = e.target.getLatLng();
    const newVertices = [...editingVertices];
    newVertices[index] = newLatLng;
    setEditingVertices(newVertices);
    
    const currentFeatureType = editingFeature?.feature_type || featureType;
    if (currentFeatureType === 'line' || currentFeatureType === 'polygon') {
      calculateMeasurements(newVertices, currentFeatureType);
    }
    
    // Save to server after drag
    if (!editingFeatureId) return;
    const coords = newVertices
      .filter(p => p.lat != null && p.lng != null)
      .map(p => [p.lng, p.lat]);
    if (coords.length < 2) {
      message.error(t('yearlyActivities.draw.errInvalidVertices'));
      return;
    }
    let newGeometry: string;
    
    if (currentFeatureType === 'polygon') {
      coords.push(coords[0]); // Close polygon
      newGeometry = JSON.stringify({
        type: 'polygon',
        coordinates: [coords]
      });
    } else if (currentFeatureType === 'line') {
      newGeometry = JSON.stringify({
        type: 'linestring',
        coordinates: coords
      });
    } else {
      newGeometry = JSON.stringify({
        type: 'point',
        coordinates: [coords[0][0], coords[0][1]]
      });
    }
    
    try {
      console.log('[handleEditingVertexDrag] Saving:', { activityId, editingFeatureId, currentFeatureType, newGeometry });
      await yearlyActivitiesApi.updateDrawnFeature(activityId, editingFeatureId, {
        geometry: newGeometry,
        feature_type: currentFeatureType
      });
      message.success(t('yearlyActivities.draw.msgVertexMoved'));
      onFeaturesChange();
    } catch (err: any) {
      const errorDetail = err?.response?.data?.detail;
      console.error('Error saving vertex drag:', errorDetail || err);
      message.error(errorDetail?.[0]?.msg || t('yearlyActivities.draw.saveVertexFailed'));
    }
  };

  // Handle right-click on editing vertex
  const handleEditingVertexDelete = (index: number) => {
    if (!editingFeatureId || !editingFeature) return;
    
    const currentFeatureType = editingFeature?.feature_type || featureType;
    const minPoints = currentFeatureType === 'polygon' ? 4 : 3;
    if (editingVertices.length <= minPoints) {
      message.warning(`Cannot delete - ${currentFeatureType} needs at least ${minPoints - 1} vertices`);
      return;
    }

    const newVertices = editingVertices.filter((_, i) => i !== index);
    setEditingVertices(newVertices);
    
    // Update the feature on the server
    const coords = newVertices.map(p => [p.lng, p.lat]);
    let newGeometry: string;
    
    if (currentFeatureType === 'polygon') {
      coords.push(coords[0]); // Close polygon
      newGeometry = JSON.stringify({
        type: 'Polygon',
        coordinates: [coords]
      });
    } else {
      newGeometry = JSON.stringify({
        type: 'LineString',
        coordinates: coords
      });
    }
    
    yearlyActivitiesApi.updateDrawnFeature(activityId, editingFeatureId, {
      geometry: newGeometry,
      feature_type: featureType
    }).then(() => {
      message.success(t('yearlyActivities.draw.msgVertexDeletedUpdated'));
      onFeaturesChange();
    }).catch((err) => {
      console.error('Error updating feature:', err);
      message.error(t('yearlyActivities.draw.deleteVertexFailed'));
      // Restore the vertex
      setEditingVertices(editingVertices);
    });
  };

const handleMapClickForEdit = (e: L.LeafletMouseEvent) => {
    if (!editingFeatureId || !editingFeature) return;
    const latlng = e.latlng;
    
    if (editingFeature.feature_type === 'point') {
      handleMovePoint(editingFeatureId, latlng, 0);
    } else if (editingFeature.feature_type === 'line') {
      const coords = parseGeometry(editingFeature.geometry, editingFeature.feature_type);
      if (!coords) return;
      
      const newCoord = [latlng.lng, latlng.lat];
      const coordsLngLat = coords.map((c: number[]) => [c[1], c[0]]);
      coordsLngLat.push(newCoord);
      const newGeometry = JSON.stringify({
        type: 'LineString',
        coordinates: coordsLngLat
      });
      
      yearlyActivitiesApi.updateDrawnFeature(activityId, editingFeatureId, {
        geometry: newGeometry,
        feature_type: 'line'
      }).then(() => {
        message.success(t('yearlyActivities.draw.msgVertexAdded'));
        onFeaturesChange();
      }).catch((err) => {
        console.error('[handleMapClickForEdit] error:', err);
        message.error(t('yearlyActivities.draw.addVertexFailed'));
      });
} else {
      message.info(t('yearlyActivities.draw.polygonEditUnsupportedYet'));
    }
  };

  // Parse WKT or GeoJSON to coordinates - return [lat, lng] for Leaflet
  const parseGeometry = (geom: string, featureType: string): number[][] | null => {
    if (!geom) return null;
    try {
      const geoJson = JSON.parse(geom);
      if (geoJson && geoJson.coordinates) {
        const coords = geoJson.coordinates;
        if (featureType === 'point') {
          return [[coords[1], coords[0]]];
        } else if (featureType === 'polygon') {
          const ring = coords[0] || coords;
          return ring.map((c: any) => [c[1], c[0]]);
        } else {
          return coords.map((c: any) => [c[1], c[0]]);
        }
      }
    } catch {
      // ignore
    }
    // Try WKT format
    const upperGeom = geom.toUpperCase();
    if (upperGeom.startsWith('POINT')) {
      const match = geom.match(/POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)/i);
      if (match && match[1] && match[2]) {
        const lng = parseFloat(match[1]);
        const lat = parseFloat(match[2]);
        return [[lat, lng]];
      }
    } else if (upperGeom.startsWith('LINESTRING')) {
      const m = geom.match(/LINESTRING\s*\((.*)\)/i);
      if (m) {
        const coords: any = m[1].split(',').map((c: string) => {
          const parts = c.trim().split(/\s+/).map(Number);
          return parts.length >= 2 ? [parts[1], parts[0]] : null;
        }).filter(Boolean);
        return coords;
      }
    } else if (upperGeom.startsWith('POLYGON')) {
      const m = geom.match(/POLYGON\s*\(\((.*)\)/i);
      if (m) {
        const ring = m[1].split(',').map((c: string) => {
          const parts = c.trim().split(/\s+/).map(Number);
          return parts.length >= 2 ? [parts[1], parts[0]] as number[] : [];
        }) as any;
        return [ring];
      }
    }
    return null;
  };

  // Render boundary/block/subarea layers
  const renderBoundaryLayers = () => {
    if (!blocksWithSubAreas) return null;
    
    return blocksWithSubAreas.map((layer: BlockSubArea, index: number) => {
      if (!layer.geometry) return null;
      
      // Visibility checks
      if (layer.type === 'boundary' && !showBoundary) return null;
      if (layer.type === 'block' && !showBlocks) return null;
      if (layer.type === 'sub_area' && !showSubAreas) return null;
      
      try {
        const gj = typeof layer.geometry === 'string' ? JSON.parse(layer.geometry) : layer.geometry;
        
        // Handle MultiPolygon
        let coords;
        if (gj.type === 'MultiPolygon') {
          // Use first polygon of multipolygon
          coords = gj.coordinates[0][0];
        } else if (gj.type === 'Polygon') {
          coords = gj.coordinates[0];
        } else {
          coords = gj.coordinates;
        }
        
        const latlngs = coords.map((c: number[]) => [c[1], c[0]]);
        
        // Different styles for each type
        const styleMap = {
          'boundary': { color: '#666666', fillColor: '#cccccc', fillOpacity: 0.05, weight: 2, dashArray: '5, 5' },
          'block': { color: '#2563eb', fillColor: '#2563eb', fillOpacity: 0.1, weight: 2 },
          'sub_area': { color: '#059669', fillColor: '#059669', fillOpacity: 0.15, weight: 2 }
        };
        
        const style = styleMap[layer.type as keyof typeof styleMap] || styleMap['block'];
        
        return (
          <Polygon
            key={layer.id || `layer-${index}`}
            positions={latlngs}
            pathOptions={style}
          >
            <Tooltip permanent={false} direction="top">
              <strong>{layer.name}</strong>
              {layer.category && <div><small>{layer.category}</small></div>}
            </Tooltip>
          </Polygon>
        );
      } catch (e) { 
        console.warn('Error rendering layer:', e);
        return null; 
      }
    });
  };

  // Render labels with halo effect for blocks and sub-areas
  const renderLabels = () => {
    if (!showLabels || !blocksWithSubAreas) return null;
    
    return blocksWithSubAreas.map((layer: BlockSubArea, index: number) => {
      // Only show labels for blocks and sub-areas (not boundary)
      if (layer.type === 'boundary') return null;
      if (layer.type === 'block' && !showBlocks) return null;
      if (layer.type === 'sub_area' && !showSubAreas) return null;
      if (!layer.geometry) return null;
      
      try {
        const gj = typeof layer.geometry === 'string' ? JSON.parse(layer.geometry) : layer.geometry;
        
        let polygon;
        if (gj.type === 'Polygon') {
          polygon = turf.polygon(gj.coordinates);
        } else if (gj.type === 'MultiPolygon') {
          polygon = turf.multiPolygon(gj.coordinates);
        } else {
          return null;
        }
        
        // Get centroid
        const centroid = turf.centroid(polygon);
        const [lng, lat] = centroid.geometry.coordinates;
        
        // Create custom icon with halo effect
        const colorMap: Record<string, string> = {
          'block': '#2563eb',
          'sub_area': '#059669'
        };
        const color = colorMap[layer.type] || '#2563eb';
        
        const icon = L.divIcon({
          className: 'custom-label',
          html: `<div style="
            background: white;
            border: 2px solid ${color};
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: bold;
            color: ${color};
            white-space: nowrap;
            box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            text-shadow: -1px -1px 0 white, 1px -1px 0 white, -1px 1px 0 white, 1px 1px 0 white;
          ">${layer.name}</div>`,
          iconSize: [0, 0],
          iconAnchor: [0, 0]
        });
        
        return (
          <Marker
            key={`label-${layer.id || index}`}
            position={[lat, lng]}
            icon={icon}
          />
        );
      } catch (e) {
        console.warn('Error rendering label:', e);
        return null;
      }
    });
  };

  // Handle feature click for selection in edit mode
  const handleFeatureClick = (feature: any) => {
    if (editMode === 'edit') {
      // Stop editing any previous feature first
      if (editingFeatureId && editingFeatureId !== feature.id) {
        const map = mapRef.current;
        if (map) {
          const prevLayer = featureLayersRef.current.get(editingFeatureId);
          if (prevLayer) {
            (prevLayer as any).pm.disable();
            map.removeLayer(prevLayer);
            featureLayersRef.current.delete(editingFeatureId);
          }
        }
      }
      setSelectedFeatureId(feature.id);
      setEditingFeature(feature);
      setIsEditing(true);
      
      // Zoom to feature on map
      const map = mapRef.current;
      if (map) {
        const coords = parseGeometry(feature.geometry, feature.feature_type);
        if (coords && coords.length > 0) {
          if (feature.feature_type === 'point') {
            map.flyTo([coords[0][0], coords[0][1]], 17);
          } else {
            const bounds = L.latLngBounds(coords as L.LatLngExpression[]);
            map.flyToBounds(bounds, { padding: [50, 50] });
          }
        }
      }
    }
  };

  const handleMovePoint = async (featureId: string, newLatLng: L.LatLng, pointIndex: number) => {
    try {
      const feature = drawnFeatures.find((f: any) => f.id === featureId);
      if (!feature) return;
      
      const coords = parseGeometry(feature.geometry, feature.feature_type);
      if (!coords) return;
      
      const newCoord = [newLatLng.lng, newLatLng.lat];
      let newGeometry: string;
      
      if (feature.feature_type === 'point') {
        newGeometry = JSON.stringify({
          type: 'Point',
          coordinates: newCoord
        });
      } else if (feature.feature_type === 'line') {
        const coordsLngLat: any = coords.map((c: any) => [c[1], c[0]]);
        coordsLngLat[pointIndex] = newCoord;
        newGeometry = JSON.stringify({
          type: 'LineString',
          coordinates: coordsLngLat
        });
      } else if (feature.feature_type === 'polygon') {
        message.info(t('yearlyActivities.draw.polygonEditUnsupported'));
        return;
      } else {
        return;
      }
      
      console.log('[handleMovePoint] newGeometry:', newGeometry);
      
      await yearlyActivitiesApi.updateDrawnFeature(activityId, featureId, {
        geometry: newGeometry,
        feature_type: feature.feature_type
      });
      
      message.success(t('yearlyActivities.draw.msgFeatureMoved'));
      onFeaturesChange();
    } catch (error) {
      message.error(t('yearlyActivities.draw.moveFeatureFailed'));
    }
  };

  // Render existing features on map
  const renderFeatures = () => {
    return drawnFeatures.map((feature: any, index: number) => {
      const coords = parseGeometry(feature.geometry, feature.feature_type);
      console.log('[renderFeatures] type:', feature.feature_type, 'parsed coords:', coords, 'original:', feature.geometry);
      if (!coords || !coords[0] || coords[0].length < 2) {
        console.warn('Invalid coords for feature:', feature.id, feature.geometry);
        return null;
      }
      
      const isSelected = selectedFeatureId === feature.id;
      
      try {
        // Show editing indicator for selected feature
      const isBeingEdited = editingFeatureId === feature.id;
      
      if (feature.feature_type === 'point') {
        const lat = coords[0][0];
        const lng = coords[0][1];
        if (isNaN(lat) || isNaN(lng)) return null;
        return (
          <Marker
            key={feature.id || index}
            position={[lat, lng]}
            opacity={isBeingEdited ? 0.5 : 1}
            eventHandlers={{
              click: () => isBeingEdited ? null : handleFeatureClick(feature)
            }}
          />
        );
      } else if (feature.feature_type === 'line') {
        const lineCoords = coords as [number, number][];
        return (
          <>
            <Polyline
              key={`line-${feature.id || index}`}
              positions={lineCoords}
              color={isBeingEdited ? '#ff9900' : '#e11d48'}
              weight={isBeingEdited ? 5 : 3}
              dashArray={isBeingEdited ? "5, 5" : undefined}
              eventHandlers={{
                click: () => handleFeatureClick(feature)
              }}
            />
            {/* Draggable vertex markers when editing - disabled when using Geoman */}
            {isBeingEdited && !featureLayersRef.current.has(feature.id) && lineCoords && lineCoords.map((pos, vidx) => (
              <Marker
                key={`v-${feature.id}-${vidx}`}
                position={pos}
                draggable={true}
                opacity={0.8}
                eventHandlers={{
                  dragend: (e) => handleEditingVertexDrag(vidx, e),
                  contextmenu: () => handleEditingVertexDelete(vidx)
                }}
              />
            ))}
          </>
        );
      } else if (feature.feature_type === 'polygon') {
        const polyCoords: any = coords;
        return (
          <>
            <Polygon
              key={`poly-${feature.id || index}`}
              positions={polyCoords}
              color={isBeingEdited ? '#ff9900' : '#059669'}
              weight={isBeingEdited ? 4 : 2}
              fillOpacity={isBeingEdited ? 0.4 : 0.3}
              dashArray={isBeingEdited ? "5, 5" : undefined}
              eventHandlers={{
                click: () => handleFeatureClick(feature)
              }}
            />
            {/* Draggable vertex markers when editing - disabled when using Geoman */}
            {isBeingEdited && !featureLayersRef.current.has(feature.id) && polyCoords && polyCoords.map((pos: number[], vidx: number) => (
              <Marker
                key={`v-${feature.id}-${vidx}`}
                position={pos as [number, number]}
                draggable={true}
                opacity={0.8}
                eventHandlers={{
                  dragend: (e) => handleEditingVertexDrag(vidx, e),
                  contextmenu: () => handleEditingVertexDelete(vidx)
                }}
              />
            ))}
          </>
        );
      }
      } catch (e) {
        console.warn('Error rendering feature:', e);
      }
      return null;
    });
  };

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div style={{ width: '350px', padding: '12px', borderRight: '1px solid #ddd', overflowY: 'auto' }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, display: 'block', marginBottom: 4 }}>{t('yearlyActivities.draw.featureName')}</label>
            <Input
              ref={nameInputRef}
              placeholder={t('yearlyActivities.draw.phFeatureName')}
              value={featureName}
              onChange={(e) => setFeatureName(e.target.value)}
              autoComplete="off"
              suffix={featureName ? <span style={{ color: 'green' }}>✓</span> : null}
            />
          </div>

          {availableYears && availableYears.length > 0 && (
            <div>
              <label style={{ fontSize: 12, fontWeight: 500, display: 'block', marginBottom: 4 }}>{t('yearlyActivities.draw.selectYears')}</label>
              <Checkbox.Group
                value={selectedYears}
                onChange={(vals) => setSelectedYears(vals as number[])}
                style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}
              >
                {availableYears.map(y => (
                  <Checkbox key={y.year} value={y.year} style={{ margin: 0 }}>{y.year}</Checkbox>
                ))}
              </Checkbox.Group>
            </div>
          )}

          <Radio.Group
              value={featureType}
              onChange={(e) => setFeatureType(e.target.value)}
              buttonStyle="solid"
              size="small"
              disabled={!selectedYears.length}
              style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}
            >
              <Radio.Button value="point" style={{ margin: 0 }}>{t('digitize.geom.point')}</Radio.Button>
              <Radio.Button value="line" style={{ margin: 0 }}>{t('digitize.geom.line')}</Radio.Button>
              <Radio.Button value="polygon" style={{ margin: 0 }}>{t('digitize.geom.polygon')}</Radio.Button>
            </Radio.Group>

          {/* Unit Toggle */}
          <Button
            type={measurementUnit === 'metric' ? 'primary' : 'default'}
            size="small"
            onClick={() => setMeasurementUnit(measurementUnit === 'metric' ? 'imperial' : 'metric')}
          >
            {measurementUnit === 'metric' ? t('yearlyActivities.draw.unitMetric') : t('yearlyActivities.draw.unitImperial')}
          </Button>

          {/* Layer Toggles */}
          <Card size="small" title={t('yearlyActivities.draw.referenceLayers')} style={{ marginTop: '8px' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Checkbox
                checked={showBoundary}
                onChange={(e) => setShowBoundary(e.target.checked)}
              >
                <span style={{ color: '#666' }}>⬜ {t('yearlyActivities.draw.layerBoundary')}</span>
              </Checkbox>
              <Checkbox
                checked={showBlocks}
                onChange={(e) => setShowBlocks(e.target.checked)}
              >
                <span style={{ color: '#2563eb' }}>🔵 {t('yearlyActivities.draw.layerBlocks')}</span>
              </Checkbox>
              <Checkbox
                checked={showSubAreas}
                onChange={(e) => setShowSubAreas(e.target.checked)}
              >
                <span style={{ color: '#059669' }}>🟢 {t('yearlyActivities.draw.layerSubAreas')}</span>
              </Checkbox>
              <Divider style={{ margin: '8px 0' }} />
              <Checkbox
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
              >
                <span>🏷️ {t('yearlyActivities.draw.layerLabels')}</span>
              </Checkbox>
            </Space>
          </Card>

          {/* Stop Edit Button - shows when editing */}
          {editingFeatureId && (
            <Button
              type="default"
              danger
              size="small"
              onClick={handleStopEdit}
              block
            >
              {t('yearlyActivities.draw.stopEditing')}
            </Button>
          )}

          <Button
            type={drawingMode ? 'primary' : 'default'}
            onClick={() => setDrawingMode(!drawingMode)}
            disabled={!selectedYears.length}
            block
          >
            {drawingMode ? t('yearlyActivities.draw.drawingActive') : t('yearlyActivities.draw.startDrawing')}
          </Button>

          <Card size="small">
            <p style={{ margin: 0, color: '#666', fontSize: '12px' }}>
              {featureType === 'point' && t('yearlyActivities.draw.hintPoint')}
              {featureType === 'line' && currentPoints.length < 2 && t('yearlyActivities.draw.hintLineStart')}
              {featureType === 'line' && currentPoints.length >= 2 && t('yearlyActivities.draw.hintLineFinish')}
              {featureType === 'polygon' && currentPoints.length < 3 && t('yearlyActivities.draw.hintPolygonStart')}
              {featureType === 'polygon' && currentPoints.length >= 3 && t('yearlyActivities.draw.hintPolygonFinish')}
            </p>
          </Card>
        </Space>

        <Card title={t('yearlyActivities.draw.drawnFeatures')} size="small" style={{ marginTop: '12px' }}>
          {drawnFeatures.length === 0 ? (
            <p style={{ color: '#999' }}>{t('yearlyActivities.draw.noFeatures')}</p>
          ) : (
            <List
              size="small"
              dataSource={drawnFeatures}
              renderItem={(feature: any, index: number) => {
                const isBeingEdited = editingFeatureId === feature.id;
                const isOtherBeingEdited = editingFeatureId && !isBeingEdited;
                return (
                <List.Item
                  style={{ 
                    backgroundColor: selectedFeatureId === feature.id ? '#e6f7ff' : undefined,
                    cursor: editMode === 'edit' ? 'pointer' : 'default'
                  }}
                  onClick={() => editMode === 'edit' && !isOtherBeingEdited && handleFeatureClick(feature)}
                  actions={[
                    <Button 
                      type="link" 
                      size="small"
                      onClick={() => handleStartEdit(feature)}
                      disabled={!!isOtherBeingEdited}
                      title={isOtherBeingEdited ? t('yearlyActivities.draw.stopOtherFirst') : t('yearlyActivities.draw.clickToEdit')}
                    >
                      {isBeingEdited ? t('yearlyActivities.draw.editing') : isOtherBeingEdited ? t('yearlyActivities.draw.inEdit') : t('yearlyActivities.draw.edit')}
                    </Button>,
                    <Button 
                      type="link" 
                      size="small"
                      onClick={() => {
                        setSelectedFeatureId(feature.id);
                        setEditingFeature(feature);
                      }}
                      title={t('yearlyActivities.draw.editYears')}
                    >
                      {t('yearlyActivities.draw.years')}
                    </Button>,
                    <Popconfirm
                      title={t('yearlyActivities.draw.confirmDelete')}
                      onConfirm={() => handleDeleteFeature(feature.id)}
                      disabled={isBeingEdited}
                    >
                      <Button type="link" danger size="small" disabled={isBeingEdited}>{t('common.delete')}</Button>
                    </Popconfirm>
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <EditableTag 
                        text={feature.properties?.name || t('yearlyActivities.draw.featureN', { n: formatNumber(index + 1) })}
                        onSave={async (newName) => {
                          try {
                            await yearlyActivitiesApi.updateDrawnFeature(activityId, feature.id, {
                              properties: { ...feature.properties, name: newName, label: newName }
                            });
                            onFeaturesChange();
                          } catch (error) {
                            message.error(t('yearlyActivities.draw.updateNameFailed'));
                          }
                        }}
                      />
                    }
                    description={`Years: ${feature.properties?.years?.join(', ') || feature.properties?.year || '-'} • ${feature.feature_type === 'point' ? '1 point' : feature.feature_type === 'line' ? `${feature.properties?.length_m || 0} m` : `${feature.properties?.area_sqm || 0} m²`}`}
                  />
                </List.Item>
              )}}
            />
          )}
        </Card>

        {/* Feature Options - always visible */}
        <Card 
          title={t('yearlyActivities.draw.featureOptions')} 
          size="small" 
          style={{ marginTop: '12px', borderColor: '#2563eb' }}
          extra={
            selectedFeatureId && (
              <Button size="small" onClick={() => { setSelectedFeatureId(null); setIsEditing(false); }}>
                {t('yearlyActivities.draw.clear')}
              </Button>
            )
          }
        >
          {!selectedFeatureId ? (
            <p style={{ color: '#999', fontSize: 12 }}>{t('yearlyActivities.draw.clickFeatureToSelect')}</p>
          ) : (
            <>
              {availableYears && availableYears.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <p style={{ fontSize: 11, marginBottom: 4, color: '#666' }}>{t('yearlyActivities.draw.assignedYears')}</p>
                  <Checkbox.Group
                    value={editingFeature?.properties?.years || [editingFeature?.properties?.year].filter(Boolean)}
                    onChange={(vals) => {
                      const newYears = vals as number[];
                      yearlyActivitiesApi.updateDrawnFeature(activityId, editingFeature.id, {
                        properties: { 
                          ...editingFeature?.properties, 
                          years: newYears,
                          year: newYears[0]
                        }
                      }).then(() => {
                        // Update local state too
                        setEditingFeature({
                          ...editingFeature,
                          properties: { ...editingFeature?.properties, years: newYears, year: newYears[0] }
                        });
                        onFeaturesChange();
                        message.success(t('yearlyActivities.draw.msgYearsUpdated'));
                      });
                    }}
                    style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}
                  >
                    {availableYears.map(y => (
                      <Checkbox key={y.year} value={y.year} style={{ margin: 0 }}>{y.year}</Checkbox>
                    ))}
                  </Checkbox.Group>
                </div>
              )}
              
              <Button 
                type="primary" 
                danger 
                block
                style={{ marginTop: 12 }}
                onClick={() => handleDeleteFeature(selectedFeatureId)}
              >
                {t('common.delete')}
              </Button>
            </>
          )}
        </Card>
      </div>

      <div style={{ flex: 1, position: 'relative' }}>
        <MapContainer
          center={[27.7172, 85.3240]}
          zoom={13}
          style={{ height: '100%' }}
          ref={mapRef}
        >
          <TileLayer
            attribution={BASE_MAPS[baseMap].attribution}
            url={BASE_MAPS[baseMap].url}
          />
          <NumericScale />
          
          {/* Boundary/Block/SubArea layers rendered by renderBoundaryLayers() */}
          <MapEventsHandler onClick={handleMapClick} onDoubleClick={handleDoubleClick} blocksWithSubAreas={blocksWithSubAreas} />
          {renderBoundaryLayers()}
          {renderLabels()}
          {renderFeatures()}
          {currentPoints.length > 1 && (featureType === 'line' || featureType === 'polygon') && (
            <Polyline
              positions={currentPoints.map(p => [p.lat, p.lng])}
              color="#2563eb"
              weight={3}
              dashArray="5, 10"
            />
          )}
          {/* Draggable vertex markers during drawing - right-click to delete */}
          {currentPoints.length > 0 && (featureType === 'line' || featureType === 'polygon') && (
            <>
              {currentPoints.map((pos, index) => (
                <Marker
                  key={`draw-vertex-${index}`}
                  position={pos}
                  draggable={true}
                  opacity={0.9}
                  eventHandlers={{
                    dragend: (e) => handleVertexDrag(index, e),
                    contextmenu: () => handleVertexDelete(index)
                  }}
                />
              ))}
              {/* Show live measurement tooltip on the shape */}
              {featureType === 'polygon' && currentPoints.length >= 3 && (
                <Polygon
                  positions={currentPoints.map(p => [p.lat, p.lng])}
                  color="#2563eb"
                  weight={2}
                  fillOpacity={0.1}
                >
                  <Tooltip permanent direction="center" opacity={0.9}>
                    {formatArea(currentArea)}
                  </Tooltip>
                </Polygon>
              )}
              {featureType === 'line' && currentPoints.length >= 2 && (
                <Polyline
                  positions={currentPoints.map(p => [p.lat, p.lng])}
                  color="#2563eb"
                  weight={3}
                >
                  <Tooltip permanent direction="top" opacity={0.9}>
                    {formatLength(currentLength)}
                  </Tooltip>
                </Polyline>
              )}
            </>
          )}
        </MapContainer>
        
        {/* Live Measurement Overlay */}
        <div style={{
          position: 'absolute',
          top: 10,
          right: 10,
          zIndex: 1000,
          backgroundColor: 'rgba(255,255,255,0.95)',
          padding: '8px 12px',
          borderRadius: 4,
          boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
          fontSize: '13px'
        }}>
          {/* Show editing vertices measurements */}
          {editingVertices.length > 0 && (
            <>
              {featureType === 'line' && editingVertices.length >= 2 && (
                <div><strong>{t('yearlyActivities.draw.length')}</strong> {formatLength(currentLength)}</div>
              )}
              {featureType === 'polygon' && editingVertices.length >= 3 && (
                <div><strong>{t('yearlyActivities.draw.area')}</strong> {formatArea(currentArea)}</div>
              )}
              <div style={{ marginTop: 4, fontSize: 11, color: '#666' }}>
                Vertices: {editingVertices.length} (drag to move, right-click to delete)
              </div>
            </>
          )}
          {/* Show current drawing measurements */}
          {editingVertices.length === 0 && (
            <>
              {featureType === 'line' && currentPoints.length >= 2 && (
                <div><strong>{t('yearlyActivities.draw.length')}</strong> {formatLength(currentLength)}</div>
              )}
              {featureType === 'polygon' && currentPoints.length >= 3 && (
                <div><strong>{t('yearlyActivities.draw.area')}</strong> {formatArea(currentArea)}</div>
              )}
              {(featureType === 'line' || featureType === 'polygon') && currentPoints.length > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: '#666' }}>
                  Points: {currentPoints.length} (drag to move, right-click to delete)
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

interface MapEventsHandlerProps {
  onClick: (e: L.LeafletMouseEvent) => void;
  onDoubleClick: (e: L.LeafletEvent) => void;
}

const MapEventsHandler: React.FC<MapEventsHandlerProps & { blocksWithSubAreas?: BlockSubArea[] }> = ({ onClick, onDoubleClick, blocksWithSubAreas }) => {
  const map = useMap();
  const [zoomDone, setZoomDone] = useState(false);
  
  useEffect(() => {
    if (map && !zoomDone && blocksWithSubAreas && blocksWithSubAreas.length > 0) {
      const bounds = L.latLngBounds([]);
      let hasCoords = false;
      blocksWithSubAreas.forEach((layer: BlockSubArea) => {
        if (layer.geometry) {
          try {
            const gj = typeof layer.geometry === 'string' ? JSON.parse(layer.geometry) : layer.geometry;
            if (gj.coordinates) {
              let allCoords: number[][] = [];
              if (gj.type === 'Polygon') {
                allCoords = gj.coordinates[0];
              } else if (gj.type === 'MultiPolygon') {
                gj.coordinates.forEach((poly: number[][][]) => {
                  allCoords = allCoords.concat(poly[0]);
                });
              } else {
                allCoords = gj.coordinates;
              }
              allCoords.forEach((c: number[]) => {
                bounds.extend([c[1], c[0]]);
                hasCoords = true;
              });
            }
          } catch (e) { console.warn('Layer bounds error', e); }
        }
      });
      if (hasCoords && bounds.isValid()) {
        map.fitBounds(bounds, { padding: [50, 50] });
        setZoomDone(true);
      }
    }
  }, [map, blocksWithSubAreas, zoomDone]);
  
  useMapEvents({
    click: onClick,
    dblclick: (e) => {
      onDoubleClick(e);
    }
  });
  return null;
};

export default DrawingCanvas;