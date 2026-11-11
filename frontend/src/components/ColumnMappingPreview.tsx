/** ColumnMappingPreview — preview of CSV column-to-database-field mapping before import. */
import { useState } from 'react';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';

interface ColumnMappingPreviewProps {
  previewData: {
    filename: string;
    total_rows: number;
    csv_columns: string[];
    sample_data: Record<string, any>[];
    mapping: Record<string, string>;
    confidence: Record<string, number>;
    unmapped_columns: string[];
    missing_required: string[];
    duplicates: Record<string, string[]>;
    needs_user_input: boolean;
    required_columns: string[];
    optional_columns: string[];
    summary?: {
      ready_for_processing?: boolean;
      [key: string]: any;
    };
    boundary_check?: {
      total_points: number;
      out_of_boundary_count: number;
      out_of_boundary_percentage: number;
      within_tolerance: boolean;
      needs_correction: boolean;
      correction_strategy?: string;
      correctable?: number;
      uncorrectable?: number;
      recommendation?: string;
      corrections?: any[];
      correction_summary?: string;
    };
  };
  onConfirm: (mapping: Record<string, string>, savePreference: boolean) => void;
  onCancel: () => void;
}

export default function ColumnMappingPreview({
  previewData,
  onConfirm,
  onCancel,
}: ColumnMappingPreviewProps) {
  const t = useT();
  const [mapping, setMapping] = useState<Record<string, string>>(
    previewData.mapping
  );
  const [savePreference, setSavePreference] = useState(false);

  const allStandardColumns = [
    ...previewData.required_columns,
    ...previewData.optional_columns,
    '_ignore', // Option to ignore a column
  ];

  const handleColumnChange = (csvCol: string, stdCol: string) => {
    setMapping((prev) => ({ ...prev, [csvCol]: stdCol }));
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 90) return 'bg-green-500';
    if (confidence >= 70) return 'bg-yellow-500';
    return 'bg-red-500';
  };

  const getConfidenceText = (confidence: number) => {
    if (confidence >= 90) return 'text-green-700';
    if (confidence >= 70) return 'text-yellow-700';
    return 'text-red-700';
  };

  // Check if mapping is valid
  const mappedValues = Object.values(mapping).filter((v) => v !== '_ignore');
  const missingRequired = previewData.required_columns.filter(
    (col) => !mappedValues.includes(col)
  );

  // Check for duplicates in current mapping
  const currentDuplicates: Record<string, string[]> = {};
  Object.entries(mapping).forEach(([csvCol, stdCol]) => {
    if (stdCol !== '_ignore') {
      if (!currentDuplicates[stdCol]) {
        currentDuplicates[stdCol] = [];
      }
      currentDuplicates[stdCol].push(csvCol);
    }
  });
  const hasDuplicates = Object.values(currentDuplicates).some(
    (cols) => cols.length > 1
  );

  // Check if upload is allowed (no missing fields, no duplicates, and ready for processing)
  const isReadyForProcessing = previewData.summary?.ready_for_processing !== false;
  const canConfirm = missingRequired.length === 0 && !hasDuplicates && isReadyForProcessing;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg max-w-6xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 rounded-t-lg">
          <h2 className="text-2xl font-bold text-gray-900">
            {t('import.mapping.title')}
          </h2>
          <p className="mt-1 text-sm text-gray-600">
            {t('import.dialog.file')} <span className="font-medium">{previewData.filename}</span> ({t('import.mapping.rowCount', { count: formatNumber(previewData.total_rows) })})
          </p>
        </div>

        <div className="px-6 py-4 space-y-6">
          {/* Warnings */}
          {(missingRequired.length > 0 || hasDuplicates) && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <div className="flex items-start">
                <svg
                  className="h-5 w-5 text-red-600 mt-0.5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                  />
                </svg>
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-red-800">
                    {t('import.mapping.issuesTitle')}
                  </h3>
                  <div className="mt-2 text-sm text-red-700 space-y-1">
                    {missingRequired.length > 0 && (
                      <p>
                        {t('import.mapping.missingRequired')}{' '}
                        <span className="font-semibold">
                          {missingRequired.join(', ')}
                        </span>
                      </p>
                    )}
                    {hasDuplicates && (
                      <div>
                        <p className="font-semibold">{t('import.mapping.duplicates')}</p>
                        <ul className="list-disc list-inside ml-2">
                          {Object.entries(currentDuplicates)
                            .filter(([_, cols]) => cols.length > 1)
                            .map(([stdCol, csvCols]) => (
                              <li key={stdCol}>
                                {t('import.mapping.duplicateRow', { column: stdCol, sources: csvCols.join(', ') })}
                              </li>
                            ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Sample Data Preview */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-3">
              {t('import.mapping.sampleData')}
            </h3>
            <div className="overflow-x-auto border rounded-lg">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {previewData.csv_columns.map((col) => (
                      <th
                        key={col}
                        className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {previewData.sample_data.slice(0, 5).map((row, idx) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      {previewData.csv_columns.map((col) => (
                        <td
                          key={col}
                          className="px-4 py-2 text-sm text-gray-900 whitespace-nowrap"
                        >
                          {row[col] !== null && row[col] !== undefined
                            ? String(row[col])
                            : '-'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Column Mapping Table */}
          <div>
            <h3 className="text-lg font-semibold text-gray-900 mb-3">
              Column Mapping
            </h3>
            <div className="overflow-x-auto border rounded-lg">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                      {t('import.mapping.colYour')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                      {t('import.mapping.colMapsTo')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                      {t('import.mapping.colConfidence')}
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-700 uppercase tracking-wider">
                      {t('import.mapping.colStatus')}
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {previewData.csv_columns.map((csvCol) => {
                    const stdCol = mapping[csvCol] || '';
                    const conf = previewData.confidence[csvCol] || 0;
                    const isRequired =
                      previewData.required_columns.includes(stdCol);

                    return (
                      <tr key={csvCol} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-mono text-gray-900">
                          {csvCol}
                        </td>
                        <td className="px-4 py-3">
                          <select
                            value={stdCol}
                            onChange={(e) =>
                              handleColumnChange(csvCol, e.target.value)
                            }
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-green-500 focus:ring-green-500 text-sm"
                          >
                            <option value="">{t('import.mapping.selectColumn')}</option>
                            <optgroup label={t('import.mapping.groupRequired')}>
                              {previewData.required_columns.map((col) => (
                                <option key={col} value={col}>
                                  {col}
                                </option>
                              ))}
                            </optgroup>
                            <optgroup label={t('import.mapping.groupOptional')}>
                              {previewData.optional_columns.map((col) => (
                                <option key={col} value={col}>
                                  {col}
                                </option>
                              ))}
                            </optgroup>
                            <optgroup label={t('import.mapping.groupOther')}>
                              <option value="_ignore">{t('import.mapping.ignoreColumn')}</option>
                            </optgroup>
                          </select>
                        </td>
                        <td className="px-4 py-3">
                          {conf > 0 && (
                            <div className="flex items-center gap-2">
                              <div className="w-24 bg-gray-200 rounded-full h-2">
                                <div
                                  className={`h-2 rounded-full ${getConfidenceColor(
                                    conf
                                  )}`}
                                  style={{ width: `${conf}%` }}
                                ></div>
                              </div>
                              <span className={`text-sm font-medium ${getConfidenceText(conf)}`}>
                                {conf}%
                              </span>
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {isRequired && stdCol !== '_ignore' && (
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                              Required
                            </span>
                          )}
                          {stdCol === '_ignore' && (
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                              Ignored
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Save Preference Checkbox */}
          <div className="flex items-center">
            <input
              id="save-preference"
              type="checkbox"
              checked={savePreference}
              onChange={(e) => setSavePreference(e.target.checked)}
              className="h-4 w-4 text-green-600 focus:ring-green-500 border-gray-300 rounded"
            />
            <label
              htmlFor="save-preference"
              className="ml-2 block text-sm text-gray-700"
            >
              {t('import.mapping.remember')}
            </label>
          </div>

          {/* Boundary Check Results */}
          {previewData.boundary_check && previewData.boundary_check.out_of_boundary_count > 0 && (
            <div className="border-t border-gray-200 pt-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">
                {t('import.mapping.boundaryValidation')}
              </h3>

              {previewData.boundary_check.within_tolerance ? (
                <div className="bg-yellow-50 border-l-4 border-yellow-400 p-4">
                  <div className="flex">
                    <div className="flex-shrink-0">
                      <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <div className="ml-3 flex-1">
                      <h4 className="text-sm font-medium text-yellow-800">
                        {t('import.mapping.correctionAvailable')}
                      </h4>
                      <div className="mt-2 text-sm text-yellow-700">
                        <p>{previewData.boundary_check.correction_summary}</p>

                        <div className="mt-3 grid grid-cols-2 gap-4 text-xs">
                          <div>
                            <span className="font-semibold">{t('import.mapping.strategy')}</span>{' '}
                            {previewData.boundary_check.correction_strategy === 'nearest_tree'
                              ? t('import.mapping.strategyNearestTree')
                              : t('import.mapping.strategyBoundaryEdge')}
                          </div>
                          <div>
                            <span className="font-semibold">{t('import.mapping.outOfBoundary')}</span>{' '}
                            {t('import.mapping.treeCountPct', {
                              count: formatNumber(previewData.boundary_check.out_of_boundary_count),
                              pct: formatNumber(previewData.boundary_check.out_of_boundary_percentage),
                            })}
                          </div>
                          {previewData.boundary_check.correctable !== undefined && (
                            <>
                              <div>
                                <span className="font-semibold">{t('import.mapping.correctable')}</span>{' '}
                                <span className="text-green-700">
                                  {t('import.mapping.treeCount', { count: formatNumber(previewData.boundary_check.correctable) })}
                                </span>
                              </div>
                              {previewData.boundary_check.uncorrectable! > 0 && (
                                <div>
                                  <span className="font-semibold">{t('import.mapping.uncorrectable')}</span>{' '}
                                  <span className="text-red-700">
                                    {t('import.mapping.treeCount', { count: formatNumber(previewData.boundary_check.uncorrectable!) })}
                                  </span>
                                </div>
                              )}
                            </>
                          )}
                        </div>

                        {previewData.boundary_check.correction_strategy === 'nearest_tree' &&
                         previewData.boundary_check.uncorrectable! > 0 && (
                          <div className="mt-3 p-3 bg-orange-50 border border-orange-200 rounded">
                            <div className="flex">
                              <svg className="h-5 w-5 text-orange-400 flex-shrink-0" viewBox="0 0 20 20" fill="currentColor">
                                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                              </svg>
                              <p className="ml-2 text-sm text-orange-800">
                                <span className="font-semibold">{t('import.mapping.note')}</span>{' '}
                                {t('import.mapping.noteUncorrectable', {
                                  count: formatNumber(previewData.boundary_check.uncorrectable!),
                                })}
                              </p>
                            </div>
                          </div>
                        )}

                        <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded">
                          <p className="text-sm text-green-800">
                            ✓ {t('import.mapping.correctionsAuto')}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="bg-red-50 border-l-4 border-red-400 p-4">
                  <div className="flex">
                    <div className="flex-shrink-0">
                      <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <div className="ml-3">
                      <h4 className="text-sm font-medium text-red-800">
                        {t('import.mapping.tooManyOutside')}
                      </h4>
                      <div className="mt-2 text-sm text-red-700">
                        <p>
                          {previewData.boundary_check.out_of_boundary_count} trees ({previewData.boundary_check.out_of_boundary_percentage}%)
                          are outside the boundary polygon. This exceeds the 20% tolerance limit.
                        </p>
                        <p className="mt-2">
                          {t('import.mapping.checkData')}
                        </p>
                        <ul className="list-disc list-inside ml-2 mt-1">
                          <li>{t('import.mapping.checkCrs')}</li>
                          <li>{t('import.mapping.checkFormat')}</li>
                          <li>{t('import.mapping.checkPolygon')}</li>
                          <li>{t('import.mapping.checkData2')}</li>
                        </ul>
                        <div className="mt-4 p-3 bg-red-100 border border-red-300 rounded font-semibold text-red-900">
                          ⛔ Upload blocked: Please fix the boundary issues before proceeding.
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 bg-gray-50 px-6 py-4 border-t border-gray-200 rounded-b-lg flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(mapping, savePreference)}
            disabled={!canConfirm}
            title={
              !isReadyForProcessing
                ? 'Upload blocked: Too many trees outside boundary (>20%)'
                : !canConfirm
                ? t('import.mapping.fixErrorsFirst')
                : t('import.mapping.confirmHint')
            }
            className={`px-4 py-2 border border-transparent rounded-md text-sm font-medium text-white focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 ${
              canConfirm
                ? 'bg-green-600 hover:bg-green-700'
                : 'bg-gray-300 cursor-not-allowed'
            }`}
          >
            {!isReadyForProcessing ? t('import.mapping.uploadBlocked') : t('import.mapping.confirmUpload')}
          </button>
        </div>
      </div>
    </div>
  );
}
