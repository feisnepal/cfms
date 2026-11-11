import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Checkbox, Modal, Space, Spin, Tag, Typography, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { subAreaPlanApi, type SubAreaPlanItem, type SubAreaPlanStatus } from '../../services/api';
import { getCategoryLabel } from '../../lib/subAreaCategories';
import { apiErrorText } from '../../lib/apiErrorText';

const { Text } = Typography;

const NEEDS = new Set(['needs_plan', 'no_unit', 'no_id']);

/** The sub-areas that stop the plan from being issued, and how many (a badge for the plan toolbar). */
export function useSubAreaPlanStatus(calculationId: string, refreshKey: unknown) {
  const [status, setStatus] = useState<SubAreaPlanStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    subAreaPlanApi
      .status(calculationId)
      .then((s) => live && setStatus(s))
      .catch(() => live && setStatus(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [calculationId, refreshKey, version]);
  return { status, loading, reload: () => setVersion((v) => v + 1) };
}

interface BadgeProps {
  count: number;
  onOpen: () => void;
}

/** "N sub-areas need a plan" - shown only when there are any. */
export const SubAreaPlanBadge: React.FC<BadgeProps> = ({ count, onOpen }) => {
  const t = useT();
  if (count <= 0) return null;
  return (
    <Button size="small" danger onClick={onOpen} data-testid="sub-area-plan-badge">
      {t('subAreaPlan.badge', { count })}
    </Button>
  );
};

interface Props {
  open: boolean;
  calculationId: string;
  /** a sub-area just drawn: the dialog asks "What will you do here?" about it first */
  focusId?: string | null;
  onClose: () => void;
  /** the plan changed (lines were created) */
  onChanged: () => void;
}

/**
 * Sub-areas must be tied to the yearly plan (private land excepted). This is the one place to do it: the guided step right
 * after drawing ("What will you do here?") and the list of everything that still needs a plan. "Decide later" just closes -
 * the sub-area stays on the list, and the plan cannot be issued until it has a plan.
 */
export const SubAreaPlanDialog: React.FC<Props> = ({ open, calculationId, focusId, onClose, onChanged }) => {
  const t = useT();
  const [status, setStatus] = useState<SubAreaPlanStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState<Record<string, number[]>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await subAreaPlanApi.status(calculationId);
      setStatus(s);
      setPicked((prev) => {
        const next = { ...prev };
        for (const item of s.sub_areas) {
          if (item.state === 'needs_plan' && !next[item.id] && item.suggestions?.length) next[item.id] = [item.suggestions[0].id];
        }
        return next;
      });
      return s;
    } catch (err) {
      message.error(apiErrorText(err, t('subAreaPlan.loadFailed') as string));
      return null;
    } finally {
      setLoading(false);
    }
  }, [calculationId, t]);

  useEffect(() => {
    if (!open) return;
    void load().then((s) => {
      // a sub-area that needs no plan (private land) or is already planned: nothing to ask
      if (s && focusId && !s.sub_areas.some((i) => i.id === focusId && NEEDS.has(i.state))) onClose();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, focusId, calculationId]);

  const needs = (status?.sub_areas ?? []).filter((i) => NEEDS.has(i.state));
  needs.sort((a, b) => Number(b.id === focusId) - Number(a.id === focusId));

  const planOne = async (item: SubAreaPlanItem) => {
    const ids = picked[item.id] ?? [];
    if (ids.length === 0) {
      message.warning(t('subAreaPlan.pickOne') as string);
      return;
    }
    setBusy(item.id);
    try {
      await subAreaPlanApi.plan(calculationId, item.id, ids);
      message.success(t('subAreaPlan.planned', { name: item.name }) as string);
      onChanged();
      await load();
    } catch (err) {
      message.error(apiErrorText(err, t('subAreaPlan.planFailed') as string));
    } finally {
      setBusy(null);
    }
  };

  const planAll = async () => {
    setBusy('all');
    try {
      const r = await subAreaPlanApi.planSuggested(calculationId);
      if (r.planned.length) message.success(t('subAreaPlan.plannedMany', { count: r.planned.length }) as string);
      if (r.skipped.length) message.warning(t('subAreaPlan.skippedMany', { count: r.skipped.length }) as string);
      onChanged();
      await load();
    } catch (err) {
      message.error(apiErrorText(err, t('subAreaPlan.planFailed') as string));
    } finally {
      setBusy(null);
    }
  };

  const row = (item: SubAreaPlanItem) => (
    <div
      key={item.id}
      data-testid={`sub-area-plan-row-${item.id}`}
      style={{ border: '1px solid #e5e7eb', borderRadius: 6, padding: 10, background: item.id === focusId ? '#f0fdf4' : undefined }}
    >
      <Space wrap>
        <Text strong>{item.name || item.id}</Text>
        <Tag>{getCategoryLabel(item.category)}</Tag>
        {item.area_ha != null && <Text type="secondary">{Number(item.area_ha).toFixed(2)} ha</Text>}
      </Space>
      {item.state === 'no_unit' && <Alert style={{ marginTop: 8 }} type="warning" showIcon message={t('subAreaPlan.noUnit') as string} />}
      {item.state === 'no_id' && <Alert style={{ marginTop: 8 }} type="warning" showIcon message={t('subAreaPlan.noId') as string} />}
      {item.state === 'needs_plan' && (
        <div style={{ marginTop: 8 }}>
          {item.suggestions && item.suggestions.length > 0 ? (
            <>
              <Text type="secondary">{t('subAreaPlan.suggested') as string}</Text>
              <div>
                <Checkbox.Group
                  value={picked[item.id] ?? []}
                  onChange={(vals) => setPicked((p) => ({ ...p, [item.id]: vals as number[] }))}
                  options={item.suggestions.map((s) => ({ value: s.id, label: s.activity }))}
                  style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}
                />
              </div>
              <Button
                type="primary"
                size="small"
                style={{ marginTop: 8 }}
                loading={busy === item.id}
                onClick={() => void planOne(item)}
                data-testid={`sub-area-plan-save-${item.id}`}
              >
                {t('subAreaPlan.planIt') as string}
              </Button>
            </>
          ) : (
            <Text type="secondary">{t('subAreaPlan.noSuggestion') as string}</Text>
          )}
        </div>
      )}
    </div>
  );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={600}
      title={t(focusId ? 'subAreaPlan.titleHere' : 'subAreaPlan.titleList') as string}
      destroyOnHidden
      footer={[
        <Button key="later" onClick={onClose} data-testid="sub-area-plan-later">
          {t(needs.length ? 'subAreaPlan.decideLater' : 'common.close') as string}
        </Button>,
        needs.length > 1 ? (
          <Button key="all" type="primary" loading={busy === 'all'} onClick={() => void planAll()} data-testid="sub-area-plan-all">
            {t('subAreaPlan.planAll') as string}
          </Button>
        ) : null,
      ]}
    >
      {loading && !status ? (
        <Spin />
      ) : needs.length === 0 ? (
        <Alert type="success" showIcon message={t('subAreaPlan.allPlanned') as string} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Text type="secondary">{t('subAreaPlan.intro') as string}</Text>
          {needs.map(row)}
        </div>
      )}
    </Modal>
  );
};
