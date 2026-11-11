/**
 * Yearly activities page — the yearly plan of one forest on a page of its own.
 *
 * The plan is the shared `PlanHome` (YEARLY_ACTIVITIES plan P5): it opens on "Your plan", an editable table whose
 * numbers save at once with a version check and Undo, with the add-activity questions and "Browse all activities".
 * There is no "Save All" and nothing to lose by leaving. What stays here is the page's own: the totals and the
 * charts that preview the operational plan. Places are drawn on the map ("Edit on map").
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Card, Row, Col, Button, Divider, Empty, Space, Statistic, Table, Typography } from 'antd';
import { BarChartOutlined, CloseOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { Bar, Pie } from 'react-chartjs-2';
import '../../utils/chartSetup';
import { yearlyPlanApi, type YearlyPlanLine } from '../../services/api';
import './YearlyActivitiesPage.css';
import CopyTag from '../DetailDescription/CopyTag';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';
import { useT } from '../../i18n/hooks';
import { PlanGuidance } from '../../features/yearly-plan/PlanGuidance';
import { PlanHome } from '../../features/yearly-plan/PlanHome';
import { PlanExportMenu } from '../../features/yearly-plan/PlanExportMenu';
import { LocationChooserModal } from '../../features/yearly-plan/LocationChooserModal';
import { PLAN_YEAR_NUMBERS } from '../../features/yearly-plan/planTableRules';
import { formatQuantity } from '../../features/yearly-plan/format';
import { isYearlyPlanGuidanceEnabled } from '../../config/featureFlags';
import { useCanDesignTemplates } from '../calculation/HazardVarChip';

const { Text, Title } = Typography;

interface YearlyActivitiesPageProps {
  calculationId?: string;
  forestName?: string;
  area?: number;
  onClose?: () => void;
}

/** The {{template}} copy-tag, shown to template designers only. */
const VarTag: React.FC<React.ComponentProps<typeof CopyTag> & { show: boolean }> = ({ show, ...rest }) =>
  show ? <CopyTag {...rest} /> : null;

const YEAR_COLOURS = ['#2ecc71', '#27ae60', '#1abc9c', '#16a085', '#3498db', '#2980b9', '#9b59b6', '#8e44ad', '#e67e22', '#d35400'];
const PROGRAM_COLOURS = ['#27ae60', '#2980b9', '#e67e22', '#e74c3c', '#9b59b6', '#f1c40f', '#1abc9c', '#2c3e50', '#d35400', '#8e44ad'];

const YearlyActivitiesPage: React.FC<YearlyActivitiesPageProps> = ({ calculationId, forestName, area, onClose }) => {
  const t = useT();
  const navigate = useNavigate();
  // the {{template}} copy-tags are for template designers; everyone else has no use for them
  const canDesign = useCanDesignTemplates();
  const [lines, setLines] = useState<YearlyPlanLine[] | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [addSignal, setAddSignal] = useState(0);
  const [locationLine, setLocationLine] = useState<YearlyPlanLine | null>(null);
  const homeRef = useRef<HTMLDivElement>(null);

  // Read the plan (for the totals and the charts) on mount, when something changes it, and when the user comes back:
  // the plan is edited from two screens over the same tables.
  const load = useCallback(async () => {
    if (!calculationId) return;
    try {
      setLines((await yearlyPlanApi.getPlan(calculationId)).lines);
    } catch {
      /* the plan table says so itself; the totals just stay as they were */
    }
  }, [calculationId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    const refetch = () => {
      if (document.visibilityState !== 'hidden') setRefreshKey((n) => n + 1);
    };
    window.addEventListener('focus', refetch);
    document.addEventListener('visibilitychange', refetch);
    return () => {
      window.removeEventListener('focus', refetch);
      document.removeEventListener('visibilitychange', refetch);
    };
  }, []);

  const totals = useMemo(() => {
    const list = lines ?? [];
    return {
      activities: list.length,
      budget: list.reduce((sum, l) => sum + (Number(l.total_budget) || 0), 0),
      places: list.reduce((sum, l) => sum + (Number(l.feature_count) || 0), 0),
    };
  }, [lines]);

  // What the operational plan will say, from the same effective numbers the table shows
  const preview = useMemo(() => {
    const list = lines ?? [];
    const byYear = PLAN_YEAR_NUMBERS.map((year) => {
      let count = 0;
      let quantity = 0;
      let budget = 0;
      for (const line of list) {
        const cell = line.years.find((y) => y.year === year);
        if (cell?.planned) {
          count += 1;
          quantity += Number(cell.quantity) || 0;
          budget += Number(cell.budget) || 0;
        }
      }
      return { year, activity_count: count, total_quantity: quantity, total_budget: budget };
    });
    const programs = new Map<string, number>();
    for (const line of list) {
      const name = line.program || (t('yearlyActivities.page.uncategorized') as string);
      programs.set(name, (programs.get(name) ?? 0) + (Number(line.total_budget) || 0));
    }
    return {
      byYear,
      programs: [...programs.entries()].map(([program, budget]) => ({ program, budget })).filter((p) => p.budget > 0),
      totalBudget: list.reduce((sum, l) => sum + (Number(l.total_budget) || 0), 0),
    };
  }, [lines, t]);

  const editOnMap = () => {
    if (calculationId) navigate(`/calculations/${calculationId}?surface=base/unified`);
  };

  if (!calculationId) {
    return (
      <div className="yearly-activities-page">
        <Empty description={t('yearlyPlan.error.loadFailed') as string} />
      </div>
    );
  }

  return (
    <div className="yearly-activities-page">
      {/* Header */}
      <div className="page-header">
        <div className="header-info">
          <Title level={4}>
            {t('yearlyActivities.page.title')}
            <VarTag show={canDesign} label="{{ya_activity_plan_detail}}" value="{{ya_activity_plan_detail}}" variant="section" />
          </Title>
          <Text strong>{t('yearlyActivities.page.forest', { name: forestName })}</Text>
          <Text type="secondary">
            {' | '}
            {t('yearlyActivities.page.area', { value: formatDecimal(area || 0, 1), unit: t('units.hectare') })}
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((n) => n + 1)}>
            {t('yearlyActivities.page.refresh')}
          </Button>
          {onClose && (
            <Button onClick={onClose} icon={<CloseOutlined />}>
              {t('common.close')}
            </Button>
          )}
        </Space>
      </div>

      {/* Summary Bar */}
      <div className="summary-bar">
        <Statistic title={t('yearlyActivities.page.statActivities')} value={totals.activities} data-testid="stat-activities" />
        <Statistic
          title={t('yearlyActivities.page.statTotalBudget')}
          value={totals.budget}
          formatter={(val) => t('units.npr', { value: formatNumber(Number(val)) })}
          data-testid="stat-budget"
        />
        <Statistic title={t('yearlyActivities.page.statFeatures')} value={totals.places} data-testid="stat-places" />
      </div>

      {isYearlyPlanGuidanceEnabled() && (
        <PlanGuidance
          calculationId={calculationId}
          refreshKey={refreshKey}
          onOpenActivity={() => homeRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })}
          onAddFirst={() => setAddSignal((n) => n + 1)}
          onPlanChanged={() => setRefreshKey((n) => n + 1)}
        />
      )}

      {/* The plan: Your plan | Browse all activities */}
      <div ref={homeRef} style={{ margin: '16px 0' }}>
        <PlanHome
          calculationId={calculationId}
          refreshKey={refreshKey}
          onPlanChanged={() => setRefreshKey((n) => n + 1)}
          onEditOnMap={editOnMap}
          onOpenDetails={setLocationLine}
          addSignal={addSignal}
          toolbarExtra={<PlanExportMenu calculationId={calculationId} size="small" onFixIssue={() => homeRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })} />}
        />
      </div>

      {/* OP Document Preview Section */}
      {(lines?.length ?? 0) > 0 && (
        <Card
          className="op-preview-card"
          size="small"
          title={
            <Space>
              <BarChartOutlined />
              <span>{t('yearlyActivities.page.opPreviewTitle')}</span>
            </Space>
          }
        >
          <Row gutter={[16, 16]}>
            {/* Year-wise Budget Bar Chart */}
            <Col xs={24} lg={14}>
              <div className="op-preview-chart">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Text strong style={{ fontSize: 13 }}>{t('yearlyActivities.page.chartYearBudget')}</Text>
                  <VarTag show={canDesign} label="{{chart:ya_budget_year_bar}}" value="{{chart:ya_budget_year_bar}}" variant="variable" />
                </div>
                <div style={{ width: '100%', height: 220 }}>
                  <Bar
                    height={220}
                    data={{
                      labels: preview.byYear.map((d) => t('yearlyPlan.planTable.yearShort', { n: formatNumber(d.year) })),
                      datasets: [
                        {
                          label: t('yearlyActivities.page.chartBudgetSeries'),
                          data: preview.byYear.map((d) => d.total_budget),
                          backgroundColor: preview.byYear.map((_, i) => YEAR_COLOURS[i % 10]),
                          borderRadius: 4,
                        },
                      ],
                    }}
                    options={{
                      responsive: true,
                      maintainAspectRatio: false,
                      scales: {
                        x: { ticks: { font: { size: 12 } }, grid: { display: true } },
                        y: { ticks: { font: { size: 11 }, callback: (v) => `${Math.round(Number(v) / 1000)}K` }, beginAtZero: true },
                      },
                      plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: (ctx) => t('units.npr', { value: formatNumber(Number(ctx.parsed.y)) }) } },
                      },
                    }}
                  />
                </div>
              </div>
            </Col>

            {/* Program-wise Budget Pie Chart */}
            <Col xs={24} lg={10}>
              <div className="op-preview-chart">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Text strong style={{ fontSize: 13 }}>{t('yearlyActivities.page.chartProgramShare')}</Text>
                  <VarTag show={canDesign} label="{{chart:ya_program_pie}}" value="{{chart:ya_program_pie}}" variant="variable" />
                </div>
                {preview.programs.length > 0 && (
                  <div style={{ width: '100%', height: 220 }}>
                    <Pie
                      height={220}
                      data={{
                        labels: preview.programs.map((d) => d.program),
                        datasets: [
                          {
                            data: preview.programs.map((d) => d.budget),
                            backgroundColor: preview.programs.map((_, i) => PROGRAM_COLOURS[i % 10]),
                            borderColor: '#fff',
                            borderWidth: 1,
                          },
                        ],
                      }}
                      options={{
                        plugins: {
                          legend: { display: false },
                          tooltip: {
                            callbacks: {
                              label: (ctx) => {
                                const d = preview.programs[ctx.dataIndex];
                                const percent = preview.totalBudget > 0 ? Math.round((d.budget / preview.totalBudget) * 100) : 0;
                                return `${d.program}: ${t('units.npr', { value: formatNumber(d.budget) })} (${formatNumber(percent)}%)`;
                              },
                            },
                          },
                        },
                      }}
                    />
                  </div>
                )}
              </div>
            </Col>
          </Row>

          {/* Year Summary Table — matches {{ya_year_summary}} */}
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <Text strong style={{ fontSize: 13 }}>{t('yearlyActivities.page.summaryTitle')}</Text>
            <VarTag show={canDesign} label="{{ya_year_summary}}" value="{{ya_year_summary}}" variant="variable" />
          </div>
          <Table
            size="small"
            dataSource={preview.byYear}
            rowKey="year"
            pagination={false}
            bordered
            columns={[
              { title: t('yearlyActivities.page.colYear'), dataIndex: 'year', width: 60, align: 'center' },
              { title: t('yearlyActivities.page.statActivities'), dataIndex: 'activity_count', width: 80, align: 'center' },
              { title: t('yearlyActivities.page.colTotalQty'), dataIndex: 'total_quantity', width: 100, align: 'right', render: (v: number) => formatQuantity(v) },
              { title: t('yearlyActivities.page.colBudgetNpr'), dataIndex: 'total_budget', align: 'right', render: (v: number) => formatNumber(v) },
            ]}
          />
        </Card>
      )}

      <LocationChooserModal
        calculationId={calculationId}
        line={locationLine}
        onClose={() => setLocationLine(null)}
        onSaved={() => setRefreshKey((n) => n + 1)}
      />
    </div>
  );
};

export default YearlyActivitiesPage;
