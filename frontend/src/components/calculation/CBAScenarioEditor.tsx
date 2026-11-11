/**
 * CBAScenarioEditor — the parameter surface for one CBA scenario
 * (CBA_MODULE_PLAN.md P5). This is the "change the parameters before using the
 * OP variable" page: discount rate, horizon, IRR start year, and the
 * **Default Rates** panel (depot / market prices). Save persists; Compute runs
 * NPV / IRR / B-C / discounted payback and shows the result.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Input, InputNumber, Slider, Button, Space, Collapse, Tooltip, message } from 'antd';
import { CalculatorOutlined, SaveOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { cbaApi, type CbaScenario } from '../../services/api';

interface Props {
  calculationId: string;
  scenario: CbaScenario;
  /** re-fetch the scenario detail + the list after Save / Compute */
  onChanged: () => void;
}

const RATE_KEYS = [
  'timber_sal',
  'timber_mixed',
  'timber_softwood',
  'fuelwood',
  'poles',
  'carbon',
  'grass',
  'bedding',
] as const;

interface FormState {
  name: string;
  description: string;
  discount_rate: number;
  time_horizon_years: number;
  irr_start_year: number;
  rates: Record<string, number>;
}

const seed = (s: CbaScenario): FormState => ({
  name: s.name,
  description: s.description ?? '',
  discount_rate: Number(s.discount_rate),
  time_horizon_years: s.time_horizon_years,
  irr_start_year: s.irr_start_year,
  rates: { ...(s.default_rates ?? {}) },
});

const money = (v: string | null): string =>
  v == null ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

const Metric: React.FC<{ label: string; value: string; tip?: string }> = ({
  label,
  value,
  tip,
}) => (
  <span style={{ display: 'inline-block' }}>
    <Tooltip title={tip}>
      <div style={{ fontSize: 12, color: '#888', cursor: tip ? 'help' : undefined }}>
        {label}
      </div>
    </Tooltip>
    <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
  </span>
);

export const CBAScenarioEditor: React.FC<Props> = ({ calculationId, scenario, onChanged }) => {
  const t = useT();
  const [form, setForm] = useState<FormState>(() => seed(scenario));
  const [saving, setSaving] = useState(false);
  const [computing, setComputing] = useState(false);

  useEffect(() => {
    setForm(seed(scenario));
  }, [scenario]);

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(seed(scenario)),
    [form, scenario],
  );

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));
  const setRate = (k: string, v: number | null) =>
    setForm((f) => {
      const rates = { ...f.rates };
      if (v == null || Number.isNaN(v)) delete rates[k];
      else rates[k] = v;
      return { ...f, rates };
    });

  const save = async () => {
    setSaving(true);
    try {
      await cbaApi.updateScenario(calculationId, scenario.id, {
        name: form.name,
        description: form.description,
        discount_rate: form.discount_rate,
        time_horizon_years: form.time_horizon_years,
        irr_start_year: form.irr_start_year,
        default_rates: form.rates,
      });
      message.success(t('cba.editor.saved'));
      onChanged();
    } catch {
      message.error(t('common.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const compute = async () => {
    setComputing(true);
    try {
      await cbaApi.compute(scenario.id);
      message.success(t('cba.editor.computed'));
      onChanged();
    } catch {
      message.error(t('cba.editor.computeFailed'));
    } finally {
      setComputing(false);
    }
  };

  const r = scenario.result;
  const irrPct = r?.irr == null ? null : Number(r.irr) * 100;
  const npvNum = r?.npv == null ? null : Number(r.npv);

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('cba.editor.heading')}</h4>

      <Space direction="vertical" size={10} style={{ width: '100%', maxWidth: 640 }}>
        <label>
          <div style={{ fontSize: 12, color: '#666' }}>{t('cba.editor.name')}</div>
          <Input value={form.name} onChange={(e) => set('name', e.target.value)} />
        </label>
        <label>
          <div style={{ fontSize: 12, color: '#666' }}>{t('cba.editor.description')}</div>
          <Input.TextArea
            rows={2}
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </label>

        <div>
          <div style={{ fontSize: 12, color: '#666' }}>{t('cba.editor.discountRate')}</div>
          <Space style={{ width: '100%' }}>
            <Slider
              min={1}
              max={25}
              step={0.5}
              style={{ flex: 1, minWidth: 220 }}
              value={form.discount_rate}
              onChange={(v) => set('discount_rate', v as number)}
            />
            <InputNumber
              min={0}
              max={100}
              step={0.5}
              addonAfter="%"
              value={form.discount_rate}
              onChange={(v) => set('discount_rate', Number(v ?? 0))}
            />
          </Space>
        </div>

        <Space size={16} wrap>
          <label>
            <div style={{ fontSize: 12, color: '#666' }}>{t('cba.editor.horizon')}</div>
            <InputNumber
              min={1}
              max={50}
              value={form.time_horizon_years}
              onChange={(v) => set('time_horizon_years', Number(v ?? 10))}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, color: '#666' }}>{t('cba.editor.irrStartYear')}</div>
            <InputNumber
              min={1}
              max={form.time_horizon_years}
              value={form.irr_start_year}
              onChange={(v) => set('irr_start_year', Number(v ?? 1))}
            />
          </label>
          <label>
            <div style={{ fontSize: 12, color: '#666' }}>{t('cba.editor.currency')}</div>
            <Input value={scenario.currency} disabled style={{ width: 80 }} />
          </label>
        </Space>

        <Collapse
          size="small"
          items={[
            {
              key: 'rates',
              label: t('cba.rates.heading'),
              children: (
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  <div style={{ fontSize: 12, color: '#888' }}>{t('cba.rates.hint')}</div>
                  {RATE_KEYS.map((k) => (
                    <div
                      key={k}
                      style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                    >
                      <span style={{ width: 200, fontSize: 13 }}>
                        {t(`cba.rates.${k}`)}
                      </span>
                      <InputNumber
                        min={0}
                        step={100}
                        addonBefore="₹"
                        placeholder={t('cba.rates.default')}
                        value={form.rates[k] ?? undefined}
                        onChange={(v) => setRate(k, v as number | null)}
                      />
                    </div>
                  ))}
                </Space>
              ),
            },
          ]}
        />

        <Space>
          <Button
            icon={<SaveOutlined />}
            loading={saving}
            disabled={!dirty}
            onClick={save}
          >
            {t('common.save')}
          </Button>
          <Button
            type="primary"
            icon={<CalculatorOutlined />}
            loading={computing}
            onClick={compute}
          >
            {t('cba.editor.compute')}
          </Button>
        </Space>
      </Space>

      {r && (
        <div
          style={{
            marginTop: 14,
            padding: 14,
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            background: '#fafafa',
            maxWidth: 640,
          }}
        >
          <Space size={28} wrap>
            <Metric label={t('cba.metric.npv')} value={money(r.npv)} tip={t('cba.tip.npv')} />
            <Metric
              label={t('cba.metric.irr')}
              value={irrPct == null ? t('common.notAvailable') : `${irrPct.toFixed(1)}%`}
              tip={irrPct == null ? t('cba.editor.irrUndefined') : t('cba.tip.irr')}
            />
            <Metric
              label={t('cba.metric.bcRatio')}
              value={
                r.benefit_cost_ratio == null
                  ? t('common.notAvailable')
                  : Number(r.benefit_cost_ratio).toFixed(2)
              }
              tip={t('cba.tip.bcRatio')}
            />
            <Metric
              label={t('cba.metric.payback')}
              value={
                r.payback_period_years == null
                  ? '—'
                  : Number(r.payback_period_years).toFixed(1)
              }
              tip={t('cba.tip.payback')}
            />
          </Space>
          {npvNum != null && (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              {npvNum > 0 ? t('cba.editor.verdictViable') : t('cba.editor.verdictReview')}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default CBAScenarioEditor;
