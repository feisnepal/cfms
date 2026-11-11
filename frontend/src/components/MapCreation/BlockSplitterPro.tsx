/** Pro block splitter with markers, popups, and polyline preview for advanced splitting workflows. */
import React, { useState, useEffect, useRef } from 'react';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import * as turf from '@turf/turf';
import {
  validateBlocksNoOverlap,
  validateBlockAreaSum,
  calculateAreaHectares,
  formatArea,
  splitPolygonWithLine,
  isPointInPolygon,
} from '../../utils/geometryValidation';
import {
  snapPointToLine,
  ensurePolygon,
  roundCoordinates,
  applyInwardBuffer,
  getGeometryCenter,
  GEOMETRY_CONFIG,
} from '../../utils/geometryHelpers';
import { GPSPoint } from '../../utils/gpsUtils';
import BaseMapSelector from './BaseMapSelector';
import { NumericScale } from '../NumericScale';

interface Block {
  id: string;
  name: string;
  geometry: any;
  area: number;
}

interface SplitLine {
  id: string;
  geometry: any; // LineString geometry
}

interface NamingPoint {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
}

interface BlockSplitterProps {
  outerBoundary: any;
  gpsPoints?: GPSPoint[];
  onBlocksChange: (blocks: Block[]) => void;
  initialBlocks?: Block[];
}

type DrawingStep = 'lines' | 'points' | 'preview' | 'done';

// Map component with drawing controls
const ProDrawingControls: React.FC<{
  step: DrawingStep;
  outerBoundary: any;
  lines: SplitLine[];
  points: NamingPoint[];
  previewBlocks: Block[];
  finalBlocks: Block[];
  onLineDrawn: (geometry: any) => void;
  onPointPlaced: (coords: [number, number]) => void;
  onLineDelete: (lineId: string) => void;
  onPointDelete: (pointId: string) => void;
}> = ({
  step,
  outerBoundary,
  lines,
  points,
  previewBlocks,
  finalBlocks,
  onLineDrawn,
  onPointPlaced,
  onLineDelete,
  onPointDelete,
}) => {
  const map = useMap();
  const linesLayerRef = useRef<Map<string, L.Layer>>(new Map());
  const blocksLayerRef = useRef<Map<string, L.Layer>>(new Map());

  useEffect(() => {
    // Configure drawing controls based on step
    if (step === 'lines') {
      map.pm.addControls({
        position: 'topleft',
        drawPolyline: true,
        drawPolygon: false,
        drawMarker: false,
        drawCircle: false,
        drawCircleMarker: false,
        drawRectangle: false,
        editMode: true,
        dragMode: false,
        cutPolygon: false,
        removalMode: true,
      });
    } else if (step === 'points') {
      map.pm.addControls({
        position: 'topleft',
        drawMarker: true,
        drawPolyline: false,
        drawPolygon: false,
        drawCircle: false,
        drawCircleMarker: false,
        drawRectangle: false,
        editMode: false,
        dragMode: false,
        cutPolygon: false,
        removalMode: true,
      });
    } else {
      map.pm.removeControls();
    }

    const handleCreate = (e: any) => {
      const layer = e.layer;
      const geoJSON = layer.toGeoJSON();

      if (geoJSON.geometry.type === 'LineString') {
        onLineDrawn(geoJSON.geometry);
        // Keep the line visible but store reference
        linesLayerRef.current.set(`temp-${Date.now()}`, layer);
      } else if (geoJSON.geometry.type === 'Point') {
        const coords: [number, number] = geoJSON.geometry.coordinates;
        onPointPlaced([coords[1], coords[0]]); // [lat, lon]
        // Remove the temporary marker (we'll render our own)
        map.removeLayer(layer);
      }
    };

    map.on('pm:create', handleCreate);

    return () => {
      map.pm.removeControls();
      map.off('pm:create', handleCreate);
    };
  }, [step, map, onLineDrawn, onPointPlaced]);

  // Render split lines
  useEffect(() => {
    // Clear old line layers
    linesLayerRef.current.forEach((layer) => {
      map.removeLayer(layer);
    });
    linesLayerRef.current.clear();

    // Add new line layers
    if (step === 'lines' || step === 'points') {
      lines.forEach((line) => {
        const coords = line.geometry.coordinates.map((c: number[]) => [c[1], c[0]]);
        const polyline = L.polyline(coords, {
          color: '#ef4444',
          weight: 3,
          dashArray: '10, 5',
        });
        polyline.addTo(map);
        linesLayerRef.current.set(line.id, polyline);
      });
    }
  }, [lines, step, map]);

  // Render preview or final blocks
  useEffect(() => {
    console.log(`[ProDrawingControls] Rendering blocks - step: ${step}, previewBlocks: ${previewBlocks.length}, finalBlocks: ${finalBlocks.length}`);

    // Clear old block layers
    blocksLayerRef.current.forEach((layer) => {
      map.removeLayer(layer);
    });
    blocksLayerRef.current.clear();

    const blocksToRender = step === 'preview' ? previewBlocks : step === 'done' ? finalBlocks : [];

    console.log(`[ProDrawingControls] Blocks to render: ${blocksToRender.length}`);

    blocksToRender.forEach((block, index) => {
      console.log(`[ProDrawingControls] Rendering block ${index + 1}:`, {
        id: block.id,
        name: block.name,
        area: block.area,
        geometry: block.geometry ? 'defined' : 'undefined'
      });

      // Skip blocks with undefined geometry
      if (!block.geometry) {
        console.warn(`[ProDrawingControls] Skipping block ${block.name} - no geometry`);
        return;
      }

      try {
        const geoJsonLayer = L.geoJSON(block.geometry, {
          style: {
            color: step === 'preview' ? '#f59e0b' : '#3b82f6',
            weight: 3,
            fillOpacity: step === 'preview' ? 0.3 : 0.2, // Increased opacity for better visibility
          },
        });

        // Add label in center
        try {
          const geoJsonForCentroid = L.geoJSON(block.geometry);
          const centroid = geoJsonForCentroid.getBounds().getCenter();
          const label = L.marker(centroid, {
          icon: L.divIcon({
            className: 'block-label',
            html: `<div style="background: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; border: 2px solid ${step === 'preview' ? '#f59e0b' : '#3b82f6'};">${block.name}</div>`,
          }),
        });

        geoJsonLayer.addTo(map);
        label.addTo(map);
        blocksLayerRef.current.set(block.id, geoJsonLayer);
        blocksLayerRef.current.set(`${block.id}-label`, label);

        console.log(`[ProDrawingControls] Successfully added block ${block.name} to map`);
        } catch (centroidError) {
          console.error(`[ProDrawingControls] Error getting centroid for block ${block.name}:`, centroidError);
        }
      } catch (error) {
        console.error(`[ProDrawingControls] Error rendering block ${block.name}:`, error);
      }
    });

    console.log(`[ProDrawingControls] Finished rendering ${blocksToRender.length} blocks`);
  }, [previewBlocks, finalBlocks, step, map]);

  return null;
};

const BlockSplitterPro: React.FC<BlockSplitterProps> = ({
  outerBoundary,
  gpsPoints = [],
  onBlocksChange,
  initialBlocks = [],
}) => {
  const t = useT();
  const [step, setStep] = useState<DrawingStep>('lines');
  const [lines, setLines] = useState<SplitLine[]>([]);
  const [points, setPoints] = useState<NamingPoint[]>([]);
  const [previewBlocks, setPreviewBlocks] = useState<Block[]>([]);
  const [finalBlocks, setFinalBlocks] = useState<Block[]>(initialBlocks);
  const [error, setError] = useState<string>('');
  const [selectedPointId, setSelectedPointId] = useState<string | null>(null);

  // Handle line drawn
  const handleLineDrawn = (geometry: any) => {
    const newLine: SplitLine = {
      id: `line-${Date.now()}`,
      geometry,
    };
    setLines([...lines, newLine]);
  };

  // Handle point placed
  const handlePointPlaced = (coords: [number, number]) => {
    const newPoint: NamingPoint = {
      id: `point-${Date.now()}`,
      name: `Block ${points.length + 1}`,
      latitude: coords[0],
      longitude: coords[1],
    };
    setPoints([...points, newPoint]);
  };

  // Delete line
  const handleDeleteLine = (lineId: string) => {
    setLines(lines.filter(l => l.id !== lineId));
  };

  // Delete point
  const handleDeletePoint = (pointId: string) => {
    setPoints(points.filter(p => p.id !== pointId));
    if (selectedPointId === pointId) {
      setSelectedPointId(null);
    }
  };

  // Update point name
  const handlePointNameChange = (pointId: string, newName: string) => {
    setPoints(points.map(p => p.id === pointId ? { ...p, name: newName } : p));
  };

  // Generate preview using polygonize (Feature to Polygon approach)
  const handlePreview = () => {
    setError('');

    try {
      console.log('[BlockSplitter] Starting polygonize approach');
      console.log('[BlockSplitter] Split lines:', lines.length);

      // Check if outerBoundary is valid
      if (!outerBoundary || !outerBoundary.coordinates) {
        setError(t('digitize.splitter.errInvalidBoundary'));
        return;
      }

      // Handle MultiPolygon (multiple islands) - collect lines from all polygons
      const allLines: any[] = [];

      if (outerBoundary.type === 'MultiPolygon') {
        console.log('[BlockSplitter] MultiPolygon detected - handling', outerBoundary.coordinates.length, 'polygons');
        
        // Convert each polygon to line and add to collection
        outerBoundary.coordinates.forEach((polyCoords: any, idx: number) => {
          try {
            const polyFeature = turf.polygon(polyCoords);
            const line = turf.polygonToLine(polyFeature);
            allLines.push(line);
            console.log(`[BlockSplitter] Added polygon ${idx + 1} as line`);
          } catch (err) {
            console.error(`[BlockSplitter] Failed to convert polygon ${idx + 1}:`, err);
          }
        });

        if (allLines.length === 0) {
          setError(t('digitize.splitter.errMultiPolygon'));
          return;
        }
      } else if (outerBoundary.type === 'Polygon') {
        // Single polygon - convert to line
        const outerBoundaryLine = turf.polygonToLine(turf.feature(outerBoundary));
        console.log('[BlockSplitter] Converted outer boundary to line');
        allLines.push(outerBoundaryLine);
      } else {
        setError(`Unsupported geometry type: ${outerBoundary.type}`);
        return;
      }

      console.log(`[BlockSplitter] Total boundary lines: ${allLines.length}`);

      lines.forEach((line, idx) => {
        const lineFeature = turf.feature(line.geometry);
        allLines.push(lineFeature);
        console.log(`[BlockSplitter] Added split line ${idx + 1} with ${line.geometry.coordinates.length} points`);
      });

      console.log(`[BlockSplitter] Total lines for polygonize: ${allLines.length}`);

      // Step 2.5: Split lines at ALL intersection points to create proper topology
      console.log('[BlockSplitter] Processing line intersections...');
      const processedLines: any[] = [];

      for (let i = 0; i < allLines.length; i++) {
        let segmentsToAdd: any[] = [allLines[i]];

        // Check intersections with all other lines
        for (let j = 0; j < allLines.length; j++) {
          if (i === j) continue;

          const otherLine = allLines[j];
          const newSegments: any[] = [];

          // For each segment, split at intersections
          for (const segment of segmentsToAdd) {
            try {
              const intersections = turf.lineIntersect(segment, otherLine);

              if (intersections.features.length === 0) {
                newSegments.push(segment);
              } else {
                console.log(`[BlockSplitter]   Line ${i+1} x Line ${j+1}: ${intersections.features.length} intersection(s)`);

                // Get coordinates and split points
                const coords = segment.geometry.coordinates;
                const splitPoints = intersections.features.map((f: any) => f.geometry.coordinates);

                // Sort split points by distance from line start
                const sortedPoints = splitPoints.sort((a: any, b: any) => {
                  const distA = turf.distance(turf.point(coords[0]), turf.point(a));
                  const distB = turf.distance(turf.point(coords[0]), turf.point(b));
                  return distA - distB;
                });

                // Split line at each point
                let remainingLine = segment;
                for (const splitPoint of sortedPoints) {
                  try {
                    const split = turf.lineSplit(remainingLine, turf.point(splitPoint));
                    if (split.features.length >= 2) {
                      newSegments.push(split.features[0]);
                      remainingLine = split.features[split.features.length - 1];
                    }
                  } catch (e) {
                    // Split failed, keep segment
                  }
                }
                if (remainingLine) newSegments.push(remainingLine);
              }
            } catch (err) {
              newSegments.push(segment);
            }
          }

          segmentsToAdd = newSegments;
        }

        processedLines.push(...segmentsToAdd);
      }

      console.log(`[BlockSplitter] After splitting: ${processedLines.length} line segments`);

      // Debug: Log each segment
      processedLines.forEach((line, idx) => {
        const coords = line.geometry.coordinates;
        console.log(`[BlockSplitter]   Segment ${idx + 1}: ${coords.length} points, start: [${coords[0][0].toFixed(6)}, ${coords[0][1].toFixed(6)}], end: [${coords[coords.length-1][0].toFixed(6)}, ${coords[coords.length-1][1].toFixed(6)}]`);
      });

      // Step 3: Snap nearby endpoints to ensure proper network topology
      console.log('[BlockSplitter] Snapping nearby endpoints...');
      const snapTolerance = 0.000001; // ~0.1 meters in degrees
      const snappedLines: any[] = [];

      // Build a map of all unique endpoints
      const endpointMap = new Map<string, [number, number]>();

      for (const line of processedLines) {
        const coords = line.geometry.coordinates;
        if (coords.length < 2) continue;

        const start = coords[0];
        const end = coords[coords.length - 1];

        // Find or add snapped start point
        let snappedStart = start;
        for (const [key, coord] of endpointMap.entries()) {
          const dist = Math.sqrt(
            Math.pow(coord[0] - start[0], 2) + Math.pow(coord[1] - start[1], 2)
          );
          if (dist < snapTolerance) {
            snappedStart = coord;
            break;
          }
        }
        if (snappedStart === start) {
          const key = `${start[0].toFixed(8)},${start[1].toFixed(8)}`;
          endpointMap.set(key, start);
        }

        // Find or add snapped end point
        let snappedEnd = end;
        for (const [key, coord] of endpointMap.entries()) {
          const dist = Math.sqrt(
            Math.pow(coord[0] - end[0], 2) + Math.pow(coord[1] - end[1], 2)
          );
          if (dist < snapTolerance) {
            snappedEnd = coord;
            break;
          }
        }
        if (snappedEnd === end) {
          const key = `${end[0].toFixed(8)},${end[1].toFixed(8)}`;
          endpointMap.set(key, end);
        }

        // Create new line with snapped endpoints and deduplicate consecutive points
        let snappedCoords = [snappedStart, ...coords.slice(1, -1), snappedEnd];

        // Remove duplicate consecutive coordinates
        const deduplicatedCoords: [number, number][] = [];
        for (let i = 0; i < snappedCoords.length; i++) {
          const coord = snappedCoords[i];

          // Always add first point
          if (i === 0) {
            deduplicatedCoords.push(coord);
            continue;
          }

          // Check if this point is different from the previous point
          const prevCoord = deduplicatedCoords[deduplicatedCoords.length - 1];
          const dist = Math.sqrt(
            Math.pow(coord[0] - prevCoord[0], 2) +
            Math.pow(coord[1] - prevCoord[1], 2)
          );

          // Only add if different from previous point
          if (dist >= snapTolerance) {
            deduplicatedCoords.push(coord);
          }
        }

        // Only add if line has at least 2 distinct points and valid length
        if (deduplicatedCoords.length >= 2) {
          const start = deduplicatedCoords[0];
          const end = deduplicatedCoords[deduplicatedCoords.length - 1];
          const dist = Math.sqrt(
            Math.pow(end[0] - start[0], 2) +
            Math.pow(end[1] - start[1], 2)
          );

          if (dist >= snapTolerance) {
            snappedLines.push(turf.lineString(deduplicatedCoords));
          } else {
            console.log(`[BlockSplitter]   Skipping degenerate segment (length: ${dist.toFixed(8)})`);
          }
        } else {
          console.log(`[BlockSplitter]   Skipping line with less than 2 distinct points`);
        }
      }

      console.log(`[BlockSplitter] After snapping: ${snappedLines.length} line segments (removed ${processedLines.length - snappedLines.length} degenerate segments)`);

      // Step 4: Validate all line geometries before polygonize
      console.log('[BlockSplitter] Validating line geometries...');
      const validLines: any[] = [];

      for (let i = 0; i < snappedLines.length; i++) {
        const line = snappedLines[i];
        const coords = line.geometry.coordinates;

        // Check for valid number of points
        if (coords.length < 2) {
          console.warn(`[BlockSplitter]   Line ${i + 1}: INVALID - Less than 2 points (${coords.length})`);
          continue;
        }

        // Check for duplicate start/end points (zero-length line)
        const start = coords[0];
        const end = coords[coords.length - 1];
        const dist = Math.sqrt(
          Math.pow(end[0] - start[0], 2) + Math.pow(end[1] - start[1], 2)
        );

        if (dist < 0.000001) {
          console.warn(`[BlockSplitter]   Line ${i + 1}: INVALID - Zero length (start = end)`);
          continue;
        }

        // Check for NaN or invalid coordinates
        let hasInvalidCoords = false;
        for (const coord of coords) {
          if (!Array.isArray(coord) || coord.length !== 2 ||
              isNaN(coord[0]) || isNaN(coord[1]) ||
              !isFinite(coord[0]) || !isFinite(coord[1])) {
            hasInvalidCoords = true;
            break;
          }
        }

        if (hasInvalidCoords) {
          console.warn(`[BlockSplitter]   Line ${i + 1}: INVALID - Contains NaN or infinite coordinates`);
          continue;
        }

        // Line is valid
        validLines.push(line);
        console.log(`[BlockSplitter]   Line ${i + 1}: VALID - ${coords.length} points, length: ${dist.toFixed(8)}`);
      }

      console.log(`[BlockSplitter] Valid lines for polygonize: ${validLines.length} / ${snappedLines.length}`);

      if (validLines.length < 3) {
        throw new Error(`Not enough valid line segments to create blocks (found ${validLines.length}, need at least 3). Try drawing split lines that clearly intersect each other and the boundary.`);
      }

      // Step 5: Create a FeatureCollection from validated lines
      const lineCollection = turf.featureCollection(validLines);

      // Log the line collection for debugging
      console.log('[BlockSplitter] Line collection for polygonize:', JSON.stringify(lineCollection, null, 2));

      // Step 6: Polygonize - this is the "Feature to Polygon" operation!
      let polygonized;
      try {
        polygonized = turf.polygonize(lineCollection as any);
        console.log(`[BlockSplitter] Polygonize created ${polygonized.features.length} polygons`);
      } catch (polygonizeError: any) {
        console.error('[BlockSplitter] Polygonize error:', polygonizeError);
        console.error('[BlockSplitter] Line collection that failed:', lineCollection);
        throw new Error(t('digitize.splitter.errSplitFailed', {
          detail: polygonizeError.message || t('digitize.splitter.errInvalidGeometry'),
        }));
      }

      // Debug: If only 1 polygon created but we expected 2, check line network
      if (polygonized.features.length === 1 && snappedLines.length > 0) {
        console.warn('[BlockSplitter] WARNING: Only 1 polygon created from split lines.');
        console.warn('[BlockSplitter] This usually means line endpoints do not match exactly.');
        console.warn('[BlockSplitter] Checking line connectivity...');

        // Check for endpoint mismatches
        const endpoints = new Map<string, number>();
        snappedLines.forEach((line, idx) => {
          const coords = line.geometry.coordinates;
          const start = `${coords[0][0].toFixed(8)},${coords[0][1].toFixed(8)}`;
          const end = `${coords[coords.length-1][0].toFixed(8)},${coords[coords.length-1][1].toFixed(8)}`;

          endpoints.set(start, (endpoints.get(start) || 0) + 1);
          endpoints.set(end, (endpoints.get(end) || 0) + 1);
        });

        // In a valid network, all endpoints should appear exactly 2 times
        const invalidEndpoints = Array.from(endpoints.entries()).filter(([_, count]) => count !== 2);
        if (invalidEndpoints.length > 0) {
          console.error(`[BlockSplitter] Found ${invalidEndpoints.length} endpoints with incorrect connections:`);
          invalidEndpoints.forEach(([coord, count]) => {
            console.error(`[BlockSplitter]   ${coord}: connected ${count} times (should be 2)`);
          });
        }
      }

      if (!polygonized || !polygonized.features || polygonized.features.length === 0) {
        throw new Error(t('digitize.splitter.errPolygonize'));
      }

      // Step 5: Filter polygons - keep only those inside outer boundary (exclude tiny slivers)
      const outerBoundaryFeature = turf.feature(outerBoundary);
      const validPolygons: any[] = [];

      polygonized.features.forEach((feature: any, idx: number) => {
        const area = turf.area(feature);
        const areaHa = area / 10000;

        console.log(`[BlockSplitter] Polygon ${idx + 1}: ${areaHa.toFixed(2)} ha`);

        // Keep polygons that are:
        // 1. Inside the outer boundary
        // 2. Have significant area (> 0.01 ha = 100 sqm)
        if (areaHa > 0.01) {
          try {
            // Use multiple checks for robust validation
            // 1. Check if centroid is inside (fast)
            const centroid = turf.centroid(feature);
            const centroidInside = turf.booleanPointInPolygon(centroid, outerBoundaryFeature);

            console.log(`[BlockSplitter]   Centroid inside: ${centroidInside}`);

            // 2. If centroid is outside, check if polygons overlap (more thorough)
            let isValid = centroidInside;

            if (!centroidInside) {
              console.log(`[BlockSplitter]   Centroid outside, checking overlap...`);
              // Check if the polygon overlaps with the boundary
              const overlaps = turf.booleanOverlap(feature, outerBoundaryFeature);
              const intersects = turf.booleanIntersects(feature, outerBoundaryFeature);

              console.log(`[BlockSplitter]   Overlaps: ${overlaps}, Intersects: ${intersects}`);

              // If it intersects but doesn't overlap, it might be contained or adjacent
              // Check if it's actually contained
              if (intersects) {
                try {
                  const intersection = turf.intersect(feature, outerBoundaryFeature);
                  if (intersection) {
                    const intersectionArea = turf.area(intersection) / 10000;
                    const overlapPercentage = (intersectionArea / areaHa) * 100;
                    console.log(`[BlockSplitter]   Intersection area: ${intersectionArea.toFixed(2)} ha (${overlapPercentage.toFixed(1)}%)`);

                    // Accept if more than 90% of the polygon is within the boundary
                    isValid = overlapPercentage > 90;
                  }
                } catch (intersectErr) {
                  console.warn(`[BlockSplitter]   Could not calculate intersection:`, intersectErr);
                  // Fallback: accept if it intersects (might be a valid block)
                  isValid = intersects;
                }
              }
            }

            if (isValid) {
              // Apply safety measures before accepting the polygon
              let safeGeometry = feature.geometry;

              // 1. Round coordinates to avoid floating-point drift
              safeGeometry = roundCoordinates(safeGeometry, GEOMETRY_CONFIG.COORDINATE_PRECISION);
              console.log(`[BlockSplitter]   Applied coordinate rounding`);

              // 2. Apply micro-inward buffer to ensure strict containment
              const bufferedGeometry = applyInwardBuffer(safeGeometry, GEOMETRY_CONFIG.BUFFER_INWARD);
              if (bufferedGeometry) {
                safeGeometry = bufferedGeometry;
                console.log(`[BlockSplitter]   Applied inward buffer (${GEOMETRY_CONFIG.BUFFER_INWARD} degrees)`);
              }

              validPolygons.push(safeGeometry);
              console.log(`[BlockSplitter]   ✓ Valid block (inside boundary)`);
            } else {
              console.log(`[BlockSplitter]   ✗ Outside boundary, skipping`);
            }
          } catch (err) {
            console.warn(`[BlockSplitter]   ✗ Error checking polygon:`, err);
          }
        } else {
          console.log(`[BlockSplitter]   ✗ Too small, skipping`);
        }
      });

      console.log(`[BlockSplitter] Valid blocks: ${validPolygons.length}`);

      if (validPolygons.length === 0) {
        throw new Error(t('digitize.splitter.errNoBlocks'));
      }

      // Step 6: Create blocks from resulting polygons (geometries are already safe)
      const blocks: Block[] = validPolygons.map((geometry, index) => ({
        id: `preview-${index}`,
        name: `Unnamed ${index + 1}`,
        geometry,
        area: calculateAreaHectares(geometry),
      }));

      console.log(`Created ${blocks.length} blocks:`, blocks.map(b => ({ name: b.name, area: b.area })));

      // Assign names based on points inside
      blocks.forEach((block) => {
        for (const point of points) {
          const isInside = isPointInPolygon([point.longitude, point.latitude], block.geometry);
          if (isInside) {
            block.name = point.name;
            break;
          }
        }
      });

      console.log('Blocks after naming:', blocks.map(b => ({ name: b.name, area: b.area })));

      setPreviewBlocks(blocks);
      setStep('preview');
      console.log('Preview step activated with', blocks.length, 'blocks');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('digitize.splitter.errPreviewFailed'));
    }
  };

  // Process and create final blocks
  const handleProcess = () => {
    setError('');

    // Validation 1: Check if all blocks have names
    const unnamedBlocks = previewBlocks.filter(b => b.name.startsWith('Unnamed'));
    if (unnamedBlocks.length > 0) {
      setError(`${unnamedBlocks.length} block(s) don't have naming points. Please place points in all areas.`);
      return;
    }

    // Validation 2: Remove blocks < 50 sqm and notify
    const validBlocks = previewBlocks.filter(b => b.area * 10000 >= 50);
    const deletedCount = previewBlocks.length - validBlocks.length;

    if (deletedCount > 0) {
      alert(`${deletedCount} polygon(s) smaller than 50 sqm were automatically deleted.`);
    }

    if (validBlocks.length === 0) {
      setError(t('digitize.splitter.errAllTooSmall'));
      return;
    }

    // Create final blocks
    setFinalBlocks(validBlocks);
    onBlocksChange(validBlocks);

    // Clear drawing features
    setLines([]);
    setPoints([]);
    setPreviewBlocks([]);
    setStep('done');
  };

  // Cancel preview
  const handleCancelPreview = () => {
    setPreviewBlocks([]);
    setStep('points');
  };

  // Reset all
  const handleReset = () => {
    if (confirm('Reset all blocks and start over?')) {
      setLines([]);
      setPoints([]);
      setPreviewBlocks([]);
      setFinalBlocks([]);
      setStep('lines');
      onBlocksChange([]);
    }
  };

  const outerArea = calculateAreaHectares(outerBoundary);

  // Use helper function that works for both Polygon and MultiPolygon
  const mapCenter = getGeometryCenter(outerBoundary, [27.7172, 85.3240]);

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-bold mb-4">{t('digitize.splitter.title')}</h2>

        {/* Step Indicator */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <div className={`flex-1 text-center py-2 ${step === 'lines' ? 'bg-green-100 font-bold' : 'bg-gray-100'}`}>
              {t('digitize.splitter.step1')}
            </div>
            <div className={`flex-1 text-center py-2 ${step === 'points' ? 'bg-green-100 font-bold' : 'bg-gray-100'}`}>
              {t('digitize.splitter.step2')}
            </div>
            <div className={`flex-1 text-center py-2 ${step === 'preview' ? 'bg-green-100 font-bold' : 'bg-gray-100'}`}>
              {t('digitize.splitter.step3')}
            </div>
            <div className={`flex-1 text-center py-2 ${step === 'done' ? 'bg-green-100 font-bold' : 'bg-gray-100'}`}>
              {t('digitize.splitter.step4')}
            </div>
          </div>
        </div>

        {/* Instructions */}
        <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-md">
          <p className="text-sm text-blue-800">
            <strong>{t('digitize.splitter.instructions')}</strong>
            <br />
            {step === 'lines' && (
              <>
                • {t('digitize.splitter.linesStep1')}
                <br />
                • {t('digitize.splitter.linesStep2')}
                <br />
                • {t('digitize.splitter.linesStep3')}
                <br />
                • {t('digitize.splitter.linesStep4')}
                <br />
                • {t('digitize.splitter.linesStep5', { button: t('digitize.splitter.nextPlacePoints') })}
              </>
            )}
            {step === 'points' && (
              <>
                • {t('digitize.splitter.pointsStep1')}
                <br />
                • {t('digitize.splitter.pointsStep2')}
                <br />
                • {t('digitize.splitter.pointsStep3')}
                <br />
                • {t('digitize.splitter.pointsStep4')}
                <br />
                • {t('digitize.splitter.pointsStep5', { button: t('digitize.splitter.previewBlocks') })}
              </>
            )}
            {step === 'preview' && (
              <>
                • Review the blocks shown in <span className="text-orange-600 font-bold">ORANGE</span>
                <br />
                • Check if all blocks are named correctly
                <br />
                • If correct, click <strong>"Confirm & Create Blocks"</strong>
                <br />
                • If not, click <strong>"Back to Edit"</strong>
              </>
            )}
            {step === 'done' && (
              <>
                • Blocks created successfully!
                <br />
                • Blocks shown in <span className="text-blue-600 font-bold">BLUE</span>
                <br />
                • Continue to next step (Sub-areas)
              </>
            )}
          </p>
        </div>

        {/* Error Messages */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md">
            {error}
          </div>
        )}

        {/* Split Lines List */}
        {step === 'lines' && lines.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold mb-2">Split Lines ({lines.length})</h3>
            <div className="space-y-2">
              {lines.map((line, index) => (
                <div key={line.id} className="flex items-center justify-between p-2 bg-red-50 border border-red-200 rounded">
                  <span>Line {index + 1}</span>
                  <button
                    onClick={() => handleDeleteLine(line.id)}
                    className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                  >
                    Delete
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Naming Points List */}
        {(step === 'points' || step === 'preview') && points.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold mb-2">Naming Points ({points.length})</h3>
            <div className="space-y-2">
              {points.map((point) => (
                <div key={point.id} className="flex items-center gap-2 p-2 bg-green-50 border border-green-200 rounded">
                  <input
                    type="text"
                    value={point.name}
                    onChange={(e) => handlePointNameChange(point.id, e.target.value)}
                    disabled={step === 'preview'}
                    className="flex-1 px-2 py-1 border border-gray-300 rounded disabled:bg-gray-100"
                  />
                  {step === 'points' && (
                    <button
                      onClick={() => handleDeletePoint(point.id)}
                      className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                    >
                      Delete
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Preview Blocks List */}
        {step === 'preview' && previewBlocks.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold mb-2">
              {t('digitize.splitter.previewHeading', { count: formatNumber(previewBlocks.length) })}
            </h3>
            <div className="border border-gray-200 rounded overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.splitter.colName')}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.splitter.colArea')}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.splitter.colStatus')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {previewBlocks.map((block) => {
                    const tooSmall = block.area * 10000 < 50;
                    const unnamed = block.name.startsWith('Unnamed');
                    return (
                      <tr key={block.id} className={tooSmall ? 'bg-red-50' : unnamed ? 'bg-yellow-50' : 'bg-white'}>
                        <td className="px-4 py-2">{block.name}</td>
                        <td className="px-4 py-2">{formatArea(block.area)}</td>
                        <td className="px-4 py-2 text-sm">
                          {tooSmall && <span className="text-red-600">{t('digitize.splitter.willBeDeleted')}</span>}
                          {!tooSmall && unnamed && <span className="text-yellow-600">{t('digitize.splitter.missingPoint')}</span>}
                          {!tooSmall && !unnamed && <span className="text-green-600">✓ {t('digitize.splitter.ready')}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Final Blocks List */}
        {step === 'done' && finalBlocks.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold mb-2">
              {t('digitize.splitter.createdHeading', { count: formatNumber(finalBlocks.length) })}
            </h3>
            <div className="border border-gray-200 rounded overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.splitter.colBlockName')}</th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('digitize.splitter.colArea')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {finalBlocks.map((block) => (
                    <tr key={block.id}>
                      <td className="px-4 py-2">{block.name}</td>
                      <td className="px-4 py-2">{formatArea(block.area)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-3">
          {step === 'lines' && (
            <button
              onClick={() => setStep('points')}
              disabled={lines.length === 0}
              className="px-6 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              {t('digitize.splitter.nextPlacePoints')} →
            </button>
          )}

          {step === 'points' && (
            <>
              <button
                onClick={() => setStep('lines')}
                className="px-6 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700"
              >
                ← {t('digitize.splitter.backEditLines')}
              </button>
              <button
                onClick={handlePreview}
                disabled={points.length === 0}
                className="px-6 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
              >
                {t('digitize.splitter.previewBlocks')} →
              </button>
            </>
          )}

          {step === 'preview' && (
            <>
              <button
                onClick={handleCancelPreview}
                className="px-6 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700"
              >
                ← {t('digitize.splitter.backToEdit')}
              </button>
              <button
                onClick={handleProcess}
                className="px-6 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 font-semibold"
              >
                ✓ {t('digitize.splitter.confirmCreate')}
              </button>
            </>
          )}

          {step === 'done' && (
            <button
              onClick={handleReset}
              className="px-6 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700"
            >
              {t('digitize.splitter.resetStartOver')}
            </button>
          )}
        </div>
      </div>

      {/* Map */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">{t('digitize.splitter.map')}</h3>
        <div className="h-[600px] rounded overflow-hidden border border-gray-300">
          <MapContainer
            center={mapCenter as [number, number]}
            zoom={14}
            style={{ height: '100%', width: '100%' }}
          >
            <BaseMapSelector />
            <NumericScale />

            {/* Outer boundary - GREEN */}
            {outerBoundary && (
              <GeoJSON
                data={outerBoundary}
                style={{
                  color: '#10b981',
                  weight: 3,
                  fillOpacity: 0.05,
                }}
              />
            )}

            {/* GPS Points (visual reference only) */}
            {gpsPoints.map((point) => (
              <Marker
                key={point.id}
                position={[point.latitude, point.longitude]}
                opacity={0.5}
              >
                <Popup>{point.name}</Popup>
              </Marker>
            ))}

            {/* Naming Points with Labels */}
            {(step === 'points' || step === 'preview') && points.map((point) => (
              <Marker
                key={point.id}
                position={[point.latitude, point.longitude]}
                icon={L.divIcon({
                  className: 'naming-point',
                  html: `<div style="background: #10b981; color: white; padding: 6px 12px; border-radius: 20px; font-weight: bold; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3); white-space: nowrap;">${point.name}</div>`,
                  iconAnchor: [50, 15],
                })}
              />
            ))}

            {/* Drawing controls */}
            <ProDrawingControls
              step={step}
              outerBoundary={outerBoundary}
              lines={lines}
              points={points}
              previewBlocks={previewBlocks}
              finalBlocks={finalBlocks}
              onLineDrawn={handleLineDrawn}
              onPointPlaced={handlePointPlaced}
              onLineDelete={handleDeleteLine}
              onPointDelete={handleDeletePoint}
            />
          </MapContainer>
        </div>
      </div>
    </div>
  );
};

// Helper function
function checkPointInPolygon(point: [number, number], polygon: any): boolean {
  try {
    const turf = require('@turf/turf');
    const pt = turf.point(point);
    const poly = turf.feature(polygon);
    return turf.booleanPointInPolygon(pt, poly);
  } catch {
    return false;
  }
}

export default BlockSplitterPro;
