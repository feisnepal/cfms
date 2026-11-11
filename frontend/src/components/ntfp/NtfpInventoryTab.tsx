/**
 * NtfpInventoryTab — the `ntfp` context: an optional page in the rail's Advanced band (owner, 2026-10-22).
 *
 * The page walks the guideline's order: choose the species, lay the plots out, take the Excel form to the field and bring it back, read the
 * results. The same results reach the operational plan as table 39 (`{{table:ntfp_inventory}}`) and `{{section:ntfp_inventory}}`; nothing here
 * is required to finish a plan.
 */
import { useCallback, useContext, useEffect, useState } from 'react';
import { Alert, Tabs } from 'antd';
import { useT } from '../../i18n/hooks';
import type { Calculation } from '../../types';
import { ntfpApi, ntfpHarvestApi, type NtfpDesign, type NtfpHarvestPlan, type NtfpRecords, type NtfpSpecies } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { emptyPick, ntfpStages, type NtfpPick, type StageKey } from '../../lib/ntfp';
import NtfpSpeciesPanel from './NtfpSpeciesPanel';
import NtfpDesignPanel from './NtfpDesignPanel';
import NtfpCollectPanel from './NtfpCollectPanel';
import NtfpResultsPanel from './NtfpResultsPanel';
import NtfpHarvestPanel from './NtfpHarvestPanel';
import NtfpCardReview from './NtfpCardReview';
import NtfpStagesStrip from './NtfpStagesStrip';
import { AuthContext } from '../../contexts/AuthContext';

interface Props {
  calculationId: string;
  calculation?: Calculation | null;
}

type TabKey = 'species' | 'design' | 'collect' | 'results' | 'harvest' | 'review';

export default function NtfpInventoryTab({ calculationId, calculation }: Props) {
  const t = useT();
  const isSuperAdmin = useContext(AuthContext)?.user?.role === 'super_admin';   // the card review is for the super admin only
  const [active, setActive] = useState<TabKey>('species');
  const [species, setSpecies] = useState<NtfpSpecies[]>([]);
  const [areaHa, setAreaHa] = useState<number | null>(null);
  const [loadingSpecies, setLoadingSpecies] = useState(true);
  const [query, setQuery] = useState('');
  const [onlyWithCard, setOnlyWithCard] = useState(false);
  const [picks, setPicks] = useState<Record<string, NtfpPick>>({});
  const [stored, setStored] = useState<NtfpDesign | null>(null);
  const [records, setRecords] = useState<NtfpRecords | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [plannedRows, setPlannedRows] = useState<number | null>(null);   // harvest rows with a planned quantity, for the steps strip
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingSpecies(true);
    ntfpApi
      .species(calculationId, { q: query || undefined, with_card: onlyWithCard || undefined })
      .then((r) => { if (!cancelled) { setSpecies(r.species); setAreaHa(r.forest_area_ha); } })
      .catch((err) => { if (!cancelled) setError(apiErrorText(err, t('ntfp.error.generic'))); })
      .finally(() => { if (!cancelled) setLoadingSpecies(false); });
    return () => { cancelled = true; };
  }, [calculationId, query, onlyWithCard, t]);

  const loadState = useCallback(async () => {
    try {
      const [d, r] = await Promise.all([ntfpApi.getDesign(calculationId), ntfpApi.records(calculationId)]);
      setStored(d.design);
      setRecords(r);
      // a saved design is the starting point of the picks, so the page shows what was designed rather than an empty list
      setPicks((cur) => {
        if (Object.keys(cur).length || !d.design) return cur;
        const next: Record<string, NtfpPick> = {};
        d.design.species.forEach((s) => { next[s.species_key] = { ...emptyPick(), plot_sqm: s.plot_sqm, intensity_pct: s.intensity_pct, growth_class: s.growth_class }; });
        return next;
      });
    } catch (err) {
      setError(apiErrorText(err, t('ntfp.error.generic')));
    }
  }, [calculationId, t]);

  useEffect(() => { void loadState(); }, [loadState]);

  const changed = () => { void loadState(); setRefreshKey((k) => k + 1); };
  const hasRecords = (records?.pairs_recorded ?? 0) > 0;

  // whether a harvest is planned is only read once there are records to plan from; the harvest tab keeps it up to date after that
  useEffect(() => {
    if (!hasRecords) { setPlannedRows(null); return; }
    let alive = true;
    ntfpHarvestApi.get(calculationId)
      .then((p) => { if (alive) setPlannedRows(p.totals.rows_planned); })
      .catch(() => { if (alive) setPlannedRows(null); });   // the strip then simply does not claim a plan
    return () => { alive = false; };
  }, [calculationId, hasRecords, refreshKey]);

  const stages = ntfpStages({
    picked: Object.keys(picks).length, designSpecies: stored?.species.length ?? 0, plots: stored?.plots.length ?? 0, hasDesign: !!stored,
    recorded: records?.pairs_recorded ?? 0, assigned: records?.pairs_assigned ?? 0, plannedRows,
  });

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ marginBottom: 4 }}>{t('ntfp.title')}</h2>
      <p style={{ marginBottom: 12, maxWidth: 820 }}>{t('ntfp.subtitle')}</p>
      {error && <Alert type="error" showIcon closable style={{ marginBottom: 12 }} title={error} onClose={() => setError(null)} />}
      <NtfpStagesStrip stages={stages} active={active} onSelect={(k: StageKey) => setActive(k)} />
      <Tabs
        activeKey={active}
        onChange={(k) => setActive(k as TabKey)}
        items={[
          {
            key: 'species', label: t('ntfp.tab.species'),
            children: (
              <NtfpSpeciesPanel calculationId={calculationId} species={species} loading={loadingSpecies} forestAreaHa={areaHa} picks={picks} onPicks={setPicks} query={query} onQuery={setQuery}
                onlyWithCard={onlyWithCard} onOnlyWithCard={setOnlyWithCard} onNext={() => setActive('design')} locked={hasRecords} />
            ),
          },
          {
            key: 'design', label: t('ntfp.tab.design'),
            children: <NtfpDesignPanel calculationId={calculationId} boundary={calculation?.geometry} species={species} picks={picks} stored={stored} hasRecords={hasRecords} onStored={(d) => { setStored(d); changed(); }} />,
          },
          {
            key: 'collect', label: t('ntfp.tab.collect'),
            children: <NtfpCollectPanel calculationId={calculationId} hasDesign={!!stored} records={records} onChanged={changed} design={stored} boundary={calculation?.geometry} />,
          },
          {
            key: 'results', label: t('ntfp.tab.results'),
            children: <NtfpResultsPanel calculationId={calculationId} refreshKey={refreshKey} />,
          },
          {
            key: 'harvest', label: t('ntfp.tab.harvest'),
            children: <NtfpHarvestPanel calculationId={calculationId} refreshKey={refreshKey} onPlan={(p: NtfpHarvestPlan) => setPlannedRows(p.totals.rows_planned)} />,
          },
          ...(isSuperAdmin ? [{ key: 'review', label: t('ntfp.tab.review'), children: <NtfpCardReview /> }] : []),
        ]}
      />
    </div>
  );
}
