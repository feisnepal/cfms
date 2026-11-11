/** MetricCard — card displaying a single metric with label, value, and optional trend. */
import React from 'react';

interface MetricCardProps {
  icon?: string;
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  color?: 'green' | 'blue' | 'yellow' | 'red' | 'gray';
  subtitle?: string;
  className?: string;
}

const MetricCard: React.FC<MetricCardProps> = ({
  icon,
  label,
  value,
  unit,
  color = 'green',
  subtitle,
  className = ''
}) => {
  // Color mapping for different metric types
  const colorClasses = {
    green: 'bg-green-50 border-green-200 text-green-900',
    blue: 'bg-blue-50 border-blue-200 text-blue-900',
    yellow: 'bg-yellow-50 border-yellow-200 text-yellow-900',
    red: 'bg-red-50 border-red-200 text-red-900',
    gray: 'bg-gray-50 border-gray-200 text-gray-900'
  };

  const valueColorClasses = {
    green: 'text-green-700',
    blue: 'text-blue-700',
    yellow: 'text-yellow-700',
    red: 'text-red-700',
    gray: 'text-gray-700'
  };

  // Format value for display
  const formattedValue = value !== null && value !== undefined
    ? typeof value === 'number'
      ? value.toLocaleString()
      : value
    : 'N/A';

  return (
    <div className={`border-2 rounded-lg p-4 ${colorClasses[color]} ${className}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          {/* Label */}
          <div className="flex items-center gap-2 mb-2">
            {icon && <span className="text-2xl">{icon}</span>}
            <p className="text-sm font-medium text-gray-600">{label}</p>
          </div>

          {/* Value */}
          <div className="flex items-baseline gap-1">
            <span className={`text-3xl font-bold ${valueColorClasses[color]}`}>
              {formattedValue}
            </span>
            {unit && (
              <span className="text-sm font-medium text-gray-500 ml-1">
                {unit}
              </span>
            )}
          </div>

          {/* Subtitle */}
          {subtitle && (
            <p className="text-xs text-gray-500 mt-1">{subtitle}</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default MetricCard;
