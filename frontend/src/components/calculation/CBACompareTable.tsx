/**
 * CBACompareTable — side-by-side metrics across every scenario of a calculation
 * (CBA_MODULE_PLAN.md P6). Reads `POST .../cba/compare`; "Set as base" marks
 * one scenario as the `{{cba*}}` source.
 */
import React, { useEffect, useState } from 'react';
import { Table, Button, Tag, Spin, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import { cbaApi, type CbaCompareItem, type CbaScenarioListItem } from '../../services/api';

interface Props {
  calculationId: string;
  scenarios: CbaScenarioListItem[];
  onChanged: () => void;
}

const money = (v: string | null): string =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const pct = (v: string | null): string =>
  v == null ? 'N/A' : `${(Number(v) * 100).toFixed(1)}%`;
const num = (v: string | null, dp = 2): string => (v == null ? 'N/A' : Number(v).toFixed(dp));

export const CBACompareTable: React.FC<Props> = ({ calculationId, scenarios, onChanged }) => {
  const t = useT();
  const [rows, setRows] = useState<CbaCompareItem[]>([]);
  const [loading, setLoading] = useState(true);

  const ids = scenarios.map((s) => s.id).join(',');
  const baseId = scenarios.find((s) => s.is_base_scenario)?.id;

  useEffect(() => {
    let live = true;
    setLoading(true);
    cbaApi
      .compare(
        calculationId,
        ids.split(',').filter(Boolean),
      )
      .then((r) => {
        if (live) setRows(r);
      })
      .catch(() => {
        if (live) setRows([]);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [calculationId, ids]);

  const setBase = async (cbaId: string) => {
    try {
      await cbaApi.setBase(calculationId, cbaId);
      message.success(t('cba.list.baseSet'));
      onChanged();
    } catch {
      message.error(t('cba.list.actionFailed'));
    }
  };

  const columns: ColumnsType<CbaCompareItem> = [
    {
      title: t('cba.compare.scenario'),
      dataIndex: 'name',
      render: (name: string, r) => (
        <span>
          {name}
          {r.cba_id === baseId && (
            <Tag color="blue" style={{ marginInlineStart: 6 }}>
              {t('cba.list.base')}
            </Tag>
          )}
        </span>
      ),
    },
    { title: t('cba.metric.npv'), dataIndex: 'npv', render: (v) => money(v) },
    { title: t('cba.metric.irr'), dataIndex: 'irr', render: (v) => pct(v) },
    {
      title: t('cba.metric.bcRatio'),
      dataIndex: 'benefit_cost_ratio',
      render: (v) => num(v),
    },
    {
      title: t('cba.metric.payback'),
      dataIndex: 'payback_period_years',
      render: (v) => num(v, 1),
    },
    { title: t('cba.compare.totalCost'), dataIndex: 'total_cost', render: (v) => money(v) },
    {
      title: t('cba.compare.totalBenefit'),
      dataIndex: 'total_benefit',
      render: (v) => money(v),
    },
    {
      title: '',
      key: 'action',
      render: (_, r) =>
        r.cba_id === baseId ? null : (
          <Button size="small" type="link" onClick={() => setBase(r.cba_id)}>
            {t('cba.compare.setBase')}
          </Button>
        ),
    },
  ];

  if (loading) {
    return (
      <div style={{ padding: 16, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (rows.length < 2) {
    return null;
  }

  return (
    <div style={{ marginTop: 20 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('cba.compare.heading')}</h4>
      <Table<CbaCompareItem>
        size="small"
        rowKey="cba_id"
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    </div>
  );
};

export default CBACompareTable;
