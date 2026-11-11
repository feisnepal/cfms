/** Tab component that renders detailed description sections with expandable cards, charts, and copy-to-clipboard support. */
import React, { useMemo, useState } from 'react';
import SectionCard from './SectionCard';
import { SECTION_GENERATORS, SECTION_TITLES } from '../../services/sectionGenerators';
import type { SectionContent } from '../../services/sectionGenerators';
import { useT } from '../../i18n/hooks';

interface DetailedDescriptionTabProps {
  calculation: any;
  fieldInventoryBreakdown?: any[];
  biodiversityData?: any;
}

interface SectionEntry {
  key: string;
  titleNp: string;
  titleEn: string;
  icon: string;
  content: SectionContent | null;
  hasData: boolean;
}

const DetailedDescriptionTab: React.FC<DetailedDescriptionTabProps> = ({ calculation, fieldInventoryBreakdown, biodiversityData }) => {

  const t = useT();  const [searchQuery, setSearchQuery] = useState('');

  const resultData = calculation?.result_data || {};

  const sections: SectionEntry[] = useMemo(() => {
    return SECTION_TITLES.map((meta) => {
      const genDef = SECTION_GENERATORS[meta.key];
      if (!genDef) return { ...meta, content: null, hasData: false };

      const hasAnyVar = genDef.variables.length === 0 || genDef.variables.some((v) => {
        const val = resultData[v];
        return val !== undefined && val !== null && val !== '' && val !== 0;
      });

      if (!hasAnyVar) return { ...meta, content: null, hasData: false };

      try {
      const extraData: Record<string, any> = {};
      if (fieldInventoryBreakdown) {
        extraData.fieldInventoryBreakdown = fieldInventoryBreakdown;
      }
      if (biodiversityData) {
        extraData.biodiversityData = biodiversityData;
      }
      const content = genDef.generatorFn(resultData, extraData);
        if (!content) return { ...meta, content: null, hasData: false };
        return { ...meta, content, hasData: true };
      } catch {
        return { ...meta, content: null, hasData: false };
      }
    });
  }, [resultData, fieldInventoryBreakdown, biodiversityData]);

  const filtered = useMemo(() => {
    const available = sections.filter((s) => s.hasData);
    if (!searchQuery.trim()) return available;
    const q = searchQuery.toLowerCase();
    return available.filter(
      (s) =>
        s.titleNp.includes(q) ||
        s.titleEn.toLowerCase().includes(q) ||
        s.key.includes(q)
    );
  }, [sections, searchQuery]);

  const availableCount = sections.filter((s) => s.hasData).length;

  return (
    <div className="p-6">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{t('operationalPlan.detail.title')}</h2>
            <p className="text-sm text-gray-500">{t('operationalPlan.detail.subtitle')}</p>
          </div>
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
            {availableCount} / {sections.length} sections available
          </span>
        </div>

        <div className="relative">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('operationalPlan.detail.search')}
            className="w-full px-3 py-2 pl-9 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500"
          />
          <svg className="absolute left-2.5 top-2.5 w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg">
          <p className="text-gray-500">
            {searchQuery
              ? t('operationalPlan.detail.noMatch')
              : t('operationalPlan.detail.noData')}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((section) => (
            <SectionCard
              key={section.key}
              sectionKey={section.key}
              content={section.content!}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default DetailedDescriptionTab;
