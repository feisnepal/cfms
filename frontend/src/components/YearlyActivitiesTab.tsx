/**
 * YearlyActivitiesTab — the yearly plan on the Reports & Outputs screen.
 *
 * The plan itself is the shared `PlanHome` (YEARLY_ACTIVITIES plan P5): the editable table of what is planned, with
 * instant saving, Undo and version checks, the wizard for adding an activity, and the finder. This screen keeps what
 * is specific to it: where an activity applies (blocks / sub-areas), the map view and the summary.
 */
import React, { useState, useEffect, useRef } from 'react';
import { Tabs, Button, message, Space, Spin, Card, Statistic, Row, Col } from 'antd';
import type { TabsProps } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { yearlyActivitiesApi, type YearlyPlanLine } from '../services/api';
import { toSurfaceId } from '../lib/calcSurface';
import { useDimensionLabels } from '../hooks/useDimensionLabels';
import i18n from '../i18n';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';
import ActivityMapView from './YearlyActivities/ActivityMapView';
import { PlanGuidance } from '../features/yearly-plan/PlanGuidance';
import { PlanHome } from '../features/yearly-plan/PlanHome';
import { PlanExportMenu } from '../features/yearly-plan/PlanExportMenu';
import { LocationChooserModal } from '../features/yearly-plan/LocationChooserModal';
import { isYearlyPlanGuidanceEnabled } from '../config/featureFlags';

interface YearlyActivitiesTabProps {
  calculationId: string;
  /** the Yearly Activities step: the plan is a typed-into grid (the Reports tab and the standalone page keep the year panel) */
  gridMode?: boolean;
}

const YearlyActivitiesTab: React.FC<YearlyActivitiesTabProps> = ({ calculationId, gridMode = false }) => {
  const labels = useDimensionLabels({ hasCompartments: false });
  const t = useT();
  const navigate = useNavigate();
  const isNe = i18n.language === 'ne';
  const unitNoun = isNe ? labels.unitLabelNp : labels.unitLabel;
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [addSignal, setAddSignal] = useState(0);
  const [summary, setSummary] = useState<any>(null);
  const [locationLine, setLocationLine] = useState<YearlyPlanLine | null>(null);
  const homeRef = useRef<HTMLDivElement>(null);

  // Load data on mount and whenever the plan changes
  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId, refreshKey]);

  // The plan is edited from two screens over the same tables: re-read it when the user comes back.
  useEffect(() => {
    const refetch = () => {
      if (document.visibilityState !== 'hidden') setRefreshKey((prev) => prev + 1);
    };
    window.addEventListener('focus', refetch);
    document.addEventListener('visibilitychange', refetch);
    return () => {
      window.removeEventListener('focus', refetch);
      document.removeEventListener('visibilitychange', refetch);
    };
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      setSummary(await yearlyActivitiesApi.getSummary(calculationId).catch(() => null));
    } catch {
      message.error(t('yearlyPlan.error.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  // Summary tab content
  const summaryContent = (
    <div style={{ padding: '16px' }}>
      {summary ? (
        <>
          <Row gutter={16} style={{ marginBottom: '24px' }}>
            <Col span={8}>
              <Card>
                <Statistic
                  title={t('yearlyActivities.tab.statTotalActivities')}
                  value={summary.total_activities}
                  suffix={t('yearlyActivities.tab.suffixActivities')}
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card>
                <Statistic
                  title={t('yearlyActivities.tab.statTotalBudget')}
                  value={Number(summary.total_budget_10_years)}
                  prefix={t('yearlyActivities.tab.nprPrefix')}
                  precision={0}
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card>
                <Statistic
                  title={t('yearlyActivities.tab.statAvgBudget')}
                  value={Number(summary.total_budget_10_years) / 10}
                  prefix={t('yearlyActivities.tab.nprPrefix')}
                  precision={0}
                />
              </Card>
            </Col>
          </Row>

          <Card title={t('yearlyActivities.tab.byProject')} style={{ marginBottom: '16px' }}>
            {Object.entries(summary.by_project || {}).map(([project, count]) => (
              <div key={project} style={{ marginBottom: '8px' }}>
                <strong>{project}:</strong> {t('yearlyActivities.tab.activityCount', { count: formatNumber(count as number) })}
              </div>
            ))}
          </Card>

          <Card title={t('yearlyActivities.tab.byBlock', { unit: unitNoun })}>
            {Object.entries(summary.by_block || {}).map(([block, count]) => (
              <div key={block} style={{ marginBottom: '8px' }}>
                <strong>{block}:</strong> {t('yearlyActivities.tab.activityCount', { count: formatNumber(count as number) })}
              </div>
            ))}
          </Card>
        </>
      ) : (
        <p>{t('yearlyActivities.tab.noActivities')}</p>
      )}
    </div>
  );

  // a row's Draw button: the map workspace, with that line's shape armed; saving the place brings the user back here
  const drawOnMap = (line: YearlyPlanLine) =>
    navigate(`/calculations/${calculationId}?surface=${toSurfaceId('base', 'unified')}&draw=${line.id}&return=yearly`);

  const editOnMap = () => navigate(`/calculations/${calculationId}?surface=base/unified`);

  const tabItems: TabsProps['items'] = [
    {
      key: '1',
      label: t('yearlyActivities.tab.tabSelection'),
      children: (
        <div ref={homeRef}>
          <PlanHome
            calculationId={calculationId}
            refreshKey={refreshKey}
            onPlanChanged={() => setRefreshKey((prev) => prev + 1)}
            onEditOnMap={editOnMap}
            onOpenDetails={setLocationLine}
            addSignal={addSignal}
            gridMode={gridMode}
            onDrawOnMap={gridMode ? drawOnMap : undefined}
            toolbarExtra={<PlanExportMenu calculationId={calculationId} size="small" onFixIssue={() => homeRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })} />}
          />
        </div>
      ),
    },
    {
      key: '2',
      label: t('yearlyActivities.tab.tabMap'),
      children: <ActivityMapView calculationId={calculationId} />,
    },
    {
      key: '3',
      label: t('yearlyActivities.tab.tabSummary'),
      children: summaryContent,
    },
  ];

  return (
    <Spin spinning={loading}>
      <div style={{ padding: '16px' }}>
        <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between' }}>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((prev) => prev + 1)}>
              {t('yearlyActivities.page.refresh')}
            </Button>
          </Space>

          {summary && (
            <Space>
              <span><strong>{t('yearlyActivities.tab.totalActivities')}</strong> {formatNumber(summary.total_activities)}</span>
              <span><strong>{t('yearlyActivities.tab.totalBudget')}</strong> {t('units.npr', { value: formatNumber(Number(summary.total_budget_10_years)) })}</span>
            </Space>
          )}
        </div>

        {isYearlyPlanGuidanceEnabled() && (
          <PlanGuidance
            calculationId={calculationId}
            refreshKey={refreshKey}
            onOpenActivity={() => homeRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })}
            onAddFirst={() => setAddSignal((n) => n + 1)}
            onPlanChanged={() => setRefreshKey((prev) => prev + 1)}
          />
        )}

        <Tabs items={tabItems} />

        <LocationChooserModal
          calculationId={calculationId}
          line={locationLine}
          onClose={() => setLocationLine(null)}
          onSaved={() => setRefreshKey((prev) => prev + 1)}
        />
      </div>
    </Spin>
  );
};

export default YearlyActivitiesTab;
