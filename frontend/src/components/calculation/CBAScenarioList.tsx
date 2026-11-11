/**
 * CBAScenarioList — the scenario picker for the Cost-Benefit Analysis context
 * (CBA_MODULE_PLAN.md P4).
 *
 * One card per scenario (name · base badge · NPV / IRR / B-C / payback · status)
 * with New / Clone / Set-as-base / Auto-populate / Delete. Selecting a card
 * raises `onSelect`; the P5 editor mounts below the list in `CBATab`.
 */
import React, { useState } from 'react';
import { Card, Button, Tag, Space, Popconfirm, message, Empty } from 'antd';
import {
  PlusOutlined,
  CopyOutlined,
  StarOutlined,
  StarFilled,
  SyncOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { cbaApi, type CbaScenarioListItem } from '../../services/api';

interface Props {
  calculationId: string;
  scenarios: CbaScenarioListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** called after any create / clone / set-base / auto-populate / delete */
  onChanged: () => void;
}

const money = (v: string | null): string =>
  v == null
    ? '—'
    : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const pct = (frac: string | null): string =>
  frac == null ? 'N/A' : `${(Number(frac) * 100).toFixed(1)}%`;
const ratio = (v: string | null): string => (v == null ? 'N/A' : Number(v).toFixed(2));
const years = (v: string | null): string => (v == null ? '—' : `${Number(v).toFixed(1)}`);

export const CBAScenarioList: React.FC<Props> = ({
  calculationId,
  scenarios,
  selectedId,
  onSelect,
  onChanged,
}) => {
  const t = useT();
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (key: string, fn: () => Promise<unknown>, okMsg?: string) => {
    setBusy(key);
    try {
      await fn();
      if (okMsg) message.success(okMsg);
      onChanged();
    } catch {
      message.error(t('cba.list.actionFailed'));
    } finally {
      setBusy(null);
    }
  };

  const newScenario = () =>
    run(
      'new',
      async () => {
        const s = await cbaApi.createScenario(calculationId, {
          name: t('cba.list.newName', { n: scenarios.length + 1 }),
        });
        onSelect(s.id);
      },
      t('cba.list.created'),
    );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
        <h4 style={{ margin: 0 }}>{t('cba.list.heading')}</h4>
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          loading={busy === 'new'}
          onClick={newScenario}
        >
          {t('cba.list.new')}
        </Button>
      </div>

      {scenarios.length === 0 ? (
        <Empty description={t('cba.list.none')} />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {scenarios.map((s) => {
            const active = s.id === selectedId;
            return (
              <Card
                key={s.id}
                size="small"
                hoverable
                onClick={() => onSelect(s.id)}
                style={{
                  borderColor: active ? '#1677ff' : undefined,
                  borderWidth: active ? 2 : 1,
                }}
                title={
                  <Space size={6}>
                    <span>{s.name}</span>
                    {s.is_base_scenario && (
                      <Tag color="blue">{t('cba.list.base')}</Tag>
                    )}
                    {!s.has_result && (
                      <Tag>{t('cba.list.notComputed')}</Tag>
                    )}
                  </Space>
                }
                extra={
                  <Space size={2} onClick={(e) => e.stopPropagation()}>
                    <Button
                      size="small"
                      type="text"
                      icon={s.is_base_scenario ? <StarFilled /> : <StarOutlined />}
                      disabled={s.is_base_scenario || busy !== null}
                      loading={busy === `base-${s.id}`}
                      title={t('cba.list.setBase')}
                      onClick={() =>
                        run(
                          `base-${s.id}`,
                          () => cbaApi.setBase(calculationId, s.id),
                          t('cba.list.baseSet'),
                        )
                      }
                    />
                    <Button
                      size="small"
                      type="text"
                      icon={<SyncOutlined />}
                      loading={busy === `pop-${s.id}`}
                      disabled={busy !== null}
                      title={t('cba.list.autoPopulate')}
                      onClick={() =>
                        run(
                          `pop-${s.id}`,
                          async () => {
                            const res = await cbaApi.autoPopulate(s.id);
                            message.success(res.message);
                            // e.g. a locked row that now duplicates an automatic one: shown, never silently kept
                            (res.warnings ?? []).forEach((w) => message.warning(w, 8));
                          },
                        )
                      }
                    />
                    <Button
                      size="small"
                      type="text"
                      icon={<CopyOutlined />}
                      loading={busy === `clone-${s.id}`}
                      disabled={busy !== null}
                      title={t('cba.list.clone')}
                      onClick={() =>
                        run(
                          `clone-${s.id}`,
                          async () => {
                            const c = await cbaApi.clone(calculationId, s.id);
                            onSelect(c.id);
                          },
                          t('cba.list.cloned'),
                        )
                      }
                    />
                    <Popconfirm
                      title={t('cba.list.deleteConfirm', { name: s.name })}
                      onConfirm={() =>
                        run(
                          `del-${s.id}`,
                          async () => {
                            await cbaApi.deleteScenario(calculationId, s.id);
                            if (active) onSelect('');
                          },
                          t('cba.list.deleted'),
                        )
                      }
                      okButtonProps={{ danger: true }}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        disabled={busy !== null}
                        title={t('common.delete')}
                      />
                    </Popconfirm>
                  </Space>
                }
              >
                <Space size={16} wrap style={{ fontSize: 12 }}>
                  <span>
                    {t('cba.metric.npv')}: <b>{money(s.npv)}</b>
                  </span>
                  <span>
                    {t('cba.metric.irr')}: <b>{pct(s.irr)}</b>
                  </span>
                  <span>
                    {t('cba.metric.bcRatio')}: <b>{ratio(s.benefit_cost_ratio)}</b>
                  </span>
                  <span>
                    {t('cba.metric.payback')}: <b>{years(s.payback_period_years)}</b>
                  </span>
                  <span style={{ color: '#999' }}>
                    {s.cost_count} {t('cba.list.costs')} · {s.benefit_count}{' '}
                    {t('cba.list.benefits')}
                  </span>
                </Space>
              </Card>
            );
          })}
        </Space>
      )}
    </div>
  );
};

export default CBAScenarioList;
