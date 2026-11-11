/**
 * AdminCbaRatesPage — the org-wide default depot / market rates for the CBA
 * (CBA_MODULE_PLAN.md P8, D4). One global row: `code fallback ▸ this ▸
 * per-scenario override`. A blank field inherits the code fallback.
 * super-admin only.
 */
import React, { useEffect, useState } from 'react';
import { InputNumber, Button, Spin, Alert, Typography, Space, message } from 'antd';
import { useT } from '../i18n/hooks';
import { cbaRateApi } from '../services/api';

const { Title, Text } = Typography;

const KEYS = [
  'timber_sal',
  'timber_mixed',
  'timber_softwood',
  'fuelwood',
  'poles',
  'carbon',
  'grass',
  'bedding',
] as const;

const AdminCbaRatesPage: React.FC = () => {
  const t = useT();
  const [defaults, setDefaults] = useState<Record<string, number>>({});
  const [rates, setRates] = useState<Record<string, number | null>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      const r = await cbaRateApi.get();
      setDefaults(r.defaults);
      setRates({ ...r.rates });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await cbaRateApi.put(rates);
      setRates({ ...r.rates });
      message.success(t('common.saveSuccess'));
    } catch {
      message.error(t('common.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          message={t('cba.rates.loadFailed')}
          action={
            <Button size="small" onClick={load}>
              {t('common.retry')}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ padding: 24, maxWidth: 560 }}>
      <Title level={4}>{t('cba.rates.adminTitle')}</Title>
      <Text type="secondary">{t('cba.rates.adminHint')}</Text>

      <Space direction="vertical" size={10} style={{ width: '100%', marginTop: 16 }}>
        {KEYS.map((k) => (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 240, fontSize: 13 }}>{t(`cba.rates.${k}`)}</span>
            <InputNumber
              min={0}
              step={100}
              addonBefore="₹"
              placeholder={`${t('cba.rates.default')}: ${defaults[k] ?? '—'}`}
              value={rates[k] ?? undefined}
              onChange={(v) =>
                setRates((r) => {
                  const next = { ...r };
                  if (v == null) delete next[k];
                  else next[k] = Number(v);
                  return next;
                })
              }
              style={{ width: 200 }}
            />
          </div>
        ))}
      </Space>

      <Button type="primary" style={{ marginTop: 16 }} loading={saving} onClick={save}>
        {t('common.save')}
      </Button>
    </div>
  );
};

export default AdminCbaRatesPage;
