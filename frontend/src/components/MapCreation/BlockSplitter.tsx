/** Map-based block splitting tool – split GeoJSON polygons into smaller blocks interactively. */
import React, { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import {
  validateBlocksNoOverlap,
  validateBlockAreaSum,
  validateBlocksWithinBoundary,
  calculateAreaHectares,
  formatArea,
  splitPolygonWithLine,
} from '../../utils/geometryValidation';
import { NumericScale } from '../NumericScale';

interface Block {
  id: string;
  name: string;
  geometry: any;
  area: number;
}

interface BlockSplitterProps {
  outerBoundary: any;
  onBlocksChange: (blocks: Block[]) => void;
  initialBlocks?: Block[];
}

type SplitMethod = 'line' | 'polygon';

// Map component with drawing controls for blocks
const BlockDrawingControls: React.FC<{
  outerBoundary: any;
  splitMethod: SplitMethod;
  onBlockCreated: (geometry: any) => void;
  onLineSplit: (lineGeometry: any) => void;
  blocks: Block[];
  selectedBlockId: string | null;
  onBlockEdit: (blockId: string, geometry: any) => void;
  onBlockDelete: (blockId: string) => void;
}> = ({
  outerBoundary,
  splitMethod,
  onBlockCreated,
  onLineSplit,
  blocks,
  selectedBlockId,
  onBlockEdit,
  onBlockDelete,
}) => {
  const map = useMap();
  const layersRef = useRef<Map<string, L.Layer>>(new Map());

  useEffect(() => {
    // Enable Leaflet-Geoman controls based on split method
    if (splitMethod === 'line') {
      map.pm.addControls({
        position: 'topleft',
        drawPolygon: false,
        drawMarker: false,
        drawCircle: false,
        drawCircleMarker: false,
        drawPolyline: true,  // Enable line drawing for splitting
        drawRectangle: false,
        editMode: true,
        dragMode: false,
        cutPolygon: false,
        removalMode: true,
      });
    } else {
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
    }

    // Handle creation events
    const handleCreate = (e: any) => {
      const layer = e.layer;
      const geoJSON = layer.toGeoJSON();

      if (e.shape === 'Line' || geoJSON.geometry.type === 'LineString') {
        // This is a splitting line
        onLineSplit(geoJSON.geometry);
        // Remove the line layer immediately
        map.removeLayer(layer);
      } else {
        // This is a polygon block
        const tempId = `temp-${Date.now()}`;
        layersRef.current.set(tempId, layer);
        onBlockCreated(geoJSON.geometry);
      }
    };

    // Handle polygon editing
    const handleEdit = (e: any) => {
      const layers = e.layers;
      layers.eachLayer((layer: any) => {
        const geoJSON = layer.toGeoJSON();

        layersRef.current.forEach((storedLayer, blockId) => {
          if (storedLayer === layer) {
            onBlockEdit(blockId, geoJSON.geometry);
          }
        });
      });
    };

    // Handle polygon removal
    const handleRemove = (e: any) => {
      const layer = e.layer;

      layersRef.current.forEach((storedLayer, blockId) => {
        if (storedLayer === layer) {
          onBlockDelete(blockId);
          layersRef.current.delete(blockId);
        }
      });
    };

    map.on('pm:create', handleCreate);
    map.on('pm:edit', handleEdit);
    map.on('pm:remove', handleRemove);

    return () => {
      map.pm.removeControls();
      map.off('pm:create', handleCreate);
      map.off('pm:edit', handleEdit);
      map.off('pm:remove', handleRemove);

      // Remove all layers
      layersRef.current.forEach((layer) => {
        map.removeLayer(layer);
      });
      layersRef.current.clear();
    };
  }, [map, splitMethod, onBlockCreated, onLineSplit, onBlockEdit, onBlockDelete]);

  // Render existing blocks as editable layers
  useEffect(() => {
    // Remove old layers
    layersRef.current.forEach((layer) => {
      map.removeLayer(layer);
    });
    layersRef.current.clear();

    // Add new layers for each block
    blocks.forEach((block) => {
      const color = block.id === selectedBlockId ? '#ef4444' : '#3b82f6';

      const geoJsonLayer = L.geoJSON(block.geometry, {
        style: {
          color,
          weight: 3,
          fillOpacity: 0.2,
        },
        pmIgnore: false,
      });

      geoJsonLayer.addTo(map);
      layersRef.current.set(block.id, geoJsonLayer);
    });
  }, [blocks, selectedBlockId, map]);

  return null;
};

const BlockSplitter: React.FC<BlockSplitterProps> = ({
  outerBoundary,
  onBlocksChange,
  initialBlocks = [],
}) => {
  const [blocks, setBlocks] = useState<Block[]>(initialBlocks);
  const [splitMethod, setSplitMethod] = useState<SplitMethod>('line');
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [error, setError] = useState<string>('');
  const [validation, setValidation] = useState<{
    overlapValid: boolean;
    areaValid: boolean;
    withinValid: boolean;
    errors: string[];
    warnings: string[];
  }>({
    overlapValid: true,
    areaValid: true,
    withinValid: true,
    errors: [],
    warnings: [],
  });

  // Validate blocks whenever they change
  useEffect(() => {
    if (blocks.length === 0) {
      setValidation({
        overlapValid: true,
        areaValid: true,
        withinValid: true,
        errors: [],
        warnings: [],
      });
      return;
    }

    const errors: string[] = [];
    const warnings: string[] = [];

    // Check overlaps
    const overlapResult = validateBlocksNoOverlap(blocks);
    if (!overlapResult.valid) {
      errors.push(overlapResult.error || 'Blocks overlap');
    }
    if (overlapResult.warnings) {
      warnings.push(...overlapResult.warnings);
    }

    // Check area sum
    const areaResult = validateBlockAreaSum(outerBoundary, blocks, 5); // 5% tolerance
    if (!areaResult.valid) {
      errors.push(areaResult.error || 'Area mismatch');
    }
    if (areaResult.warnings) {
      warnings.push(...areaResult.warnings);
    }

    // Check blocks are within boundary
    const withinResult = validateBlocksWithinBoundary(outerBoundary, blocks);
    if (!withinResult.valid) {
      errors.push(withinResult.error || 'Block outside boundary');
    }

    setValidation({
      overlapValid: overlapResult.valid,
      areaValid: areaResult.valid,
      withinValid: withinResult.valid,
      errors,
      warnings,
    });

    // Update parent
    onBlocksChange(blocks);
  }, [blocks, outerBoundary, onBlocksChange]);

  // Handle line-based splitting
  const handleLineSplit = (lineGeometry: any) => {
    setError('');

    try {
      // If no blocks exist, split the outer boundary
      if (blocks.length === 0) {
        const resultPolygons = splitPolygonWithLine(outerBoundary, lineGeometry);

        const newBlocks: Block[] = resultPolygons.map((geometry, index) => ({
          id: `block-${Date.now()}-${index}`,
          name: `Block ${index + 1}`,
          geometry,
          area: calculateAreaHectares(geometry),
        }));

        setBlocks(newBlocks);
        return;
      }

      // If blocks exist, ask which one to split
      if (selectedBlockId) {
        const selectedBlock = blocks.find(b => b.id === selectedBlockId);
        if (selectedBlock) {
          const resultPolygons = splitPolygonWithLine(selectedBlock.geometry, lineGeometry);

          // Replace the selected block with the split results
          const newBlocks = blocks.filter(b => b.id !== selectedBlockId);
          const splitBlocks: Block[] = resultPolygons.map((geometry, index) => ({
            id: `block-${Date.now()}-${index}`,
            name: index === 0 ? selectedBlock.name : `${selectedBlock.name}-${index + 1}`,
            geometry,
            area: calculateAreaHectares(geometry),
          }));

          setBlocks([...newBlocks, ...splitBlocks]);
          setSelectedBlockId(null);
          return;
        }
      }

      // No block selected, try to split the first block that intersects the line
      setError('Please select a block to split, or draw the first split line on the outer boundary');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to split polygon');
    }
  };

  // Handle direct polygon creation
  const handleBlockCreated = (geometry: any) => {
    setError('');

    try {
      const area = calculateAreaHectares(geometry);
      const newBlock: Block = {
        id: `block-${Date.now()}`,
        name: `Block ${blocks.length + 1}`,
        geometry,
        area,
      };

      setBlocks([...blocks, newBlock]);
    } catch (err) {
      setError('Failed to create block');
    }
  };

  // Handle block edit
  const handleBlockEdit = (blockId: string, geometry: any) => {
    try {
      const area = calculateAreaHectares(geometry);
      setBlocks(
        blocks.map((block) =>
          block.id === blockId ? { ...block, geometry, area } : block
        )
      );
    } catch (err) {
      setError('Failed to update block');
    }
  };

  // Handle block delete
  const handleBlockDelete = (blockId: string) => {
    const newBlocks = blocks.filter((b) => b.id !== blockId);

    // Renumber remaining blocks
    newBlocks.forEach((block, index) => {
      block.name = `Block ${index + 1}`;
    });

    setBlocks(newBlocks);
    if (selectedBlockId === blockId) {
      setSelectedBlockId(null);
    }
  };

  // Handle block name change
  const handleBlockNameChange = (blockId: string, newName: string) => {
    setBlocks(
      blocks.map((block) =>
        block.id === blockId ? { ...block, name: newName } : block
      )
    );
  };

  // Delete selected block
  const handleDeleteSelected = () => {
    if (selectedBlockId) {
      handleBlockDelete(selectedBlockId);
    }
  };

  // Clear all blocks
  const handleClearAll = () => {
    if (confirm('Are you sure you want to delete all blocks?')) {
      setBlocks([]);
      setSelectedBlockId(null);
    }
  };

  // Calculate total area
  const totalBlockArea = blocks.reduce((sum, block) => sum + block.area, 0);
  const outerArea = calculateAreaHectares(outerBoundary);
  const areaDiff = Math.abs(outerArea - totalBlockArea);
  const areaDiffPercent = (areaDiff / outerArea) * 100;

  const mapCenter = outerBoundary
    ? [
        (outerBoundary.coordinates[0][0][1] + outerBoundary.coordinates[0][2][1]) / 2,
        (outerBoundary.coordinates[0][0][0] + outerBoundary.coordinates[0][2][0]) / 2,
      ]
    : [27.7172, 85.3240];

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg shadow">
        <h2 className="text-xl font-bold mb-4">Create Forest Blocks</h2>

        {/* Split Method Selector */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Block Creation Method
          </label>
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => setSplitMethod('line')}
              className={`px-4 py-3 rounded-lg border-2 transition-colors text-left ${
                splitMethod === 'line'
                  ? 'border-green-600 bg-green-50'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              <div className="font-semibold">Split with Line</div>
              <div className="text-sm text-gray-600 mt-1">
                Draw lines to split boundary into blocks
              </div>
            </button>
            <button
              onClick={() => setSplitMethod('polygon')}
              className={`px-4 py-3 rounded-lg border-2 transition-colors text-left ${
                splitMethod === 'polygon'
                  ? 'border-green-600 bg-green-50'
                  : 'border-gray-300 hover:border-gray-400'
              }`}
            >
              <div className="font-semibold">Draw Polygons</div>
              <div className="text-sm text-gray-600 mt-1">
                Draw separate polygons for each block
              </div>
            </button>
          </div>
        </div>

        {/* Instructions */}
        <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-md">
          <p className="text-sm text-blue-800">
            <strong>Instructions:</strong>
            <br />
            {splitMethod === 'line' ? (
              <>
                • Click the <strong>line icon</strong> in the map toolbar
                <br />
                • Draw a line across the boundary or selected block to split it
                <br />
                • The line must cross completely from one edge to another
                <br />
                • Blocks will appear immediately after drawing the line
                <br />
                • Select a block (click in list) before splitting to split that specific block
              </>
            ) : (
              <>
                • Click the <strong>polygon icon</strong> in the map toolbar to draw blocks
                <br />
                • Draw polygons within the outer boundary (green outline)
                <br />
                • Blocks must not overlap each other
                <br />
                • Click on a block in the list below to select it
              </>
            )}
            <br />• Use <strong>edit mode</strong> to modify blocks, <strong>delete mode</strong> to remove
          </p>
        </div>

        {/* Validation Status */}
        {validation.errors.length > 0 && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md">
            <strong>Validation Errors:</strong>
            <ul className="list-disc list-inside mt-1">
              {validation.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {validation.warnings.length > 0 && (
          <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 text-yellow-700 rounded-md">
            <strong>Warnings:</strong>
            <ul className="list-disc list-inside mt-1">
              {validation.warnings.map((warning, i) => (
                <li key={i}>{warning}</li>
              ))}
            </ul>
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded-md">
            {error}
          </div>
        )}

        {/* Area Summary */}
        <div className="mb-4 p-4 bg-gray-50 border border-gray-200 rounded-md">
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-gray-600">Outer Boundary:</span>
              <div className="font-semibold text-lg">{formatArea(outerArea)}</div>
            </div>
            <div>
              <span className="text-gray-600">Total Blocks:</span>
              <div className="font-semibold text-lg">{formatArea(totalBlockArea)}</div>
            </div>
            <div>
              <span className="text-gray-600">Difference:</span>
              <div
                className={`font-semibold text-lg ${
                  areaDiffPercent > 5 ? 'text-red-600' : 'text-green-600'
                }`}
              >
                {formatArea(areaDiff)} ({areaDiffPercent.toFixed(1)}%)
              </div>
            </div>
          </div>
        </div>

        {/* Blocks List */}
        {blocks.length > 0 && (
          <div className="mb-4">
            <div className="flex justify-between items-center mb-2">
              <h3 className="font-semibold">Blocks ({blocks.length})</h3>
              <div className="flex gap-2">
                {selectedBlockId && (
                  <button
                    onClick={handleDeleteSelected}
                    className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
                  >
                    Delete Selected
                  </button>
                )}
                <button
                  onClick={handleClearAll}
                  className="px-3 py-1 text-sm bg-gray-600 text-white rounded hover:bg-gray-700 transition-colors"
                >
                  Clear All
                </button>
              </div>
            </div>

            <div className="border border-gray-200 rounded overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                      Block Name
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                      Area
                    </th>
                    <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {blocks.map((block) => (
                    <tr
                      key={block.id}
                      className={`hover:bg-gray-50 cursor-pointer ${
                        selectedBlockId === block.id ? 'bg-blue-50' : ''
                      }`}
                      onClick={() => setSelectedBlockId(block.id)}
                    >
                      <td className="px-4 py-2">
                        <input
                          type="text"
                          value={block.name}
                          onChange={(e) =>
                            handleBlockNameChange(block.id, e.target.value)
                          }
                          onClick={(e) => e.stopPropagation()}
                          className="w-full px-2 py-1 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </td>
                      <td className="px-4 py-2 text-sm">{formatArea(block.area)}</td>
                      <td className="px-4 py-2">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleBlockDelete(block.id);
                          }}
                          className="text-red-600 hover:text-red-800 text-sm"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Map */}
      <div className="bg-white p-6 rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-4">Map</h3>
        <div className="h-[600px] rounded overflow-hidden border border-gray-300">
          <MapContainer
            center={mapCenter as [number, number]}
            zoom={14}
            style={{ height: '100%', width: '100%' }}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            />
            <NumericScale />

            {/* Outer boundary */}
            {outerBoundary && (
              <GeoJSON
                data={outerBoundary}
                style={{
                  color: '#10b981',
                  weight: 3,
                  fillOpacity: 0.1,
                  dashArray: '10, 5',
                }}
              />
            )}

            {/* Drawing controls */}
            <BlockDrawingControls
              outerBoundary={outerBoundary}
              splitMethod={splitMethod}
              onBlockCreated={handleBlockCreated}
              onLineSplit={handleLineSplit}
              blocks={blocks}
              selectedBlockId={selectedBlockId}
              onBlockEdit={handleBlockEdit}
              onBlockDelete={handleBlockDelete}
            />
          </MapContainer>
        </div>
      </div>
    </div>
  );
};

export default BlockSplitter;
