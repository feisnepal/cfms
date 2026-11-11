/** Report generation tab — previews, edits, and downloads AI-assisted OP reports. */
import { ReportSectionFixLinks } from './ReportSectionFixLinks';
import { useState, useEffect, useCallback } from 'react';
import DOMPurify from 'dompurify';
import { reportApi } from '../../services/api';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';
import { apiErrorText } from '../../lib/apiErrorText';

interface ReportTabProps {
  calculationId: string;
  forestName?: string;
  onNavigateToTab?: (tabId: string) => void;
  calculationData?: any;
}

interface DataComponent {
  status: 'complete' | 'empty' | 'partial';
  details: Record<string, any>;
}

interface DataCompleteness {
  components: Record<string, DataComponent>;
  readiness_score: number;
  complete_count: number;
  total_count: number;
}

interface SectionInfo {
  section: string;
  title_ne: string;
  title_en: string;
  status: 'available' | 'missing_data' | 'manual_input';
  missing?: string[];
  auto_generate: boolean;
  subsections?: {
    key: string;
    title_ne: string;
    title_en: string;
    status: 'available' | 'missing_data';
    auto_generate: boolean;
  }[];
}

interface Metadata {
  forest_name: string;
  group_name: string;
  district: string;
  palika: string;
  ward: string;
  province: string;
  division: string;
  sub_division: string;
  address: string;
  serial_number: string;
  cf_national_code: string;
  fy_start: string;
  fy_end: string;
}

export function ReportTab({ calculationId, forestName = '', calculationData }: ReportTabProps) {
  const t = useT();
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [dataCompleteness, setDataCompleteness] = useState<DataCompleteness | null>(null);
  const [availableSections, setAvailableSections] = useState<SectionInfo[]>([]);
  const [selectedSections, setSelectedSections] = useState<string[]>([]);

  const resultData = calculationData?.result_data || {};

  const [metadata, setMetadata] = useState<Metadata>({
    forest_name: forestName,
    group_name: '',
    district: resultData.whole_district || '',
    palika: resultData.whole_municipality || '',
    ward: resultData.whole_ward || '',
    province: resultData.whole_province || '',
    division: '',
    sub_division: '',
    address: '',
    serial_number: '',
    cf_national_code: '',
    fy_start: '',
    fy_end: '',
  });
  const [generating, setGenerating] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [previewHtml, setPreviewHtml] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [includeImages, setIncludeImages] = useState(true);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({});

  const loadDataCompleteness = useCallback(async () => {
    try {
      const data = await reportApi.checkDataCompleteness(calculationId);
      setDataCompleteness(data);
    } catch (err) {
      setError(t('reports.tab.completenessFailed'));
    }
  }, [calculationId]);

  const loadAvailableSections = useCallback(async () => {
    try {
      const data = await reportApi.getAvailableSections(calculationId);
      setAvailableSections(data.sections || []);

      // Auto-select available sections
      const autoSelect = (data.sections || [])
        .filter((s: SectionInfo) => s.status === 'available' && s.auto_generate)
        .map((s: SectionInfo) => s.section);
      setSelectedSections(autoSelect);
    } catch (err: any) {
      const msg = apiErrorText(err, err.message || t('reports.tab.sectionsFailed'));
      setError(msg);
      console.error('Error loading sections:', err);
    }
  }, [calculationId]);

  useEffect(() => {
    loadDataCompleteness();
    loadAvailableSections();
  }, [loadDataCompleteness, loadAvailableSections]);

  const handleGenerate = async () => {
    if (selectedSections.length === 0) {
      setError(t('reports.tab.selectAtLeastOne'));
      return;
    }

    setGenerating(true);
    setProgress(0);
    setStatusMessage(t('reports.tab.msgStarting'));
    setError(null);

    try {
      // `metadata` is no longer passed: the server reads the saved forest
      // metadata record (WORKSPACE_FLOW_NAV_PLAN D5), and this local form was
      // the reason the cover page used to differ between users. This component
      // is unreachable and pending deletion in P5e; the call is corrected only so
      // the tree still typechecks. See `ForestMetadataPanel` for the live UI.
      const result = await reportApi.generateReport(
        calculationId,
        selectedSections,
        includeImages
      );

      setJobId(result.job_id);

      // Poll for status
      const pollInterval = setInterval(async () => {
        const status = await reportApi.getReportStatus(result.job_id);
        setProgress(status.progress);
        setStatusMessage(t('reports.tab.msgProgress', {
          done: formatNumber(status.sections_completed.length),
          total: formatNumber(status.sections_total),
        }));

        if (status.status === 'completed') {
          clearInterval(pollInterval);
          setGenerating(false);
          setStatusMessage(t('reports.tab.msgGenerated'));
          setStep(4);

          // Load preview
          const preview = await reportApi.previewReport(result.job_id);
          setPreviewHtml(preview.html);
        } else if (status.status === 'failed') {
          clearInterval(pollInterval);
          setGenerating(false);
          setError(status.error || t('reports.tab.generationFailed'));
        }
      }, 2000);
    } catch (err: any) {
      setGenerating(false);
      setError(apiErrorText(err, t('reports.tab.startFailed')));
    }
  };

  const handleDownload = async () => {
    if (!jobId) return;
    try {
      await reportApi.downloadReport(jobId);
    } catch (err: any) {
      const msg = err.message || t('reports.tab.downloadFailed');
      setError(msg);
      console.error('Download error:', err);
    }
  };

  const toggleSection = (section: string) => {
    setSelectedSections(prev =>
      prev.includes(section)
        ? prev.filter(s => s !== section)
        : [...prev, section]
    );
  };

  const toggleSectionExpand = (section: string) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'complete':
        return <span className="text-green-500">&#x2705;</span>;
      case 'partial':
        return <span className="text-yellow-500">&#x26A0;&#xFE0F;</span>;
      default:
        return <span className="text-red-500">&#x274C;</span>;
    }
  };

  // Section titles arrive from the API as a title_ne/title_en pair.
  const isNe = i18n.language === 'ne';

  const componentLabels: Record<string, string> = {
    analysis: t('reports.tab.comp.analysis'),
    species: t('reports.tab.comp.species'),
    sampling: t('reports.tab.comp.sampling'),
    inventory: t('reports.tab.comp.inventory'),
    households: t('reports.tab.comp.households'),
    committees: t('reports.tab.comp.committees'),
    biodiversity: t('reports.tab.comp.biodiversity'),
    activities: t('reports.tab.comp.activities'),
    user_group: t('reports.tab.comp.userGroup'),
  };

  // DataComponent.status is a closed union, so the three cases are keyed
  // statically rather than through a computed key the i18n scanner cannot see.
  const componentStatusLabels: Record<string, string> = {
    complete: t('reports.tab.compStatus.complete'),
    partial: t('reports.tab.compStatus.partial'),
    empty: t('reports.tab.compStatus.empty'),
  };

  return (
    <div className="p-4 space-y-4 bg-gray-50 min-h-full">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-800">
          &#x1F4CB; {t('reports.tab.title')}
        </h2>
        <div className="flex gap-2">
          <button
            onClick={() => setStep(1)}
            className={`px-3 py-1.5 text-sm rounded ${step === 1 ? 'bg-green-600 text-white' : 'bg-gray-200'}`}
          >
            {t('reports.tab.step1')}
          </button>
          <button
            onClick={() => setStep(2)}
            className={`px-3 py-1.5 text-sm rounded ${step === 2 ? 'bg-green-600 text-white' : 'bg-gray-200'}`}
          >
            {t('reports.tab.step2')}
          </button>
          <button
            onClick={() => setStep(3)}
            className={`px-3 py-1.5 text-sm rounded ${step === 3 ? 'bg-green-600 text-white' : 'bg-gray-200'}`}
          >
            {t('reports.tab.step3')}
          </button>
          <button
            onClick={() => setStep(4)}
            className={`px-3 py-1.5 text-sm rounded ${step === 4 ? 'bg-green-600 text-white' : 'bg-gray-200'}`}
          >
            {t('reports.tab.step4')}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-500 hover:text-red-700">&#x2716;</button>
        </div>
      )}

      {/* Step 1: Data Completeness Check */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="text-lg font-semibold mb-3">{t('reports.dataCompleteness')}</h3>

            {dataCompleteness && (
              <>
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm text-gray-600">
                      {t('reports.tab.readiness', {
                        pct: formatNumber(Math.round(dataCompleteness.readiness_score * 100)),
                      })}
                    </span>
                    <span className="text-sm text-gray-600">
                      {t('reports.tab.componentsReady', {
                        done: formatNumber(dataCompleteness.complete_count),
                        total: formatNumber(dataCompleteness.total_count),
                      })}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2.5">
                    <div
                      className="bg-green-600 h-2.5 rounded-full transition-all duration-500"
                      style={{ width: `${dataCompleteness.readiness_score * 100}%` }}
                    ></div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(dataCompleteness.components).map(([key, component]) => (
                    <div
                      key={key}
                      className="flex items-center gap-2 p-2 bg-gray-50 rounded text-sm"
                    >
                      {getStatusIcon(component.status)}
                      <span className="font-medium">{componentLabels[key] || key}</span>
                      <span className="text-gray-400">- {componentStatusLabels[component.status] || component.status}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => setStep(2)}
              className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
            >
              {t('reports.tab.nextMetadata')} &#x2192;
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Metadata */}
      {step === 2 && (
        <div className="space-y-4">
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="text-lg font-semibold mb-3">{t('reports.tab.metadataTitle')}</h3>
            <p className="text-sm text-gray-500 mb-4">
              {t('reports.tab.metadataHint')}
            </p>

            <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded">
              <p className="text-sm font-medium text-green-800">
                &#x2705; {t('reports.tab.autoFilled')}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {/* Auto-filled location (read-only) */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.forestName')} &#x2A;</label>
                <input
                  type="text"
                  value={metadata.forest_name}
                  onChange={(e) => setMetadata({ ...metadata, forest_name: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.groupName')} &#x2A;</label>
                <input
                  type="text"
                  value={metadata.group_name}
                  onChange={(e) => setMetadata({ ...metadata, group_name: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                  placeholder={t('reports.tab.phGroupName')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('reports.tab.province')} <span className="text-xs text-green-600 font-normal">({t('reports.tab.autoFilledShort')})</span>
                </label>
                <input
                  type="text"
                  value={metadata.province}
                  onChange={(e) => setMetadata({ ...metadata, province: e.target.value })}
                  className="w-full px-3 py-2 border border-green-300 bg-green-50 rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('reports.tab.district')} <span className="text-xs text-green-600 font-normal">({t('reports.tab.autoFilledShort')})</span>
                </label>
                <input
                  type="text"
                  value={metadata.district}
                  onChange={(e) => setMetadata({ ...metadata, district: e.target.value })}
                  className="w-full px-3 py-2 border border-green-300 bg-green-50 rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('reports.tab.municipality')} <span className="text-xs text-green-600 font-normal">({t('reports.tab.autoFilledShort')})</span>
                </label>
                <input
                  type="text"
                  value={metadata.palika}
                  onChange={(e) => setMetadata({ ...metadata, palika: e.target.value })}
                  className="w-full px-3 py-2 border border-green-300 bg-green-50 rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('reports.tab.ward')} <span className="text-xs text-green-600 font-normal">({t('reports.tab.autoFilledShort')})</span>
                </label>
                <input
                  type="text"
                  value={metadata.ward}
                  onChange={(e) => setMetadata({ ...metadata, ward: e.target.value })}
                  className="w-full px-3 py-2 border border-green-300 bg-green-50 rounded text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.address')}</label>
                <input
                  type="text"
                  value={metadata.address}
                  onChange={(e) => setMetadata({ ...metadata, address: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                  placeholder={t('reports.tab.phAddress')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.fyStart')} &#x2A;</label>
                <input
                  type="text"
                  value={metadata.fy_start}
                  onChange={(e) => setMetadata({ ...metadata, fy_start: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                  placeholder={t('reports.tab.phFyStart')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.fyEnd')} &#x2A;</label>
                <input
                  type="text"
                  value={metadata.fy_end}
                  onChange={(e) => setMetadata({ ...metadata, fy_end: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                  placeholder={t('reports.tab.phFyEnd')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.serialNumber')}</label>
                <input
                  type="text"
                  value={metadata.serial_number}
                  onChange={(e) => setMetadata({ ...metadata, serial_number: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                  placeholder={t('reports.tab.phOptional')}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('reports.tab.cfNationalCode')}</label>
                <input
                  type="text"
                  value={metadata.cf_national_code}
                  onChange={(e) => setMetadata({ ...metadata, cf_national_code: e.target.value })}
                  className="w-full px-3 py-2 border rounded text-sm"
                  placeholder={t('reports.tab.phOptional')}
                />
              </div>
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setStep(1)}
              className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300"
            >
              &#x2190; {t('common.back')}
            </button>
            <button
              onClick={() => setStep(3)}
              className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
            >
              {t('reports.tab.nextSections')} &#x2192;
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Section Selection & Generation */}
      {step === 3 && (
        <div className="space-y-4">
          <div className="bg-white rounded-lg shadow p-4">
            <h3 className="text-lg font-semibold mb-3">{t('reports.tab.selectSections')}</h3>
            <p className="text-sm text-gray-500 mb-4">
              {t('reports.tab.sectionsSelected', {
                count: selectedSections.length,
                shown: formatNumber(selectedSections.length),
              })}
            </p>

            <div className="space-y-2">
              {availableSections.map((section) => (
                <div key={section.section} className="border rounded overflow-hidden">
                  <div className="flex items-center gap-2 p-3 bg-gray-50">
                    <input
                      type="checkbox"
                      checked={selectedSections.includes(section.section)}
                      onChange={() => toggleSection(section.section)}
                      disabled={section.status === 'missing_data' && !section.auto_generate}
                      className="w-4 h-4"
                    />
                    <span className="font-medium text-sm">
                      {section.section}. {isNe ? section.title_ne : section.title_en || section.title_ne}
                    </span>
                    <span className="text-xs text-gray-400 ml-2">
                      {isNe ? section.title_en : section.title_ne}
                    </span>
                    {section.status === 'missing_data' && (
                      <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded ml-auto">
                        {t('reports.tab.missingData')}
                      </span>
                    )}
                    {section.status === 'manual_input' && (
                      <span className="text-xs bg-yellow-100 text-yellow-600 px-2 py-0.5 rounded ml-auto">
                        {t('reports.tab.manualInput')}
                      </span>
                    )}
                    <ReportSectionFixLinks calculationId={calculationId} status={section.status} missing={section.missing} titleNe={section.title_ne} />
                  </div>

                  {section.subsections && (
                    <div className="pl-8 pr-3 py-2 bg-white">
                      <button
                        onClick={() => toggleSectionExpand(section.section)}
                        className="text-xs text-gray-500 hover:text-gray-700"
                      >
                        {expandedSections[section.section] ? '\u25BC' : '\u25B6'} {t('reports.tab.toggleSubsections')}
                      </button>
                      {expandedSections[section.section] && (
                        <div className="mt-2 space-y-1">
                          {section.subsections.map((sub) => (
                            <div key={sub.key} className="flex items-center gap-2 text-sm py-1">
                              <span className="text-gray-500">({sub.key})</span>
                              <span>{isNe ? sub.title_ne : sub.title_en || sub.title_ne}</span>
                              {sub.status === 'missing_data' && (
                                <span className="text-xs bg-red-100 text-red-500 px-1 rounded">{t('reports.tab.noData')}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeImages}
                onChange={(e) => setIncludeImages(e.target.checked)}
                className="w-4 h-4"
              />
              <label className="text-sm">{t('reports.tab.includeImages')}</label>
            </div>
          </div>

          {generating && (
            <div className="bg-white rounded-lg shadow p-4">
              <h3 className="text-lg font-semibold mb-2">{t('reports.tab.generatingTitle')}</h3>
              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className="bg-green-600 h-3 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              <p className="text-sm text-gray-600 mt-2">{statusMessage}</p>
            </div>
          )}

          <div className="flex justify-between">
            <button
              onClick={() => setStep(2)}
              className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300"
            >
              &#x2190; {t('common.back')}
            </button>
            <button
              onClick={handleGenerate}
              disabled={generating || selectedSections.length === 0}
              className="px-6 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {generating ? t('reports.tab.generating') : t('reports.tab.generateSelected')}
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Preview & Download */}
      {step === 4 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">{t('reports.tab.previewTitle')}</h3>
            <div className="flex gap-2">
              <button
                onClick={handleDownload}
                disabled={!jobId}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                &#x1F4E5; {t('reports.tab.downloadDocx')}
              </button>
            </div>
          </div>

          {previewHtml ? (
            <div className="bg-white rounded-lg shadow p-4">
              <div
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(previewHtml) }}
                className="prose max-w-none"
              />
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
              <p className="text-lg">{t('reports.tab.noReport')}</p>
              <p className="text-sm mt-2">{t('reports.tab.noReportHint')}</p>
              <button
                onClick={() => setStep(3)}
                className="mt-4 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
              >
                {t('reports.tab.goToGeneration')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
