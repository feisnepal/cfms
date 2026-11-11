/**
 * HazardChartsPanel — the charts half of the Hazard & Erosion context
 * (HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P4). The page had no charts before;
 * these are the core-4 `chart:hazard_*` variables, resolved for this forest
 * via `variable-catalog?keys=` and each carrying its copy-token chip.
 */
import React, { useEffect, useState } from 'react';
import { Spin, Empty, Space } from 'antd';
import { Bar } from 'react-chartjs-2';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';
import { operationalPlanApi } from '../../services/api';
import { HazardVarChip } from './HazardVarChip';

interface Props {
  calculationId: string;
  refreshKey?: number;
}

const CHART_KEYS = [
  'chart:hazard_landslide_area_by_class',
  'chart:hazard_slope_class_split',
  'chart:hazard_household_driver_split',
  'chart:hazard_erosion_aoi_comparison',
] as const;

const OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: { y: { beginAtZero: true } },
};

type ChartDict = { labels: string[]; datasets: unknown[] };
const isChartDict = (v: unknown): v is ChartDict =>
  !!v && typeof v === 'object' && !Array.isArray(v) && 'datasets' in (v as object);

export const HazardChartsPanel: React.FC<Props> = ({ calculationId, refreshKey = 0 }) => {
  const t = useT();
  const [byKey, setByKey] = useState<Record<string, ChartDict | null>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    operationalPlanApi
      .getVariableCatalog(calculationId, { keys: CHART_KEYS.join(',') })
      .then((d: { variables?: { key: string; resolved?: unknown }[] }) => {
        if (!live) return;
        const m: Record<string, ChartDict | null> = {};
        for (const r of d.variables || []) {
          m[r.key] = isChartDict(r.resolved) ? (r.resolved as ChartDict) : null;
        }
        setByKey(m);
      })
      .catch(() => { if (live) setByKey({}); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [calculationId, refreshKey]);

  if (loading) {
    return <div style={{ padding: 20, textAlign: 'center' }}><Spin /></div>;
  }

  const present = CHART_KEYS.filter((k) => byKey[k]);
  if (!present.length) return null;

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('hazardErosion.charts.heading')}</h4>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
        {present.map((k) => (
          <div key={k} style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12 }}>
            <Space style={{ marginBottom: 4 }}>
              <span style={{ fontSize: 12, color: '#666' }}>{t(`hazardErosion.charts.${k.replace('chart:hazard_', '')}`)}</span>
              <HazardVarChip tokenKey={k} />
            </Space>
            <div style={{ height: 200 }}>
              <Bar data={byKey[k] as never} options={OPTS as never} />
            </div>
          </div>
        ))}
      </div>
      {!present.length && <Empty description={t('hazardErosion.charts.none')} />}
    </div>
  );
};

export default HazardChartsPanel;
