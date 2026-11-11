/** TemplateStoreReadiness -- what is still missing for this forest, shown above the template store. It never blocks: a template
 *  can be chosen and edited any time; only the export asks for the mandatory steps. */
import React, { useEffect, useState } from 'react';
import { Alert, Collapse, Spin } from 'antd';
import { useNavigate } from 'react-router-dom';
import { operationalPlanApi } from '../services/api';
import type { ExportRequirements } from '../services/api';
import { ExportRequirementsChecklist } from './ExportRequirementsChecklist';
import { useT } from '../i18n/hooks';

export default function TemplateStoreReadiness({ calculationId }: { calculationId: string }) {
  const t = useT();
  const navigate = useNavigate();
  const [data, setData] = useState<ExportRequirements | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setFailed(false);
    operationalPlanApi
      .getExportRequirementsForCalculation(calculationId)
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [calculationId]);

  if (failed) return null; // advisory only; the export enforces the same rule
  if (!data) return <Spin size="small" style={{ marginBottom: 16 }} />;

  const open = data.items.filter((i) => !i.done).length;
  if (open === 0) {
    return <Alert type="success" showIcon style={{ marginBottom: 16 }} message={t('templates.gallery.readyAll')} data-testid="store-readiness-ready" />;
  }
  return (
    <Alert
      type="warning"
      showIcon
      style={{ marginBottom: 16 }}
      data-testid="store-readiness-open"
      message={t('templates.gallery.readyOpen', { open, total: data.items.length })}
      description={
        <Collapse
          ghost
          items={[{
            key: 'list',
            label: t('templates.gallery.readyShow'),
            children: <ExportRequirementsChecklist data={data} calculationId={calculationId} onNavigate={(url) => navigate(url)} />,
          }]}
        />
      }
    />
  );
}
