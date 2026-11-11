/**
 *  MapVariablesPage — the map-variable reference (THEMATIC_MAP_VARIABLES_PLAN §3.9 / P4).
 *
 *  Every `thememap:` / `opsmap:` / legacy `map:` variable, grouped by family →
 *  section, each card carrying a copyable token, a bilingual description, a
 *  lazy fixture thumbnail, the technique + palette, and the §3.9.1 `Copyable?`
 *  status pill. Gated to TEMPLATE_DESIGNER + SUPER_ADMIN in App.tsx.
 *
 *  `?calc_id=<uuid>` in the URL evaluates the pill against that real forest;
 *  otherwise the pill is the generic requirement.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Input, Tag, Spin, Empty, Tooltip, Segmented, Switch, Space, Typography, message, Button, Select,
} from 'antd';
import { SearchOutlined, CopyOutlined } from '@ant-design/icons';
import { operationalPlanApi } from '../services/api';
import { useT } from '../i18n/hooks';

const { Text, Paragraph } = Typography;

interface Availability {
  status: 'available' | 'partial' | 'unavailable';
  copyable: boolean;
  requires: string[];
  reason_ne: string; reason_en: string;
  hint_ne: string; hint_en: string;
}
interface MapVar {
  key: string;
  family: 'thememap' | 'opsmap' | 'legacy';
  section: string;
  section_ne: string; section_en: string;
  label_ne: string; label_en: string;
  description_ne: string; description_en: string;
  viz: string;
  palette: string;
  palette_swatch: string[];
  basemap: string;
  preview_url: string;
  availability: Availability;
}

const STATUS_META: Record<Availability['status'], { color: string; dot: string }> = {
  available:   { color: 'success', dot: '🟢' },
  partial:     { color: 'warning', dot: '🟡' },
  unavailable: { color: 'error',   dot: '🔴' },
};

const FAMILY_ORDER: MapVar['family'][] = ['thememap', 'opsmap', 'legacy'];

// One lazily-loaded thumbnail (auth-gated endpoint → blob object URL).
const Thumb: React.FC<{ mvKey: string; calcId?: string; alt: string }> = ({ mvKey, calcId, alt }) => {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    let objUrl: string | null = null;
    operationalPlanApi
      .mapVariablePreviewObjectUrl(mvKey, calcId)
      .then((u) => { if (live) { objUrl = u; setUrl(u); } else { URL.revokeObjectURL(u); } })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (objUrl) URL.revokeObjectURL(objUrl); };
  }, [mvKey, calcId]);

  if (failed) return <div style={thumbBox}><Text type="secondary" style={{ fontSize: 11 }}>{t('mapVars.previewFailed')}</Text></div>;
  if (!url) return <div style={thumbBox}><Spin size="small" /></div>;
  return <img src={url} alt={alt} style={{ width: '100%', borderRadius: 4, display: 'block', background: '#fafafa' }} loading="lazy" />;
};

const thumbBox: React.CSSProperties = {
  height: 140, display: 'flex', alignItems: 'center', justifyContent: 'center',
  border: '1px solid #f0f0f0', borderRadius: 4, background: '#fafafa',
};

interface ForestOpt {
  calc_id: string;
  forest_name: string;
  status: string;
  has_field_inventory: boolean;
  created_at: string | null;
}

const MapVariablesPage: React.FC = () => {
  const t = useT();
  const [params, setSearchParams] = useSearchParams();
  const calcId = params.get('calc_id') || undefined;

  const [rows, setRows] = useState<MapVar[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState(params.get('q') ?? ''); // ?q=<token>: the placeholder icon opens the page on its card
  const [family, setFamily] = useState<'all' | MapVar['family']>('all');
  const [hideUnavailable, setHideUnavailable] = useState(false);
  const [onlyReady, setOnlyReady] = useState(false);
  const [forests, setForests] = useState<ForestOpt[]>([]);
  const autoPicked = React.useRef(false);

  useEffect(() => {
    operationalPlanApi
      .listMapVariableForests()
      .then((d) => {
        const list = d.forests || [];
        setForests(list);
        // First load with no forest in the URL: evaluate against a real forest
        // straight away — the generic (no-calc) view marks every data-backed
        // map "🟡 Needs data", which reads as broken. Prefer the newest forest
        // that has a processed field inventory. The user can still clear it.
        if (!autoPicked.current && !calcId && list.length) {
          autoPicked.current = true;
          const best = list.find((f) => f.has_field_inventory) || list[0];
          if (best) pickForest(best.calc_id);
        }
      })
      .catch(() => setForests([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickForest = useCallback((next?: string) => {
    setSearchParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next) p.set('calc_id', next);
      else p.delete('calc_id');
      return p;
    });
    setOnlyReady(false);
  }, [setSearchParams]);

  useEffect(() => {
    setLoading(true);
    operationalPlanApi
      .listMapVariables(calcId ? { calc_id: calcId } : undefined)
      .then((d) => setRows(d.variables || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [calcId]);

  const copy = useCallback((key: string) => {
    navigator.clipboard.writeText(`{{${key}}}`).then(
      () => message.success(t('mapVars.copied', { key })),
      () => message.error(t('mapVars.copyFailed')),
    );
  }, [t]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((v) => {
      if (family !== 'all' && v.family !== family) return false;
      if (hideUnavailable && v.availability.status === 'unavailable') return false;
      if (onlyReady && v.availability.status !== 'available') return false;
      if (!q) return true;
      return (
        v.key.toLowerCase().includes(q) ||
        v.label_ne.toLowerCase().includes(q) ||
        v.label_en.toLowerCase().includes(q) ||
        v.section_en.toLowerCase().includes(q)
      );
    });
  }, [rows, search, family, hideUnavailable, onlyReady]);

  // family → section → [vars]
  const grouped = useMemo(() => {
    const out: Record<string, Record<string, MapVar[]>> = {};
    for (const v of filtered) {
      (out[v.family] ??= {});
      (out[v.family][`${v.section}|${v.section_en}`] ??= []).push(v);
    }
    return out;
  }, [filtered]);

  const familyLabel: Record<string, string> = {
    thememap: t('mapVars.familyAnalysis'),
    opsmap: t('mapVars.familyPlan'),
    legacy: t('mapVars.familyLegacy'),
  };

  return (
    <div style={{ padding: 20, maxWidth: 1200, margin: '0 auto' }}>
      <Typography.Title level={3} style={{ marginBottom: 2 }}>{t('mapVars.title')}</Typography.Title>
      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        {t('mapVars.subtitle')}
        {calcId
          ? <> · <Text type="warning">{t('mapVars.forestContext')}</Text></>
          : <> · <Text type="secondary">{t('mapVars.genericHint')}</Text></>}
        {' · '}
        <a href={calcId ? `/templates/hazard-variables?calc_id=${calcId}` : '/templates/hazard-variables'}>
          {t('hazardVars.title')} →
        </a>
        {' · '}
        <a href={calcId ? `/templates/sfm-variables?calc_id=${calcId}` : '/templates/sfm-variables'}>
          {t('sfm.vars.title')} →
        </a>
      </Paragraph>

      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          showSearch
          allowClear
          style={{ width: 300 }}
          placeholder={t('mapVars.pickForest')}
          value={calcId}
          onChange={(v) => pickForest(v)}
          onClear={() => pickForest(undefined)}
          optionFilterProp="label"
          options={forests.map((f) => ({
            value: f.calc_id,
            label: f.forest_name,
          }))}
          optionRender={(opt) => {
            const f = forests.find((x) => x.calc_id === opt.value);
            return (
              <Space size={6}>
                <span>{f?.forest_name}</span>
                {f?.has_field_inventory && (
                  <Tag color="green" style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>
                    {t('mapVars.hasInventory')}
                  </Tag>
                )}
              </Space>
            );
          }}
        />
        <Input
          prefix={<SearchOutlined />} allowClear placeholder={t('mapVars.search')}
          value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 240 }}
        />
        <Segmented
          value={family}
          onChange={(v) => setFamily(v as 'all' | MapVar['family'])}
          options={[
            { label: t('mapVars.all'), value: 'all' },
            { label: familyLabel.thememap, value: 'thememap' },
            { label: familyLabel.opsmap, value: 'opsmap' },
            { label: familyLabel.legacy, value: 'legacy' },
          ]}
        />
        <Space size={4}><Switch size="small" checked={hideUnavailable} onChange={setHideUnavailable} />{t('mapVars.hideUnavailable')}</Space>
        {calcId && <Space size={4}><Switch size="small" checked={onlyReady} onChange={setOnlyReady} />{t('mapVars.onlyReady')}</Space>}
      </Space>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
      ) : filtered.length === 0 ? (
        <Empty description={t('mapVars.empty')} />
      ) : (
        FAMILY_ORDER.filter((f) => grouped[f]).map((fam) => (
          <section key={fam} style={{ marginBottom: 32 }}>
            <Typography.Title level={4} style={{ borderBottom: '2px solid #f0f0f0', paddingBottom: 6 }}>
              {familyLabel[fam]}
            </Typography.Title>
            {Object.entries(grouped[fam]).map(([sk, vars]) => {
              const secEn = sk.split('|')[1];
              const secNe = vars[0]?.section_ne;
              return (
                <div key={sk} style={{ marginBottom: 20 }}>
                  <Text strong style={{ fontSize: 13 }}>{secNe} <Text type="secondary">/ {secEn}</Text></Text>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 14, marginTop: 8 }}>
                    {vars.map((v) => <Card key={v.key} v={v} calcId={calcId} onCopy={copy} />)}
                  </div>
                </div>
              );
            })}
          </section>
        ))
      )}
    </div>
  );
};

const Card: React.FC<{ v: MapVar; calcId?: string; onCopy: (k: string) => void }> = ({ v, calcId, onCopy }) => {
  const t = useT();
  const sm = STATUS_META[v.availability.status];
  const disabled = !v.availability.copyable;
  const reason = v.availability.reason_en;
  const hint = v.availability.hint_en;

  return (
    <div style={{ border: '1px solid #eee', borderRadius: 8, padding: 12, background: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
        <code style={{ fontSize: 12, fontWeight: 600, wordBreak: 'break-all' }}>{`{{${v.key}}}`}</code>
        <Tooltip title={disabled ? reason : undefined}>
          <Button
            size="small" type="text" icon={<CopyOutlined />} disabled={disabled}
            onClick={() => onCopy(v.key)} title={t('mapVars.copy')}
          />
        </Tooltip>
      </div>

      <div style={{ margin: '4px 0 8px' }}>
        <Tooltip title={`${reason}${hint ? ` — ${hint}` : ''}`}>
          <Tag color={sm.color} style={{ marginRight: 4 }}>{sm.dot} {t(`mapVars.status.${v.availability.status}`)}</Tag>
        </Tooltip>
        <Tag>{v.viz}</Tag>
        {v.palette_swatch.length > 0 && (
          <span style={{ display: 'inline-flex', verticalAlign: 'middle', marginLeft: 4, borderRadius: 3, overflow: 'hidden', border: '1px solid #ddd' }}>
            {v.palette_swatch.map((c, i) => <span key={i} style={{ width: 12, height: 12, background: c }} />)}
          </span>
        )}
      </div>

      <Thumb mvKey={v.key} calcId={calcId} alt={v.label_en} />

      <div style={{ marginTop: 8, fontSize: 12 }}>
        <div><Text strong>{v.label_ne}</Text> <Text type="secondary">/ {v.label_en}</Text></div>
        {v.description_en && <div style={{ color: '#666', marginTop: 2 }}>{v.description_ne || v.description_en}</div>}
        {v.availability.requires.length > 0 && (
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>{t('mapVars.requires')}: </Text>
            {v.availability.requires.map((r) => <Tag key={r} style={{ fontSize: 10 }}>{r.replace(/_/g, ' ')}</Tag>)}
          </div>
        )}
        {v.availability.status !== 'available' && hint && (
          <div style={{ marginTop: 4, color: '#999', fontSize: 11 }}>{t('mapVars.howToEnable')}: {hint}</div>
        )}
      </div>
    </div>
  );
};

export default MapVariablesPage;
