/** Chart editor for selecting data sources and previewing pie/bar charts within the operational plan document. */
import React, { useState, useEffect } from 'react';
import { Select, Spin, Empty, message, Card, Row, Col, Tag, Statistic } from 'antd';
import { Pie, Bar } from 'react-chartjs-2';
import { operationalPlanApi } from '../../services/api';
import '../../utils/chartSetup';
import { useDimensionLabels } from '../../hooks/useDimensionLabels';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';

interface ChartEditorProps {
  planId: string;
}

interface ChartData {
  chart_type: string;
  title: string;
  labels: string[];
  datasets: {
    label: string;
    data: number[];
    backgroundColor: string | string[];
    borderColor?: string | string[];
    borderWidth?: number;
  }[];
}

function makeChartOptions(
  labels: ReturnType<typeof useDimensionLabels>,
  t: (k: string, opts?: Record<string, unknown>) => string,
): { value: string; label: string; category: string }[] {
  return [
    { value: 'species_pie', label: t('operationalPlan.chart.speciesComposition'), category: 'Pie' },
    { value: 'forest_type_pie', label: t('operationalPlan.chart.forestType'), category: 'Pie' },
    { value: 'slope_pie', label: t('operationalPlan.chart.slope'), category: 'Pie' },
    { value: 'canopy_pie', label: t('operationalPlan.chart.canopy'), category: 'Pie' },
    { value: 'landcover_pie', label: t('operationalPlan.chart.landCover'), category: 'Pie' },
    { value: 'block_area_bar', label: t('operationalPlan.chart.unitWiseArea', { unit: i18n.language === 'ne' ? labels.unitLabelNp : labels.unitLabel }), category: 'Bar' },
    { value: 'dbh_histogram', label: t('operationalPlan.chart.dbhClass'), category: 'Bar' },
    { value: 'biomass_bar', label: t('operationalPlan.chart.biomassCarbon'), category: 'Bar' },
  ];
}

const PIE_OPTIONS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { position: 'bottom' as const, labels: { font: { size: 12 }, padding: 12 } },
    title: { display: true, text: '', font: { size: 14 } },
  },
};

const BAR_OPTIONS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    title: { display: true, text: '', font: { size: 14 } },
  },
  scales: {
    y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.06)' } },
    x: { grid: { display: false } },
  },
};

const ChartEditor: React.FC<ChartEditorProps> = ({ planId }) => {
  const t = useT();
  const labels = useDimensionLabels({ hasCompartments: false });
  const [selectedType, setSelectedType] = useState<string>('species_pie');
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadChartData(selectedType);
  }, [selectedType, planId]);

  const loadChartData = async (chartType: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await operationalPlanApi.getChartData(planId, chartType);
      setChartData(data);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setError(t('operationalPlan.chart.noDataForType'));
      } else {
        setError(t('operationalPlan.chart.loadFailed'));
      }
      setChartData(null);
    } finally {
      setLoading(false);
    }
  };

  const chartOptions = makeChartOptions(labels, t);
  const selectedOption = chartOptions.find(o => o.value === selectedType);
  const isPie = selectedOption?.category === 'Pie';
  const total = chartData?.datasets?.[0]?.data?.reduce((a: number, b: number) => a + b, 0) ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Select
          style={{ width: 320 }}
          value={selectedType}
          onChange={setSelectedType}
          options={[
            { label: t('operationalPlan.chart.groupPie'), value: '', disabled: true },
            ...chartOptions.filter(o => o.category === 'Pie').map(o => ({ value: o.value, label: o.label })),
            { label: t('operationalPlan.chart.groupBar'), value: '', disabled: true },
            ...chartOptions.filter(o => o.category === 'Bar').map(o => ({ value: o.value, label: o.label })),
          ]}
        />
        {selectedOption && (
          <Tag color={isPie ? 'blue' : 'geekblue'}>{selectedOption.category}</Tag>
        )}
        {chartData && (
          <Statistic
            title={t('operationalPlan.chart.dataPoints')}
            value={chartData.labels.length}
            suffix={isPie ? 'categories' : 'items'}
            valueStyle={{ fontSize: 14 }}
          />
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {loading ? (
          <div style={{ textAlign: 'center' }}>
            <Spin size="large" />
            <div style={{ marginTop: 12 }}>{t('operationalPlan.chart.loadingData')}</div>
          </div>
        ) : error ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>{isPie ? '🥧' : '📊'}</div>
            <div style={{ fontSize: 16, fontWeight: 500, marginBottom: 8 }}>{error}</div>
            <div style={{ fontSize: 13 }}>
              {t('operationalPlan.chart.emptyHint')}
            </div>
          </div>
        ) : chartData ? (
          <Row gutter={24} style={{ width: '100%', maxWidth: 900 }}>
            <Col xs={24} md={isPie ? 14 : 24}>
              <Card style={{ minHeight: 400 }}>
                <div style={{ height: isPie ? 380 : 350 }}>
                  {isPie ? (
                    <Pie
                      data={{
                        labels: chartData.labels,
                        datasets: chartData.datasets.map(ds => ({
                          ...ds,
                          backgroundColor: Array.isArray(ds.backgroundColor)
                            ? ds.backgroundColor
                            : [ds.backgroundColor],
                        })),
                      }}
                      options={{
                        ...PIE_OPTIONS,
                        plugins: {
                          ...PIE_OPTIONS.plugins,
                          title: { ...PIE_OPTIONS.plugins.title, text: chartData.title },
                        },
                      }}
                    />
                  ) : (
                    <Bar
                      data={{
                        labels: chartData.labels,
                        datasets: chartData.datasets.map(ds => ({
                          ...ds,
                          backgroundColor: Array.isArray(ds.backgroundColor)
                            ? ds.backgroundColor
                            : [ds.backgroundColor],
                        })),
                      }}
                      options={{
                        ...BAR_OPTIONS,
                        plugins: {
                          ...BAR_OPTIONS.plugins,
                          title: { ...BAR_OPTIONS.plugins.title, text: chartData.title },
                        },
                      }}
                    />
                  )}
                </div>
              </Card>
            </Col>
            {isPie && (
              <Col xs={24} md={10}>
                <Card title={t('operationalPlan.chart.dataBreakdown')} size="small">
                  <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '2px solid #f0f0f0' }}>
                        <th style={{ textAlign: 'left', padding: '6px 8px' }}>{t('operationalPlan.chart.category')}</th>
                        <th style={{ textAlign: 'right', padding: '6px 8px' }}>{t('operationalPlan.chart.value')}</th>
                        <th style={{ textAlign: 'right', padding: '6px 8px' }}>{t('operationalPlan.chart.share')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {chartData.labels.map((label, i) => {
                        const val = chartData.datasets[0]?.data?.[i] ?? 0;
                        const colors = chartData.datasets[0]?.backgroundColor;
                        const color = Array.isArray(colors) ? colors[i] : '#999';
                        const pct = total > 0 ? ((val / total) * 100).toFixed(1) : '0.0';
                        return (
                          <tr key={i} style={{ borderBottom: '1px solid #f5f5f5' }}>
                            <td style={{ padding: '4px 8px' }}>
                              <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: color as string, marginRight: 8 }} />
                              {label}
                            </td>
                            <td style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600 }}>{val}</td>
                            <td style={{ textAlign: 'right', padding: '4px 8px', color: '#666' }}>{pct}%</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Card>
              </Col>
            )}
          </Row>
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
            <div>{t('operationalPlan.chart.selectPrompt')}</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChartEditor;
