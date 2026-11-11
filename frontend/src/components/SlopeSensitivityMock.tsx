/** SlopeSensitivityMock — mock UI for slope sensitivity classification analysis. */
import React, { useState } from 'react';
import { useT } from '../i18n/hooks';

interface SlopeClassOption {
  value: number;
  /** i18n key — the array is module scope, so t() is applied at render. */
  labelKey: string;
  range: string;
  color: string;
}

const SLOPE_CLASSES: SlopeClassOption[] = [
  { value: 1, labelKey: 'treeMapping.slope.gentleFlat', range: '0-19°', color: '#22C55E' },      // Green
  { value: 2, labelKey: 'treeMapping.slope.moderateSteep', range: '19-31°', color: '#F59E0B' }, // Amber
  { value: 3, labelKey: 'treeMapping.slope.highlySteep', range: '31-45°', color: '#EF4444' },   // Red
  { value: 4, labelKey: 'treeMapping.slope.extremeCliffs', range: '>45°', color: '#991B1B' },    // Dark Red
];

const SlopeSensitivityMock: React.FC = () => {
  const t = useT();
  const [enabledClasses, setEnabledClasses] = useState<number[]>([3, 4]);
  const [showLegend, setShowLegend] = useState(true);

  const toggleClass = (classValue: number) => {
    setEnabledClasses(prev => 
      prev.includes(classValue)
        ? prev.filter(c => c !== classValue)
        : [...prev, classValue].sort((a, b) => a - b)
    );
  };

  const toggleAllHigher = (classValue: number) => {
    const higherClasses = SLOPE_CLASSES.filter(c => c.value >= classValue).map(c => c.value);
    const allEnabled = higherClasses.every(c => enabledClasses.includes(c));
    
    if (allEnabled) {
      setEnabledClasses(prev => prev.filter(c => !higherClasses.includes(c)));
    } else {
      setEnabledClasses(prev => [...new Set([...prev, ...higherClasses])].sort((a, b) => a - b));
    }
  };

  return (
    <div className="max-w-md mx-auto p-6 bg-white rounded-lg shadow-lg">
      <h2 className="text-lg font-bold text-gray-800 mb-4">
        {t('treeMapping.slope.title')}
      </h2>
      <p className="text-sm text-gray-600 mb-4">
        {t('treeMapping.slope.subtitle')}
      </p>

      {/* Slope Class Toggles */}
      <div className="space-y-2 mb-6">
        {SLOPE_CLASSES.map((slopeClass) => (
          <div 
            key={slopeClass.value}
            className="flex items-center justify-between p-3 rounded-lg border-2 transition-all"
            style={{ 
              borderColor: enabledClasses.includes(slopeClass.value) ? slopeClass.color : '#E5E7EB',
              backgroundColor: enabledClasses.includes(slopeClass.value) ? `${slopeClass.color}15` : 'transparent'
            }}
          >
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={enabledClasses.includes(slopeClass.value)}
                onChange={() => toggleClass(slopeClass.value)}
                className="w-5 h-5 rounded"
                style={{ accentColor: slopeClass.color }}
              />
              <div>
                <div className="font-medium text-gray-800" style={{ color: enabledClasses.includes(slopeClass.value) ? slopeClass.color : '#6B7280' }}>
                  {t('treeMapping.slope.classLabel', { value: slopeClass.value, label: t(slopeClass.labelKey) })}
                </div>
                <div className="text-xs text-gray-500">
                  {t('treeMapping.slope.range', { range: slopeClass.range })}
                </div>
              </div>
            </div>
            
            <div 
              className="w-4 h-4 rounded-full"
              style={{ backgroundColor: slopeClass.color }}
            />
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setEnabledClasses([1, 2, 3, 4])}
          className="flex-1 px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded text-sm font-medium text-gray-700 transition-colors"
        >
          {t('treeMapping.slope.enableAll')}
        </button>
        <button
          onClick={() => setEnabledClasses([4])}
          className="flex-1 px-3 py-2 bg-red-50 hover:bg-red-100 rounded text-sm font-medium text-red-700 transition-colors"
        >
          {t('treeMapping.slope.extremeOnly')}
        </button>
        <button
          onClick={() => setEnabledClasses([])}
          className="flex-1 px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded text-sm font-medium text-gray-700 transition-colors"
        >
          {t('treeMapping.slope.clearAll')}
        </button>
      </div>

      {/* Current Selection Display */}
      <div className="p-4 bg-gray-50 rounded-lg mb-4">
        <div className="text-sm font-medium text-gray-700 mb-2">
          {t('treeMapping.slope.currentlyDisplaying')}
        </div>
        <div className="flex flex-wrap gap-2">
          {enabledClasses.length === 0 ? (
            <span className="text-gray-400 text-sm">{t('treeMapping.slope.noneSelected')}</span>
          ) : (
            SLOPE_CLASSES
              .filter(c => enabledClasses.includes(c.value))
              .map(c => (
                <span
                  key={c.value}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium text-white"
                  style={{ backgroundColor: c.color }}
                >
                  <span className="w-2 h-2 rounded-full bg-white/50" />
                  {t('treeMapping.slope.classShort', { value: c.value })}
                </span>
              ))
          )}
        </div>
      </div>

      {/* Map Legend (if enabled) */}
      {showLegend && (
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">{t('treeMapping.slope.mapLegend')}</span>
            <button 
              onClick={() => setShowLegend(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {SLOPE_CLASSES.map((c) => (
              <div 
                key={c.value}
                className="flex items-center gap-2 p-2 rounded"
                style={{ backgroundColor: enabledClasses.includes(c.value) ? `${c.color}20` : '#F3F4F6' }}
              >
                <div 
                  className="w-3 h-3 rounded-sm"
                  style={{ backgroundColor: c.color }}
                />
                <span className="text-xs" style={{ color: enabledClasses.includes(c.value) ? '#1F2937' : '#9CA3AF' }}>
                  {t(c.labelKey)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default SlopeSensitivityMock;