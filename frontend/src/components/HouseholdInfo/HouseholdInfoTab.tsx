/**
 * Household Information Tab
 * Main container for household survey data management
 */
import React, { useState, useEffect } from 'react';
import { onDataImported } from '../../lib/uploadEvents';
import { Alert, Tabs, Spin, Button, Modal, Radio, message } from 'antd';
import {
  FileTextOutlined,
  UploadOutlined,
  TableOutlined,
  BarChartOutlined,
  TeamOutlined,
  AuditOutlined,
  ReloadOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { downloadFromApi } from '../../utils/download';
import * as api from '../../services/api';
import type { HouseholdInfo, HouseholdSummary } from '../../types/household';
import TemplateDownloadSection from './TemplateDownloadSection';
import FileUploadSection from './FileUploadSection';
import HouseholdDataTable from './HouseholdDataTable';
import HouseholdSummaryDashboard from './HouseholdSummary';
import CommitteeManagement from './CommitteeManagement';
import DemandSupplyTab from './DemandSupplyTab';
import HouseholdSummaryEntry from './HouseholdSummaryEntry';
import UserGroupChecklist from './UserGroupChecklist';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';

interface HouseholdInfoTabProps {
  calculationId: string;
  /** The tab to open on (`2` upload, `3` household data, `5` committee). Defaults to the first. */
  initialTab?: string;
}

const HouseholdInfoTab: React.FC<HouseholdInfoTabProps> = ({
  calculationId,
  initialTab = '1',
}) => {

  const t = useT();  const [households, setHouseholds] = useState<HouseholdInfo[]>([]);
  const [summary, setSummary] = useState<HouseholdSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState(initialTab);
  // For the reminder above the tabs: how many committee members are entered (reloaded when the user comes back from a tab).
  const [committeeCounts, setCommitteeCounts] = useState<{ main: number; other: number } | null>(null);
  useEffect(() => {
    let live = true;
    api.userGroupApi
      .getAllCommittees(calculationId)
      .then((c: any) => {
        if (live) setCommitteeCounts({ main: (c?.main_committee ?? []).length, other: (c?.advisory_committee ?? []).length + (c?.financial_committee ?? []).length });
      })
      .catch(() => {
        if (live) setCommitteeCounts({ main: 0, other: 0 }); // 404: nothing entered yet
      });
    return () => {
      live = false;
    };
  }, [calculationId, activeTab]);
  // Without household rows the user picks how to give the data: per household, or totals only.
  const [entryMode, setEntryMode] = useState<'households' | 'summary'>('households');

  // Load household data
  const loadHouseholds = async () => {
    setLoading(true);
    try {
      const data = await api.userGroupApi.getHouseholds(calculationId);
      setHouseholds(data);

      // If we have data, also load summary
      if (data.length > 0) {
        const summaryData = await api.userGroupApi.getHouseholdSummary(calculationId);
        setSummary(summaryData);
      } else {
        // No rows: a saved totals-only summary may still exist (the endpoint reads either).
        try {
          setSummary(await api.userGroupApi.getHouseholdSummary(calculationId));
          setEntryMode('summary');
        } catch (e: any) {
          if (e?.response?.status !== 404) throw e;
          setSummary(null);
        }
      }
    } catch (error: any) {
      // If 404, no data exists yet - this is OK
      if (error.response?.status === 404) {
        setHouseholds([]);
        setSummary(null);
      } else {
        console.error('Error loading households:', error);
        message.error(t('household.msgLoadFailed'));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHouseholds();
  }, [calculationId, refreshKey]);

  // A household list imported from "Add data" arrives from outside this tab: read it again.
  const reloadHouseholds = React.useRef<() => void>(() => {});
  reloadHouseholds.current = () => { void loadHouseholds(); };
  useEffect(
    () => onDataImported(({ purposes }) => {
      if (purposes.includes('households')) reloadHouseholds.current();
    }),
    [],
  );

  // Handle successful upload
  const handleUploadSuccess = () => {
    message.success(t('household.msgImported'));
    setRefreshKey((prev) => prev + 1);
    setActiveTab('3'); // Switch to data table tab
  };

  // Handle delete all
  const handleDeleteAll = () => {
    Modal.confirm({
      title: t('household.confirmDeleteAllTitle'),
      content: `This will permanently delete all ${households.length} household records. This action cannot be undone.`,
      okText: t('household.confirmDeleteAllOk'),
      okType: 'danger',
      cancelText: t('household.cancel'),
      onOk: async () => {
        try {
          await api.userGroupApi.deleteAllHouseholds(calculationId);
          message.success(t('household.msgAllDeleted'));
          setRefreshKey((prev) => prev + 1);
          setActiveTab('1');
        } catch (error) {
          console.error('Error deleting households:', error);
          message.error(t('household.msgDeleteFailed'));
        }
      },
    });
  };

  // Handle export
  const handleExport = async () => {
    try {
      await downloadFromApi(
        `/api/household/calculations/${calculationId}/excel`,
        `household_analysis_${new Date().toISOString().split('T')[0].replace(/-/g, '')}.xlsx`
      );
      message.success(t('household.msgExported'));
    } catch (error) {
      console.error('Error exporting analysis:', error);
      message.error(error instanceof Error ? error.message : t('household.msgExportFailed'));
    }
  };

  const hasData = households.length > 0;
  const summaryMode = !hasData && entryMode === 'summary';

  const householdItems = [
    {
      key: '1',
      label: (
        <span>
          <FileTextOutlined /> Download Template
        </span>
      ),
      children: (
        <TemplateDownloadSection
          calculationId={calculationId}
          hasExistingData={hasData}
        />
      ),
    },
    {
      key: '2',
      label: (
        <span>
          <UploadOutlined /> Upload Data
        </span>
      ),
      children: (
        <FileUploadSection
          calculationId={calculationId}
          hasExistingData={hasData}
          onUploadSuccess={handleUploadSuccess}
          onUploadPartial={() => setRefreshKey((prev) => prev + 1)}
          existingCount={households.length}
        />
      ),
      disabled: !hasData && false, // Always allow upload
    },
    {
      key: '3',
      label: (
        <span>
          <TableOutlined /> Household Data {hasData && `(${households.length})`}
        </span>
      ),
      children: hasData ? (
        <HouseholdDataTable
          households={households}
          onRefresh={() => setRefreshKey((prev) => prev + 1)}
          calculationId={calculationId}
        />
      ) : (
        <Alert
          message={t('household.noDataTitle')}
          description={t('household.noDataHint')}
          type="info"
          showIcon
        />
      ),
    },
    {
      key: '4',
      label: (
        <span>
          <BarChartOutlined /> Summary & Analysis
        </span>
      ),
      children: summary ? (
        <HouseholdSummaryDashboard summary={summary} calculationId={calculationId} />
      ) : (
        <Alert
          message={t('household.noAnalysisTitle')}
          description={t('household.noAnalysisHint')}
          type="info"
          showIcon
        />
      ),
    },
    {
      key: '5',
      label: (
        <span>
          <TeamOutlined /> Forest User Committee
        </span>
      ),
      children: (
        <CommitteeManagement calculationId={calculationId} />
      ),
    },
    {
      key: '6',
      label: (
        <span>
          <AuditOutlined /> Demand & Supply
        </span>
      ),
      children: (
        <DemandSupplyTab calculationId={calculationId} />
      ),
    },
  ];

  // Totals-only forests: the entry form, then the same analysis views. The per-household tabs are hidden --
  // switching the mode above brings them back.
  const summaryItems = [
    {
      key: '1',
      label: <span><TableOutlined /> {t('household.summaryEntry.tab', 'Summary entry')}</span>,
      children: (
        <HouseholdSummaryEntry calculationId={calculationId} onChanged={() => setRefreshKey((prev) => prev + 1)} />
      ),
    },
    householdItems[3],
    householdItems[4],
    householdItems[5],
  ];
  const items = summaryMode ? summaryItems : householdItems;

  return (
    <div style={{ padding: '20px' }}>
      <div
        style={{
          marginBottom: 20,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <h2 style={{ margin: 0 }}>{t('household.title')}</h2>
          <p style={{ margin: '5px 0 0 0', color: '#666' }}>
            {t('household.subtitle')}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          {hasData && (
            <>
              <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((prev) => prev + 1)}>
                {t('household.refresh')}
              </Button>
              <Button icon={<UploadOutlined />} onClick={handleExport}>
                {t('household.exportAnalysis')}
              </Button>
              <Button
                icon={<DeleteOutlined />}
                danger
                onClick={handleDeleteAll}
              >
                {t('household.deleteAll')}
              </Button>
            </>
          )}
        </div>
      </div>

      {!hasData && (
        <Radio.Group
          style={{ marginBottom: 16 }}
          value={entryMode}
          onChange={(e) => { setEntryMode(e.target.value); setActiveTab('1'); }}
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="households">{t('household.mode.households', 'Household-wise (upload or enter)')}</Radio.Button>
          <Radio.Button value="summary">{t('household.mode.summary', 'I only have totals (summary)')}</Radio.Button>
        </Radio.Group>
      )}

      {hasData && (
        <Alert
          message={t('household.recordCount', { count: formatNumber(households.length) })}
          description={`Total Population: ${summary?.total_population || 0} | Forest Dependent: ${summary?.forest_dependent_households || 0}`}
          type="success"
          showIcon
          style={{ marginBottom: 20 }}
        />
      )}

      <UserGroupChecklist
        committeesLoaded={committeeCounts !== null}
        hasHouseholds={hasData || summary !== null}
        mainCommitteeCount={committeeCounts?.main ?? 0}
        otherCommitteeCount={committeeCounts?.other ?? 0}
        onGoHouseholds={() => setActiveTab(summaryMode ? '3' : '2')}
        onGoCommittee={() => setActiveTab('5')}
      />

      <Spin spinning={loading}>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={items}
          type="card"
        />
      </Spin>
    </div>
  );
};

export default HouseholdInfoTab;
