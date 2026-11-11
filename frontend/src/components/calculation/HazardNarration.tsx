/**
 * HazardNarration — the prose half of the Hazard & Erosion context
 * (HAZARD_EROSION_CONTEXT_PLAN.md P5).
 *
 * A three-panel accordion (methodology / findings / prescription) over the
 * adaptive NE + EN narration from the RUSLE and landslide/household collectors,
 * with a language toggle and the caveat (assumptions) list boxed at the top of
 * "findings". Below it, an idempotent **Insert into Operational Plan** button
 * that appends the seed-tree subsections ३.८ / ३.९ to this forest's OP tree and
 * offers a jump to the plan.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Collapse, Segmented, Button, Alert, Spin, Space, message } from 'antd';
import { FileAddOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { useSearchParams } from 'react-router-dom';
import { useT } from '../../i18n/hooks';
import { hazardErosionApi, type HazardErosionNarration } from '../../services/api';
import { HazardVarChip } from './HazardVarChip';

interface Props {
  calculationId: string;
  /** en | ne — initial language for the toggle */
  lang?: string;
  /** called after a successful insert so the parent can refresh */
  onInserted?: () => void;
}

type Lang = 'ne' | 'en';
type Section = 'methodology' | 'findings' | 'prescription';

const para = (text: string): React.ReactNode =>
  text ? <p style={{ whiteSpace: 'pre-wrap', margin: '0 0 8px' }}>{text}</p> : null;

export const HazardNarration: React.FC<Props> = ({ calculationId, lang = 'en', onInserted }) => {
  const t = useT();
  const [, setSearchParams] = useSearchParams();
  const [data, setData] = useState<HazardErosionNarration | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState<Lang>(lang === 'ne' ? 'ne' : 'en');
  const [inserting, setInserting] = useState(false);
  const [inserted, setInserted] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setFailed(false);
    hazardErosionApi
      .narration(calculationId)
      .then((d) => {
        if (live) setData(d);
      })
      .catch(() => {
        if (live) setFailed(true);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [calculationId]);

  const pick = (sec: Section, block: 'soil' | 'hazard'): string =>
    (data?.[block]?.[`${sec}_${view}` as keyof (typeof data)['soil']] as string) || '';

  const caveats = useMemo(() => {
    if (!data) return [];
    const k = `assumptions_${view}` as 'assumptions_ne' | 'assumptions_en';
    return Array.from(new Set([...(data.soil[k] || []), ...(data.hazard[k] || [])]));
  }, [data, view]);

  const openPlan = () =>
    setSearchParams((prev) => {
      prev.set('surface', 'data-maps/mgmtplan');
      prev.delete('context');
      prev.delete('tab');
      return prev;
    });

  const doInsert = async () => {
    setInserting(true);
    try {
      const res = await hazardErosionApi.insertOpSubsections(calculationId);
      setInserted(true);
      if (res.status === 'inserted') message.success(t('hazardErosion.narration.insertDone'));
      else message.info(t('hazardErosion.narration.insertAlready'));
      onInserted?.();
    } catch (err: unknown) {
      const code = (err as { response?: { data?: { detail?: { code?: string } } } })?.response?.data
        ?.detail?.code;
      if (code === 'NO_OP') message.warning(t('hazardErosion.narration.insertNoOp'));
      else if (code === 'PLAN_APPROVED') message.warning(t('hazardErosion.narration.insertApproved'));
      else message.error(t('hazardErosion.narration.insertFailed'));
    } finally {
      setInserting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 20, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (failed || !data) {
    return (
      <Alert
        type="error"
        showIcon
        style={{ marginTop: 16 }}
        message={t('hazardErosion.narration.loadFailed')}
      />
    );
  }

  const block = (sec: Section) => {
    const soil = pick(sec, 'soil');
    const haz = pick(sec, 'hazard');
    return (
      <>
        {sec === 'findings' && caveats.length > 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 10, fontSize: 12 }}
            message={t('hazardErosion.narration.caveatsTitle')}
            description={
              <ul style={{ margin: '4px 0 0', paddingInlineStart: 18 }}>
                {caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            }
          />
        )}
        {soil && (
          <div style={{ marginBottom: 6 }}>
            <b style={{ fontSize: 12, color: '#888' }}>{t('hazardErosion.narration.soilLabel')}</b>
            {para(soil)}
          </div>
        )}
        {haz && (
          <div>
            <b style={{ fontSize: 12, color: '#888' }}>{t('hazardErosion.narration.hazardLabel')}</b>
            {para(haz)}
          </div>
        )}
        {!soil && !haz && (
          <span style={{ color: '#999' }}>{t('hazardErosion.narration.nothing')}</span>
        )}
      </>
    );
  };

  return (
    <div style={{ marginTop: 16 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <h4 style={{ margin: 0 }}>
          {t('hazardErosion.narration.heading')}
          <HazardVarChip tokenKey="hazard_erosion_full_narration" />
        </h4>
        <Segmented
          size="small"
          value={view}
          onChange={(v) => setView(v as Lang)}
          options={[
            { label: 'नेपाली', value: 'ne' },
            { label: 'EN', value: 'en' },
          ]}
        />
      </div>

      <Collapse
        size="small"
        defaultActiveKey={['findings']}
        items={(['methodology', 'findings', 'prescription'] as Section[]).map((sec) => ({
          key: sec,
          label: (
            <span>
              {t(`hazardErosion.narration.${sec}`)}
              <HazardVarChip tokenKey={`hazard_erosion_${sec}_narration`} />
              <HazardVarChip tokenKey={`hazard_${sec}_narration`} />
            </span>
          ),
          children: block(sec),
        }))}
      />

      <Space style={{ marginTop: 12 }} wrap>
        <Button
          type="primary"
          icon={<FileAddOutlined />}
          loading={inserting}
          onClick={doInsert}
        >
          {t('hazardErosion.narration.insertBtn')}
        </Button>
        {inserted && (
          <Button icon={<ArrowRightOutlined />} onClick={openPlan}>
            {t('hazardErosion.narration.openPlan')}
          </Button>
        )}
      </Space>
    </div>
  );
};

export default HazardNarration;
