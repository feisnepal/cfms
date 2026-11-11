/**
 * CBALineItemEditor — the editable cost / benefit table for one CBA scenario
 * (CBA_MODULE_PLAN.md P5). One component drives both (`kind` prop) since the
 * rows differ only by a few columns.
 *
 * Rows are **auto** (`source_link` set — re-populate overwrites them) or
 * **manual** (`source_link` null — never touched). "Lock" converts an auto row
 * to manual so an edited value survives the next auto-populate. Every edit
 * saves on blur / change and re-fetches through `onChanged`.
 */
import React, { useEffect, useState } from 'react';
import { Table, Input, InputNumber, Button, Tag, Popconfirm, Space, message } from 'antd';
import { PlusOutlined, DeleteOutlined, UnlockOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import {
  cbaApi,
  type CbaCostItem,
  type CbaBenefitItem,
} from '../../services/api';

/** the shared shape — a cost row (has `category`) or a benefit row (has
 * `source` / `quantity` / `unit_price`); all kind-specific fields optional. */
type Row = Omit<CbaCostItem, 'category'> &
  Partial<Pick<CbaCostItem, 'category'>> &
  Partial<Pick<CbaBenefitItem, 'source' | 'quantity' | 'unit_price'>>;

interface Props {
  cbaId: string;
  kind: 'cost' | 'benefit';
  items: Row[];
  onChanged: () => void;
}

/** number cell that saves on blur when the value actually changed */
const NumCell: React.FC<{
  value: string | null;
  onSave: (v: number) => void;
  min?: number;
  step?: number;
}> = ({ value, onSave, min = 0, step = 1 }) => {
  const [v, setV] = useState<number>(Number(value ?? 0));
  useEffect(() => setV(Number(value ?? 0)), [value]);
  return (
    <InputNumber
      size="small"
      min={min}
      step={step}
      value={v}
      onChange={(n) => setV(Number(n ?? 0))}
      onBlur={() => {
        if (v !== Number(value ?? 0)) onSave(v);
      }}
      style={{ width: '100%' }}
    />
  );
};

const TextCell: React.FC<{ value: string; onSave: (v: string) => void }> = ({
  value,
  onSave,
}) => {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <Input
      size="small"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        if (v !== value) onSave(v);
      }}
    />
  );
};

const money = (v: string | null): string =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

export const CBALineItemEditor: React.FC<Props> = ({ cbaId, kind, items, onChanged }) => {
  const t = useT();
  const [busy, setBusy] = useState(false);

  const save = async (
    id: string,
    patch: Record<string, unknown>,
  ): Promise<void> => {
    // client-side guard: keep year_from ≤ year_to
    if ('year_from' in patch || 'year_to' in patch) {
      const row = items.find((r) => r.id === id);
      const yf = Number(patch.year_from ?? row?.year_from ?? 1);
      const yt = Number(patch.year_to ?? row?.year_to ?? 1);
      if (yf < 1 || yt < yf) {
        message.error(t('cba.items.yearRangeInvalid'));
        onChanged(); // re-fetch to reset the edited cell
        return;
      }
    }
    if ('amount_per_year' in patch && Number(patch.amount_per_year) < 0) {
      message.error(t('cba.items.amountNegative'));
      onChanged();
      return;
    }
    try {
      if (kind === 'cost') await cbaApi.updateCost(cbaId, id, patch);
      else await cbaApi.updateBenefit(cbaId, id, patch);
      onChanged();
    } catch {
      message.error(t('cba.items.saveFailed'));
    }
  };

  const addRow = async () => {
    setBusy(true);
    try {
      if (kind === 'cost')
        await cbaApi.createCost(cbaId, {
          category: '',
          description: '',
          year_from: 1,
          year_to: 10,
          amount_per_year: 0,
        });
      else
        await cbaApi.createBenefit(cbaId, {
          source: 'other',
          description: '',
          year_from: 1,
          year_to: 10,
          amount_per_year: 0,
        });
      onChanged();
    } catch {
      message.error(t('cba.items.addFailed'));
    } finally {
      setBusy(false);
    }
  };

  const removeRow = async (id: string) => {
    try {
      if (kind === 'cost') await cbaApi.deleteCost(cbaId, id);
      else await cbaApi.deleteBenefit(cbaId, id);
      onChanged();
    } catch {
      message.error(t('cba.items.deleteFailed'));
    }
  };

  const columns: ColumnsType<Row> = [
    {
      title: '',
      dataIndex: 'source_link',
      width: 66,
      render: (sl: string | null) => (
        <Tag color={sl ? 'blue' : 'default'}>
          {sl ? t('cba.items.auto') : t('cba.items.manual')}
        </Tag>
      ),
    },
    kind === 'cost'
      ? {
          title: t('cba.items.category'),
          dataIndex: 'category',
          render: (_: string, row: Row) => (
            <TextCell
              value={row.category ?? ''}
              onSave={(v) => save(row.id, { category: v })}
            />
          ),
        }
      : {
          title: t('cba.items.source'),
          dataIndex: 'source',
          render: (_: string, row: Row) => (
            <TextCell
              value={row.source ?? ''}
              onSave={(v) => save(row.id, { source: v })}
            />
          ),
        },
    {
      title: t('cba.items.description'),
      dataIndex: 'description',
      render: (_: string, row: Row) => (
        <TextCell
          value={row.description}
          onSave={(v) => save(row.id, { description: v })}
        />
      ),
    },
    {
      title: t('cba.items.yearFrom'),
      dataIndex: 'year_from',
      width: 90,
      render: (_: number, row: Row) => (
        <NumCell
          value={String(row.year_from)}
          min={1}
          onSave={(v) => save(row.id, { year_from: v })}
        />
      ),
    },
    {
      title: t('cba.items.yearTo'),
      dataIndex: 'year_to',
      width: 90,
      render: (_: number, row: Row) => (
        <NumCell
          value={String(row.year_to)}
          min={1}
          onSave={(v) => save(row.id, { year_to: v })}
        />
      ),
    },
    ...(kind === 'benefit'
      ? [
          {
            title: t('cba.items.quantity'),
            dataIndex: 'quantity',
            width: 110,
            render: (_: unknown, row: Row) => (
              <NumCell
                value={row.quantity ?? null}
                step={0.1}
                onSave={(v) => save(row.id, { quantity: v })}
              />
            ),
          },
          {
            title: t('cba.items.unitPrice'),
            dataIndex: 'unit_price',
            width: 120,
            render: (_: unknown, row: Row) => (
              <NumCell
                value={row.unit_price ?? null}
                step={100}
                onSave={(v) => save(row.id, { unit_price: v })}
              />
            ),
          },
        ]
      : []),
    {
      title: t('cba.items.amountPerYear'),
      dataIndex: 'amount_per_year',
      width: 130,
      render: (_: string, row: Row) => (
        <NumCell
          value={row.amount_per_year}
          step={1000}
          onSave={(v) => save(row.id, { amount_per_year: v })}
        />
      ),
    },
    {
      title: t('cba.items.total'),
      dataIndex: 'total_amount',
      width: 110,
      render: (v: string | null) => (
        <span style={{ color: '#888' }}>{money(v)}</span>
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 78,
      render: (_: unknown, row: Row) => (
        <Space size={2}>
          {row.source_link && (
            <Button
              size="small"
              type="text"
              icon={<UnlockOutlined />}
              title={t('cba.items.lock')}
              onClick={() => save(row.id, { source_link: null })}
            />
          )}
          <Popconfirm
            title={t('cba.items.deleteConfirm')}
            onConfirm={() => removeRow(row.id)}
            okButtonProps={{ danger: true }}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <h4 style={{ margin: 0 }}>
          {kind === 'cost' ? t('cba.items.costsHeading') : t('cba.items.benefitsHeading')}
        </h4>
        <Button size="small" icon={<PlusOutlined />} loading={busy} onClick={addRow}>
          {t('cba.items.addRow')}
        </Button>
      </div>
      <Table<Row>
        size="small"
        rowKey="id"
        columns={columns}
        dataSource={items}
        pagination={items.length > 20 ? { pageSize: 20, size: 'small' } : false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: t('cba.items.empty') }}
      />
    </div>
  );
};

export default CBALineItemEditor;
