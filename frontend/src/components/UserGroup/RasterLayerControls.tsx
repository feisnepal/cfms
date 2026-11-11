/** Raster layer controls — toggles visibility of land-cover, DEM, and other raster overlays on the map. */
import React from 'react';
import { Layers, Info, Eye, EyeOff } from 'lucide-react';

interface RasterLayerControlsProps {
  landCoverEnabled: boolean;
  landCoverOpacity: number;
  biomassEnabled: boolean;
  biomassOpacity: number;
  legendType: 'landcover' | 'biomass' | null;
  clickQueryEnabled: boolean;
  onLandCoverToggle: (enabled: boolean) => void;
  onLandCoverOpacityChange: (opacity: number) => void;
  onBiomassToggle: (enabled: boolean) => void;
  onBiomassOpacityChange: (opacity: number) => void;
  onLegendToggle: (type: 'landcover' | 'biomass' | null) => void;
  onClickQueryToggle: (enabled: boolean) => void;
}

export function RasterLayerControls({
  landCoverEnabled,
  landCoverOpacity,
  biomassEnabled,
  biomassOpacity,
  legendType,
  clickQueryEnabled,
  onLandCoverToggle,
  onLandCoverOpacityChange,
  onBiomassToggle,
  onBiomassOpacityChange,
  onLegendToggle,
  onClickQueryToggle,
}: RasterLayerControlsProps) {
  return (
    <div className="bg-white rounded-lg shadow-lg p-4 w-72 flex-shrink-0" style={{ height: 'fit-content' }}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-4 pb-3 border-b border-gray-200">
        <Layers className="w-5 h-5 text-blue-600" />
        <h3 className="font-semibold text-gray-800">Raster Layers</h3>
      </div>

      {/* Land Cover Layer */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={landCoverEnabled}
              onChange={(e) => onLandCoverToggle(e.target.checked)}
              className="w-4 h-4 rounded text-blue-600 focus:ring-2 focus:ring-blue-500"
            />
            <span className="text-sm font-medium text-gray-700">Land Cover</span>
          </label>
          <button
            onClick={() =>
              onLegendToggle(legendType === 'landcover' ? null : 'landcover')
            }
            className={`p-1 rounded transition-colors ${
              legendType === 'landcover'
                ? 'bg-blue-100 text-blue-600'
                : 'text-gray-400 hover:text-gray-600'
            }`}
            title="Show legend"
          >
            <Info className="w-4 h-4" />
          </button>
        </div>

        {landCoverEnabled && (
          <div className="ml-6 space-y-1">
            <label className="text-xs text-gray-600">
              Opacity: {Math.round(landCoverOpacity * 100)}%
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={landCoverOpacity}
              onChange={(e) => onLandCoverOpacityChange(parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
          </div>
        )}
      </div>

      {/* Biomass Layer */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={biomassEnabled}
              onChange={(e) => onBiomassToggle(e.target.checked)}
              className="w-4 h-4 rounded text-green-600 focus:ring-2 focus:ring-green-500"
            />
            <span className="text-sm font-medium text-gray-700">Biomass</span>
          </label>
          <button
            onClick={() =>
              onLegendToggle(legendType === 'biomass' ? null : 'biomass')
            }
            className={`p-1 rounded transition-colors ${
              legendType === 'biomass'
                ? 'bg-green-100 text-green-600'
                : 'text-gray-400 hover:text-gray-600'
            }`}
            title="Show legend"
          >
            <Info className="w-4 h-4" />
          </button>
        </div>

        {biomassEnabled && (
          <div className="ml-6 space-y-1">
            <label className="text-xs text-gray-600">
              Opacity: {Math.round(biomassOpacity * 100)}%
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={biomassOpacity}
              onChange={(e) => onBiomassOpacityChange(parseFloat(e.target.value))}
              className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-green-600"
            />
          </div>
        )}
      </div>

      {/* Click to Query Toggle */}
      <div className="pt-3 border-t border-gray-200">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={clickQueryEnabled}
            onChange={(e) => onClickQueryToggle(e.target.checked)}
            className="w-4 h-4 rounded text-purple-600 focus:ring-2 focus:ring-purple-500"
          />
          <div className="flex items-center gap-2 flex-1">
            {clickQueryEnabled ? (
              <Eye className="w-4 h-4 text-purple-600" />
            ) : (
              <EyeOff className="w-4 h-4 text-gray-400" />
            )}
            <span className="text-sm font-medium text-gray-700">Click to Query</span>
          </div>
        </label>
        <p className="text-xs text-gray-500 ml-6 mt-1">
          Click on map to see pixel values
        </p>
      </div>
    </div>
  );
}
