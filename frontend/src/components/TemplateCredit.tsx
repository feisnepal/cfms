/** Small pieces that show who made a template and how far it can be trusted: tier tag, author line, credit chain, report. */
import React, { useEffect, useState } from 'react';
import { Tag, Typography, Steps, Modal, Input, Select, message, Spin } from 'antd';
import { operationalPlanApi } from '../services/api';
import type { LineageItem, TemplateTier } from '../services/api';
import { useT } from '../i18n/hooks';

const { Text } = Typography;

const TIER_COLOR: Record<TemplateTier, string> = { official: 'gold', verified: 'blue', community: 'default' };

export function TierTag({ tier }: { tier?: string }) {
  const t = useT();
  const key = (tier as TemplateTier) || 'community';
  return <Tag color={TIER_COLOR[key] ?? 'default'} style={{ fontSize: 9 }} data-testid="tier-tag">{t(`templates.tier.${key}`)}</Tag>;
}

export function AuthorLine({ name }: { name?: string | null }) {
  const t = useT();
  if (!name) return null;
  return <Text type="secondary" style={{ fontSize: 11, display: 'block' }}>{t('templates.credit.by', { name })}</Text>;
}

/** The chain, original author first. A private step the viewer may not see is a gap, not a name. */
export function TemplateLineage({ templateId }: { templateId: string }) {
  const t = useT();
  const [chain, setChain] = useState<LineageItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setChain(null);
    operationalPlanApi
      .getTemplateLineage(templateId)
      .then((r) => { if (!cancelled) setChain(r.chain); })
      .catch(() => { if (!cancelled) setChain([]); });
    return () => { cancelled = true; };
  }, [templateId]);

  if (!chain) return <Spin size="small" />;
  if (chain.length <= 1 && !chain[0]?.author_name) return null;
  return (
    <div style={{ marginBottom: 12 }} data-testid="template-lineage">
      <Text strong style={{ display: 'block', marginBottom: 6 }}>{t('templates.credit.chain')}</Text>
      <Steps
        direction="vertical"
        size="small"
        current={chain.length - 1}
        items={chain.map((c, i) => ({
          title: c.visible ? (c.name ?? '') : t('templates.credit.privateStep'),
          description: c.visible && c.author_name
            ? `${t(i === 0 ? 'templates.credit.originalBy' : 'templates.credit.adaptedBy', { name: c.author_name })}${c.withdrawn ? ` (${t('templates.credit.withdrawn')})` : ''}`
            : undefined,
        }))}
      />
    </div>
  );
}

export function ReportTemplateModal({ templateId, open, onClose }: { templateId: string | null; open: boolean; onClose: () => void }) {
  const t = useT();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setReason(''); }, [open]);

  const send = async () => {
    if (!templateId) return;
    setBusy(true);
    try {
      await operationalPlanApi.reportTemplate(templateId, reason.trim());
      message.success(t('templates.report.sent'));
      onClose();
    } catch {
      message.error(t('templates.report.failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onCancel={onClose} onOk={send} confirmLoading={busy} title={t('templates.report.title')}
      okText={t('templates.report.send')} okButtonProps={{ disabled: reason.trim().length < 5 }}>
      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>{t('templates.report.hint')}</Text>
      <Input.TextArea rows={4} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
    </Modal>
  );
}

/** Super admin only: Community / Verified / Official. */
export function TierControl({ templateId, tier, onChanged }: { templateId: string; tier?: string; onChanged: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const change = async (next: TemplateTier) => {
    setBusy(true);
    try {
      await operationalPlanApi.setTemplateTier(templateId, next);
      message.success(t('templates.tier.saved'));
      onChanged();
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      message.error(typeof d === 'string' ? d : (d?.message ?? t('templates.tier.failed')));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ marginBottom: 12 }}>
      <Text strong style={{ marginRight: 8 }}>{t('templates.tier.label')}</Text>
      <Select
        size="small"
        value={(tier as TemplateTier) || 'community'}
        loading={busy}
        onChange={change}
        style={{ width: 160 }}
        options={(['community', 'verified', 'official'] as TemplateTier[]).map((v) => ({ value: v, label: t(`templates.tier.${v}`) }))}
        data-testid="tier-control"
      />
    </div>
  );
}
