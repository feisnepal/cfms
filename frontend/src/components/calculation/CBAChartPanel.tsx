/**
 * CBAChartPanel — the chart view for a computed CBA scenario
 * (CBA_MODULE_PLAN.md P6). Year-wise cost vs benefit (stacked bar) + cumulative
 * net cash flow (line), and cost-by-category / benefit-by-source pies. Data is
 * the scenario's `export-data` payload.
 */
import React, { useEffect, useState } from 'react';
import { Bar, Line, Pie } from 'react-chartjs-2';
import { Spin, Empty, Row, Col } from 'antd';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';
import { cbaApi, type CbaExportData } from '../../services/api';

interface Props {
  cbaId: string;
  /** changes to re-fetch after a Compute / edit (e.g. the scenario's updated_at) */
  refreshKey?: number | string;
}

const PIE_COLORS = [
  '#1677ff',
  '#52c41a',
  '#faad14',
  '#eb2f96',
  '#722ed1',
  '#13c2c2',
  '#fa541c',
  '#a0d911',
];

export const CBAChartPanel: React.FC<Props> = ({ cbaId, refreshKey = '' }) => {
  const t = useT();
  const [data, setData] = useState<CbaExportData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    cbaApi
      .exportData(cbaId)
      .then((d) => {
        if (live) setData(d);
      })
      .catch(() => {
        if (live) setData(null);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [cbaId, refreshKey]);

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (!data || data.cash_flow_table.length === 0) {
    return <Empty description={t('cba.charts.needCompute')} style={{ marginTop: 16 }} />;
  }

  const years = data.cash_flow_table.map((r) => `${t('cba.charts.year')} ${r.year}`);
  let cum = 0;
  const cumulative = data.cash_flow_table.map((r) => {
    cum += r.net;
    return Math.round(cum);
  });

  const pie = (rows: { label: string; amount: number }[]) => ({
    labels: rows.map((r) => r.label),
    datasets: [
      {
        data: rows.map((r) => Math.round(r.amount)),
        backgroundColor: rows.map((_, i) => PIE_COLORS[i % PIE_COLORS.length]),
      },
    ],
  });

  return (
    <div style={{ marginTop: 20 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('cba.charts.heading')}</h4>

      <div style={{ maxWidth: 720, marginBottom: 16 }}>
        <Bar
          data={{
            labels: years,
            datasets: [
              {
                label: t('cba.charts.cost'),
                data: data.cash_flow_table.map((r) => Math.round(r.cost)),
                backgroundColor: '#ff4d4f',
                stack: 'cf',
              },
              {
                label: t('cba.charts.benefit'),
                data: data.cash_flow_table.map((r) => Math.round(r.benefit)),
                backgroundColor: '#52c41a',
                stack: 'cf',
              },
            ],
          }}
          options={{
            responsive: true,
            plugins: { legend: { position: 'bottom' } },
            scales: { x: { stacked: true }, y: { stacked: true } },
          }}
        />
      </div>

      <div style={{ maxWidth: 720, marginBottom: 16 }}>
        <Line
          data={{
            labels: years,
            datasets: [
              {
                label: t('cba.charts.cumulativeNet'),
                data: cumulative,
                borderColor: '#1677ff',
                backgroundColor: 'rgba(22,119,255,0.1)',
                fill: true,
                tension: 0.2,
              },
            ],
          }}
          options={{ responsive: true, plugins: { legend: { position: 'bottom' } } }}
        />
      </div>

      <Row gutter={16}>
        {data.cost_breakdown.length > 0 && (
          <Col xs={24} md={12}>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>
              {t('cba.charts.costByCategory')}
            </div>
            <div style={{ maxWidth: 320 }}>
              <Pie data={pie(data.cost_breakdown)} options={{ plugins: { legend: { position: 'bottom' } } }} />
            </div>
          </Col>
        )}
        {data.benefit_breakdown.length > 0 && (
          <Col xs={24} md={12}>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>
              {t('cba.charts.benefitBySource')}
            </div>
            <div style={{ maxWidth: 320 }}>
              <Pie
                data={pie(data.benefit_breakdown)}
                options={{ plugins: { legend: { position: 'bottom' } } }}
              />
            </div>
          </Col>
        )}
      </Row>
    </div>
  );
};

export default CBAChartPanel;
