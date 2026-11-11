/** Legend component for chart items, rendering color swatches and Nepali-formatted labels. */
import React from 'react';
import { toNepaliDigit } from '../../constants/nepaliLabels';
import { LegendItem } from '../../services/sectionGenerators';

interface NepaliLegendProps {
  items: LegendItem[];
}

const NepaliLegend: React.FC<NepaliLegendProps> = ({ items }) => {
  if (items.length === 0) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 mt-3">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block w-3 h-3 rounded-sm flex-shrink-0"
            style={{ backgroundColor: item.color }}
          />
          <div className="flex flex-col leading-tight">
            <span className="font-medium text-gray-800">{item.labelNp}</span>
            <span className="text-gray-500" style={{ fontSize: '9px' }}>{item.labelEn}</span>
            {item.value !== undefined && (
              <span className="text-gray-600 font-semibold">{toNepaliDigit(item.value, 1)}%</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

export default NepaliLegend;
