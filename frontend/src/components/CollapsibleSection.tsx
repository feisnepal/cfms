/** CollapsibleSection — expandable/collapsible panel section wrapper. */
import React, { useState } from 'react';

interface CollapsibleSectionProps {
  title: string;
  icon?: string;
  defaultExpanded?: boolean;
  children: React.ReactNode;
  className?: string;
  headerColor?: 'green' | 'blue' | 'yellow' | 'gray';
}

const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  title,
  icon,
  defaultExpanded = false,
  children,
  className = '',
  headerColor = 'green'
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const headerColorClasses = {
    green: 'bg-green-50 hover:bg-green-100 border-green-200',
    blue: 'bg-blue-50 hover:bg-blue-100 border-blue-200',
    yellow: 'bg-yellow-50 hover:bg-yellow-100 border-yellow-200',
    gray: 'bg-gray-50 hover:bg-gray-100 border-gray-200'
  };

  return (
    <div className={`border border-gray-200 rounded-lg shadow-sm overflow-hidden ${className}`}>
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`w-full px-6 py-4 flex items-center justify-between transition-colors ${headerColorClasses[headerColor]} border-b`}
      >
        <div className="flex items-center gap-3">
          {icon && <span className="text-2xl">{icon}</span>}
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
        </div>

        <div className="flex items-center gap-2">
          {/* Status badge */}
          {isExpanded ? (
            <span className="text-xs font-medium text-gray-500">Collapse</span>
          ) : (
            <span className="text-xs font-medium text-gray-500">Expand</span>
          )}

          {/* Chevron icon (SVG) */}
          <svg
            className={`w-5 h-5 text-gray-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Content */}
      {isExpanded && (
        <div className="bg-white">
          {children}
        </div>
      )}
    </div>
  );
};

export default CollapsibleSection;
