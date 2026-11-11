/** CorrectionPreviewDialog — modal dialog for reviewing and applying data corrections. */
import { useState } from 'react';
import { useT } from '../i18n/hooks';

interface Correction {
  row_number: number;
  species: string;
  original_x: number;
  original_y: number;
  corrected_x: number;
  corrected_y: number;
  distance_moved_meters: number;
}

interface CorrectionSummary {
  total_corrections: number;
  max_distance: number;
  min_distance: number;
  avg_distance: number;
}

interface BoundaryCheck {
  total_points: number;
  out_of_boundary_count: number;
  out_of_boundary_percentage: number;
  within_tolerance: boolean;
  needs_correction: boolean;
}

interface CorrectionPreviewDialogProps {
  boundaryCheck: BoundaryCheck;
  corrections: Correction[];
  summary: CorrectionSummary;
  onAccept: () => void;
  onCancel: () => void;
  isProcessing: boolean;
}

export function CorrectionPreviewDialog({
  boundaryCheck,
  corrections,
  summary,
  onAccept,
  onCancel,
  isProcessing
}: CorrectionPreviewDialogProps) {
  const t = useT();
  const [showAllCorrections, setShowAllCorrections] = useState(false);
  const displayedCorrections = showAllCorrections ? corrections : corrections.slice(0, 10);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="bg-yellow-50 border-b border-yellow-200 px-6 py-4">
          <div className="flex items-start justify-between">
            <div className="flex items-center">
              <svg className="w-8 h-8 text-yellow-600 mr-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">
                  {t('treeMapping.correction.title')}
                </h3>
                <p className="text-sm text-yellow-800 mt-1">
                  {t('treeMapping.correction.subtitle')}
                </p>
              </div>
            </div>
            <button
              onClick={onCancel}
              disabled={isProcessing}
              className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            >
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {/* Summary Statistics */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            <h4 className="font-semibold text-blue-900 mb-3">{t('treeMapping.correction.summary')}</h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-blue-700">{t('treeMapping.correction.treesOutside')}</p>
                <p className="text-2xl font-bold text-blue-900">
                  {boundaryCheck.out_of_boundary_count}
                </p>
                <p className="text-xs text-blue-600">
                  of {boundaryCheck.total_points} ({boundaryCheck.out_of_boundary_percentage}%)
                </p>
              </div>
              <div>
                <p className="text-xs text-blue-700">{t('treeMapping.correction.avgDistance')}</p>
                <p className="text-2xl font-bold text-blue-900">
                  {summary.avg_distance.toFixed(1)}m
                </p>
              </div>
              <div>
                <p className="text-xs text-blue-700">{t('treeMapping.correction.maxDistance')}</p>
                <p className="text-2xl font-bold text-blue-900">
                  {summary.max_distance.toFixed(1)}m
                </p>
              </div>
              <div>
                <p className="text-xs text-blue-700">{t('treeMapping.correction.minDistance')}</p>
                <p className="text-2xl font-bold text-blue-900">
                  {summary.min_distance.toFixed(1)}m
                </p>
              </div>
            </div>
          </div>

          {/* Explanation */}
          <div className="mb-6">
            <h4 className="font-semibold text-gray-900 mb-2">{t('treeMapping.correction.whatsHappening')}</h4>
            <p className="text-sm text-gray-700 mb-2">
              <strong>{boundaryCheck.out_of_boundary_percentage}%</strong> of your tree coordinates fall outside the forest boundary.
              This is within the acceptable <strong>5% GPS error tolerance</strong>.
            </p>
            <p className="text-sm text-gray-700 mb-2">
              The system can automatically correct these coordinates by moving each point to the nearest location on the boundary.
            </p>
            <p className="text-sm text-gray-600 italic">
              {t('treeMapping.correction.commonCauses')}
            </p>
          </div>

          {/* Corrections Table */}
          <div className="mb-6">
            <h4 className="font-semibold text-gray-900 mb-3">
              Proposed Corrections ({corrections.length} trees)
            </h4>
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.correction.colTree')}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.species')}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.correction.colOriginal')}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.correction.colCorrected')}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.correction.colMoved')}</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {displayedCorrections.map((correction) => (
                      <tr key={correction.row_number} className="hover:bg-gray-50">
                        <td className="px-4 py-2 text-sm font-medium text-gray-900">
                          #{correction.row_number}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700">
                          {correction.species}
                        </td>
                        <td className="px-4 py-2 text-xs font-mono text-gray-600">
                          {correction.original_x.toFixed(6)}, {correction.original_y.toFixed(6)}
                        </td>
                        <td className="px-4 py-2 text-xs font-mono text-green-600">
                          {correction.corrected_x.toFixed(6)}, {correction.corrected_y.toFixed(6)}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-900">
                          {correction.distance_moved_meters.toFixed(1)}m
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {corrections.length > 10 && !showAllCorrections && (
                <div className="bg-gray-50 px-4 py-3 text-center border-t border-gray-200">
                  <button
                    onClick={() => setShowAllCorrections(true)}
                    className="text-sm text-blue-600 hover:text-blue-800 font-medium"
                  >
                    Show all {corrections.length} corrections
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Important Note */}
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-start">
              <svg className="w-5 h-5 text-green-600 mt-0.5 mr-2 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div className="text-sm text-green-800">
                <p className="font-semibold mb-1">{t('treeMapping.correction.ifAccept')}</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>{t('treeMapping.correction.effect1')}</li>
                  <li>{t('treeMapping.correction.effect2')}</li>
                  <li>{t('treeMapping.correction.effect3')}</li>
                  <li>{t('treeMapping.correction.effect4')}</li>
                  <li>{t('treeMapping.correction.effect5')}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="bg-gray-50 border-t border-gray-200 px-6 py-4 flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={isProcessing}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('treeMapping.correction.cancelUpload')}
          </button>
          <button
            onClick={onAccept}
            disabled={isProcessing}
            className="px-6 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center"
          >
            {isProcessing ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {t('treeMapping.correction.applying')}
              </>
            ) : (
              <>
                <svg className="w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {t('treeMapping.correction.accept')}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
