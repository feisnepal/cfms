/** Expandable card that wraps a section title, its chart/legend, and a copy-tag for each content entry. */
import React, { useState } from 'react';
import NepaliChart from './NepaliChart';
import NepaliLegend from './NepaliLegend';
import CopyTag from './CopyTag';
import { SectionContent } from '../../services/sectionGenerators';
import { useT } from '../../i18n/hooks';

interface SectionCardProps {
  sectionKey: string;
  content: SectionContent;
  onInsert?: (sectionKey: string) => void;
}

const SectionCard: React.FC<SectionCardProps> = ({ sectionKey, content, onInsert }) => {

  const t = useT();  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-lg">{expanded ? '▼' : '▶'}</span>
          <div>
            <h3 className="font-semibold text-gray-900">{content.titleNp}</h3>
            <p className="text-xs text-gray-500">{content.titleEn}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <CopyTag
            label={`{{section:${sectionKey}}}`}
            value={`{{section:${sectionKey}}}`}
            variant="section"
          />
          <CopyTag
            label={`{{section:${sectionKey}:full}}`}
            value={`{{section:${sectionKey}:full}}`}
            variant="section"
          />
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-100">
          <div className="mt-3 space-y-4">
            <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-line">
              {content.narrative}
            </div>

            {content.graphics.type !== 'none' && content.graphics.data.length > 0 && (
              <div className="bg-gray-50 rounded-lg p-3">
                <NepaliChart graphic={content.graphics} />
              </div>
            )}

            {content.legend.length > 0 && <NepaliLegend items={content.legend} />}

            <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-gray-100">
              <span className="text-xs text-gray-500 font-medium mr-1">{t('operationalPlan.detail.variables')}</span>
              {content.variables.map((v) => (
                <CopyTag key={v} label={`{{${v}}}`} value={`{{${v}}}`} variant="variable" />
              ))}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-gray-100">
              <span className="text-xs text-gray-400">Source: {content.source}</span>
              {onInsert && (
                <button
                  onClick={() => onInsert(sectionKey)}
                  className="px-3 py-1.5 text-xs font-medium text-white bg-green-600 rounded-md hover:bg-green-700 transition-colors"
                >
                  + Insert into Document
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SectionCard;
