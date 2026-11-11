/** PercentageBar — horizontal percentage bar with segmented colour-coded sections. */
import React from 'react';
import { formatDecimal } from '../i18n/numberFormat';

interface PercentageItem {
  label: string;
  value: number;
  color?: string;
}

interface PercentageBarProps {
  data: PercentageItem[];
  showValues?: boolean;
  showLegend?: boolean;
  height?: 'sm' | 'md' | 'lg';
  className?: string;
}

const PercentageBar: React.FC<PercentageBarProps> = ({
  data,
  showValues = true,
  showLegend = true,
  height = 'md',
  className = ''
}) => {
  // Default color palette if colors not provided
  const defaultColors = [
    '#10b981', // green-500
    '#3b82f6', // blue-500
    '#f59e0b', // amber-500
    '#ef4444', // red-500
    '#8b5cf6', // purple-500
    '#ec4899', // pink-500
    '#14b8a6', // teal-500
    '#f97316'  // orange-500
  ];

  // Height mapping
  const heightClasses = {
    sm: 'h-6',
    md: 'h-8',
    lg: 'h-10'
  };

  // Ensure percentages add up to 100 (normalize if needed)
  const total = data.reduce((sum, item) => sum + item.value, 0);
  const normalizedData = total > 0
    ? data.map(item => ({
        ...item,
        normalizedValue: (item.value / total) * 100
      }))
    : [];

  return (
    <div className={className}>
      {/* Percentage Bar */}
      <div className={`flex w-full rounded-lg overflow-hidden ${heightClasses[height]} shadow-sm border border-gray-200`}>
        {normalizedData.map((item, index) => {
          const color = item.color || defaultColors[index % defaultColors.length];
          const percentage = item.normalizedValue;

          if (percentage === 0) return null;

          return (
            <div
              key={index}
              className="relative group"
              style={{
                width: `${percentage}%`,
                backgroundColor: color
              }}
              title={`${item.label}: ${formatDecimal(item.value, 1)}%`}
            >
              {/* Tooltip on hover */}
              <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
                {item.label}: {item.value.toFixed(1)}%
              </div>

              {/* Show value inside bar if space available */}
              {showValues && percentage > 8 && (
                <span className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-white">
                  {item.value.toFixed(1)}%
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      {showLegend && (
        <div className="mt-3 flex flex-wrap gap-4">
          {data.map((item, index) => {
            const color = item.color || defaultColors[index % defaultColors.length];

            return (
              <div key={index} className="flex items-center gap-2">
                <div
                  className="w-4 h-4 rounded border border-gray-300"
                  style={{ backgroundColor: color }}
                />
                <span className="text-sm text-gray-700">
                  {item.label}: <span className="font-semibold">{item.value.toFixed(1)}%</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default PercentageBar;
