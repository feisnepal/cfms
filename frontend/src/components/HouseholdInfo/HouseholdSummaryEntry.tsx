/**
 * Household SUMMARY entry -- for a forest that has totals but no household-wise records.
 *
 * Owner decisions (2026-10-05): no tole level; household-wise data (upload or manual) replaces the summary;
 * the yearly demands are auto-calculated from the entered population and livestock, with the same formulas the
 * household form uses (shown live from the server, so the two can never drift). The demands can still be typed.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, AutoComplete, Button, Card, Checkbox, Form, InputNumber, Radio, Space, message } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import * as api from '../../services/api';
import { useT } from '../../i18n/hooks';

interface Props {
  calculationId: string;
  /** Called after a save or delete so the parent re-reads the forest's household state. */
  onChanged: () => void;
}

const PROSPERITY_LEVELS = ['सम्पन्न', 'मध्यम', 'विपन्न', 'अति विपन्न'];
const CASTE_GROUPS = ['दलित', 'जनजाती', 'सीमान्तकृत', 'अति सीमान्तकृत', 'लोपोन्मुख र सीमान्तकृत', 'अन्य'];

interface CasteRow { name: string; count: number | null }

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const sumCounts = (values: Array<number | null>): number => values.reduce((s: number, n) => s + num(n), 0);

const HouseholdSummaryEntry: React.FC<Props> = ({ calculationId, onChanged }) => {
  const t = useT();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [hasSaved, setHasSaved] = useState(false);
  const [auto, setAuto] = useState(true);
  const [demands, setDemands] = useState<Record<string, number> | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [casteRows, setCasteRows] = useState<CasteRow[]>([]);
  const [prosperity, setProsperity] = useState<Record<string, number | null>>({});
  const previewSeq = useRef(0);

  // Existing summary -> form
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const saved = await api.userGroupApi.getHouseholdSummaryEntry(calculationId);
        if (cancelled || !saved) return;
        form.setFieldsValue(saved);
        setAuto(saved.demands_auto_calculated);
        setCasteRows(Object.entries(saved.caste_distribution || {}).map(([name, count]) => ({ name, count: count as number })));
        setProsperity(saved.prosperity_distribution || {});
        setHasSaved(true);
      } catch (e) {
        console.error('summary entry load failed', e);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [calculationId, form]);

  const watched = Form.useWatch([], form) as Record<string, number> | undefined;
  const households = num(watched?.total_households);

  // Live demands from the server (same formulas as the household form).
  useEffect(() => {
    if (!auto || households < 1) { setDemands(null); return; }
    const seq = ++previewSeq.current;
    const timer = setTimeout(async () => {
      try {
        const d = await api.userGroupApi.previewHouseholdSummaryDemands(calculationId, {
          total_households: households,
          male_count: num(watched?.male_count), female_count: num(watched?.female_count),
          cow_ox_count: num(watched?.cow_ox_count), buffalo_count: num(watched?.buffalo_count),
          goat_sheep_count: num(watched?.goat_sheep_count),
        });
        if (seq === previewSeq.current) setDemands(d);
      } catch (e) {
        console.error('demand preview failed', e);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [auto, households, watched?.male_count, watched?.female_count, watched?.cow_ox_count,
      watched?.buffalo_count, watched?.goat_sheep_count, calculationId]);

  const casteSum = useMemo(() => casteRows.reduce((s, r) => s + num(r.count), 0), [casteRows]);
  const prosperitySum = useMemo(() => sumCounts(Object.values(prosperity)), [prosperity]);

  const save = async () => {
    let values;
    try { values = await form.validateFields(); } catch { return; }
    const caste: Record<string, number> = {};
    casteRows.filter((r) => r.name.trim() && num(r.count) > 0).forEach((r) => { caste[r.name.trim()] = num(r.count); });
    const pros: Record<string, number> = {};
    Object.entries(prosperity).forEach(([k, v]) => { if (num(v) > 0) pros[k] = num(v); });
    setSaving(true);
    try {
      const res = await api.userGroupApi.saveHouseholdSummaryEntry(calculationId, {
        ...values, demands_auto_calculated: auto, caste_distribution: caste, prosperity_distribution: pros,
      });
      setWarnings(res.warnings || []);
      setHasSaved(true);
      message.success(t('household.summaryEntry.saved', 'Summary saved'));
      onChanged();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : t('household.summaryEntry.saveFailed', 'Could not save the summary'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api.userGroupApi.deleteHouseholdSummaryEntry(calculationId);
      form.resetFields(); setCasteRows([]); setProsperity({}); setHasSaved(false); setWarnings([]);
      onChanged();
    } catch (e) {
      console.error(e);
      message.error(t('household.msgDeleteFailed', 'Delete failed'));
    }
  };

  if (!loaded) return null;

  const demandField = (name: string, label: string, autoKey: string) =>
    auto ? (
      <Form.Item label={label}>
        <InputNumber disabled style={{ width: '100%' }} value={demands?.[autoKey]} />
      </Form.Item>
    ) : (
      <Form.Item name={name} label={label}>
        <InputNumber min={0} style={{ width: '100%' }} />
      </Form.Item>
    );

  // Switching to typed totals starts from what was being calculated, so nothing is retyped from scratch.
  const toggleAuto = (checked: boolean) => {
    if (!checked && demands) form.setFieldsValue(demands);
    setAuto(checked);
  };

  return (
    <Card>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        message={t('household.summaryEntry.title', 'Enter household totals only')}
        description={t(
          'household.summaryEntry.hint',
          'Use this when you do not have household-wise records. The plan chapters and the demand–supply balance work from these totals. Household-wise maps and tables need the household upload; uploading or entering households later replaces this summary.',
        )}
      />
      <Form form={form} layout="vertical" initialValues={{ male_count: 0, female_count: 0, forest_occupation_households: 0, other_occupation_households: 0, cow_ox_count: 0, buffalo_count: 0, goat_sheep_count: 0, land_unit: 'ropani' }}>
        <Space size="large" wrap align="start">
          <Form.Item name="total_households" label={t('household.summaryEntry.households', 'Total households (घरधुरी)')} rules={[{ required: true, type: 'number', min: 1 }]}>
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item name="male_count" label={t('household.summaryEntry.male', 'Male population (पुरुष)')}><InputNumber min={0} precision={0} /></Form.Item>
          <Form.Item name="female_count" label={t('household.summaryEntry.female', 'Female population (महिला)')}><InputNumber min={0} precision={0} /></Form.Item>
        </Space>
        <Space size="large" wrap align="start">
          <Form.Item name="forest_occupation_households" label={t('household.summaryEntry.forestOcc', 'Households in forest-based occupation')}><InputNumber min={0} precision={0} /></Form.Item>
          <Form.Item name="other_occupation_households" label={t('household.summaryEntry.otherOcc', 'Households in other occupation')}><InputNumber min={0} precision={0} /></Form.Item>
        </Space>
        <Space size="large" wrap align="start">
          <Form.Item name="cow_ox_count" label={t('household.summaryEntry.cowOx', 'Cow / ox (गाइ गोरू)')}><InputNumber min={0} precision={0} /></Form.Item>
          <Form.Item name="buffalo_count" label={t('household.summaryEntry.buffalo', 'Buffalo (भैसी राँगा)')}><InputNumber min={0} precision={0} /></Form.Item>
          <Form.Item name="goat_sheep_count" label={t('household.summaryEntry.goat', 'Goat / sheep (बाख्रा भेडा)')}><InputNumber min={0} precision={0} /></Form.Item>
        </Space>
        <Space size="large" wrap align="start">
          <Form.Item name="avg_land_area" label={t('household.summaryEntry.land', 'Average land per household')}><InputNumber min={0} /></Form.Item>
          <Form.Item name="land_unit" label={t('household.summaryEntry.landUnit', 'Unit')}>
            <Radio.Group><Radio value="ropani">ropani</Radio><Radio value="kaththa">kaththa</Radio></Radio.Group>
          </Form.Item>
        </Space>

        <Card size="small" title={t('household.summaryEntry.demands', 'Yearly forest-product demand')} style={{ margin: '8px 0 16px' }}
          extra={<Checkbox checked={auto} onChange={(e) => toggleAuto(e.target.checked)}>{t('household.summaryEntry.auto', 'Calculate automatically')}</Checkbox>}>
          <Space size="large" wrap align="start">
            {demandField('timber_demand_cft', t('household.summaryEntry.timber', 'Timber (cft)'), 'timber_demand_cft')}
            {demandField('pole_demand', t('household.summaryEntry.poles', 'Poles'), 'pole_demand')}
            {demandField('firewood_demand_bhari', t('household.summaryEntry.firewood', 'Firewood (bhari)'), 'firewood_demand_bhari')}
            {demandField('grass_demand_bhari', t('household.summaryEntry.grass', 'Grass (bhari)'), 'grass_demand_bhari')}
            {demandField('bedding_demand_bhari', t('household.summaryEntry.bedding', 'Bedding (bhari)'), 'bedding_demand_bhari')}
          </Space>
        </Card>

        <Space size="large" wrap align="start" style={{ width: '100%' }}>
          <Card size="small" title={t('household.summaryEntry.caste', 'Households by caste group')} style={{ minWidth: 340 }}
            extra={<span style={{ color: casteSum === households || casteSum === 0 ? '#52c41a' : '#fa8c16' }}>{casteSum} / {households}</span>}>
            {casteRows.map((r, i) => (
              <Space key={i} style={{ display: 'flex', marginBottom: 6 }}>
                <AutoComplete style={{ width: 190 }} value={r.name} options={CASTE_GROUPS.map((value) => ({ value }))}
                  onChange={(name) => setCasteRows(casteRows.map((x, j) => (j === i ? { ...x, name } : x)))} />
                <InputNumber min={0} precision={0} value={r.count} onChange={(count) => setCasteRows(casteRows.map((x, j) => (j === i ? { ...x, count } : x)))} />
                <Button icon={<DeleteOutlined />} onClick={() => setCasteRows(casteRows.filter((_, j) => j !== i))} />
              </Space>
            ))}
            <Button icon={<PlusOutlined />} onClick={() => setCasteRows([...casteRows, { name: '', count: null }])}>
              {t('household.summaryEntry.addRow', 'Add group')}
            </Button>
          </Card>
          <Card size="small" title={t('household.summaryEntry.prosperity', 'Households by prosperity level')} style={{ minWidth: 300 }}
            extra={<span style={{ color: prosperitySum === households || prosperitySum === 0 ? '#52c41a' : '#fa8c16' }}>{prosperitySum} / {households}</span>}>
            {PROSPERITY_LEVELS.map((level) => (
              <div key={level} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, gap: 12 }}>
                <span>{level}</span>
                <InputNumber min={0} precision={0} value={prosperity[level] ?? null} onChange={(v) => setProsperity({ ...prosperity, [level]: v })} />
              </div>
            ))}
          </Card>
        </Space>
      </Form>

      {warnings.length > 0 && (
        <Alert type="warning" showIcon style={{ marginTop: 16 }}
          message={t('household.summaryEntry.warnTitle', 'Saved, but please check')}
          description={warnings.map((w) => t(`household.summaryEntry.warn.${w}`, w)).join(' · ')} />
      )}

      <Space style={{ marginTop: 16 }}>
        <Button type="primary" loading={saving} onClick={save}>{t('household.summaryEntry.save', 'Save summary')}</Button>
        {hasSaved && <Button danger onClick={remove}>{t('household.summaryEntry.remove', 'Remove summary')}</Button>}
      </Space>
    </Card>
  );
};

export default HouseholdSummaryEntry;
