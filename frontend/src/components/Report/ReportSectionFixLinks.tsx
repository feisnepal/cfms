import React from 'react';
import { useTranslation } from 'react-i18next';
import { reportSectionFixes } from '../../lib/exportRequirementLinks';

/**
 * Next to a report section that cannot be generated yet: where to go to fix it. A section with data missing links to
 * the page that provides each missing kind of data; a section written by hand links to the Operational Plan.
 */
export function ReportSectionFixLinks({
  calculationId,
  status,
  missing,
  titleNe,
}: {
  calculationId: string;
  status: string;
  missing?: string[];
  /** the section's Nepali title: the chapter of the plan that holds its text */
  titleNe?: string;
}) {
  const { i18n } = useTranslation();
  const ne = i18n.language?.startsWith('ne');
  const fixes = reportSectionFixes(calculationId, status, missing, titleNe);
  if (fixes.length === 0) return null;
  return (
    <span className="ml-2 text-xs" data-testid="report-section-fix-links">
      {fixes.map((f) => (
        <a key={f.key} href={f.url} className="mr-2 text-blue-600 hover:underline" data-testid={`report-fix-${f.key}`}>
          {ne ? f.ne : f.en} &rarr;
        </a>
      ))}
    </span>
  );
}
