/** AdminCostsPage — super-admin per-forest compute cost aggregation (CB-2).

Reads the /api/admin/costs/forests aggregation (pay-as-you-go CPU + memory per
forest) and renders it in an antd Table with a grand total row. Costs follow
the calculation cost engine's per-unit vCPU and per-unit GB-RAM billing.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Table, Button, Typography, Spin, Empty, Alert, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../i18n/hooks';
import { formatDecimal, formatDateTime } from '../i18n/numberFormat';
import { forestCostsApi, type ForestCostRow } from '../services/api';

const { Title, Text } = Typography;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const AdminCostsPage: React.FC = () => {
  const t = useT();
  const [rows, setRows] = useState<ForestCostRow[]>([]);
  const [grandTotal, setGrandTotal] = useState(0);
  const [currency, setCurrency] = useState('USD');
  const [loading, setLoading] = useState(true);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const data = await forestCostsApi.list();
      setRows(data.rows);
      setGrandTotal(data.grand_total);
      setCurrency(data.currency || 'USD');
    } catch (err) {
      message.error(t('adminCosts.loadFailed'));
      if (import.meta.env.DEV) console.error('[admin-costs] list failed', err);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  const displayName = (row: ForestCostRow) => {
    // A forest surfaced purely by its name never yields a UUID. The backend
    // coalesces blank names to the calculation id, so a UUID-shaped
    // forest_name is an unnamed forest.
    if (!row.forest_name || UUID_RE.test(row.forest_name)) {
      return t('adminCosts.unnamedForest');
    }
    return row.forest_name;
  };

  const columns: ColumnsType<ForestCostRow> = [
    {
      title: t('adminCosts.forestName'),
      dataIndex: 'forest_name',
      key: 'forest_name',
      render: (_, row) => displayName(row),
    },
    {
      title: t('adminCosts.calcCount'),
      dataIndex: 'calculation_count',
      key: 'calculation_count',
      align: 'right',
      width: 120,
      render: (v: number) => formatDecimal(v, 0),
    },
    {
      title: t('adminCosts.cpuSeconds'),
      dataIndex: 'total_cpu_seconds',
      key: 'total_cpu_seconds',
      align: 'right',
      width: 140,
      render: (v: number) => formatDecimal(v, 0),
    },
    {
      title: t('adminCosts.peakMemGb'),
      dataIndex: 'total_peak_memory_mb',
      key: 'total_peak_memory_mb',
      align: 'right',
      width: 150,
      render: (v: number) => formatDecimal(v / 1024, 2),
    },
    {
      title: t('adminCosts.cpuCost'),
      dataIndex: 'total_cpu_cost',
      key: 'total_cpu_cost',
      align: 'right',
      width: 130,
      render: (v: number) => formatDecimal(v, 4),
    },
    {
      title: t('adminCosts.memoryCost'),
      dataIndex: 'total_memory_cost',
      key: 'total_memory_cost',
      align: 'right',
      width: 130,
      render: (v: number) => formatDecimal(v, 4),
    },
    {
      title: `${t('adminCosts.totalCost')} (${currency})`,
      dataIndex: 'total_cost',
      key: 'total_cost',
      align: 'right',
      width: 150,
    },
    {
      title: t('adminCosts.lastRun'),
      dataIndex: 'last_run_at',
      key: 'last_run_at',
      align: 'right',
      width: 180,
    },
  ];

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-4">
        <Title level={3} style={{ marginBottom: 0 }}>
          {t('adminCosts.title')}
        </Title>
        <Button icon={<ReloadOutlined />} onClick={fetchRows} loading={loading}>
          {t('adminCosts.refresh')}
        </Button>
      </div>

      <Alert
        type="info"
        showIcon
        message={t('adminCosts.superAdminOnly')}
        description={t('adminCosts.superAdminOnlyDesc')}
        style={{ marginBottom: 16 }}
      />

      <Spin spinning={loading}>
        {rows.length === 0 && !loading ? (
          <Empty description={t('adminCosts.empty')} />
        ) : (
          <Table<ForestCostRow>
            rowKey="forest_name"
            columns={columns}
            dataSource={rows}
            pagination={false}
            bordered
            summary={() => (
              <Table.Summary.Row>
                <Table.Summary.Cell index={0} colSpan={6}>
                  <Text strong>{t('adminCosts.grandTotal')}</Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={6} align="right">
                  <Text strong>{formatDecimal(grandTotal, 4)}</Text>
                </Table.Summary.Cell>
                <Table.Summary.Cell index={7} />
              </Table.Summary.Row>
            )}
          />
        )}
      </Spin>
    </div>
  );
};

export default AdminCostsPage;
