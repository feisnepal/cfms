/** ShareTemplateModal -- the author chooses who sees a template (only me / my office / everyone) and under what licence.
 *  The publish check runs first; its errors stop the sharing, its warnings are shown and the author decides. */
import React, { useEffect, useState } from 'react';
import { Modal, Radio, Select, Alert, List, Spin, Typography, message } from 'antd';
import { operationalPlanApi } from '../services/api';
import type { PublishCheck, PublishCheckIssue, ShareScope, TemplateLicense } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';

const { Text } = Typography;

// Issue codes with a plain line in both languages (templates.share.code.*); any other shows the server's text.
const KNOWN = new Set(['description_short', 'name_missing', 'forest_name_inside', 'typed_numbers', 'unknown_token', 'empty_section']);

interface Props {
  open: boolean;
  template: { id: string; name: string; share_scope?: string; license?: string } | null;
  onClose: () => void;
  onShared: () => void;
}

export default function ShareTemplateModal({ open, template, onClose, onShared }: Props) {
  const t = useT();
  const { user } = useAuth();
  const hasOffice = Boolean(user?.organization_id);
  const [scope, setScope] = useState<ShareScope>('public');
  const [license, setLicense] = useState<TemplateLicense>('cc_by');
  const [check, setCheck] = useState<PublishCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !template) return;
    const current = (template.share_scope as ShareScope) || 'private';
    setScope(current === 'private' ? 'public' : current);
    setLicense((template.license as TemplateLicense) || 'cc_by');
    setCheck(null);
  }, [open, template]);

  useEffect(() => {
    if (!open || !template || scope === 'private') { setCheck(null); return; }
    let cancelled = false;
    setChecking(true);
    operationalPlanApi
      .checkTemplateForSharing(template.id)
      .then((c) => { if (!cancelled) setCheck(c); })
      .catch(() => { if (!cancelled) setCheck(null); })
      .finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, [open, template, scope]);

  const line = (i: PublishCheckIssue) =>
    KNOWN.has(i.code) ? t(`templates.share.code.${i.code}`, { name: i.name ?? '', numbers: (i.numbers ?? []).join(', ') }) : i.message;

  const issues = (list: PublishCheckIssue[], tone: 'error' | 'warning') =>
    list.length === 0 ? null : (
      <Alert
        type={tone}
        showIcon
        style={{ marginTop: 8 }}
        message={t(tone === 'error' ? 'templates.share.mustFix' : 'templates.share.lookAt')}
        description={
          <List size="small" split={false} dataSource={list}
            renderItem={(i) => (
              <List.Item style={{ padding: '2px 0' }} data-testid={`share-issue-${i.code}`}>
                {line(i)}{i.title ? <Text type="secondary"> ({i.title})</Text> : null}
              </List.Item>
            )} />
        }
      />
    );

  const submit = async () => {
    if (!template) return;
    setSaving(true);
    try {
      await operationalPlanApi.shareTemplate(template.id, scope, license);
      message.success(t(scope === 'private' ? 'templates.share.msgPrivate' : 'templates.share.msgShared'));
      onShared();
      onClose();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail?.issues) setCheck({ ok: false, errors: detail.issues, warnings: [] });
      else message.error(typeof detail === 'string' ? detail : t('templates.share.failed'));
    } finally {
      setSaving(false);
    }
  };

  const blocked = scope !== 'private' && (checking || !check || !check.ok);

  return (
    <Modal
      open={open}
      title={t('templates.share.title', { name: template?.name ?? '' })}
      onCancel={onClose}
      onOk={submit}
      okText={t(scope === 'private' ? 'templates.share.makePrivate' : 'templates.share.share')}
      okButtonProps={{ disabled: blocked, 'data-testid': 'share-ok' } as any}
      confirmLoading={saving}
      width={560}
    >
      <Radio.Group value={scope} onChange={(e) => setScope(e.target.value)} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Radio value="public">
          <b>{t('templates.share.public')}</b>
          <div><Text type="secondary">{t('templates.share.publicHint')}</Text></div>
        </Radio>
        <Radio value="office" disabled={!hasOffice}>
          <b>{t('templates.share.office')}</b>
          <div><Text type="secondary">{hasOffice ? t('templates.share.officeHint') : t('templates.share.noOffice')}</Text></div>
        </Radio>
        <Radio value="private">
          <b>{t('templates.share.private')}</b>
          <div><Text type="secondary">{t('templates.share.privateHint')}</Text></div>
        </Radio>
      </Radio.Group>

      {scope !== 'private' && (
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 4 }}>{t('templates.share.licence')}</div>
          <Select
            value={license}
            onChange={setLicense}
            style={{ width: '100%' }}
            options={[
              { value: 'cc_by', label: t('templates.share.licCcBy') },
              { value: 'cc0', label: t('templates.share.licCc0') },
              { value: 'view_only', label: t('templates.share.licViewOnly') },
            ]}
          />
          <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>{t('templates.share.terms')}</Text>
          {checking && <div style={{ marginTop: 12 }}><Spin size="small" /> {t('templates.share.checking')}</div>}
          {check && issues(check.errors, 'error')}
          {check && issues(check.warnings, 'warning')}
          {check && check.ok && check.warnings.length === 0 && (
            <Alert type="success" showIcon style={{ marginTop: 8 }} message={t('templates.share.checkOk')} />
          )}
        </div>
      )}
    </Modal>
  );
}
