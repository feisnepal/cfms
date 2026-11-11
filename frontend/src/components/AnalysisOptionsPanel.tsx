/** AnalysisOptionsPanel — panel for configuring analysis parameters and thresholds. */
import React, { useState, useEffect } from 'react';
import {
  AnalysisOptions,
  ANALYSIS_PRESETS,
  PresetName,
  AnalysisPreset,
  ANALYSIS_OPTION_INFO,
  DEFAULT_ANALYSIS_OPTIONS,
} from '../constants/analysisPresets';
import { useT } from '../i18n/hooks';

interface AnalysisOptionsPanelProps {
  options: AnalysisOptions;
  onChange: (options: AnalysisOptions) => void;
  disabled?: boolean;
}

const AnalysisOptionsPanel: React.FC<AnalysisOptionsPanelProps> = ({
  options,
  onChange,
  disabled = false,
}) => {
  const t = useT();
  const [selectedPreset, setSelectedPreset] = useState<PresetName>('complete');
  const [showRasterOptions, setShowRasterOptions] = useState(false);
  const [showAutoGenOptions, setShowAutoGenOptions] = useState(false);

  // Detect which preset matches current options
  useEffect(() => {
    const matchingPreset = ANALYSIS_PRESETS.find(preset => {
      if (preset.name === 'custom') return false;
      return JSON.stringify(preset.options) === JSON.stringify(options);
    });

    if (matchingPreset) {
      setSelectedPreset(matchingPreset.name);
    } else {
      setSelectedPreset('custom');
    }
  }, [options]);

  const handlePresetChange = (presetName: PresetName) => {
    setSelectedPreset(presetName);
    const preset = ANALYSIS_PRESETS.find(p => p.name === presetName);
    if (preset) {
      onChange(preset.options);
    }
  };

  const handleOptionChange = (key: keyof AnalysisOptions, value: boolean) => {
    const updatedOptions = { ...options, [key]: value };
    onChange(updatedOptions);
    setSelectedPreset('custom'); // Switch to custom when manually changing options
  };

  const handleSelectAll = () => {
    onChange(DEFAULT_ANALYSIS_OPTIONS);
  };

  const handleDeselectAll = () => {
    const allDisabled: AnalysisOptions = {
      run_raster_analysis: false,
      run_elevation: false,
      run_slope: false,
      run_aspect: false,
      run_canopy: false,
      run_biomass: false,
      run_forest_health: false,
      run_forest_type: false,
      run_landcover: false,
      run_forest_loss: false,
      run_forest_gain: false,
      run_fire_loss: false,
      run_temperature: false,
      run_precipitation: false,
      run_soil: false,
      run_proximity: false,
      auto_generate_fieldbook: false,
      auto_generate_sampling: false,
    };
    onChange(allDisabled);
  };

  // Group options by category
  const rasterOptions: Array<{ key: keyof AnalysisOptions; category: string }> = [
    { key: 'run_elevation', category: 'Terrain' },
    { key: 'run_slope', category: 'Terrain' },
    { key: 'run_aspect', category: 'Terrain' },
    { key: 'run_canopy', category: 'Forest Structure' },
    { key: 'run_biomass', category: 'Forest Structure' },
    { key: 'run_forest_health', category: 'Forest Structure' },
    { key: 'run_forest_type', category: 'Classification' },
    { key: 'run_landcover', category: 'Classification' },
    { key: 'run_forest_loss', category: 'Change Detection' },
    { key: 'run_forest_gain', category: 'Change Detection' },
    { key: 'run_fire_loss', category: 'Change Detection' },
    { key: 'run_temperature', category: 'Climate' },
    { key: 'run_precipitation', category: 'Climate' },
    { key: 'run_soil', category: 'Soil' },
    { key: 'run_proximity', category: 'Vector' },
  ];

  // Group by category
  const groupedOptions: Record<string, Array<keyof AnalysisOptions>> = {};
  rasterOptions.forEach(({ key, category }) => {
    if (!groupedOptions[category]) {
      groupedOptions[category] = [];
    }
    groupedOptions[category].push(key);
  });

  return (
    <div className="border rounded-lg p-6 bg-white">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">{t('analysis.optionsTitle')}</h3>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleSelectAll}
            disabled={disabled}
            className="text-sm px-3 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('analysis.selectAll')}
          </button>
          <button
            type="button"
            onClick={handleDeselectAll}
            disabled={disabled}
            className="text-sm px-3 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('analysis.deselectAll')}
          </button>
        </div>
      </div>

      {/* Preset Selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          {t('analysis.presetConfig')}
        </label>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {ANALYSIS_PRESETS.map((preset) => (
            <button
              key={preset.name}
              type="button"
              onClick={() => handlePresetChange(preset.name)}
              disabled={disabled}
              className={`p-3 border rounded-lg text-left transition-all ${
                selectedPreset === preset.name
                  ? 'border-green-500 bg-green-50 ring-2 ring-green-200'
                  : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              <div className="font-semibold text-sm">{t(preset.label)}</div>
              <div className="text-xs text-gray-600 mt-1">{t(preset.estimatedTime)}</div>
              <div className="text-xs text-gray-500 mt-1 line-clamp-2">{t(preset.description)}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Master Switch */}
      <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={options.run_raster_analysis}
            onChange={(e) => handleOptionChange('run_raster_analysis', e.target.checked)}
            disabled={disabled}
            className="w-4 h-4 text-green-600 rounded focus:ring-green-500 disabled:opacity-50"
          />
          <div className="ml-3">
            <span className="font-semibold text-sm text-gray-900">{t('analysis.runRasterAnalysis')}</span>
            <p className="text-xs text-gray-600">{t('analysis.runRasterAnalysisDesc')}</p>
          </div>
        </label>
      </div>

      {/* Raster Analysis Options (Collapsible) */}
      <div className="mb-4">
        <button
          type="button"
          onClick={() => setShowRasterOptions(!showRasterOptions)}
          className="w-full flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <span className="font-medium text-sm text-gray-900">{t('analysis.rasterParams')}</span>
          <svg
            className={`w-5 h-5 text-gray-600 transition-transform ${showRasterOptions ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {showRasterOptions && (
          <div className="mt-3 space-y-4">
            {Object.entries(groupedOptions).map(([category, optionKeys]) => (
              <div key={category} className="border-l-4 border-gray-300 pl-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-2">{t(`analysis.category${category}`)}</h4>
                <div className="space-y-2">
                  {optionKeys.map((key) => {
                    const info = ANALYSIS_OPTION_INFO[key as keyof typeof ANALYSIS_OPTION_INFO];
                    return (
                      <label key={key} className="flex items-start cursor-pointer group">
                        <input
                          type="checkbox"
                          checked={options[key as keyof AnalysisOptions] as boolean}
                          onChange={(e) => handleOptionChange(key as keyof AnalysisOptions, e.target.checked)}
                          disabled={disabled || !options.run_raster_analysis}
                          className="w-4 h-4 mt-0.5 text-green-600 rounded focus:ring-green-500 disabled:opacity-50"
                        />
                        <div className="ml-3 flex-1">
                          <span className="text-sm text-gray-900 group-hover:text-green-600">{t(info.label)}</span>
                          <p className="text-xs text-gray-500">{t(info.description)}</p>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Auto-Generation Options (Collapsible) */}
      <div>
        <button
          type="button"
          onClick={() => setShowAutoGenOptions(!showAutoGenOptions)}
          className="w-full flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <span className="font-medium text-sm text-gray-900">{t('analysis.autoGenOptions')}</span>
          <svg
            className={`w-5 h-5 text-gray-600 transition-transform ${showAutoGenOptions ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {showAutoGenOptions && (
          <div className="mt-3 space-y-2 pl-4">
            <label className="flex items-start cursor-pointer group">
              <input
                type="checkbox"
                checked={options.auto_generate_fieldbook}
                onChange={(e) => handleOptionChange('auto_generate_fieldbook', e.target.checked)}
                disabled={disabled}
                className="w-4 h-4 mt-0.5 text-green-600 rounded focus:ring-green-500 disabled:opacity-50"
              />
              <div className="ml-3 flex-1">
                <span className="text-sm text-gray-900 group-hover:text-green-600">{t('analysis.autoFieldbook')}</span>
                <p className="text-xs text-gray-500">{t('analysis.autoFieldbookDesc')}</p>
              </div>
            </label>

            <label className="flex items-start cursor-pointer group">
              <input
                type="checkbox"
                checked={options.auto_generate_sampling}
                onChange={(e) => handleOptionChange('auto_generate_sampling', e.target.checked)}
                disabled={disabled}
                className="w-4 h-4 mt-0.5 text-green-600 rounded focus:ring-green-500 disabled:opacity-50"
              />
              <div className="ml-3 flex-1">
                <span className="text-sm text-gray-900 group-hover:text-green-600">{t('analysis.autoSampling')}</span>
                <p className="text-xs text-gray-500">{t('analysis.autoSamplingDesc')}</p>
              </div>
            </label>
          </div>
        )}
      </div>

      {/* Summary */}
      <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <div className="text-xs text-blue-800">
          <strong>{t('analysis.selectedLabel')}: </strong>{
            Object.values(options).filter(Boolean).length
          } / {Object.keys(options).length} {t('analysis.optionsEnabled')}
        </div>
      </div>
    </div>
  );
};

export default AnalysisOptionsPanel;
