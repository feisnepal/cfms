/**
 * HazardVariablesPage — the in-context reference for every Hazard & Erosion OP
 * variable (HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P3).
 *
 * Pick a forest; each variable is shown next to a *real* preview of what it
 * renders — the resolved number / string, the actual table rows, the actual
 * chart, a clamped narration block, or the map thumbnail — with a one-click
 * copy of its `{{token}}`. Ordered to mirror the Hazard & Erosion analysis
 * page: numbers ▸ maps ▸ tables ▸ charts ▸ narrative.
 *
 * Gated to TEMPLATE_DESIGNER + SUPER_ADMIN in App.tsx.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Select, Spin, Empty, Tag, Table, Typography, Space, Button, message, Alert,
} from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { Bar } from 'react-chartjs-2';
import '../utils/chartSetup';
import { useTranslation } from 'react-i18next';
import {
  hazardErosionApi, operationalPlanApi,
  type HazardVariableGroups, type HazardVariableRow,
} from '../services/api';

const { Title, Paragraph, Text } = Typography;

type Resolved = string | number | boolean | null | Record<string, unknown> | unknown[];
interface CatalogRow { key: string; var_type: string; resolved?: Resolved; data_status?: string }
interface ForestOpt { calc_id: string; forest_name: string; has_field_inventory: boolean }

const CHART_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: { y: { beginAtZero: true } },
};

const isChartDict = (v: Resolved): v is { labels: string[]; datasets: unknown[] } =>
  !!v && typeof v === 'object' && !Array.isArray(v) && 'datasets' in v;

const CopyToken: React.FC<{ tokenKey: string }> = ({ tokenKey }) => {
  const { t } = useTranslation();
  return (
    <Button
      size="small"
      type="text"
      icon={<CopyOutlined />}
      onClick={() =>
        navigator.clipboard.writeText(`{{${tokenKey}}}`).then(
          () => message.success(t('hazardVars.copied', { key: tokenKey })),
          () => message.error(t('hazardVars.copyFailed')),
        )
      }
      title={t('hazardVars.copy')}
    >
      <code style={{ fontSize: 11 }}>{`{{${tokenKey}}}`}</code>
    </Button>
  );
};

const MapThumb: React.FC<{ mvKey: string; calcId: string }> = ({ mvKey, calcId }) => {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let obj: string | null = null;
    operationalPlanApi
      .mapVariablePreviewObjectUrl(mvKey, calcId)
      .then((u) => { if (live) { obj = u; setUrl(u); } else URL.revokeObjectURL?.(u); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (obj) URL.revokeObjectURL?.(obj); };
  }, [mvKey, calcId]);
  if (failed) return <div style={thumbBox}><Text type="secondary" style={{ fontSize: 11 }}>—</Text></div>;
  if (!url) return <div style={thumbBox}><Spin size="small" /></div>;
  return <img src={url} alt={mvKey} style={{ width: '100%', borderRadius: 4, display: 'block' }} loading="lazy" />;
};

const thumbBox: React.CSSProperties = {
  height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center',
  border: '1px solid #f0f0f0', borderRadius: 4, background: '#fafafa',
};

const Preview: React.FC<{ row: HazardVariableRow; cat?: CatalogRow }> = ({ row, cat }) => {
  const { t } = useTranslation();
  const val = cat?.resolved;

  if (row.key.startsWith('thememap:')) return null; // handled by MapThumb in the card

  if (row.key.startsWith('chart:')) {
    if (isChartDict(val ?? null)) {
      return (
        <div style={{ height: 180 }}>
          <Bar data={val as never} options={CHART_OPTS as never} />
        </div>
      );
    }
    return <Text type="secondary" style={{ fontSize: 12 }}>{t('hazardVars.noData')}</Text>;
  }

  if (Array.isArray(val)) {
    if (!val.length) return <Text type="secondary" style={{ fontSize: 12 }}>{t('hazardVars.noData')}</Text>;
    const rows = (val as Record<string, unknown>[]).slice(0, 8);
    const cols = Object.keys(rows[0] ?? {}).map((k) => ({
      title: k.replace(/_/g, ' '), dataIndex: k, key: k,
      render: (c: unknown) => (c === null || c === undefined || c === '' ? '—' : String(c)),
    }));
    return (
      <Table
        size="small"
        rowKey={(_, i) => String(i)}
        columns={cols}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    );
  }

  if (typeof val === 'string' && row.key.includes('narration')) {
    return (
      <Paragraph style={{ fontSize: 12, whiteSpace: 'pre-wrap', margin: 0 }} ellipsis={{ rows: 5, expandable: true }}>
        {val}
      </Paragraph>
    );
  }

  if (val === null || val === undefined) {
    return <Text type="secondary" style={{ fontSize: 12 }}>{t('hazardVars.noData')}</Text>;
  }
  return <Text strong style={{ fontSize: 15 }}>{String(val)}</Text>;
};

const HazardVariablesPage: React.FC = () => {
  const { t, i18n } = useTranslation();
  const [params, setParams] = useSearchParams();
  const calcId = params.get('calc_id') || undefined;

  const [forests, setForests] = useState<ForestOpt[]>([]);
  const [groups, setGroups] = useState<HazardVariableGroups['groups']>([]);
  const [catalog, setCatalog] = useState<Map<string, CatalogRow>>(new Map());
  const [loading, setLoading] = useState(false);
  const picked = React.useRef(false);

  const pick = useCallback((next?: string) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next) p.set('calc_id', next); else p.delete('calc_id');
      return p;
    });
  }, [setParams]);

  useEffect(() => {
    operationalPlanApi.listMapVariableForests()
      .then((d) => {
        const list: ForestOpt[] = d.forests || [];
        setForests(list);
        if (!picked.current && !calcId && list.length) {
          picked.current = true;
          pick((list.find((f) => f.has_field_inventory) || list[0]).calc_id);
        }
      })
      .catch(() => setForests([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!calcId) { setGroups([]); return; }
    setLoading(true);
    hazardErosionApi.variables(calcId)
      .then(async (d) => {
        setGroups(d.groups);
        const keys = d.groups.flatMap((g) => g.variables.map((v) => v.key))
          .filter((k) => !k.startsWith('thememap:'));
        try {
          const cat = await operationalPlanApi.getVariableCatalog(calcId, { keys: keys.join(',') });
          const m = new Map<string, CatalogRow>();
          for (const r of (cat.variables || [])) m.set(r.key, r as CatalogRow);
          setCatalog(m);
        } catch { setCatalog(new Map()); }
      })
      .catch(() => setGroups([]))
      .finally(() => setLoading(false));
  }, [calcId]);

  const lang = i18n.language;
  const forestOpts = useMemo(
    () => forests.map((f) => ({ value: f.calc_id, label: f.forest_name })),
    [forests],
  );

  return (
    <div style={{ padding: 20, maxWidth: 1100, margin: '0 auto' }}>
      <Title level={3} style={{ marginBottom: 2 }}>{t('hazardVars.title')}</Title>
      <Paragraph type="secondary">{t('hazardVars.subtitle')}</Paragraph>

      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          showSearch allowClear style={{ width: 300 }}
          placeholder={t('hazardVars.pickForest')}
          value={calcId}
          onChange={(v) => pick(v)}
          onClear={() => pick(undefined)}
          optionFilterProp="label"
          options={forestOpts}
        />
      </Space>

      {!calcId ? (
        <Alert type="info" showIcon message={t('hazardVars.pickForestHint')} />
      ) : loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
      ) : !groups.length ? (
        <Empty description={t('hazardVars.empty')} />
      ) : (
        groups.map((g) => (
          <section key={g.id} style={{ marginBottom: 28 }}>
            <Title level={4} style={{ borderBottom: '2px solid #f0f0f0', paddingBottom: 6 }}>
              {lang === 'ne' ? g.label_ne : g.label_en}
            </Title>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
              {g.variables.map((v) => (
                <div key={v.key} style={{ border: '1px solid #eee', borderRadius: 8, padding: 12, background: '#fff' }}>
                  <div style={{ marginBottom: 6 }}>
                    <CopyToken tokenKey={v.key} />
                    {v.registered === false && <Tag color="red" style={{ marginLeft: 4, fontSize: 10 }}>unregistered</Tag>}
                  </div>
                  <div style={{ fontSize: 12, marginBottom: 8 }}>
                    <Text strong>{lang === 'ne' ? v.label_ne : v.label_en}</Text>
                    {v.sub_group && <Text type="secondary"> · {v.sub_group}</Text>}
                  </div>
                  {g.id === 'maps'
                    ? <MapThumb mvKey={v.key} calcId={calcId} />
                    : <Preview row={v} cat={catalog.get(v.key)} />}
                </div>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
};

export default HazardVariablesPage;
