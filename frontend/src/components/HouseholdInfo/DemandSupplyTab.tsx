/** Tab displaying demand vs. supply data with a bar chart and summary table for a user group. */
import React, { useState, useEffect } from 'react';
import { Table, Card, Alert, Spin, Typography, Divider } from 'antd';
import { Bar } from 'react-chartjs-2';
import '../../utils/chartSetup';
import { userGroupApi } from '../../services/api';
import { toNepaliDigit } from '../../constants/nepaliLabels';
import type { DemandSupplyResponse, ProductQuantities } from '../../types/demand_supply';
import HouseholdVariablePanel from './HouseholdVariablePanel';
import { formatDecimal } from '../../i18n/numberFormat';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';

const { Paragraph } = Typography;

interface DemandSupplyTabProps {
  calculationId: string;
}

const PRODUCT_LABELS: Record<string, string> = {
  firewood_bhari: 'demandSupply.firewoodBhari',
  grass_bhari: 'demandSupply.grassBhari',
  bedding_bhari: 'demandSupply.beddingBhari',
  timber_cft: 'demandSupply.timberCft',
  poles_count: 'demandSupply.poleCount',
};

/** The five product keys, typed so indexed access into `ProductQuantities` is safe. */
const PRODUCT_KEYS: readonly (keyof ProductQuantities)[] = [
  'firewood_bhari',
  'grass_bhari',
  'bedding_bhari',
  'timber_cft',
  'poles_count',
];

/** Deficit cells may be a number or the backend's dash placeholder for N/A. */
const isDash = (v: unknown) => v === '-' || v === null || v === undefined;

const np = (v: any, d = 2) => {
  if (v === '-' || v === null || v === undefined) return '-';
  return formatDecimal(Number(v), d);
};

const DemandSupplyTab: React.FC<DemandSupplyTabProps> = ({ calculationId }) => {

  const t = useT();  const [data, setData] = useState<DemandSupplyResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const result = await userGroupApi.getDemandSupply(calculationId);
        setData(result);
      } catch (err) {
        console.error(t('demandSupply.msgLoadFailed'), err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [calculationId]);

  const tableData = data
    ? PRODUCT_KEYS.map((key) => ({
        key,
        product: t(PRODUCT_LABELS[key]),
        demand: np(data.demand[key]),
        cf_regular: np(data.supply_cf_regular[key]),
        cf_aah: np(data.supply_cf_aah[key]),
        private: np(data.supply_private[key]),
        total_supply: np(data.total_supply[key]),
        deficit: data.deficit[key],
        deficit_display: isDash(data.deficit[key])
          ? '-' : toNepaliDigit(Math.abs(Number(data.deficit[key])), 2),
        deficit_sign: isDash(data.deficit[key])
          ? '' : Number(data.deficit[key]) >= 0 ? t('demandSupply.surplus') : t('demandSupply.deficit'),
      }))
    : [];

  const chartData = data
    ? PRODUCT_KEYS.map((key) => ({
        name: t(PRODUCT_LABELS[key]),
        demand: data.demand[key] ?? 0,
        supply: data.total_supply[key] ?? 0,
      }))
    : [];

  return (
    <Spin spinning={loading}>
      {data?.nepali_description && (
        <Card style={{ marginBottom: 16 }}>
          <Paragraph style={{ fontSize: 16, lineHeight: 1.8 }}>
            {i18n.language === 'ne'
              ? data.nepali_description.replace(/\d/g, (d) => '०१२३४५६७८९'[parseInt(d)])
              : data.nepali_description}
          </Paragraph>
        </Card>
      )}

      <Card title={t('demandSupply.statusTitle')} style={{ marginBottom: 16 }}>
        <p className="text-xs text-gray-400 font-mono mb-2">{'{{section:demand_supply_narration}}'}</p>
        <p className="text-xs text-gray-400 font-mono mb-2">{'{{table:demand_supply}}'}</p>
        <Table
          dataSource={tableData}
          columns={[
            { title: t('demandSupply.productType'), dataIndex: 'product', key: 'product', width: 140 },
            { title: t('demandSupply.demand'), dataIndex: 'demand', key: 'demand', align: 'right' },
            { title: t('demandSupply.collection'), dataIndex: 'cf_regular', key: 'cf_regular', align: 'right' },
            { title: t('demandSupply.annualCollection'), dataIndex: 'cf_aah', key: 'cf_aah', align: 'right' },
            { title: t('demandSupply.privateProduction'), dataIndex: 'private', key: 'private', align: 'right' },
            { title: t('demandSupply.totalSupply'), dataIndex: 'total_supply', key: 'total_supply', align: 'right', render: (v: any) => <strong>{v}</strong> },
            { title: t('demandSupply.surplusDeficit'), dataIndex: 'deficit', key: 'deficit', align: 'right', render: (_: any, record: any) => {
              if (record.deficit === '-' || record.deficit === null) return '-';
              return (
                <span style={{ color: Number(record.deficit) >= 0 ? '#059669' : '#dc2626', fontWeight: 600 }}>
                  {record.deficit_sign} {record.deficit_display}
                </span>
              );
            }},
          ]}
          pagination={false}
          bordered
          size="middle"
        />
      </Card>

      {chartData.length > 0 && (
        <Card title={t('demandSupply.comparison')}>
          <p className="text-xs text-gray-400 font-mono mb-1">{'{{chart:hh_demand_supply_bar}}'}</p>
          <div style={{ width: '100%', height: 350 }}>
            <Bar
              height={350}
              data={{
                labels: chartData.map((d) => d.name),
                datasets: [
                  { label: t('demandSupply.demand'), data: chartData.map((d) => d.demand), backgroundColor: '#dc2626', borderRadius: 4 },
                  { label: t('demandSupply.supply'), data: chartData.map((d) => d.supply), backgroundColor: '#059669', borderRadius: 4 },
                ],
              }}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                  x: { ticks: { font: { size: 12 } }, grid: { display: true } },
                  y: { ticks: { font: { size: 12 }, callback: (v) => toNepaliDigit(Number(v), 0) }, beginAtZero: true },
                },
                plugins: {
                  tooltip: {
                    callbacks: {
                      label: (ctx) => `${ctx.dataset.label}: ${toNepaliDigit(Number(ctx.parsed.y), 2)}`,
                    },
                  },
                },
              }}
            />
          </div>
        </Card>
      )}

      {!data && !loading && (
        <Alert message={t('demandSupply.noData')} type="info" showIcon />
      )}

      {calculationId && (
        <div style={{ marginTop: 24 }}>
          <Divider>{t('demandSupply.variables')}</Divider>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 60%', minWidth: 300 }}>
              <div style={{
                border: '1px solid #d9d9d9',
                borderRadius: 6,
                padding: 12,
                background: '#fafafa',
              }}>
                <h4 style={{ margin: '0 0 8px 0', fontSize: 13 }}>
                  {t('demandSupply.additionalNotes')}
                </h4>
                <textarea
                  id="demand-notes"
                  rows={4}
                  style={{
                    width: '100%',
                    border: '1px solid #d9d9d9',
                    borderRadius: 4,
                    padding: '8px 12px',
                    fontSize: 13,
                    lineHeight: 1.6,
                    fontFamily: 'inherit',
                    resize: 'vertical',
                  }}
                  placeholder={t('demandSupply.insertHint')}
                />
              </div>
            </div>
            <div style={{ flex: '0 0 340px' }}>
              <HouseholdVariablePanel
                calculationId={calculationId}
                tabKey="demand"
                onInsert={(varStr) => {
                  const ta = document.getElementById('demand-notes') as HTMLTextAreaElement;
                  if (ta) {
                    const start = ta.selectionStart;
                    const end = ta.selectionEnd;
                    ta.value = ta.value.substring(0, start) + varStr + ta.value.substring(end);
                    ta.focus();
                    ta.selectionStart = ta.selectionEnd = start + varStr.length;
                  }
                }}
              />
            </div>
          </div>
        </div>
      )}
    </Spin>
  );
};

export default DemandSupplyTab;
