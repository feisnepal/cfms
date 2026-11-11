/**
 * SfmSlopeHelperPanel — the P11 slope-class digitizing aid for `protected`
 * sub-areas (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P11, follow-on).
 *
 * Nothing here is authoritative — the user's hand-edited sub-area polygon is.
 * This panel only (1) summarises the raw 4-value slope raster inside the forest
 * by the guideline's §15.2 band (< 19° / 19–31° / 31–45° / > 45°), and (2)
 * generates a DRAFT `category='protected'` polygon from the union of the steep
 * bands that the user copies out, trims against the §23.2 felling-plot
 * exclusion checklist, and saves through the normal sub-area path (which stamps
 * `slope_profile`). It deliberately does NOT touch the workspace map / editor.
 */
import React, { useEffect, useState } from 'react';
import { Select, Button, Alert, Spin, Space, Tag, message } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useT } from '../../i18n/hooks';
import {
  sfmApi,
  type SfmSlopeClassFC,
  type SfmDraftProtectionResponse,
  type SfmSlopeProfile,
} from '../../services/api';

interface Props {
  calculationId: string;
}

/** {1: '< 19°', …} — the guideline §15.2 zonation bands. */
export const SLOPE_BAND_LABEL: Record<number, string> = {
  1: '< 19°',
  2: '19–31°',
  3: '31–45°',
  4: '> 45°',
};

/** steep = red; matches the growing-stock ramp direction. */
export const SLOPE_BAND_COLOR: Record<number, string> = {
  1: '#2b83ba',
  2: '#abdda4',
  3: '#fdae61',
  4: '#d7191c',
};

/** A compact horizontal stacked bar of the per-band area share. */
export const SlopeBandBar: React.FC<{
  pctByBand: Record<string, number>;
  width?: number;
  height?: number;
}> = ({ pctByBand, width = 90, height = 10 }) => {
  const segs = [1, 2, 3, 4]
    .map((b) => ({ b, pct: Number(pctByBand[String(b)] || 0) }))
    .filter((s) => s.pct > 0.05);
  if (segs.length === 0) return <span style={{ color: '#bbb' }}>—</span>;
  const title = segs
    .map((s) => `${SLOPE_BAND_LABEL[s.b]} ${s.pct.toFixed(0)}%`)
    .join(' · ');
  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        width,
        height,
        borderRadius: 2,
        overflow: 'hidden',
        border: '1px solid rgba(0,0,0,0.12)',
        verticalAlign: 'middle',
      }}
    >
      {segs.map((s) => (
        <span
          key={s.b}
          style={{ width: `${s.pct}%`, background: SLOPE_BAND_COLOR[s.b] }}
        />
      ))}
    </span>
  );
};

const ProfileReadout: React.FC<{ profile: SfmSlopeProfile }> = ({ profile }) => {
  const t = useT();
  return (
    <div style={{ marginTop: 8 }}>
      <Space size={8} wrap>
        <span style={{ fontSize: 12, color: '#666' }}>
          {t('sfm.slope.dominantBand')}:
        </span>
        <Tag color={profile.dominant_band ? undefined : 'default'}>
          {profile.dominant_band
            ? SLOPE_BAND_LABEL[profile.dominant_band] ?? profile.dominant_band
            : '—'}
        </Tag>
        <SlopeBandBar pctByBand={profile.area_pct_by_band} width={120} />
      </Space>
    </div>
  );
};

export const SfmSlopeHelperPanel: React.FC<Props> = ({ calculationId }) => {
  const t = useT();
  const { i18n } = useTranslation();
  const ne = i18n.language.startsWith('ne');

  const [fc, setFc] = useState<SfmSlopeClassFC | null>(null);
  const [loading, setLoading] = useState(true);
  const [minBand, setMinBand] = useState(3);
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<SfmDraftProtectionResponse | null>(null);
  const [draftMsg, setDraftMsg] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    sfmApi
      .slopeClassPolygons(calculationId)
      .then((r) => {
        if (live) setFc(r);
      })
      .catch(() => {
        if (live) setFc({ type: 'FeatureCollection', features: [] });
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [calculationId]);

  const generate = async () => {
    setDrafting(true);
    setDraft(null);
    setDraftMsg(null);
    try {
      const r = await sfmApi.draftProtectionSubarea(calculationId, minBand);
      setDraft(r);
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setDraftMsg(
        status === 404 ? t('sfm.slope.noneThatSteep') : t('sfm.slope.draftFailed'),
      );
    } finally {
      setDrafting(false);
    }
  };

  const copyGeoJson = () => {
    if (!draft) return;
    navigator.clipboard.writeText(JSON.stringify(draft.polygon)).then(
      () => message.success(t('sfm.slope.copied')),
      () => message.error(t('sfm.slope.copyFailed')),
    );
  };

  const bandRows = (fc?.features ?? [])
    .slice()
    .sort((a, b) => a.properties.band - b.properties.band);
  const hasRaster = bandRows.length > 0;

  return (
    <div
      style={{
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        padding: 14,
        background: '#fafafa',
      }}
    >
      <div style={{ marginBottom: 8 }}>
        <b>{t('sfm.slope.heading')}</b>
        <div style={{ fontSize: 12, color: '#888' }}>{t('sfm.slope.subtitle')}</div>
      </div>

      {loading ? (
        <Spin size="small" />
      ) : !hasRaster ? (
        <Alert type="info" showIcon message={t('sfm.slope.noRaster')} />
      ) : (
        <>
          <div style={{ lineHeight: 2 }}>
            {bandRows.map((f) => (
              <div key={f.properties.band} style={{ fontSize: 13 }}>
                <span
                  style={{
                    display: 'inline-block',
                    width: 12,
                    height: 12,
                    marginRight: 6,
                    verticalAlign: 'middle',
                    background: SLOPE_BAND_COLOR[f.properties.band],
                    border: '1px solid rgba(0,0,0,0.15)',
                  }}
                />
                {ne ? f.properties.label_ne : f.properties.label_en}
                <span style={{ color: '#999', marginLeft: 8 }}>
                  {f.properties.area_ha.toFixed(2)} {t('sfm.unit.ha')}
                </span>
              </div>
            ))}
          </div>

          <Space wrap style={{ marginTop: 12 }}>
            <span style={{ fontSize: 13, color: '#666' }}>
              {t('sfm.slope.fromClass')}
            </span>
            <Select<number>
              size="small"
              style={{ width: 130 }}
              value={minBand}
              onChange={setMinBand}
              options={[2, 3, 4].map((b) => ({
                value: b,
                label: `≥ ${SLOPE_BAND_LABEL[b]}`,
              }))}
            />
            <Button
              size="small"
              type="primary"
              loading={drafting}
              onClick={generate}
            >
              {t('sfm.slope.generate')}
            </Button>
          </Space>

          {draftMsg && (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 10 }}
              message={draftMsg}
            />
          )}

          {draft && (
            <div style={{ marginTop: 12 }}>
              <ProfileReadout profile={draft.slope_profile} />
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 8 }}
                message={t('sfm.slope.draftTitle')}
                description={ne ? draft.hint_ne : draft.hint_en}
              />
              <Space style={{ marginTop: 8 }}>
                <Button
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={copyGeoJson}
                >
                  {t('sfm.slope.copyGeoJson')}
                </Button>
                <span style={{ fontSize: 12, color: '#888' }}>
                  {t('sfm.slope.pasteHint')}
                </span>
              </Space>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default SfmSlopeHelperPanel;
