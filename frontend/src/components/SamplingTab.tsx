/** SamplingTab — tab for sampling design configuration, plot management, and data collection. */
import { useState, useEffect, useRef } from 'react';
import { samplingApi, forestApi, compartmentApi, type SamplingSuggestions, type SamplingUnitPlan, type SamplingUnitRow } from '../services/api';
import { SamplingUnitTable, orientationFor, plotCountProblem } from './sampling/SamplingUnitTable';
import { useWorkspaceStore } from '../store/workspaceStore';
import { SamplingMapView } from './SamplingMapView';
import { AccessibleForestPreview } from './AccessibleForestPreview';
import { UnitSizeReviewPanel } from './sampling/UnitSizeReviewPanel';
import { downloadFromApi } from '../utils/download';
import HelpTooltip from './HelpTooltip';
import { useT } from '../i18n/hooks';
import { useDimensionLabels } from '../hooks/useDimensionLabels';
import { readDetail } from '../hooks/useErrorHandler';
import { parseLocaleNumber , formatDateTime } from '../i18n/numberFormat';
import { apiErrorText } from '../lib/apiErrorText';

interface SamplingTabProps {
  calculationId: string;
  /**
   * Open straight onto the create form when the forest has no design yet. Used by the
   * map workspace's "Create sample plots" command, so the user lands on the form and not
   * on a page that only says "Create New Design". Applies to the first load only: after
   * that the user is in control of the form.
   */
  startInCreateForm?: boolean;
  /**
   * Told when a design is created or deleted, so a host that shows the plots elsewhere (the
   * map workspace's Sample Plots layer) can refresh. Called after the tab has reloaded its
   * own state.
   */
  onDesignChanged?: (change: 'created' | 'deleted' | 'updated') => void;
}

// SFM stratum -> i18n label key (SS-1.5). A plain object literal, not a
// template-literal lookup, so keySync's static-scan can still verify these
// keys exist in both locale bundles.
const STRATUM_LABEL_KEY: Record<string, string> = {
  production: 'sampling.stratumLabelProduction',
  conservation: 'sampling.stratumLabelConservation',
  protection: 'sampling.stratumLabelProtection',
};

function VarHint({ name, className = '' }: { name: string; className?: string }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono cursor-pointer select-none 
        ${copied ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'} ${className}`}
      onClick={() => {
        navigator.clipboard.writeText(`{{${name}}}`);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      title={t('sampling.copyVariable', { name: `{{${name}}}` })}
    >
      {copied ? t('sampling.copied') : `{{${name}}}`}
    </span>
  );
}

export function SamplingTab({ calculationId, startInCreateForm = false, onDesignChanged }: SamplingTabProps) {
  const t = useT();
  const autoOpenedRef = useRef(false);
  const STORAGE_PREFIX = `samplingtab_${calculationId}`;
  const [designs, setDesigns] = useState<any[]>(() => {
    try { return JSON.parse(sessionStorage.getItem(`${STORAGE_PREFIX}_designs`) || '[]'); }
    catch { return []; }
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [successResult, setSuccessResult] = useState<any>(() => {
    try { return JSON.parse(sessionStorage.getItem(`${STORAGE_PREFIX}_result`) || 'null'); }
    catch { return null; }
  });

  // Which area basis produced `successResult`. Stored ALONGSIDE the result
  // rather than read back from `designs[0]` at render time, because those two
  // update at different moments: creating a design calls setSuccessResult()
  // immediately and refreshes `designs` afterwards, so for one render the
  // summary describes the new design while the basis still describes the
  // previous one -- or none at all, if this is the first.
  //
  // The low-coverage warning below depends on this, and it used to default to
  // "assume tree cover" when the basis was unknown. That is the wrong bias: it
  // could flash a coverage warning about a full-area design, on a screen that
  // reports statutory sampling adequacy. `null` means not yet known, and an
  // unknown basis does not warn.
  const [successTreeCoverBasis, setSuccessTreeCoverBasis] = useState<boolean | null>(() => {
    try {
      const raw = sessionStorage.getItem(`${STORAGE_PREFIX}_basis`);
      return raw === null ? null : JSON.parse(raw);
    } catch { return null; }
  });

  // `area_basis` is the modern field; `filter_tree_cover` is what older designs
  // carry. Returns null when there are no parameters to read at all.
  const basisIsTreeCover = (params: any): boolean | null => {
    if (!params) return null;
    if (params.area_basis) return params.area_basis === 'tree_cover';
    return params.filter_tree_cover !== false;
  };

  // Sampling points table
  const [samplingPoints, setSamplingPoints] = useState<any[]>(() => {
    try { return JSON.parse(sessionStorage.getItem(`${STORAGE_PREFIX}_points`) || '[]'); }
    catch { return []; }
  });
  const [loadingPoints, setLoadingPoints] = useState(false);

  // Navigation support options (Phase 2 enhancement)
  const [includeElevation, setIncludeElevation] = useState(true); // Default: ON
  const [includeTopoFeatures, setIncludeTopoFeatures] = useState(true); // Default: ON (ridge/river info)

  // Calculation data
  const [calculation, setCalculation] = useState<any>(null);

  // Check if compartments exist — block-level sampling is mutually exclusive with compartment mode
  const [hasCompartments, setHasCompartments] = useState(false);

  // Form state (method is derived from type: systematic → Guideline-2061 (block OR
  // compartment — PROTECTION_WORKING_CIRCLE_PLAN.md P5); random → intensity engine
  // (compartment) / intensity-based random fallback (block))
  const [samplingType, setSamplingType] = useState<'systematic' | 'random'>('systematic');
  const [samplingIntensity, setSamplingIntensity] = useState(2.0); // compartment default 2.0%; block random fallback = 0.5
  const [minDistance, setMinDistance] = useState(30); // random-point min spacing (m)
  // '2.0' — the production-stratum floor (कार्यविधि §16) — is the sane
  // default; a unit-specific override always comes from the stratum table
  // below when SFM's classification is available (SS-1.5).
  const [productiveIntensity, setProductiveIntensity] = useState<'0.5' | '1.0' | '2.0'>('2.0');
  const [sampleProtectedZone, setSampleProtectedZone] = useState(false);
  const [plotSizeSqm, setPlotSizeSqm] = useState(500);
  // कार्यविधि §16's flat 5-plot-per-unit floor — checked (enforced) by default
  // per owner decision (2026-09-15: "let user choose whether to enforce or
  // not; default checked"), refined the same day to be per-stratum ("user
  // should get a chance for each zone -- production, conservation, and
  // protection"). Three independent toggles, all default-checked.
  const [enforceMinSamplesProduction, setEnforceMinSamplesProduction] = useState(true);
  const [enforceMinSamplesConservation, setEnforceMinSamplesConservation] = useState(true);
  const [enforceMinSamplesProtection, setEnforceMinSamplesProtection] = useState(true);

  // SFM stratum classification per unit (कार्यविधि §16 — SFM_STRATUM_SAMPLING
  // PLAN, SS-1.5). Every unit (block/compartment/sub-compartment) is
  // classified into production/conservation/protection with an enforced
  // minimum intensity + plot size; the per-unit table below is always shown
  // (no more opt-in checkbox) and its values are always sent with the create/
  // preview request — the backend rejects anything below the unit's floor.
  // One row per polygon, for ANY forest (no forest type or plots needed): stratum + reason, legal minimum, plots already there.
  const [unitPlan, setUnitPlan] = useState<SamplingUnitPlan | null>(null);
  // The polygons the user ticked. Nothing ticked = every polygon that can be sampled; once any is ticked, only those.
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busyUnit, setBusyUnit] = useState<string | null>(null);
  // How many plots each polygon's intensity amounts to, and the number we suggest (never fewer than 5), from the server.
  const [suggestions, setSuggestions] = useState<SamplingSuggestions | null>(null);
  // Plots the user typed per polygon. A polygon without one uses the suggestion; what is shown is exactly what is placed.
  const [plots, setPlots] = useState<Record<string, number>>({});
  const [addingRound, setAddingRound] = useState(false);
  const mapSelectedIds = useWorkspaceStore((st) => st.selection.featureIds);
  const [perBlockIntensity, setPerBlockIntensity] = useState<Record<string, number>>({});
  const [protectedZoneInfo, setProtectedZoneInfo] = useState<any>(null);
  const [loadingProtectedInfo, setLoadingProtectedInfo] = useState(false);

  // Sampling area basis (Phase D): sample inside tree-covered pixels, or the whole unit
  const [areaBasis, setAreaBasis] = useState<'tree_cover' | 'full_area'>('tree_cover'); // Default: Tree Cover
  const filterTreeCover = areaBasis === 'tree_cover';

  // Forest area preview
  const [previewData, setPreviewData] = useState<any>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  // Phase F — pre-create sample-plot preview (exact locs → deterministic create)
  const [samplePlotPreview, setSamplePlotPreview] = useState<any>(null);
  const [loadingPlotPreview, setLoadingPlotPreview] = useState(false);
  const [showPlotPreview, setShowPlotPreview] = useState(false);

  useEffect(() => {
    loadDesigns();
    loadCalculation();
  }, [calculationId]);

  const loadProtectedZoneInfo = async () => {
    setLoadingProtectedInfo(true);
    try {
      const data = await samplingApi.getProtectedZones(calculationId);
      setProtectedZoneInfo(data);
    } catch (err: any) {
      console.error('Failed to load protected zone info:', err);
      setProtectedZoneInfo(null);
    } finally {
      setLoadingProtectedInfo(false);
    }
  };

  // Method derived from type: systematic → Guideline-2061 (block AND compartment
  // forests — PROTECTION_WORKING_CIRCLE_PLAN.md P5 / research Q7; the backend
  // engine + the DoF sample-count tables are keyed by absolute area, not by
  // "block" vs "compartment"). random → intensity-based fallback.
  const isGuidelineMode = samplingType === 'systematic';

  // Load protected zone info when Guideline-2061 (systematic — block or compartment) is active
  useEffect(() => {
    if (isGuidelineMode && showCreateForm) {
      loadProtectedZoneInfo();
    }
  }, [isGuidelineMode, showCreateForm, calculationId]);

  // Intensity defaults adapt to mode & type (E.1): compartment → 2.0%, block+random → 0.5%
  useEffect(() => {
    setSamplingIntensity(hasCompartments ? 2.0 : 0.5);
  }, [hasCompartments, samplingType]);

  // Phase F — stale preview invalidation: any sampling-affecting setting change
  // means the captured plot locations no longer match what Create would do.
  useEffect(() => {
    setSamplePlotPreview(null);
    setShowPlotPreview(false);
  }, [
    hasCompartments,
    samplingType,
    samplingIntensity,
    minDistance,
    productiveIntensity,
    sampleProtectedZone,
    plotSizeSqm,
    areaBasis,
    perBlockIntensity,
    enforceMinSamplesProduction,
    enforceMinSamplesConservation,
    enforceMinSamplesProtection,
  ]);

  const loadCalculation = async () => {
    try {
      const data = await forestApi.getCalculation(calculationId);
      setCalculation(data);

      // Check if compartments exist
      try {
        const availableBlocks = await compartmentApi.getAvailableBlocks(calculationId);
        const anyCompartment = availableBlocks.some((b: any) => b.has_compartments);
        setHasCompartments(anyCompartment);
      } catch {
        setHasCompartments(false);
      }
    } catch (err: any) {
      console.error('Failed to load calculation:', err);
    }
  };

  // The per-polygon plan comes from the server for every forest. Its stratum is the SAME rule the sampling engines enforce with
  // (stratum_spec.stratum_and_source: the user's own orientation, SFM, a protected area, the slope, else production), so the floor
  // shown here is the floor the server demands. Re-pulled whenever the create form opens, because a polygon's orientation can be
  // changed elsewhere (the Sustainable FM tab, the attribute table) while this tab stays mounted.
  useEffect(() => {
    if (!unitPlan || unitPlan.units.length === 0) {
      setSuggestions(null);
      return;
    }
    let cancelled = false;
    const intensities: Record<string, number> = {};
    for (const r of unitPlan.units) intensities[r.name] = perBlockIntensity[r.name] ?? r.floor_pct;
    const timer = setTimeout(() => {
      samplingApi
        .suggestedCounts(calculationId, intensities, isGuidelineMode ? 'guideline' : 'manual')
        .then((res) => { if (!cancelled) setSuggestions(res); })
        .catch(() => { if (!cancelled) setSuggestions(null); }); // without suggestions the form still works from the intensities
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [calculationId, unitPlan, perBlockIntensity, isGuidelineMode]);  // eslint-disable-line react-hooks/exhaustive-deps

  const refreshUnitPlan = async () => {
    try {
      setUnitPlan(await samplingApi.unitPlan(calculationId));
    } catch {
      setUnitPlan(null); // the table simply is not shown; the forest-wide settings still work
    }
  };
  useEffect(() => {
    refreshUnitPlan();
  }, [calculationId, showCreateForm]);  // eslint-disable-line react-hooks/exhaustive-deps

  const loadDesigns = async () => {
    // Only show loading spinner on initial load (no cached data)
    const needsLoading = designs.length === 0;
    if (needsLoading) setLoading(true);
    setError(null);
    try {
      const data = await samplingApi.list(calculationId);
      setDesigns(data);
      sessionStorage.setItem(`${STORAGE_PREFIX}_designs`, JSON.stringify(data));

      // First load only: a host that wants the form (the map workspace) gets it when
      // there is no design yet. With one already there, the tab's own "one design per
      // forest" notice — and its delete button — is what the user needs to see.
      if (startInCreateForm && !autoOpenedRef.current) {
        autoOpenedRef.current = true;
        if (data.length === 0) setShowCreateForm(true);
      }

      if (data.length === 0) {
        setSuccessResult(null);
        setSuccessTreeCoverBasis(null);
        setSamplingPoints([]);
        sessionStorage.removeItem(`${STORAGE_PREFIX}_result`);
        sessionStorage.removeItem(`${STORAGE_PREFIX}_basis`);
        sessionStorage.removeItem(`${STORAGE_PREFIX}_points`);
      } else {
        // Restore persisted summary from most recent design's result_data
        if (data[0].result_data) {
          const basis = basisIsTreeCover(data[0].default_parameters);
          setSuccessResult(data[0].result_data);
          setSuccessTreeCoverBasis(basis);
          sessionStorage.setItem(`${STORAGE_PREFIX}_result`, JSON.stringify(data[0].result_data));
          sessionStorage.setItem(`${STORAGE_PREFIX}_basis`, JSON.stringify(basis));
        }
        // Auto-load sampling points for the first design
        loadSamplingPoints(data[0].id);
      }
    } catch (err: any) {
      setError(apiErrorText(err, t('sampling.loadDesignsFailed')));
    } finally {
      if (needsLoading) setLoading(false);
    }
  };

  const loadSamplingPoints = async (designId: string) => {
    // Only show loading spinner if no cached points
    const needsLoading = samplingPoints.length === 0;
    if (needsLoading) setLoadingPoints(true);
    try {
      const data = await samplingApi.getPoints(designId, {
        include_elevation: includeElevation,
        include_topographic_features: includeTopoFeatures,
      });
      setSamplingPoints(data.points || []);
      sessionStorage.setItem(`${STORAGE_PREFIX}_points`, JSON.stringify(data.points || []));
    } catch (err: any) {
      alert(apiErrorText(err, t('sampling.loadPointsFailed')));
    } finally {
      if (needsLoading) setLoadingPoints(false);
    }
  };

  const handlePreviewForestAreas = async () => {
    setLoadingPreview(true);
    setPreviewData(null);
    setError(null);

    try {
      const data = await samplingApi.previewAccessibleForest(calculationId, {
        filter_tree_cover: filterTreeCover,
      });
      setPreviewData(data);
      setShowPreview(true);
    } catch (err: any) {
      const errorDetail = apiErrorText(err, t('sampling.previewFailed'));

      // Check if it's a timeout error (408 status)
      if (err.response?.status === 408) {
        setError(t('sampling.previewTimeout', { detail: errorDetail }));
      } else {
        setError(errorDetail);
      }

      setShowPreview(false);
    } finally {
      setLoadingPreview(false);
    }
  };

  const unitRows: SamplingUnitRow[] = unitPlan?.units ?? [];
  // Plots are filed under a unit's sampling key (its code, else its name); the screen shows the Name the workspace attribute table shows.
  const unitDisplayName = (key: string | null | undefined): string => {
    if (!key) return '';
    return unitRows.find((r) => r.name === key)?.display_name ?? key;
  };
  // The polygon's dominant land cover from its stored analysis (so a mostly non-forest polygon's few plots are explained)
  const landCoverCell = (key: string | null | undefined, cls: string) => {
    const row = unitRows.find((x) => x.name === key);
    if (!row || !row.landcover_dominant) {
      return <td className={`${cls} text-gray-400`} title={t('sampling.landcoverNotAnalysed')}>-</td>;
    }
    const low = row.forest_pct != null && row.forest_pct < 30;
    const detail = (row.landcover_breakdown ?? []).map((b) => `${b.name} ${b.pct}%`).join(', ');
    return (
      <td className={cls} title={low ? `${detail} - ${t('sampling.landcoverLowForest', { pct: row.forest_pct })}` : detail} data-testid="sampling-landcover">
        {row.landcover_dominant}
        {row.landcover_dominant_pct != null ? ` ${row.landcover_dominant_pct}%` : ''}
        {low && <span className="ml-1 text-yellow-600" aria-label={t('sampling.landcoverLowForest', { pct: row.forest_pct })}>⚠️</span>}
      </td>
    );
  };
  const anyTicked = unitRows.some((r) => r.sampled_plots === 0 && ticked.has(r.name));
  // a polygon gets plots when it has none yet and (nothing is ticked, or it is ticked)
  const willSample = (r: SamplingUnitRow): boolean => r.sampled_plots === 0 && (!anyTicked || ticked.has(r.name));

  // Effective per-unit intensity: the user's edit if present, else the legal minimum of its stratum.
  const effectiveUnitIntensity = (row: SamplingUnitRow): number => perBlockIntensity[row.name] ?? row.floor_pct;
  // What is SENT: 0 ("do not sample this unit") for every polygon that is not to get plots in this round.
  const sentIntensity = (row: SamplingUnitRow): number => (willSample(row) ? effectiveUnitIntensity(row) : 0);

  // The number of plots a polygon will get: what the user typed, else the suggestion. Undefined until the suggestions have loaded.
  const effectivePlots = (row: SamplingUnitRow): number | undefined => plots[row.name] ?? suggestions?.units[row.name]?.suggested;
  const sentPlots = (row: SamplingUnitRow): number | undefined => (willSample(row) ? effectivePlots(row) : 0);
  const hasPlotCountProblem = unitRows.some((r) => willSample(r) && plotCountProblem(r, effectivePlots(r)) !== null);

  const isUnitBelowFloor = (row: SamplingUnitRow): boolean => {
    if (!willSample(row)) return false;
    const v = effectiveUnitIntensity(row);
    // 0 is the one value below the floor that is allowed: "do not sample this unit".
    if (v === 0) return false;
    return Number.isNaN(v) || v < row.floor_pct;
  };

  // Blocks the design from being created/previewed while any polygon that will be sampled sits below its legal minimum
  // (the backend rejects it anyway: 400 SFM_INTENSITY_BELOW_FLOOR - this gives the message before the round-trip).
  const hasStratumFloorViolation = unitRows.some(isUnitBelowFloor) || hasPlotCountProblem;

  // An explicit number of plots for every polygon, once the suggestions have loaded: the number on the screen is the number placed.
  const explicitCounts = (): Record<string, number> | null => {
    if (!suggestions) return null;
    const out: Record<string, number> = {};
    for (const row of unitRows) {
      const n = sentPlots(row);
      if (n === undefined) return null;
      out[row.name] = n;
    }
    return out;
  };

  const buildCreateParams = (): any => {
    const params: any = {
      sampling_method: isGuidelineMode ? 'guideline_2061' : 'manual',
      filter_tree_cover: filterTreeCover,
      enforce_min_samples_production: enforceMinSamplesProduction,
      enforce_min_samples_conservation: enforceMinSamplesConservation,
      enforce_min_samples_protection: enforceMinSamplesProtection,
    };

    // The per-unit stratum table is always sent when SFM has classified any
    // units (SS-1.5 -- no more opt-in checkbox); the two engines take the
    // override in different shapes.
    const hasStratumPlan = unitRows.length > 0;

    if (isGuidelineMode) {
      params.productive_intensity = productiveIntensity;
      params.sample_protected_zone = sampleProtectedZone;
      params.plot_size_sqm = plotSizeSqm;
      if (hasStratumPlan) {
        const perBlock: Record<string, number> = {};
        for (const row of unitRows) perBlock[row.name] = sentIntensity(row);
        params.per_block_intensity = perBlock;
        const counts = explicitCounts();
        if (counts) params.per_block_plots = counts;
      }
    } else {
      // Compartment mode (and block+Random fallback) → intensity engine
      if (hasStratumPlan) {
        const overrides: Record<string, { sampling_intensity_percent: number }> = {};
        for (const row of unitRows) {
          overrides[row.name] = { sampling_intensity_percent: sentIntensity(row) };
        }
        params.block_overrides = overrides;
        const counts = explicitCounts();
        if (counts) params.per_block_plots = counts;
      }
      params.sampling_type = samplingType;
      params.sampling_intensity_percent = samplingIntensity;
      if (samplingType === 'random') {
        params.min_distance_meters = minDistance;
      }
    }
    return params;
  };

  const handlePreviewSamplePlots = async () => {
    setLoadingPlotPreview(true);
    setSamplePlotPreview(null);
    setError(null);
    try {
      const data = await samplingApi.preview(calculationId, buildCreateParams());
      setSamplePlotPreview(data);
      setShowPlotPreview(true);
    } catch (err: any) {
      // P8/P6: a bilingual `detail` used to be JSON.stringify'd, so a floor refusal
      // reached the user as a raw blob - code, message, message_np and the raw
      // service prefix all in one line. `readDetail` picks the message for the active
      // language and ignores `raw`, which is a log field, not user-facing text.
      const errorDetail = readDetail(err.response?.data?.detail) ?? t('sampling.plotPreviewFailed');
      setError(errorDetail);
      setShowPlotPreview(false);
    } finally {
      setLoadingPlotPreview(false);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const params: any = buildCreateParams();

      // Phase F — deterministic create from the captured preview (if any).
      // What the user previewed is exactly what gets created.
      if (samplePlotPreview?.sampling_points_geojson) {
        params.preview = samplePlotPreview;
      }

      const result = await samplingApi.create(calculationId, params);

      // Store result and show success summary. The basis comes from what was
      // just submitted, so the summary and the warning describe the same design
      // on the very first render rather than after `loadDesigns()` returns.
      setSuccessResult(result);
      setSuccessTreeCoverBasis(filterTreeCover);
      try {
        sessionStorage.setItem(`${STORAGE_PREFIX}_basis`, JSON.stringify(filterTreeCover));
      } catch { /* storage unavailable; state still holds it for this session */ }
      setShowCreateForm(false);
      setSamplePlotPreview(null);
      setShowPlotPreview(false);
      setPlots({});

      try {
        await loadDesigns();
      } catch (loadErr) {
        console.error('Failed to reload designs:', loadErr);
      }
      onDesignChanged?.('created');
    } catch (err: any) {
      console.error('Create sampling error:', err);
      // readDetail, not JSON.stringify: the bilingual detail is for humans and
      // `raw` is a log field. Stringifying it produced the whole JSON payload on
      // screen, including a nested escaped service string.
      const errorMsg =
        readDetail(err.response?.data?.detail) ??
        (err.message
          ? err.message
          : typeof err === 'string'
            ? err
            : t('sampling.createFailed'));
      setError(errorMsg);
      alert(t('sampling.errorAlert', { message: errorMsg }));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (designId: string) => {
    if (!confirm(t('sampling.confirmDelete'))) {
      return;
    }

    try {
      await samplingApi.delete(designId);
      setSuccessResult(null);
      setSuccessTreeCoverBasis(null);
      await loadDesigns();
      onDesignChanged?.('deleted');
      alert(t('sampling.deleteSuccess'));
    } catch (err: any) {
      alert(apiErrorText(err, t('sampling.deleteFailed')));
    }
  };

  const handleExport = async (designId: string, format: 'csv' | 'gpx' | 'geojson' | 'kml') => {
    try {
      await downloadFromApi(
        `/api/sampling/${designId}/points`,
        `sampling_${designId.substring(0, 8)}.${format}`,
        { format }
      );
    } catch (err: any) {
      alert(err.message || t('sampling.exportFailed', { format }));
    }
  };

  const toggleTick = (name: string) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });

  const handleStratum = async (row: SamplingUnitRow, stratum: SamplingUnitRow['stratum']) => {
    setBusyUnit(row.name);
    setError(null);
    try {
      await forestApi.setUnitOrientation(calculationId, row.unit_id, orientationFor(stratum));
      // the legal minimum changed with the stratum: drop a typed value so the row starts from the new minimum
      setPerBlockIntensity((prev) => {
        const next = { ...prev };
        delete next[row.name];
        return next;
      });
      setPlots((prev) => { const next = { ...prev }; delete next[row.name]; return next; });
      await refreshUnitPlan();
    } catch (err: any) {
      setError(apiErrorText(err, t('sampling.unitTable.stratumFailed', { defaultValue: 'The stratum could not be changed.' })));
    } finally {
      setBusyUnit(null);
    }
  };

  const handleDeleteUnitPlots = async (row: SamplingUnitRow) => {
    const design = designs[0];
    if (!design) return;
    if (!confirm(t('sampling.unitTable.confirmDeletePlots', { defaultValue: 'Delete all {{n}} sample plots of {{name}}? The remaining plots are renumbered.', n: row.sampled_plots, name: row.name }))) {
      return;
    }
    setBusyUnit(row.name);
    setError(null);
    try {
      await samplingApi.deleteUnitPlots(design.id, row.name);
      await loadDesigns();
      await refreshUnitPlan();
      onDesignChanged?.('updated');
    } catch (err: any) {
      setError(readDetail(err.response?.data?.detail) ?? apiErrorText(err, t('sampling.unitTable.deletePlotsFailed', { defaultValue: 'The plots could not be deleted.' })));
    } finally {
      setBusyUnit(null);
    }
  };

  // A LATER ROUND: sample more polygons into the forest's one design. Existing plots do not move; the new ones are numbered after them.
  const handleAddRound = async () => {
    const design = designs[0];
    if (!design) return;
    setAddingRound(true);
    setError(null);
    try {
      const params: any = buildCreateParams();
      const prev = await samplingApi.previewAdd(calculationId, design.id, params);
      const unitsHit = (prev.blocks_info ?? []).filter((b: any) => (b.samples_generated ?? 0) > 0).length;
      if (!confirm(t('sampling.unitTable.confirmAdd', { defaultValue: 'Add {{n}} sample plots in {{units}} polygon(s) to the design?', n: prev.total_points, units: unitsHit }))) {
        return;
      }
      await samplingApi.addUnits(calculationId, design.id, { ...params, preview: prev });
      setTicked(new Set());
      setPlots({});
      await loadDesigns();
      await refreshUnitPlan();
      onDesignChanged?.('updated');
    } catch (err: any) {
      setError(readDetail(err.response?.data?.detail) ?? apiErrorText(err, t('sampling.unitTable.addFailed', { defaultValue: 'The plots could not be added.' })));
    } finally {
      setAddingRound(false);
    }
  };

  const unitTableElement = (
    <SamplingUnitTable
      rows={unitRows}
      fieldDataExists={!!unitPlan?.field_data_exists}
      ticked={ticked}
      intensities={perBlockIntensity}
      mapSelectedIds={mapSelectedIds}
      busyUnit={busyUnit}
      stratumLabel={(st) => t(STRATUM_LABEL_KEY[st] ?? st)}
      onToggle={toggleTick}
      onTickAll={() => setTicked(new Set(unitRows.filter((r) => r.sampled_plots === 0).map((r) => r.name)))}
      onTickNone={() => setTicked(new Set())}
      onTickFromMap={() => setTicked(new Set(unitRows.filter((r) => r.sampled_plots === 0 && (mapSelectedIds ?? []).includes(r.unit_id)).map((r) => r.name)))}
      onIntensity={(name, v) => {
        setPerBlockIntensity((prev) => ({ ...prev, [name]: v }));
        setPlots((prev) => { const next = { ...prev }; delete next[name]; return next; });
      }}
      suggestions={suggestions?.units}
      minSuggested={suggestions?.minimum_suggested}
      plots={plots}
      onPlots={(name, n) => setPlots((prev) => ({ ...prev, [name]: n }))}
      onResetPlots={(name) => setPlots((prev) => { const next = { ...prev }; delete next[name]; return next; })}
      onStratum={handleStratum}
      onDeletePlots={handleDeleteUnitPlots}
    />
  );

  const labels = useDimensionLabels({ hasCompartments });
  const { unitLabel, unitLabelPlural } = labels;

  // Per-unit SFM stratum (production/conservation/protection, कार्यविधि §16),
  // keyed by block_name -- for the Sampling Points table's "SFM Stratum"
  // column and the map popups. This is a DIFFERENT axis than a point's own
  // zone_type (productive vs a protected sub-area carve-out inside the
  // unit): a whole "conservation"-stratum block can still contain
  // productive-zone points. Works on anything shaped like blocks_info OR
  // SfmSamplingRow[] (both carry block_name + stratum).
  const buildStratumMap = (rows: any[] | undefined | null): Record<string, string | undefined> =>
    (rows || []).reduce((acc: Record<string, string | undefined>, b: any) => {
      if (b?.block_name) acc[b.block_name] = b.stratum;
      return acc;
    }, {});

  // successResult and samplingPoints are always loaded for the same design
  // (see loadDesigns/loadSamplingPoints), so this join is safe.
  const blockStratumByName = buildStratumMap(successResult?.blocks_info);

  if (loading) {
    return (
      <div className="flex justify-center items-center py-12">
        <div className="text-gray-600">{t('sampling.loadingDesigns')}</div>
      </div>
    );
  }

  return (
    <div className="space-y-6 sampling-page">
      {/* Mode banner — explains the active method path (rule C) */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
        <div className="flex items-center gap-2 text-sm text-blue-800">
          <span>{isGuidelineMode ? '📋' : hasCompartments ? '📦' : '🗂️'}</span>
          <span>
            {isGuidelineMode
              ? t('sampling.modeBannerGuideline')
              : hasCompartments
                ? t('sampling.modeBannerCompartment', {
                    unit: labels.unitLabelLower,
                    method: samplingType,
                  })
                : t('sampling.modeBannerBlockRandom')}
          </span>
          <span className="ml-auto px-2 py-0.5 rounded text-xs font-medium bg-white border border-blue-300 text-blue-700 whitespace-nowrap">
            {samplingType === 'systematic' ? t('sampling.methodSystematic') : t('sampling.methodRandom')}
          </span>
        </div>
      </div>

      {/* Create Button */}
      {!showCreateForm && designs.length === 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <button
            onClick={() => setShowCreateForm(true)}
            className="w-full bg-blue-600 text-white px-4 py-3 rounded-md hover:bg-blue-700"
          >
            {t('sampling.createNewDesign')}
          </button>
        </div>
      )}

      {/* Warning if design exists */}
      {!showCreateForm && designs.length > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-yellow-800 mb-2">
            {t('sampling.oneDesignPerForestTitle')}
          </h3>
          <p className="text-sm text-yellow-700 mb-4">
            {t('sampling.oneDesignPerForestBody')}
          </p>
          <button
            onClick={() => setShowCreateForm(true)}
            disabled
            className="w-full bg-gray-400 text-white px-4 py-3 rounded-md cursor-not-allowed"
          >
            {t('sampling.createNewDesignDeleteFirst')}
          </button>
        </div>
      )}

      {/* Create Form */}
      {showCreateForm && (
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold">{t('sampling.createDesign')}</h3>
            <button
              onClick={() => setShowCreateForm(false)}
              className="text-gray-500 hover:text-gray-700"
            >
              ✕
            </button>
          </div>

          <div className="space-y-4">
            {/* Sampling Type selector — shown in both modes (Phase E) */}
            <div className="space-y-3 border-t pt-4">
              <h4 className="font-semibold text-gray-900 flex items-center gap-2">
                <span className="text-gray-600">🎯</span>
                {t('sampling.typeLabel')}
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setSamplingType('systematic')}
                  className={`rounded-lg border p-4 text-left transition-colors ${
                    samplingType === 'systematic'
                      ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                      : 'border-gray-300 hover:border-gray-400 bg-white'
                  }`}
                >
                  <div className="font-medium text-gray-900">{t('sampling.methodSystematic')}</div>
                  <div className="text-xs text-gray-600 mt-1">
                    {t('sampling.methodSystematicDescription', { unit: labels.unitLabelLower })}
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setSamplingType('random')}
                  className={`rounded-lg border p-4 text-left transition-colors ${
                    samplingType === 'random'
                      ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                      : 'border-gray-300 hover:border-gray-400 bg-white'
                  }`}
                >
                  <div className="font-medium text-gray-900">{t('sampling.methodRandom')}</div>
                  <div className="text-xs text-gray-600 mt-1">
                    {t('sampling.methodRandomDescription')}
                  </div>
                </button>
              </div>
            </div>

            {/* Mode + type config — systematic (block OR compartment): Guideline-2061;
                compartment+random: unit-intensity; block+random: intensity fallback */}
            {!isGuidelineMode && hasCompartments ? (
              <div className="space-y-4 border-t pt-4">
                <h4 className="font-semibold text-gray-900 flex items-center gap-2">
                  <span className="text-gray-600">⚙️</span>
                  {t('sampling.intensityCompartmentMode', { unit: labels.unitLabel })}
                </h4>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                    {t('sampling.intensityOfUnitArea', { unit: labels.unitLabelLower })}
                    <HelpTooltip tKey="tooltips.samplingIntensity" />
                  </label>
                  <input
                    type="text" inputMode="decimal"
                    min="0.1"
                    max="10"
                    step="0.1"
                    value={samplingIntensity}
                    onChange={(e) => setSamplingIntensity(parseLocaleNumber(e.target.value))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    {t('sampling.intensityDefaultHint', { unit: labels.unitLabelLower })}
                  </p>
                </div>

                {samplingType === 'random' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                      {t('sampling.minDistanceBetweenPoints')}
                      <HelpTooltip tKey="tooltips.samplingMinDistance" />
                    </label>
                    <input
                      type="text" inputMode="decimal"
                      min="1"
                      step="1"
                      value={minDistance}
                      onChange={(e) => setMinDistance(Math.trunc(parseLocaleNumber(e.target.value)) || 0)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md"
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      {t('sampling.minDistanceHint', { distance: minDistance })}
                    </p>
                  </div>
                )}
              </div>
            ) : isGuidelineMode ? (
              <div className="space-y-4 border-t pt-4">
                <h4 className="font-semibold text-gray-900 flex items-center gap-2">
                  <span className="text-blue-600">📋</span>
                  {t('sampling.guidelineConfig')}
                </h4>

                {/* Sampling Intensity */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                    {t('sampling.intensityProductiveForest')}
                    <HelpTooltip tKey="tooltips.samplingProductiveIntensity" />
                  </label>
                  <select
                    value={productiveIntensity}
                    onChange={(e) => setProductiveIntensity(e.target.value as '0.5' | '1.0' | '2.0')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white"
                  >
                    <option value="0.5">{t('sampling.intensity05Standard')}</option>
                    <option value="1.0">{t('sampling.intensity10Detailed')}</option>
                    <option value="2.0">{t('sampling.intensity20Sfm')}</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    {t('sampling.sampleCountLookupHint')}
                  </p>
                  {unitRows.length > 0 && (
                    <p className="mt-1 text-xs text-emerald-700">
                      {t('sampling.productiveIntensityFallbackHint')}
                    </p>
                  )}
                </div>

                {/* Plot Size */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                    {t('sampling.plotSizeProductiveForest')}
                    <HelpTooltip tKey="tooltips.samplingPlotSize" />
                  </label>
                  <select
                    value={plotSizeSqm}
                    onChange={(e) => setPlotSizeSqm(Math.trunc(parseLocaleNumber(e.target.value)))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md bg-white"
                  >
                    <option value="500">{t('sampling.plot500')}</option>
                    <option value="400">{t('sampling.plot400')}</option>
                    <option value="300">{t('sampling.plot300')}</option>
                    <option value="200">{t('sampling.plot200')}</option>
                    <option value="100">{t('sampling.plot100')}</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    {t('sampling.plotSizeIntro')} {sampleProtectedZone && protectedZoneInfo?.has_protected ? (
                      <span className="text-green-700 font-medium">{t('sampling.protectedPlots100')}</span>
                    ) : (
                      t('sampling.sampleCountsVaryByPlot')
                    )}
                  </p>
                </div>

                {/* Protected Zone Sampling Option */}
                {protectedZoneInfo && protectedZoneInfo.has_protected && (
                  <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                    <label className="flex items-start cursor-pointer">
                      <input
                        type="checkbox"
                        checked={sampleProtectedZone}
                        onChange={(e) => setSampleProtectedZone(e.target.checked)}
                        className="mt-0.5 mr-3 h-4 w-4 text-green-600 focus:ring-green-500 border-gray-300 rounded"
                      />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-gray-900">
                          {t('sampling.sampleProtectedZones0_1')}
                        </div>
                        <p className="text-xs text-gray-600 mt-1">
                          {t('sampling.protectedZonesFound', {
                            count: protectedZoneInfo.protected_zone_count,
                            area: protectedZoneInfo.protected_area_hectares,
                          })}
                          {sampleProtectedZone ? (
                            <span className="text-green-700 font-medium"> {t('sampling.protectedZonesSampledSep')}</span>
                          ) : (
                            <span className="text-orange-700 font-medium"> {t('sampling.protectedZonesExcluded')}</span>
                          )}
                        </p>
                      </div>
                    </label>
                  </div>
                )}

                <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                  <p className="text-xs text-gray-700">
                    <strong className="text-blue-900">{t('sampling.noteColon')}</strong> {t('sampling.guidelineNoteBody')}
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-4 border-t pt-4">
                <h4 className="font-semibold text-gray-900 flex items-center gap-2">
                  <span className="text-orange-600">⚙️</span>
                  {t('sampling.intensityRandomFallback')}
                </h4>

                <div className="bg-orange-50 border border-orange-200 rounded-lg p-3">
                  <p className="text-xs text-orange-800">
                    <strong>{t('sampling.fallbackModeColon')}</strong> {t('sampling.fallbackModeBody')}
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                    {t('sampling.intensityOfUnitArea', { unit: labels.unitLabelLower })}
                    <HelpTooltip tKey="tooltips.samplingIntensity" />
                  </label>
                  <input
                    type="text" inputMode="decimal"
                    min="0.1"
                    max="10"
                    step="0.1"
                    value={samplingIntensity}
                    onChange={(e) => setSamplingIntensity(parseLocaleNumber(e.target.value))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    {t('sampling.intensityFallbackDefault')}
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center gap-2">
                    {t('sampling.minDistanceBetweenPoints')}
                    <HelpTooltip tKey="tooltips.samplingMinDistance" />
                  </label>
                  <input
                    type="text" inputMode="decimal"
                    min="1"
                    step="1"
                    value={minDistance}
                    onChange={(e) => setMinDistance(Math.trunc(parseLocaleNumber(e.target.value)) || 0)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    {t('sampling.minDistanceHint', { distance: minDistance })}
                  </p>
                </div>
              </div>
            )}

            {/* कार्यविधि §16 minimum-5-plots floor — user-toggleable PER
                STRATUM, checked (enforced) by default for all three.
                Applies to both engines. */}
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
              <div className="text-sm font-medium text-gray-900 mb-2">
                {t('sampling.enforceMinSamplesTitle')}
              </div>
              <p className="text-xs text-gray-600 mb-3">
                {t('sampling.enforceMinSamplesHint')}
              </p>
              <div className="space-y-2">
                <label className="flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enforceMinSamplesProduction}
                    onChange={(e) => setEnforceMinSamplesProduction(e.target.checked)}
                    className="mr-3 h-4 w-4 text-emerald-600 focus:ring-emerald-500 border-gray-300 rounded"
                  />
                  <span className="text-sm text-gray-800">{t('sampling.stratumLabelProduction')}</span>
                </label>
                <label className="flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enforceMinSamplesConservation}
                    onChange={(e) => setEnforceMinSamplesConservation(e.target.checked)}
                    className="mr-3 h-4 w-4 text-emerald-600 focus:ring-emerald-500 border-gray-300 rounded"
                  />
                  <span className="text-sm text-gray-800">{t('sampling.stratumLabelConservation')}</span>
                </label>
                <label className="flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enforceMinSamplesProtection}
                    onChange={(e) => setEnforceMinSamplesProtection(e.target.checked)}
                    className="mr-3 h-4 w-4 text-emerald-600 focus:ring-emerald-500 border-gray-300 rounded"
                  />
                  <span className="text-sm text-gray-800">{t('sampling.stratumLabelProtection')}</span>
                </label>
              </div>
            </div>

            {/* One row per polygon, for every forest: tick the polygons to sample (none ticked = all), see the stratum and its legal
                minimum, set the intensity. Polygons that already have plots are disabled and say what to do. */}
            {unitRows.length > 0 && (
              <div className="border-t pt-6 mt-6">
                <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3">
                  <div className="text-sm font-medium text-gray-900">
                    {t('sampling.unitTable.title', { count: unitRows.length, defaultValue: 'Polygons to sample ({{count}})' })}
                  </div>
                  <p className="text-xs text-gray-600 mt-1 mb-2">{t('sampling.stratumCardHint')}</p>
                  {unitTableElement}
                </div>
              </div>
            )}

            {/* Accessible Forest Filtering (common to both methods) */}
            <div className="border-t pt-6 mt-6">
              <h4 className="text-md font-semibold text-gray-900 mb-3">
                {t('sampling.areaFiltersTitle')}
              </h4>
              <p className="text-xs text-gray-600 mb-4">
                {t('sampling.areaFiltersSubtitle')}
              </p>

              {/* Sampling Area Basis (Phase D) */}
              <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="font-medium text-gray-900 flex items-center gap-2">
                    {t('sampling.areaBasisTitle')}
                    <HelpTooltip tKey="tooltips.samplingAreaBasis" />
                  </div>
                  <span className="text-xs bg-green-100 text-green-800 px-2 py-1 rounded whitespace-nowrap">
                    {t('sampling.recommendedTreeCover')}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setAreaBasis('tree_cover')}
                    className={`rounded-lg border p-4 text-left transition-colors ${
                      areaBasis === 'tree_cover'
                        ? 'border-green-500 bg-white ring-2 ring-green-200'
                        : 'border-gray-300 bg-transparent hover:border-gray-400'
                    }`}
                  >
                    <div className="font-medium text-gray-900">🌳 {t('sampling.areaBasisTreeCover')}</div>
                    <p className="text-sm text-gray-600 mt-1">
                      {t('sampling.areaBasisTreeCoverDesc', { unit: labels.unitLabelLower })}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      {t('sampling.areaBasisTreeCoverDesc2')}
                    </p>
                  </button>
                  <button
                    type="button"
                    onClick={() => setAreaBasis('full_area')}
                    className={`rounded-lg border p-4 text-left transition-colors ${
                      areaBasis === 'full_area'
                        ? 'border-green-500 bg-white ring-2 ring-green-200'
                        : 'border-gray-300 bg-transparent hover:border-gray-400'
                    }`}
                  >
                    <div className="font-medium text-gray-900">🗺️ {t('sampling.areaBasisFull', { unit: labels.unitLabel })}</div>
                    <p className="text-sm text-gray-600 mt-1">
                      {t('sampling.areaBasisFullDesc', { unit: labels.unitLabelLower })}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      {t('sampling.areaBasisFullDesc2')}
                    </p>
                  </button>
                </div>
              </div>

              {/* Filter Summary */}
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <div className="text-xs text-gray-700">
                  <span className="font-semibold">{t('sampling.activeFilters')}:</span>
                  {filterTreeCover && (
                    <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
                      {t('sampling.filterTreeCover')}
                    </span>
                  )}
                  {!filterTreeCover && (
                    <span className="ml-2 text-gray-500">{t('sampling.filterFullArea', { unit: labels.unitLabel })}</span>
                  )}
                </div>
              </div>

              {/* Preview Button */}
              {filterTreeCover && (
                <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4">
                  <h5 className="text-sm font-semibold text-yellow-900 mb-2">
                    📊 {t('sampling.previewClassificationTitle')}
                  </h5>
                  <p className="text-xs text-yellow-800 mb-3">
                    {t('sampling.previewClassificationBody')}
                  </p>
                  <button
                    onClick={handlePreviewForestAreas}
                    disabled={loadingPreview}
                    className="w-full bg-yellow-600 text-white px-4 py-2 rounded-md hover:bg-yellow-700 disabled:bg-gray-400 font-medium transition-colors"
                  >
                    {loadingPreview ? (
                      <span className="flex items-center justify-center gap-2">
                        <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span>{t('sampling.analyzingForestAreas')}</span>
                      </span>
                    ) : '🗺️ ' + t('sampling.previewAccessibleProtected')}
                  </button>
                  {!showPreview && (
                    <p className="text-xs text-gray-600 mt-2 text-center">
                      {t('sampling.skipPreviewHint')}
                    </p>
                  )}
                </div>
              )}

              {/* Preview Visualization */}
              {showPreview && previewData && (
                <div className="border-t pt-4 mt-4">
                  <div className="flex justify-between items-center mb-3">
                    <h4 className="text-md font-semibold text-gray-900">
                      {t('sampling.forestAreaPreview')}
                    </h4>
                    <button
                      onClick={() => setShowPreview(false)}
                      className="text-sm text-gray-600 hover:text-gray-800"
                    >
                      ✕ {t('common.hide')} {t('sampling.preview')}
                    </button>
                  </div>
                  <AccessibleForestPreview previewData={previewData} />
                </div>
              )}
            </div>

            {/* SFM stratum floor violation blocks both actions (SS-1.5) — the
                backend rejects it anyway, this is the pre-round-trip message. */}
            {hasStratumFloorViolation && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
                {t('sampling.stratumFloorViolationBanner')}
              </div>
            )}

            {/* Buttons */}
            <div className="flex gap-2 sampling-action-bar">
              <button
                onClick={handlePreviewSamplePlots}
                disabled={loadingPlotPreview || hasStratumFloorViolation}
                className="flex-1 bg-yellow-600 text-white px-4 py-2 rounded-md hover:bg-yellow-700 disabled:bg-gray-400"
              >
                {loadingPlotPreview ? t('sampling.previewing') : '📍 ' + t('sampling.previewSamplePlots')}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || hasStratumFloorViolation}
                className="flex-1 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:bg-gray-400"
              >
                {creating ? t('sampling.creating') : t('sampling.createDesignConfirm')}
              </button>
              <button
                onClick={() => setShowCreateForm(false)}
                className="px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50"
              >
                {t('common.cancel')}
              </button>
            </div>

            {/* Phase F — Sample Plot Preview Visualization */}
            {showPlotPreview && samplePlotPreview && samplePlotPreview.sampling_points_geojson && (
              <div className="mt-4 border-t pt-4">
                <div className="flex justify-between items-center mb-3">
                  <h4 className="text-md font-semibold text-gray-900">
                    📍 {t('sampling.samplePlotPreview')}
                  </h4>
                  <button
                    onClick={() => setShowPlotPreview(false)}
                    className="text-sm text-gray-600 hover:text-gray-800"
                  >
                    ✕ {t('common.hide')} {t('sampling.preview')}
                  </button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 bg-yellow-50 border border-yellow-300 rounded-lg p-4">
                  <div>
                    <div className="text-sm text-gray-600">{t('sampling.totalPoints')}</div>
                    <div className="text-xl font-bold">
                      {samplePlotPreview.total_points}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-gray-600">{t('sampling.totalUnits', { unit: unitLabelPlural })}</div>
                    <div className="text-xl font-bold">
                      {samplePlotPreview.total_blocks}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-gray-600">{t('sampling.requestedIntensity')}</div>
                    <div className="text-xl font-bold">
                      {samplePlotPreview.requested_intensity_percent}%
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-gray-600">{t('sampling.actualSampling')}</div>
                    <div className="text-xl font-bold">
                      {parseFloat(samplePlotPreview.sampling_percentage || 0).toFixed(2)}%
                    </div>
                  </div>
                </div>
                <SamplingMapView
                  preview={{
                    calculation_id: samplePlotPreview.calculation_id,
                    boundary_layer: samplePlotPreview.boundary_layer,
                    forest_blocks_layer: samplePlotPreview.forest_blocks_layer,
                    filter_settings: samplePlotPreview.filter_settings,
                    sampling_points_geojson: samplePlotPreview.sampling_points_geojson,
                  }}
                  defaultShowAccessible={samplePlotPreview.filter_settings?.filter_tree_cover !== false}
                  blockStratumByName={buildStratumMap(unitRows.map((r) => ({ block_name: r.name, stratum: r.stratum })))}
                />
                <p className="mt-2 text-xs text-gray-500">
                  {t('sampling.exactPlotLocations')}
                </p>
              </div>
            )}
          </div>

          {error && (
            <div className="mt-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}
        </div>
      )}

      {/* Success Summary */}
      {successResult && (
        <div className="bg-white rounded-lg shadow-lg p-6">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold text-green-700">
              ✓ {t('sampling.designCreatedSuccess')}
            </h3>
          </div>

          {/* Summary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 bg-green-50 border border-green-200 rounded-lg p-4">
            <div>
              <div className="text-sm text-gray-600">{t('sampling.totalPoints')} <VarHint name="sampling_total_points" /></div>
              <div className="text-xl font-bold">{successResult.total_points}</div>
            </div>
            <div>
              <div className="text-sm text-gray-600">{t('sampling.totalUnits', { unit: unitLabelPlural })} <VarHint name="sampling_total_blocks" /></div>
              <div className="text-xl font-bold">{successResult.total_blocks}</div>
            </div>
            <div>
              <div className="text-sm text-gray-600">{t('sampling.requestedIntensity')} <VarHint name="sampling_requested_intensity" /></div>
              <div className="text-xl font-bold">{successResult.requested_intensity_percent}%</div>
            </div>
            <div>
              <div className="text-sm text-gray-600">{t('sampling.actualSampling')} <VarHint name="sampling_actual_intensity" /></div>
              <div className="text-xl font-bold">
                {parseFloat(successResult.sampling_percentage || 0).toFixed(2)}%
              </div>
            </div>
          </div>

          {/* Low tree-cover coverage warning (Phase D.2) — only relevant for Tree Cover basis */}
          {(() => {
            // Only warn when the basis is KNOWN to be tree cover. This read
            // `designs[0]?.default_parameters` and defaulted to true when that
            // was not loaded yet, so a full-area design could show a
            // tree-cover warning for one render -- `designs` refreshes after
            // the summary appears, not with it. `successTreeCoverBasis` is set
            // at the same moment as `successResult`, from the same design.
            if (successTreeCoverBasis !== true) return null;
            const lowCoverageUnits = (successResult.blocks_info || []).filter((b: any) => {
              const area = parseFloat(b.block_area_hectares) || 0;
              const accessible = parseFloat(b.accessible_forest_area_ha) || 0;
              if (!(area > 0)) return false;
              // Raster pixel area can slightly exceed the authoritative polygon area — clamp
              const coverage = Math.min(accessible / area, 1);
              return coverage < 0.2;
            });
            if (lowCoverageUnits.length === 0) return null;
            const total = successResult.blocks_info.length;
            const names = lowCoverageUnits
              .slice(0, 5)
              .map((b: any) => unitDisplayName(b.block_name))
              .filter(Boolean)
              .join(', ');
            return (
              <div className="mt-6 bg-yellow-50 border border-yellow-300 rounded-lg p-4">
                <h4 className="text-sm font-semibold text-yellow-900 mb-2">
                  ⚠️ {t('sampling.lowTreeCoverage')}
                </h4>
                <p className="text-sm text-yellow-800">
                  {t('sampling.lowTreeCoverageBody', {
                    count: lowCoverageUnits.length,
                    total,
                    unit: unitLabelPlural,
                    names,
                    unitCap: unitLabel,
                  })}
                </p>
              </div>
            );
          })()}

          {/* Protected Area Preview */}
          {successResult.blocks_info && successResult.blocks_info.some((b: any) => b.protected_area_ha > 0) && (
            <div className="mt-6 bg-purple-50 border border-purple-200 rounded-lg p-4">
              <h4 className="text-md font-semibold text-purple-800 mb-3 flex items-center gap-2">
                <span className="text-lg">🛡️</span> {t('sampling.protectedAreaPreview')}
              </h4>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="bg-white rounded p-3 shadow-sm">
                  <div className="text-xs text-gray-500 uppercase">{t('sampling.totalProtectedArea')}</div>
                  <div className="text-lg font-semibold text-purple-700">
                    {successResult.blocks_info
                      .reduce((sum: number, b: any) => sum + (parseFloat(b.protected_area_ha) || 0), 0)
                      .toFixed(4)} ha
                  </div>
                </div>
                <div className="bg-white rounded p-3 shadow-sm">
                  <div className="text-xs text-gray-500 uppercase">{t('sampling.unitsWithProtectedArea', { unit: unitLabelPlural })}</div>
                  <div className="text-lg font-semibold text-purple-700">
                    {successResult.blocks_info.filter((b: any) => b.protected_area_ha > 0).length}
                  </div>
                </div>
                <div className="bg-white rounded p-3 shadow-sm">
                  <div className="text-xs text-gray-500 uppercase">{t('sampling.protectedSamples')}</div>
                  <div className="text-lg font-semibold text-purple-700">
                    {successResult.blocks_info
                      .reduce((sum: number, b: any) => sum + (b.protected_samples_count || 0), 0)}
                  </div>
                </div>
                <div className="bg-white rounded p-3 shadow-sm">
                  <div className="text-xs text-gray-500 uppercase">{t('sampling.protectedIntensity')}</div>
                  <div className="text-lg font-semibold text-purple-700">
                    {(() => {
                      const totalProtectedArea = successResult.blocks_info
                        .reduce((sum: number, b: any) => sum + (parseFloat(b.protected_area_ha) || 0), 0);
                      const totalProtectedSamples = successResult.blocks_info
                        .reduce((sum: number, b: any) => sum + (b.protected_samples_count || 0), 0);
                      if (totalProtectedArea > 0 && totalProtectedSamples > 0) {
                        const plotAreaHa = 0.01; // 100 sqm = 0.01 ha
                        const intensity = (totalProtectedSamples * plotAreaHa / totalProtectedArea) * 100;
                        return intensity.toFixed(4) + '%';
                      }
                      return '0.0000%';
                    })()}
                  </div>
                </div>
              </div>

              {/* Protected Area Details by {unitLabel} */}
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs border border-purple-200 rounded bg-white">
                  <thead className="bg-purple-100">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-purple-700">{t('sampling.unitNameHeader', { unit: unitLabel })}</th>
                      <th className="px-3 py-2 text-right font-medium text-purple-700">{t('sampling.protectedAreaHa')}</th>
                      <th className="px-3 py-2 text-right font-medium text-purple-700">{t('sampling.samplesShort')}</th>
                      <th className="px-3 py-2 text-center font-medium text-purple-700">{t('sampling.method')}</th>
                      <th className="px-3 py-2 text-right font-medium text-purple-700">{t('sampling.gridSpacingM')}</th>
                      <th className="px-3 py-2 text-right font-medium text-purple-700">{t('sampling.intensityPct')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-purple-100">
                    {successResult.blocks_info
                      .filter((b: any) => b.protected_area_ha > 0)
                      .map((block: any, index: number) => (
                        <tr key={index}>
                          <td className="px-3 py-2 font-medium text-gray-900">
                            {unitDisplayName(block.block_name)}
                          </td>
                          <td className="px-3 py-2 text-right text-gray-700">
                            {block.protected_area_ha ? parseFloat(block.protected_area_ha).toFixed(4) : '-'}
                          </td>
                          <td className="px-3 py-2 text-right font-semibold text-gray-900">
                            {block.protected_samples_count || 0}
                          </td>
                          <td className="px-3 py-2 text-center">
                            {block.protected_sampling_method ? (
                              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                                block.protected_sampling_method === 'random' 
                                  ? 'bg-yellow-100 text-yellow-800' 
                                  : 'bg-green-100 text-green-800'
                              }`}>
                                {block.protected_sampling_method === 'random' ? t('sampling.methodRandom') : t('sampling.methodSystematic')}
                              </span>
                            ) : '-'}
                          </td>
                          <td className="px-3 py-2 text-right text-gray-700">
                            {block.protected_grid_spacing_meters ? parseFloat(block.protected_grid_spacing_meters).toFixed(1) : '-'}
                          </td>
                          <td className="px-3 py-2 text-right text-gray-700">
                            {block.protected_intensity_percent ? parseFloat(block.protected_intensity_percent).toFixed(4) : '-'}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>

              {/* Productive vs Protected Summary */}
              <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-green-50 rounded p-3 border border-green-200">
                  <h5 className="text-sm font-semibold text-green-800 mb-2">🌲 {t('sampling.productiveZoneSummary')}</h5>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>{t('sampling.totalArea')}:</div>
                    <div className="text-right font-medium">
                      {successResult.blocks_info
                        .reduce((sum: number, b: any) => sum + (parseFloat(b.productive_area_ha) || 0), 0)
                        .toFixed(4)} ha
                    </div>
                    <div>{t('sampling.totalSamples')}:</div>
                    <div className="text-right font-medium">
                      {successResult.blocks_info
                        .reduce((sum: number, b: any) => sum + (b.productive_samples_count || 0), 0)}
                    </div>
                    <div>{t('sampling.method')}:</div>
                    <div className="text-right">
                      {successResult.blocks_info.some((b: any) => b.productive_sampling_method === 'random') ? (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-yellow-100 text-yellow-800">{t('sampling.methodRandomFallback')}</span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-800">{t('sampling.methodSystematic')}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="bg-purple-50 rounded p-3 border border-purple-200">
                  <h5 className="text-sm font-semibold text-purple-800 mb-2">🛡️ {t('sampling.protectedZoneSummary')}</h5>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>{t('sampling.totalArea')}:</div>
                    <div className="text-right font-medium">
                      {successResult.blocks_info
                        .reduce((sum: number, b: any) => sum + (parseFloat(b.protected_area_ha) || 0), 0)
                        .toFixed(4)} ha
                    </div>
                    <div>{t('sampling.totalSamples')}:</div>
                    <div className="text-right font-medium">
                      {successResult.blocks_info
                        .reduce((sum: number, b: any) => sum + (b.protected_samples_count || 0), 0)}
                    </div>
                    <div>{t('sampling.method')}:</div>
                    <div className="text-right">
                      {successResult.blocks_info.some((b: any) => b.protected_sampling_method === 'random') ? (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-yellow-100 text-yellow-800">{t('sampling.methodRandomFallback')}</span>
                      ) : successResult.blocks_info.some((b: any) => b.protected_sampling_method === 'systematic') ? (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-800">{t('sampling.methodSystematic')}</span>
                      ) : (
                        <span className="text-gray-500">-</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Per-Block Summary Table */}
          {successResult.blocks_info && successResult.blocks_info.length > 0 && (
            <div>
              <h4 className="text-md font-semibold mb-3">{t('sampling.perUnitSummary', { unit: unitLabel })} <VarHint name="sampling_block_summary" /></h4>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 border border-gray-200 rounded-lg">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.unitNameHeader', { unit: unitLabel })}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.stratumTableStratum')}</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.landcoverHeader')}</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('sampling.unitAreaHa', { unit: unitLabel })}</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('sampling.accessibleForestHa')}</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('sampling.protected')}</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('sampling.samplesShort')}</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('sampling.gridSpacingM')}</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('sampling.actualIntensityPct')}</th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">{t('sampling.method')}</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {successResult.blocks_info.map((block: any, index: number) => (
                      <tr key={index} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                        <td className="px-4 py-2 text-sm font-medium text-gray-900">
                          {unitDisplayName(block.block_name) || `${unitLabel} ${index + 1}`}
                          {block.minimum_enforced && (
                            <span className="ml-2 text-xs text-yellow-600" title={t('sampling.minimumSamplesEnforced')}>⚠️</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700">
                          {block.stratum ? t(STRATUM_LABEL_KEY[block.stratum] ?? block.stratum) : '-'}
                        </td>
                        {landCoverCell(block.block_name, 'px-4 py-2 text-sm text-gray-700')}
                        <td className="px-4 py-2 text-sm text-gray-700 text-right">
                          {block.block_area_hectares ? parseFloat(block.block_area_hectares).toFixed(4) : '-'}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700 text-right">
                          {block.accessible_forest_area_ha ? parseFloat(block.accessible_forest_area_ha).toFixed(4) : '-'}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700 text-right">
                          {typeof block.is_protected === 'string' ? block.is_protected : (block.is_protected ? t('common.yes') : t('common.no'))}
                        </td>
                        <td className="px-4 py-2 text-sm font-semibold text-gray-900 text-right">
                          {block.samples_generated}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700 text-right">
                          {block.grid_spacing_meters ? parseFloat(block.grid_spacing_meters).toFixed(1) : '-'}
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-700 text-right">
                          {block.actual_intensity_percent ? parseFloat(block.actual_intensity_percent).toFixed(4) : '-'}
                        </td>
                        <td className="px-4 py-2 text-sm text-center">
                          <span className={`px-2 py-1 rounded text-xs font-medium ${
                            block.sampling_method === 'random' 
                              ? 'bg-yellow-100 text-yellow-800' 
                              : 'bg-green-100 text-green-800'
                          }`} title={block.sampling_method === 'random' ? t('sampling.randomFallbackUsed') : t('sampling.systematicGridTitle')}>
                            {block.sampling_method === 'random' ? t('sampling.methodRandom') : t('sampling.methodSystematic')}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-gray-100">
                    <tr>
                      <td className="px-4 py-2 text-sm font-bold text-gray-900" colSpan={3}>{t('sampling.total')}</td>
                      <td className="px-4 py-2 text-sm font-bold text-gray-900 text-right">
                        {successResult.blocks_info.reduce((sum: number, b: any) => sum + (parseFloat(b.block_area_hectares) || 0), 0).toFixed(4)}
                      </td>
                      <td className="px-4 py-2 text-sm font-bold text-gray-900 text-right">
                        {successResult.blocks_info.reduce((sum: number, b: any) => sum + (parseFloat(b.accessible_forest_area_ha) || 0), 0).toFixed(4)}
                      </td>
                      <td className="px-4 py-2 text-sm font-bold text-gray-900 text-right">-</td>
                      <td className="px-4 py-2 text-sm font-bold text-gray-900 text-right">
                        {successResult.blocks_info.reduce((sum: number, b: any) => sum + (b.samples_generated || 0), 0)}
                      </td>
                      <td className="px-4 py-2 text-right">-</td>
                      <td className="px-4 py-2 text-sm font-bold text-gray-900 text-right">
                        {parseFloat(successResult.sampling_percentage || 0).toFixed(4)}
                      </td>
                      <td className="px-4 py-2 text-right">-</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}

        </div>
      )}

      {/* Later rounds: sample more polygons into the design that exists, or free a polygon by deleting its plots */}
      {designs.length > 0 && !showCreateForm && unitRows.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6" data-testid="sampling-add-round">
          <h3 className="text-lg font-semibold">{t('sampling.unitTable.roundTitle', { defaultValue: 'Sample more polygons' })}</h3>
          <p className="text-sm text-gray-600 mt-1 mb-3">
            {t('sampling.unitTable.roundHint', {
              defaultValue: 'Tick the polygons that have no plots yet and add their plots to this design. Existing plots do not move. A polygon that already has plots can be sampled again only after its plots are deleted.',
            })}
          </p>
          {unitTableElement}
          <div className="mt-4">
            <button
              type="button"
              onClick={handleAddRound}
              disabled={addingRound || hasStratumFloorViolation || unitRows.every((r) => r.sampled_plots > 0) || !!unitPlan?.field_data_exists}
              title={unitPlan?.field_data_exists ? t('sampling.unitTable.addLocked', { defaultValue: 'Field inventory data exists for this forest, so plots can no longer be added. Delete the field inventory first.' }) : undefined}
              className="px-4 py-2 bg-emerald-600 text-white rounded-md hover:bg-emerald-700 disabled:opacity-50"
              data-testid="sampling-add-round-button"
            >
              {addingRound ? t('sampling.unitTable.adding', { defaultValue: 'Adding…' }) : t('sampling.unitTable.addPlots', { defaultValue: 'Add plots for the ticked polygons' })}
            </button>
          </div>
        </div>
      )}

      {/* Designs List */}
      {designs.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-semibold">{t('sampling.designsTitleCount', { count: designs.length })}</h3>
          </div>
          <div className="divide-y divide-gray-200">
            {designs.map((design) => (
              <div key={design.id} className="p-6">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`px-3 py-1 rounded text-sm font-medium ${
                        design.sampling_type === 'systematic'
                          ? 'bg-blue-100 text-blue-800'
                          : 'bg-green-100 text-green-800'
                      }`}>
                        {design.sampling_type === 'random'
                          ? t('sampling.methodRandom')
                          : design.sampling_type === 'imported'
                            ? t('sampling.methodImported')
                            : t('sampling.methodSystematic')}
                      </span>
                      <span className="text-sm text-gray-600">
                        {formatDateTime(design.created_at, {
                          year: 'numeric', month: 'numeric', day: 'numeric',
                        })}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
                      <div>
                        <div className="text-gray-600">{t('sampling.totalPoints')} <VarHint name="sampling_total_points" /></div>
                        <div className="font-semibold">{design.total_points}</div>
                      </div>
                      {design.total_blocks && (
                        <div>
                          <div className="text-gray-600">{t('sampling.totalUnits', { unit: unitLabelPlural })} <VarHint name="sampling_total_blocks" /></div>
                          <div className="font-semibold">{design.total_blocks}</div>
                        </div>
                      )}
                      {design.requested_intensity_percent && (
                        <div>
                          <div className="text-gray-600">{t('sampling.requestedIntensity')} <VarHint name="sampling_requested_intensity" /></div>
                          <div className="font-semibold">{design.requested_intensity_percent}%</div>
                        </div>
                      )}
                      {design.plot_area_sqm && (
                        <div>
                          <div className="text-gray-600">{t('sampling.plotAreaLabel')} <VarHint name="sampling_plot_area_sqm" /></div>
                          <div className="font-semibold">{parseFloat(design.plot_area_sqm).toFixed(2)} m²</div>
                        </div>
                      )}
                    </div>

                    {/* Per-Block Summary Table */}
                    {design.blocks_info && design.blocks_info.length > 0 && (
                      <div className="mt-4 border-t pt-4">
                        <h4 className="text-sm font-semibold text-gray-700 mb-3">{t('sampling.perUnitSummary', { unit: unitLabel })}: <VarHint name="sampling_block_summary" /></h4>
                        <div className="overflow-x-auto">
                          <table className="min-w-full text-xs border border-gray-200 rounded">
                            <thead className="bg-gray-50">
                              <tr>
                                <th className="px-2 py-2 text-left font-medium text-gray-600">{t('sampling.unitNameHeader', { unit: unitLabel })}</th>
                                <th className="px-2 py-2 text-left font-medium text-gray-600">{t('sampling.stratumTableStratum')}</th>
                                <th className="px-2 py-2 text-left font-medium text-gray-600">{t('sampling.landcoverHeader')}</th>
                                <th className="px-2 py-2 text-right font-medium text-gray-600">{t('sampling.areaHa')}</th>
                                <th className="px-2 py-2 text-right font-medium text-gray-600">{t('sampling.accessibleHa')}</th>
                                <th className="px-2 py-2 text-center font-medium text-gray-600">{t('sampling.protectedHeader')}</th>
                                <th className="px-2 py-2 text-right font-medium text-gray-600">{t('sampling.samplesHeader')}</th>
                                <th className="px-2 py-2 text-right font-medium text-gray-600">{t('sampling.spacingMeters')}</th>
                                <th className="px-2 py-2 text-right font-medium text-gray-600">{t('sampling.intensityPct')}</th>
                                <th className="px-2 py-2 text-center font-medium text-gray-600">{t('sampling.methodHeader')}</th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-100">
                              {design.blocks_info.map((block: any, idx: number) => (
                                <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                  <td className="px-2 py-2 font-medium text-gray-900">
                                    {unitDisplayName(block.block_name)}
                                    {block.minimum_enforced && (
                                      <span className="ml-1 text-yellow-600" title={t('sampling.minimumEnforced')}>⚠️</span>
                                    )}
                                  </td>
                                  <td className="px-2 py-2 text-gray-700">
                                    {block.stratum ? t(STRATUM_LABEL_KEY[block.stratum] ?? block.stratum) : '-'}
                                  </td>
                                  {landCoverCell(block.block_name, 'px-2 py-2 text-gray-700')}
                                  <td className="px-2 py-2 text-right text-gray-700">
                                    {block.block_area_hectares ? parseFloat(block.block_area_hectares).toFixed(4) : '-'}
                                  </td>
                                  <td className="px-2 py-2 text-right text-gray-700">
                                    {block.accessible_forest_area_ha ? parseFloat(block.accessible_forest_area_ha).toFixed(4) : '-'}
                                  </td>
                                  <td className="px-2 py-2 text-center text-gray-700">
                                    {typeof block.is_protected === 'string' ? block.is_protected : (block.is_protected ? t('common.yes') : (block.is_protected === false ? t('common.no') : '-'))}
                                  </td>
                                  <td className="px-2 py-2 text-right font-semibold text-gray-900">
                                    {block.samples_generated}
                                  </td>
                                  <td className="px-2 py-2 text-right text-gray-700">
                                    {block.grid_spacing_meters ? parseFloat(block.grid_spacing_meters).toFixed(1) : '-'}
                                  </td>
                                  <td className="px-2 py-2 text-right text-gray-700">
                                    {block.actual_intensity_percent ? parseFloat(block.actual_intensity_percent).toFixed(4) : '-'}
                                  </td>
                                  <td className="px-2 py-2 text-center">
                                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                                      block.sampling_method === 'random' 
                                        ? 'bg-yellow-100 text-yellow-800' 
                                        : 'bg-green-100 text-green-800'
                                    }`}>
                                      {block.sampling_method === 'random' ? t('sampling.methodRandom') : t('sampling.methodSystematic')}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                            <tfoot className="bg-gray-100">
                              <tr className="font-semibold">
                                <td className="px-2 py-2 text-gray-900" colSpan={3}>{t('sampling.total')}</td>
                                <td className="px-2 py-2 text-right text-gray-900">
                                  {design.blocks_info.reduce((sum: number, b: any) => sum + (parseFloat(b.block_area_hectares) || 0), 0).toFixed(4)}
                                </td>
                                <td className="px-2 py-2 text-right text-gray-900">
                                  {design.blocks_info.reduce((sum: number, b: any) => sum + (parseFloat(b.accessible_forest_area_ha) || 0), 0).toFixed(4)}
                                </td>
                                <td className="px-2 py-2 text-center text-gray-900">-</td>
                                <td className="px-2 py-2 text-right text-gray-900">
                                  {design.blocks_info.reduce((sum: number, b: any) => sum + (b.samples_generated || 0), 0)}
                                </td>
                                <td className="px-2 py-2 text-right text-gray-900">-</td>
                                <td className="px-2 py-2 text-right text-gray-900">
                                  {design.sampling_percentage ? parseFloat(design.sampling_percentage).toFixed(4) : '-'}
                                </td>
                                <td className="px-2 py-2 text-center text-gray-900">-</td>
                              </tr>
                            </tfoot>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => handleDelete(design.id)}
                    className="text-red-600 hover:text-red-800 text-sm"
                  >
                    {t('common.delete')}
                  </button>
                </div>

                <div className="space-y-2">
                  {/* Navigation Support Options */}
                  <div className="bg-gray-50 border border-gray-200 rounded p-3 mb-2">
                    <div className="text-xs font-semibold text-gray-700 mb-2">{t('sampling.navigationSupport')}</div>
                    <div className="flex gap-4 text-sm">
                      <label className="flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          checked={includeElevation}
                          onChange={(e) => {
                            setIncludeElevation(e.target.checked);
                            setTimeout(() => loadSamplingPoints(design.id), 100);
                          }}
                          className="mr-2 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                        />
                        <span className="text-gray-700">{t('sampling.elevationAslm')}</span>
                      </label>
                      <label className="flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          checked={includeTopoFeatures}
                          onChange={(e) => {
                            setIncludeTopoFeatures(e.target.checked);
                            setTimeout(() => loadSamplingPoints(design.id), 100);
                          }}
                          className="mr-2 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                        />
                        <span className="text-gray-700">{t('sampling.nearestRidgeValley')}</span>
                      </label>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {t('sampling.navigationHint')}
                    </p>
                  </div>

                  {/* Export Buttons */}
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleExport(design.id, 'csv')}
                      className="flex-1 bg-green-600 text-white px-3 py-1.5 rounded text-sm hover:bg-green-700"
                    >
                      CSV
                    </button>
                    <button
                      onClick={() => handleExport(design.id, 'geojson')}
                      className="flex-1 bg-green-600 text-white px-3 py-1.5 rounded text-sm hover:bg-green-700"
                    >
                      GeoJSON
                    </button>
                    <button
                      onClick={() => handleExport(design.id, 'gpx')}
                      className="flex-1 bg-green-600 text-white px-3 py-1.5 rounded text-sm hover:bg-green-700"
                    >
                      GPX
                    </button>
                    <button
                      onClick={() => handleExport(design.id, 'kml')}
                      className="flex-1 bg-green-600 text-white px-3 py-1.5 rounded text-sm hover:bg-green-700"
                    >
                      KML
                    </button>
                  </div>
                </div>

                {/* Sampling Points Table */}
                {samplingPoints.length > 0 && (
                  <div className="mt-6 border-t pt-6">
                    <div className="flex justify-between items-center mb-4">
                      <h4 className="text-md font-semibold text-gray-700">
                        {t('sampling.samplingPoints', { count: samplingPoints.length })} <VarHint name="sampling_point_locations" />
                      </h4>
                    </div>

                    {loadingPoints ? (
                      <div className="text-center py-8 text-gray-600">{t('sampling.loadingPoints')}</div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.plotNum')}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{unitLabel}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.zoneHeader')}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.sfmStratumHeader')}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.longitudeHeader')}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.latitudeHeader')}</th>
                              {includeElevation && samplingPoints.some(p => p.elevation_m !== undefined) && (
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase bg-blue-50">
                                  {t('sampling.elevationHeader')}
                                </th>
                              )}
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.utmEastingHeader')}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.utmNorthingHeader')}</th>
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.utmZoneHeader')}</th>
                              {includeTopoFeatures && samplingPoints.some(p => p.topographic_context) && (
                                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase bg-green-50">
                                  {t('sampling.nearestRidgeValleyHeader')}
                                </th>
                              )}
                              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('sampling.distanceFromBoundaryHeader')}</th>
                            </tr>
                          </thead>
                          <tbody className="bg-white divide-y divide-gray-200">
                            {samplingPoints.map((point: any) => (
                              <tr key={point.id} className="hover:bg-gray-50">
                                <td className="px-4 py-2 text-sm font-mono">P{point.plot_number}</td>
                                <td className="px-4 py-2 text-sm">
                                  <span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs font-medium">
                                    {unitDisplayName(point.block_name) || `${unitLabel} ${point.block_number}`}
                                  </span>
                                </td>
                                <td className="px-4 py-2 text-sm">
                                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                                    point.zone_type === 'protected' 
                                      ? 'bg-red-100 text-red-800' 
                                      : 'bg-blue-100 text-blue-800'
                                  }`}>
                                    {point.zone_type === 'protected' ? t('sampling.protected') : t('sampling.productive')}
                                  </span>
                                </td>
                                <td className="px-4 py-2 text-sm text-gray-700">
                                  {(() => {
                                    const stratum = blockStratumByName[point.block_name];
                                    return stratum ? t(STRATUM_LABEL_KEY[stratum] ?? stratum) : '-';
                                  })()}
                                </td>
                                <td className="px-4 py-2 text-sm font-mono">{parseFloat(point.longitude).toFixed(7)}</td>
                                <td className="px-4 py-2 text-sm font-mono">{parseFloat(point.latitude).toFixed(7)}</td>
                                {includeElevation && samplingPoints.some(p => p.elevation_m !== undefined) && (
                                  <td className="px-4 py-2 text-sm font-semibold bg-blue-50">
                                    {point.elevation_m ? `${point.elevation_m}m` : t('sampling.na')}
                                  </td>
                                )}
                                <td className="px-4 py-2 text-sm font-mono">{point.utm_easting ? parseFloat(point.utm_easting).toFixed(2) : t('sampling.na')}</td>
                                <td className="px-4 py-2 text-sm font-mono">{point.utm_northing ? parseFloat(point.utm_northing).toFixed(2) : t('sampling.na')}</td>
                                <td className="px-4 py-2 text-sm">{point.utm_zone || t('sampling.na')}</td>
                                {includeTopoFeatures && samplingPoints.some(p => p.topographic_context) && (
                                  <td className="px-4 py-2 text-sm bg-green-50" title={point.nearest_feature_type ? `${point.nearest_feature_type} at bearing ${point.nearest_feature_bearing}°` : undefined}>
                                    {point.topographic_context || t('sampling.na')}
                                  </td>
                                )}
                                <td className="px-4 py-2 text-sm">{point.distance_from_boundary ? parseFloat(point.distance_from_boundary).toFixed(2) : t('sampling.na')}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* OP Document Map Variables — insert into template near here */}
                    <div className="mt-8 bg-blue-50 rounded-lg p-3 border border-blue-200">
                      <div className="text-sm font-semibold text-blue-800 mb-2">
                        📋 नक्सा भेरिएबलहरू / Map Variables
                      </div>
                      <div className="flex flex-wrap gap-1">
                        <VarHint name="map:sampling_plot" />
                        <VarHint name="map:sampling_plot_topo" />
                        <VarHint name="map:sampling_plot_satellite" />
                      </div>
                      <div className="text-[10px] text-blue-600 mt-1">
                        {t('sampling.clickToCopyHint')}
                      </div>
                    </div>

                    {/* Interactive Map Visualization */}
                    <div className="mt-8">
                      <h4 className="text-md font-semibold text-gray-700 mb-4">
                        {t('sampling.interactiveMapTitle')}
                      </h4>
                      <div className="bg-gray-50 rounded-lg p-3 mb-4 border border-gray-200">
                        <div className="text-sm text-gray-700">
                          <strong>{t('sampling.mapFeaturesHeader')}:</strong>
                          <ul className="list-disc list-inside mt-1 text-xs text-gray-600 space-y-1">
                            <li>{t('sampling.mapFeatureSatellite')}</li>
                            <li>{t('sampling.mapFeatureBoundary')}</li>
                            {design.default_parameters && design.default_parameters.filter_tree_cover && (
                              <li>{t('sampling.mapFeatureAccessible')}</li>
                            )}
                            <li>{t('sampling.mapFeatureSamplePlots')}</li>
                            <li>{t('sampling.mapFeatureNorthArrow')}</li>
                            <li>{t('sampling.mapFeatureScaleBar')}</li>
                          </ul>
                        </div>
                      </div>
                      <SamplingMapView
                        designId={design.id}
                        defaultShowAccessible={design.default_parameters?.filter_tree_cover !== false}
                        blockStratumByName={buildStratumMap(design.blocks_info)}
                        // The enriched per-point fields (elevation/UTM/topo/distance-
                        // from-boundary) are only cached client-side for the most
                        // recently loaded design -- see loadSamplingPoints.
                        points={design.id === designs[0]?.id ? samplingPoints : undefined}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {designs.length === 0 && !showCreateForm && (
        <div className="bg-white rounded-lg shadow p-12 text-center text-gray-500">
          {t('sampling.designsEmpty')}
        </div>
      )}

      {/*
        P8 tier 1 - unit size review. Sits at the END of the page, below the design
        list, on purpose: it is the *prevention* half of a defect that otherwise
        surfaces much later on the field-inventory page, and putting it at the top
        would lead a page whose job is designing a sampling scheme with a warning
        about unit sizes. Collapsed, because most forests have nothing to say.
      */}
      {designs.length === 0 && (
        <UnitSizeReviewPanel calculationId={calculationId} />
      )}
    </div>
  );
}
