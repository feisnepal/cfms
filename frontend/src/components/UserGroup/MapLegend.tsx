/** Collapsible map legend — renders color swatches and labels for active raster/vector layers. */
import React from 'react';
import { X } from 'lucide-react';
import { useT } from '../../i18n/hooks';

interface LegendItem {
  color: string;
  label: string;
  value?: string;
}

interface MapLegendProps {
  type: 'landcover' | 'biomass' | null;
  onClose?: () => void;
}

export function MapLegend({ type, onClose }: MapLegendProps) {
  const t = useT();
  if (!type) return null;

  const getLandCoverItems = (): LegendItem[] => [
    { color: '#006400', label: t('landCover.treeCover') },
    { color: '#FFBB22', label: t('landCover.shrubland') },
    { color: '#FFFF4C', label: t('landCover.grassland') },
    { color: '#F096FF', label: t('landCover.cropland') },
    { color: '#FA0000', label: t('landCover.builtUp') },
    { color: '#B4B4B4', label: t('landCover.bare') },
    { color: '#F0F0F0', label: t('landCover.snowIce') },
    { color: '#0064C8', label: t('landCover.water') },
    { color: '#0096A0', label: t('landCover.wetland') },
    { color: '#00CF75', label: t('landCover.mangroves') },
    { color: '#FAE6A0', label: t('landCover.mossLichen') },
  ];

  const getBiomassItems = (): LegendItem[] => [
    { color: '#003300', label: t('biomassClass.veryHigh'), value: t('biomassClass.veryHighRange') },
    { color: '#006600', label: t('biomassClass.high'), value: t('biomassClass.highRange') },
    { color: '#228B22', label: t('biomassClass.mediumHigh'), value: t('biomassClass.mediumHighRange') },
    { color: '#90EE90', label: t('biomassClass.medium'), value: t('biomassClass.mediumRange') },
    { color: '#ADFF2F', label: t('biomassClass.mediumLow'), value: t('biomassClass.mediumLowRange') },
    { color: '#FFFF00', label: t('biomassClass.low'), value: t('biomassClass.lowRange') },
    { color: '#FFD700', label: t('biomassClass.veryLow'), value: t('biomassClass.veryLowRange') },
  ];

  const items = type === 'landcover' ? getLandCoverItems() : getBiomassItems();
  const title = type === 'landcover'
    ? t('userGroup.legend.landCoverTitle')
    : t('userGroup.legend.biomassTitle');
  const source = type === 'landcover'
    ? t('userGroup.legend.landCoverSource')
    : t('userGroup.legend.biomassSource');

  return (
    <div className="absolute bottom-6 left-6 bg-white rounded-lg shadow-lg p-4 z-[1000] max-w-xs">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-gray-800 text-sm">{title}</h4>
        {onClose && (
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            title={t('userGroup.legend.close')}
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Legend Items */}
      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {items.map((item, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <div
              className="w-5 h-5 rounded border border-gray-300 flex-shrink-0"
              style={{ backgroundColor: item.color }}
            />
            <div className="flex-1 min-w-0">
              <span className="text-xs text-gray-700">{item.label}</span>
              {item.value && (
                <span className="text-xs text-gray-500 ml-1">({item.value})</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Source */}
      <div className="mt-3 pt-3 border-t border-gray-200">
        <p className="text-xs text-gray-500">{source}</p>
      </div>
    </div>
  );
}
