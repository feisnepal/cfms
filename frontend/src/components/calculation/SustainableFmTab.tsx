/**
 * SustainableFmTab — the "Sustainable Forest Management" (दिगो वन व्यवस्थापन)
 * context in the calc shell (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4).
 *
 * Table view, no maps (those mount in P5). Fetches the three read endpoints
 * (summary / blocks / narration — each builds result_data['sfm'] on first
 * access), then renders the summary bar, the felling-series strip, the block
 * table (with per-block type / crown overrides), a prescription card for the
 * selected block, and the adaptive NE/EN narration.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Spin, Alert, Button, Result, Segmented, Space } from 'antd';
import { useTranslation } from 'react-i18next';
import { useT } from '../../i18n/hooks';
import {
  sfmApi,
  type SfmSummaryResponse,
  type SfmBlocksResponse,
  type SfmNarrationBlock,
  type SfmBlockPatch,
  type SfmVariant,
  type SfmCompareResponse,
} from '../../services/api';
import SfmSummaryBar from './SfmSummaryBar';
import SfmFellingSeriesStrip from './SfmFellingSeriesStrip';
import StemMappingSuggestion from '../StemMappingSuggestion';
import SfmMapPanel from './SfmMapPanel';
import SfmSlopeHelperPanel from './SfmSlopeHelperPanel';
import SfmParamsPanel from './SfmParamsPanel';
import SfmBlockTable from './SfmBlockTable';
import { SfmTypeReferenceProvider, SfmTypeReferenceButton } from './SfmTypeReference';
import SfmPrescriptionCard from './SfmPrescriptionCard';
import SfmNarration from './SfmNarration';
import BackToMapLink from './BackToMapLink';
import OpenDecisionsNotice from './OpenDecisionsNotice';
import SfmComparePanel from './SfmComparePanel';
import { SfmVarCopyMenu } from './SfmVarChip';

// P8 — the ordered token block the "Copy variables ▾" menu emits, mirroring
// the tab layout (also what the seed ३.१० subsection lays out).
const VAR_MENU_GROUPS = [
  {
    labelKey: 'sfm.varChip.grpNumbers',
    keys: [
      'sfm_dominant_type_ne', 'sfm_total_annual_harvest_m3',
      'sfm_production_area_ha', 'sfm_protection_area_ha',
      'sfm_plan_regime_note', 'sfm_sampling_intensity_note', 'sfm_felling_series_note',
    ],
  },
  {
    labelKey: 'sfm.varChip.grpMaps',
    keys: [
      'thememap:sfm__forest_type', 'thememap:sfm__orientation',
      'thememap:sfm__gs_vs_threshold',
    ],
  },
  {
    labelKey: 'sfm.varChip.grpTables',
    keys: [
      'sfm_block_prescription_table', 'sfm_type_area_table', 'sfm_yield_table',
      'sfm_working_circle_table', 'sfm_sampling_plan_table',
    ],
  },
  {
    labelKey: 'sfm.varChip.grpNarrative',
    keys: ['sfm_methodology', 'sfm_findings', 'sfm_prescription'],
  },
];

interface Props {
  calculationId: string;
}

export const SustainableFmTab: React.FC<Props> = ({ calculationId }) => {
  const t = useT();
  const { i18n } = useTranslation();
  const [summary, setSummary] = useState<SfmSummaryResponse | null>(null);
  const [blocks, setBlocks] = useState<SfmBlocksResponse | null>(null);
  const [narration, setNarration] = useState<SfmNarrationBlock | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedBlock, setSelectedBlock] = useState<string | null>(null);
  const [patching, setPatching] = useState<string | null>(null);
  const [mapNonce, setMapNonce] = useState(0);
  // SV-1.8 — which SFM result drives this tab: the immutable raster baseline
  // (Guideline) or the workspace-adjusted user variant (My adjustments).
  const [variant, setVariant] = useState<SfmVariant>('baseline');
  // SV-1.9 — compare panel (baseline vs user) toggle + fetch-on-open.
  const [compareOpen, setCompareOpen] = useState(false);
  const [compare, setCompare] = useState<SfmCompareResponse | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [s, b, n] = await Promise.all([
        sfmApi.getSummary(calculationId, variant),
        sfmApi.getBlocks(calculationId, variant),
        sfmApi.getNarration(calculationId, variant),
      ]);
      setSummary(s);
      setBlocks(b);
      setNarration(n);
      setSelectedBlock((prev) => {
        if (prev && b.blocks.some((x) => x.block_name === prev)) return prev;
        return b.blocks[0]?.block_name ?? null;
      });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [calculationId, variant]);

  useEffect(() => {
    load();
  }, [load]);

  // SV-1.9 — compare is baseline-vs-user and independent of which variant is
  // being displayed, so it only depends on the open flag + calculation.
  useEffect(() => {
    if (!compareOpen) return;
    let live = true;
    setCompareLoading(true);
    sfmApi
      .compareSfm(calculationId)
      .then((c) => {
        if (live) setCompare(c);
      })
      .catch(() => {
        if (live) setCompare(null);
      })
      .finally(() => {
        if (live) setCompareLoading(false);
      });
    return () => {
      live = false;
    };
  }, [compareOpen, calculationId]);

  // A variant switch must make the thematic PNGs re-fetch too (SV-1.8; the
  // variant-aware URL itself lands in SV-1.10 via SfmMapPanel's variant prop).
  useEffect(() => {
    setMapNonce((n) => n + 1);
  }, [variant]);

  const patchBlock = useCallback(
    async (blockName: string, patch: SfmBlockPatch) => {
      setPatching(blockName);
      try {
        await sfmApi.patchBlock(calculationId, blockName, patch);
        await load();
        setMapNonce((n) => n + 1);
      } finally {
        setPatching(null);
      }
    },
    [calculationId, load],
  );

  const selected = useMemo(
    () => blocks?.blocks.find((b) => b.block_name === selectedBlock) ?? null,
    [blocks, selectedBlock],
  );
  const selectedSeries = useMemo(() => {
    if (!selected || !summary) return null;
    return (
      summary.felling_series.find((s) => s.type_no === selected.effective_type_no) ??
      null
    );
  }, [selected, summary]);

  if (loading) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin tip={t('sfm.loading')} />
      </div>
    );
  }

  if (error || !summary || !blocks) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          message={t('sfm.loadFailed')}
          action={
            <Button size="small" onClick={load}>
              {t('sfm.retry')}
            </Button>
          }
        />
      </div>
    );
  }

  if (blocks.blocks.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Result
          status="info"
          title={t('sfm.empty.title')}
          subTitle={t('sfm.empty.body')}
        />
      </div>
    );
  }

  return (
    <SfmTypeReferenceProvider>
    <div style={{ padding: 20, maxWidth: 1180 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 12,
          flexWrap: 'wrap',
          marginBottom: 12,
        }}
      >
        <div>
          <h3 style={{ margin: 0 }}>{t('sfm.title')}</h3>
          <span style={{ fontSize: 12, color: '#888' }}>{t('sfm.subtitle')}</span>
        </div>
        <Space wrap style={{ alignItems: 'center' }}>
          <Segmented<SfmVariant>
            size="small"
            value={variant}
            onChange={(v) => setVariant(v)}
            options={[
              { value: 'baseline', label: t('sfm.variantBaseline') },
              { value: 'user', label: t('sfm.variantUser') },
            ]}
          />
          <span style={{ fontSize: 12, color: '#888' }}>{t('sfm.variantHint')}</span>
          <Button size="small" onClick={() => setCompareOpen((o) => !o)}>
            {t('sfm.compare')}
          </Button>
          <BackToMapLink calculationId={calculationId} />
          <SfmTypeReferenceButton />
          <SfmVarCopyMenu groups={VAR_MENU_GROUPS} />
        </Space>
      </div>

      <SfmSummaryBar summary={summary} />

      <OpenDecisionsNotice calculationId={calculationId} />

      {(summary.forest_summary.inventory_gaps ?? []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 12 }}
          data-testid="sfm-inventory-gaps"
          message={t('sfm.gaps.title')}
          description={(summary.forest_summary.inventory_gaps ?? [])
            .map((g) =>
              `${g.block_name}: ${g.state === 'inventory_missing' ? t('sfm.gaps.none') : t('sfm.gaps.few', { n: g.plot_count })}`,
            )
            .join(' · ')}
        />
      )}

      {compareOpen && (
        <div style={{ marginTop: 16 }}>
          {compareLoading ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Spin />
            </div>
          ) : compare ? (
            <SfmComparePanel compare={compare} />
          ) : (
            <Alert type="error" message={t('sfm.loadFailed')} />
          )}
        </div>
      )}

      <div style={{ marginTop: 16 }}>
        <SfmParamsPanel
          calculationId={calculationId}
          onSaved={() => {
            load();
            setMapNonce((n) => n + 1);
          }}
        />
      </div>

      <div style={{ marginTop: 16 }}>
        <SfmFellingSeriesStrip series={summary.felling_series} lang={i18n.language} />
      </div>

      <div style={{ marginTop: 16 }}>
        <StemMappingSuggestion calculationId={calculationId} />
      </div>

      <div style={{ marginTop: 16 }}>
        <SfmMapPanel calculationId={calculationId} refreshKey={mapNonce} variant={variant} />
      </div>

      <div style={{ marginTop: 16 }}>
        <SfmSlopeHelperPanel calculationId={calculationId} />
      </div>

      <div
        style={{
          display: 'flex',
          gap: 16,
          marginTop: 16,
          flexWrap: 'wrap',
          alignItems: 'flex-start',
        }}
      >
        <div style={{ flex: '1 1 640px', minWidth: 0 }}>
          <SfmBlockTable
            blocks={blocks.blocks}
            zoneByBlock={blocks.zone_by_block}
            selectedBlock={selectedBlock}
            patchingBlock={patching}
            lang={i18n.language}
            onSelect={setSelectedBlock}
            onPatch={patchBlock}
          />
        </div>
        <div style={{ flex: '0 1 380px', minWidth: 280 }}>
          <SfmPrescriptionCard
            block={selected}
            series={selectedSeries}
            lang={i18n.language}
          />
        </div>
      </div>

      <div style={{ marginTop: 20 }}>
        <SfmNarration narration={narration} lang={i18n.language} />
      </div>
    </div>
    </SfmTypeReferenceProvider>
  );
};

export default SustainableFmTab;
