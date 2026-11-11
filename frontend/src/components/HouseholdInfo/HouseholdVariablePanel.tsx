/** Panel for viewing and editing household-level variables with type-based rendering and save support. */
import React, { useState, useEffect } from 'react';
import { Card, Spin, Tag, Button, message, Empty } from 'antd';
import {
  CodeOutlined,
  InsertRowBelowOutlined,
  NumberOutlined,
  FieldStringOutlined,
  PieChartOutlined,
  CheckCircleFilled,
} from '@ant-design/icons';
import { operationalPlanApi } from '../../services/api';
import { toNepaliDigit } from '../../constants/nepaliLabels';
import { useT } from '../../i18n/hooks';
import { formatDecimal } from '../../i18n/numberFormat';

export type HouseholdTabKey = 'households' | 'summary' | 'committee' | 'demand';

interface VariableItem {
  key: string;
  label_ne: string;
  label_en: string;
  var_type: string;
  data_status: 'available' | 'empty' | 'unknown';
  sample_value: any;
}

interface HouseholdVariablePanelProps {
  calculationId: string;
  tabKey: HouseholdTabKey;
  onInsert: (variableKey: string) => void;
  nepalSummary?: string;
}

const TAB_VARIABLES: Record<HouseholdTabKey, string[]> = {
  households: [
    'hh_available', 'hh_total_households', 'hh_total_population',
    'hh_total_male', 'hh_total_female', 'hh_prosperity_distribution',
    'hh_caste_distribution', 'hh_timber_demand_cft', 'hh_firewood_demand_bhari',
    'hh_forest_based_occupation', 'ug_total_settlements', 'ug_buildings',
    'hh_records', 'section:household_narration', 'section:user_group_narration',
  ],
  summary: [
    'hh_total_households', 'hh_total_population', 'hh_total_male',
    'hh_total_female', 'hh_prosperity_distribution', 'hh_caste_distribution',
    'chart:hh_caste_pie', 'chart:hh_prosperity_bar',
  ],
  committee: [
    'uc_members', 'uc_total_members', 'ac_members', 'ac_total_members',
    'fc_members', 'fc_total_members', 'uc_gender_distribution',
    'uc_position_distribution', 'uc_caste_distribution', 'cf_chairperson',
    'section:committee_narration',
  ],
  demand: [
    'hh_timber_demand_cft', 'hh_firewood_demand_bhari',
    'chart:hh_demand_supply_bar', 'section:demand_supply_narration',
  ],
};

const TYPE_COLORS: Record<string, string> = {
  string: 'blue',
  number: 'green',
  boolean: 'orange',
  dict: 'purple',
  list: 'cyan',
  chart: 'magenta',
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  string: <FieldStringOutlined />,
  number: <NumberOutlined />,
  boolean: <CheckCircleFilled />,
  dict: <PieChartOutlined />,
  list: <InsertRowBelowOutlined />,
  chart: <PieChartOutlined />,
};

function formatSampleValue(v: any, type: string, t: (k: string, o?: any) => string): string {
  if (v === null || v === undefined) return '—';
  if (type === 'number') return formatDecimal(Number(v), 2);
  if (type === 'boolean') return v ? t('household.yes') : t('household.no');
  if (type === 'dict' && typeof v === 'object') {
    const entries = Object.entries(v).slice(0, 3);
    const parts = entries.map(([k, val]) => `${k}: ${val}`);
    if (Object.keys(v).length > 3) parts.push('...');
    return parts.join(', ');
  }
  if (type === 'list' && Array.isArray(v)) {
    return t('household.rowCount', { count: v.length });
  }
  if (type === 'chart') return t('household.chartData');
  return String(v).substring(0, 80);
}

const HouseholdVariablePanel: React.FC<HouseholdVariablePanelProps> = ({
  calculationId,
  tabKey,
  onInsert,
  nepalSummary,
}) => {

  const t = useT();  const [variables, setVariables] = useState<VariableItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (!calculationId) return;
    loadVariables();
  }, [calculationId, tabKey]);

  const loadVariables = async () => {
    setLoading(true);
    try {
      const response = await operationalPlanApi.getVariableCatalog(calculationId);
      const variablesList = response.variables || response;
      const allowedKeys = TAB_VARIABLES[tabKey] || [];
      const filtered: VariableItem[] = [];
      for (const item of variablesList) {
        if (allowedKeys.includes(item.key)) {
          filtered.push(item);
        }
      }
      filtered.sort((a, b) => allowedKeys.indexOf(a.key) - allowedKeys.indexOf(b.key));
      setVariables(filtered);
    } catch (err) {
      console.error('[HouseholdVariablePanel] Failed to load variables:', err);
      setVariables([]);
    } finally {
      setLoading(false);
    }
  };

  const handleInsert = (key: string) => {
    onInsert(`{{${key}}}`);
    message.success(t('household.variableInserted', { key }));
  };

  const typeColor = (type: string): string => {
    if (type.startsWith('chart')) return 'magenta';
    return TYPE_COLORS[type] || 'default';
  };

  const typeIcon = (type: string): React.ReactNode => {
    if (type.startsWith('chart')) return <PieChartOutlined />;
    return TYPE_ICONS[type] || <CodeOutlined />;
  };

  return (
    <Card
      size="small"
      title={
        <span style={{ fontSize: 13 }}>
          <CodeOutlined /> {t('household.availableVariables')}
        </span>
      }
      extra={
        <Button size="small" type="text" onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? t('household.expand') : t('household.collapse')}
        </Button>
      }
      style={{ marginBottom: 16, borderLeft: '3px solid #52c41a' }}
      styles={{ body: collapsed ? { display: 'none' } : { padding: '8px 12px', maxHeight: 400, overflowY: 'auto' } }}
    >
      {nepalSummary && (
        <div style={{
          background: '#f6ffed',
          border: '1px solid #b7eb8f',
          borderRadius: 6,
          padding: '10px 14px',
          marginBottom: 12,
          fontSize: 14,
          lineHeight: 1.8,
          fontFamily: 'inherit',
        }}>
          {nepalSummary}
        </div>
      )}

      <Spin spinning={loading}>
        {variables.length === 0 && !loading && (
          <Empty description={t('household.noVariables')} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {variables.map((v) => (
            <div
              key={v.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 8px',
                borderRadius: 4,
                background: v.data_status === 'available' ? '#fafff0' : '#fafafa',
                border: '1px solid',
                borderColor: v.data_status === 'available' ? '#b7eb8f' : '#f0f0f0',
                fontSize: 12,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 12, fontFamily: 'monospace', marginBottom: 2 }}>
                  <Tag color={typeColor(v.var_type)} style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                    {typeIcon(v.var_type)} {v.var_type}
                  </Tag>
                  {'{'}{'{'}{v.key}{'}'}{'}'}
                </div>
                <div style={{ color: '#555', fontSize: 12, lineHeight: 1.4 }}>
                  {v.label_ne || v.label_en}
                </div>
                <div style={{ color: '#888', fontSize: 11, marginTop: 2 }}>
                  {formatSampleValue(v.sample_value, v.var_type, t)}
                </div>
              </div>
              <Button
                size="small"
                type="primary"
                ghost
                style={{ fontSize: 11, marginLeft: 8, flexShrink: 0 }}
                onClick={() => handleInsert(v.key)}
              >
                {t('household.included')}
              </Button>
            </div>
          ))}
        </div>
      </Spin>
    </Card>
  );
};

export default HouseholdVariablePanel;
