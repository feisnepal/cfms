/**
 * Field inventory data, lifted out of the component so it can outlive a pane.
 *
 * WORKSPACE_FLOW_NAV_PLAN P5d splits Field Inventory into Upload Data / Forest
 * Metadata / Results. `ContextTabHost` mounts one pane at a time — that is what
 * stops two panes holding two copies of the same data — so anything the panes
 * share has to live above the host. That is what this module is: the shared
 * state, the effects that load it, and the handlers that change it, exposed
 * through a context the group provider mounts once.
 *
 * Nothing here renders. The component keeps the guards and the markup, and reads
 * everything else from `useFieldInventoryData()`.
 */
import { onDataImported } from '../../lib/uploadEvents';
import { autoMapFieldInventoryColumns } from '../../lib/fieldInventoryAutoMapping';
import { findingsFromError, type UploadFinding } from '../../lib/uploadFindings';
import React, { createContext, useContext, useState } from 'react';
import { fieldInventoryApi, forestApi } from '../../services/api';
import { downloadFromApi, downloadBlob } from '../../utils/download';
import { useDimensionLabels } from '../../hooks/useDimensionLabels';
import { readDetail } from '../../hooks/useErrorHandler';
import { useT } from '../../i18n/hooks';

/** Per-unit effective-forest-area row returned by the tree-cover calculation. */
export interface TreeCoverArea {
  block_name: string;
  total_area_ha: number;
  effective_area_ha: number;
  tree_cover_percentage: number;
  tree_pixels: number;
  total_pixels: number;
  tree_cover_ratio: number;
}

/** Editable economic rates (NPR) for one unit. */
export interface BlockRates {
  timber: number;
  fuelwood: number;
  carbon: number;
}

export interface FieldInventoryData {
  // --- loaded records
  fieldInventory: any;
  summary: any;
  speciesBreakdown: any;
  maiAahData: any;
  hasCompartments: boolean;
  loading: boolean;
  initialized: boolean;

  // --- total-inventory / per-species-DBH data (Results)
  speciesDbhData: any[] | null;
  speciesDbhForestWide: any[] | null;
  totalData: any;
  blockAreas: Record<string, number>;
  treeCoverAreas: Record<string, TreeCoverArea>;
  /** each unit's own polygon (geometric) area in ha, from block-area-detail; the effective area is always smaller */
  polygonAreas: Record<string, number>;
  treeCoverLoading: boolean;
  treeCoverError: string | null;
  totalsLoading: boolean;
  blockRates: Record<string, BlockRates>;
  setBlockRates: React.Dispatch<React.SetStateAction<Record<string, BlockRates>>>;

  // --- upload / mutation state
  file: File | null;
  uploading: boolean;
  processing: boolean;
  deleting: boolean;
  validationResult: any;
  error: string | null;
  uploadFindings: UploadFinding[] | null;
  componentError: string | null;

  // --- configuration the user can edit
  sampleSizes: {
    regeneration_area_sqm: number;
    sapling_area_sqm: number;
    pole_area_sqm: number;
    tree_area_sqm: number;
  };
  setSampleSizes: React.Dispatch<React.SetStateAction<FieldInventoryData['sampleSizes']>>;
  aahMultipliers: { good: number; moderate: number; weak: number };
  setAahMultipliers: React.Dispatch<React.SetStateAction<FieldInventoryData['aahMultipliers']>>;
  customMultipliers: Record<string, number>;
  setCustomMultipliers: React.Dispatch<React.SetStateAction<Record<string, number>>>;
  setMaiAahData: React.Dispatch<React.SetStateAction<any>>;
  setEditingValue: React.Dispatch<React.SetStateAction<string>>;

  // --- inline / modal multiplier editing
  editingBlock: string | null;
  editingValue: string;
  handleStartInlineEdit: (blockName: string, currentValue: number) => void;
  handleSaveInlineEdit: (blockName: string) => Promise<void>;
  handleCancelInlineEdit: () => void;
  modalBlock: any | null;
  handleOpenModal: (block: any) => void;
  handleCloseModal: () => void;
  handleSaveModal: (multiplier: number) => Promise<void>;

  // --- actions
  checkFieldInventory: () => Promise<void>;
  handleFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleUpload: () => Promise<void>;
  handleProcess: (inventoryId: string, fileToProcess: File) => Promise<void>;
  handleExportExcel: () => Promise<void>;
  handleDfoExport: () => Promise<void>;
  /** `confirmText` replaces the standard confirmation (the Replace button names the file it replaces) */
  handleDelete: (confirmText?: string) => Promise<void>;

  // --- error recovery
  setComponentError: React.Dispatch<React.SetStateAction<string | null>>;
  setFieldInventory: React.Dispatch<React.SetStateAction<any>>;
  setInitialized: React.Dispatch<React.SetStateAction<boolean>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;

  /**
   * Load the field-inventory record, once, if it has not been loaded already.
   *
   * This exists because the provider is mounted for the whole *step* while the
   * host mounts one *pane* at a time, and the third pane in this group (Forest
   * Metadata, D5) has no field inventory to read. Loading eagerly on mount
   * therefore made opening Metadata fire two requests and set state nothing
   * there would ever read. Pane bodies that do need the record call this on
   * mount; the second one to mount is a no-op, so Data -> Results still costs
   * one fetch and the shared state (the chosen file, edited multipliers)
   * still survives the switch.
   */
  ensureLoaded: () => void;

  /**
   * Load the Results-only data (tree cover, effective areas, total inventory),
   * once per calculation, and recompute the totals whenever the AAH thresholds
   * or the per-unit multipliers change.
   *
   * Results is the only consumer of these, so they are not part of
   * `ensureLoaded`: the Data pane and Forest Metadata must not pay for a
   * tree-cover raster calculation they never read.
   */
  ensureResultsLoaded: () => void;
  /**
   * Re-fetch tree cover + effective areas (the error state's retry button).
   * Resolves to the effective areas it stored, or null when the calculation has
   * none — the totals call needs them immediately after, and reading them back
   * out of state would mean reading a stale closure.
   */
  loadTreeCoverAreas: () => Promise<Record<string, number> | null>;
  /** Recompute the total inventory. `showAlerts` surfaces failures to the user. */
  handleCalculateTotals: (showAlerts?: boolean) => Promise<void>;

  // --- display helpers
  labels: ReturnType<typeof useDimensionLabels>;
  displayBlockName: (name: string) => string;
  /** The forest's name, as the provider was configured with it. */
  forestName: string;
}

const FieldInventoryDataContext = createContext<FieldInventoryData | null>(null);

/**
 * The whole of Field Inventory's state, effects and handlers.
 *
 * `blocks` and `forestName` are inputs the component used to take as props; they
 * are passed in here so the provider and the pane cannot disagree about them.
 */
export function useFieldInventoryDataState(
  calculationId: string,
  blocks: any[] = [],
  forestName = 'Forest',
  /**
   * Called after a write that can change this step's readiness, so the shell
   * re-reads it. Optional so the hook still mounts in a test without one.
   */
  onStepDataChanged?: () => void,
): FieldInventoryData {
  const t = useT();

  const [fieldInventory, setFieldInventory] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [speciesBreakdown, setSpeciesBreakdown] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [validationResult, setValidationResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  // plain-language findings of a refused upload (what is wrong, where, how to fix); shown by the upload screen
  const [uploadFindings, setUploadFindings] = useState<UploadFinding[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [componentError, setComponentError] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);
  const [hasCompartments, setHasCompartments] = useState(false);
  const labels = useDimensionLabels({ hasCompartments });

  // Sample plot sizes (configurable)
  const [sampleSizes, setSampleSizes] = useState({
    regeneration_area_sqm: 10.0,
    sapling_area_sqm: 25.0,
    pole_area_sqm: 100.0,
    tree_area_sqm: 500.0,
  });

  // MAI and AAH data
  const [maiAahData, setMaiAahData] = useState<any>(null);
  const [aahMultipliers, setAahMultipliers] = useState({
    good: 75.0,
    moderate: 60.0,
    weak: 40.0,
  });

  // Custom multipliers per block (blockName -> multiplier percentage)
  const [customMultipliers, setCustomMultipliers] = useState<Record<string, number>>({});

  // Inline editing state
  const [editingBlock, setEditingBlock] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState<string>('');

  // Modal editing state
  const [modalBlock, setModalBlock] = useState<any | null>(null);

  // --- total-inventory data (Results only; see `ensureResultsLoaded`)
  const [speciesDbhData, setSpeciesDbhData] = useState<any[] | null>(null);
  const [speciesDbhForestWide, setSpeciesDbhForestWide] = useState<any[] | null>(null);
  const [blockAreas, setBlockAreas] = useState<Record<string, number>>({});
  const [treeCoverAreas, setTreeCoverAreas] = useState<Record<string, TreeCoverArea>>({});
  const [polygonAreas, setPolygonAreas] = useState<Record<string, number>>({});
  const [treeCoverLoading, setTreeCoverLoading] = useState(false);
  const [treeCoverError, setTreeCoverError] = useState<string | null>(null);
  const [totalData, setTotalData] = useState<any>(null);
  const [totalsLoading, setTotalsLoading] = useState(false);
  const [blockRates, setBlockRates] = useState<Record<string, BlockRates>>({});

  /**
   * Mirror of the loaded inventory id.
   *
   * `handleCalculateTotals` is reachable from a pane's mount effect, whose
   * closure still sees the `fieldInventory` of the render that mounted it --
   * i.e. `null`, because the record request has not resolved yet. Reading the id
   * from a ref is what lets the totals be calculated in the same pass that
   * starts the record load.
   */
  const inventoryIdRef = React.useRef<string | null>(null);

  const checkFieldInventory = async () => {
    try {
      setLoading(true);
      setComponentError(null);
      setError(null);

      console.log('Fetching field inventory for calculation:', calculationId);

      const inventory = await fieldInventoryApi.getByCalculation(calculationId);
      console.log('Field inventory found:', inventory);
      setFieldInventory(inventory);
      inventoryIdRef.current = inventory?.id ?? null;

      // Load summary and species breakdown if inventory exists
      if (inventory?.id) {
        try {
          console.log('Loading summary for inventory:', inventory.id);
          const summaryData = await fieldInventoryApi.getSummary(inventory.id);
          setSummary(summaryData);
        } catch (summaryErr: any) {
          console.warn('Failed to load summary:', summaryErr);
          setSummary(null);
        }

        try {
          console.log('Loading species breakdown for inventory:', inventory.id);
          const speciesData = await fieldInventoryApi.getSpeciesBreakdown(inventory.id);
          setSpeciesBreakdown(speciesData);
        } catch (speciesErr: any) {
          console.warn('Failed to load species breakdown:', speciesErr);
          setSpeciesBreakdown(null);
        }

        // Species x DBH class breakdown. Loaded with the record for the same
        // reason as `getSpeciesBreakdown` above: only the Results tables read
        // it, but it is one inventory-scoped GET and putting it here removes a
        // race with the pane that triggers the record load.
        try {
          console.log('Loading species/DBH breakdown for inventory:', inventory.id);
          const sdbh = await fieldInventoryApi.getSpeciesDbhBreakdown(inventory.id);
          setSpeciesDbhData(sdbh?.species_dbh_breakdown || []);
          setSpeciesDbhForestWide(sdbh?.species_dbh_forest_wide || []);
        } catch (sdbhErr: any) {
          console.warn('Failed to load species/DBH breakdown:', sdbhErr);
          setSpeciesDbhData(null);
          setSpeciesDbhForestWide(null);
        }

        try {
          console.log('Loading MAI/AAH data for inventory:', inventory.id);
          const maiAahResult = await fieldInventoryApi.getMaiAah(
            inventory.id,
            aahMultipliers.good,
            aahMultipliers.moderate,
            aahMultipliers.weak,
            Object.keys(customMultipliers).length > 0 ? customMultipliers : undefined
          );
          setMaiAahData(maiAahResult);
        } catch (maiErr: any) {
          console.warn('Failed to load MAI/AAH data:', maiErr);
          setMaiAahData(null);
        }
      }
      setInitialized(true);
    } catch (err: any) {
      console.error('Error in checkFieldInventory:', err);
      // 404 means no field inventory exists yet
      if (err?.response?.status === 404) {
        console.log('No field inventory found (404), showing upload interface');
        setFieldInventory(null);
        inventoryIdRef.current = null;
        setSummary(null);
        setSpeciesBreakdown(null);
        setSpeciesDbhData(null);
        setSpeciesDbhForestWide(null);
        setMaiAahData(null);
        setTotalData(null);
        setInitialized(true);
      } else {
        const errorMessage = readDetail(err?.response?.data?.detail, err?.response?.data?.correlation_id)
          || err?.message
          || t('fieldInventory.unknownError');
        console.error('Field inventory error:', errorMessage);
        setComponentError(`Failed to load field inventory: ${errorMessage}`);
        setInitialized(true);
      }
    } finally {
      setLoading(false);
    }
  };

  // The compartments flag decides which dimension vocabulary the tables use, so
  // it is part of the same lazy load as the record itself rather than a separate
  // eager effect. See `ensureLoaded` for why it is not done on mount.
  //
  // The guard records *which* calculation has been loaded rather than a boolean.
  // A boolean plus a "reset it on mount" effect looks equivalent and is not:
  // React runs a child's effects before its parent's, so the first pane would
  // start the load and the provider's own mount effect would then clear the flag
  // behind it, and the next pane to mount would fetch a second time. Keying on
  // the id needs no reset at all -- a different calculation is simply a different
  // key.
  const loadedFor = React.useRef<string | null>(null);
  // The in-flight record load, so Results can wait for the inventory id instead
  // of racing the request it needs. Null once the load has settled.
  const recordLoadRef = React.useRef<Promise<void> | null>(null);

  const ensureLoaded = React.useCallback(() => {
    if (loadedFor.current === calculationId) return;
    loadedFor.current = calculationId;

    if (!calculationId) {
      console.error('No calculationId provided to FieldInventoryTab');
      setComponentError('No calculation ID provided');
      setLoading(false);
      return;
    }

    console.log('FieldInventoryTab mounted, calculationId:', calculationId);

    forestApi
      .getCalculation(calculationId)
      .then((calc: any) => {
        const compartments = calc?.result_data?.compartments;
        setHasCompartments(Array.isArray(compartments) && compartments.length > 0);
      })
      .catch(() => {});

    recordLoadRef.current = checkFieldInventory()
      .catch(() => {})
      .finally(() => {
        recordLoadRef.current = null;
      });
    // `checkFieldInventory` is a plain function re-created every render, and this
    // callback is only ever invoked on a pane's first mount -- once per
    // calculation -- so depending on it would defeat the ref that makes it
    // idempotent. The same suppression is used elsewhere in this file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId]);

  /**
   * Tree cover + effective areas.
   *
   * The effective (tree-covered) area is the denominator for every per-hectare
   * figure in Results, so it is resolved once here: the raster calculation
   * first, then `block-area-detail` for the authoritative effective area, and
   * only if that returns nothing does it fall back to the raster's own value.
   */
  const loadTreeCoverAreas = async (): Promise<Record<string, number> | null> => {
    try {
      setTreeCoverLoading(true);
      setTreeCoverError(null);

      // The tree-cover POST is a *recompute*, and it is allowed to come back
      // empty -- no raster overlap with the boundary, or blocks whose geometry
      // did not survive an edit. It is NOT the authoritative area source:
      // `/block-area-detail` is, and the totals endpoint resolves areas the same
      // way server-side.
      //
      // This used to `return null` the moment the recompute came back empty,
      // which meant the block-area-detail call below never ran. With no areas,
      // every per-hectare figure has no denominator, so the Results pane
      // rendered no per-hectare tables at all -- on forests where the areas were
      // sitting right there in block-area-detail the whole time.
      let treeCoverAreas: TreeCoverArea[] = [];
      try {
        const response = await forestApi.calculateTreeCoverAreas(calculationId);
        treeCoverAreas = response?.tree_cover_areas ?? [];
        if (treeCoverAreas.length > 0) {
          const treeCoverMap: Record<string, TreeCoverArea> = {};
          treeCoverAreas.forEach((area: TreeCoverArea) => {
            treeCoverMap[area.block_name] = area;
          });
          setTreeCoverAreas(treeCoverMap);
        } else {
          console.warn('Tree-cover recompute returned no areas; using block-area-detail');
        }
      } catch (tcErr: any) {
        console.warn(
          'Tree-cover recompute failed; using block-area-detail:',
          tcErr?.response?.data || tcErr?.message || tcErr
        );
      }

      const effectiveAreas: Record<string, number> = {};
      try {
        const blockDetail = await forestApi.getBlockAreaDetail(calculationId);
        if (blockDetail?.block_details && blockDetail.block_details.length > 0) {
          const polygon: Record<string, number> = {};
          blockDetail.block_details.forEach((bd: any) => {
            effectiveAreas[bd.block_name] = bd.effective_area_ha || 0;
            if (bd.total_area_ha != null) polygon[bd.block_name] = Number(bd.total_area_ha) || 0;
          });
          setPolygonAreas(polygon);
        } else {
          console.warn('Block-area-detail returned no block_details');
        }
      } catch (bdErr: any) {
        console.warn('Failed to load block area details:', bdErr?.response?.data || bdErr.message || bdErr);
      }

      if (Object.keys(effectiveAreas).length === 0 && treeCoverAreas.length > 0) {
        console.log('Falling back to tree_cover_areas effective_area_ha');
        treeCoverAreas.forEach((area: TreeCoverArea) => {
          effectiveAreas[area.block_name] = area.effective_area_ha;
        });
      }

      // Only now, with both sources exhausted, is there genuinely nothing.
      if (Object.keys(effectiveAreas).length === 0) {
        setTreeCoverError('No effective block areas available. Blocks may not have geometry.');
        return null;
      }

      setBlockAreas(effectiveAreas);
      return effectiveAreas;
    } catch (err: any) {
      const errorMsg = readDetail(err.response?.data?.detail, err.response?.data?.correlation_id)
        || err.message
        || t('generalErrors.unknown');
      console.error('Error loading tree cover areas:', err);
      setTreeCoverError(`Failed to calculate tree cover areas: ${errorMsg}`);
      return null;
    } finally {
      setTreeCoverLoading(false);
    }
  };

  /** Identifies the multiplier/threshold inputs the current totals were built from. */
  const totalsParamsKey = JSON.stringify([customMultipliers, aahMultipliers]);
  const fetchedTotalsKey = React.useRef<string | null>(null);

  /**
   * `areas` is a parameter rather than read from `blockAreas` because the
   * automatic path calls this straight after resolving them: the callback that
   * drives it is memoised on the calculation id, so `blockAreas` in its closure
   * is still the empty object the provider started with and the request would
   * go out with no areas at all. The manual Calculate button and the
   * multiplier/threshold recompute run in renders where the state is current,
   * so they keep the default.
   *
   * @param showAlerts surface failures to the user; the automatic path stays quiet.
   * @param areas effective area per block, defaulting to the resolved state.
   */
  const handleCalculateTotals = async (
    showAlerts: boolean = true,
    areas: Record<string, number> = blockAreas,
  ) => {
    const inventoryId = inventoryIdRef.current;
    if (!inventoryId) {
      if (showAlerts) console.log('No field inventory available yet');
      return;
    }

    const missingAreas = Object.entries(areas).filter(([_, area]) => area === 0);
    if (missingAreas.length > 0) {
      if (showAlerts) {
        alert(`Please enter areas for all blocks: ${missingAreas.map(([name]) => name).join(', ')}`);
      }
      return;
    }

    // No areas at all means the tree-cover step resolved nothing. Every
    // per-hectare figure would then be divided by a missing denominator, so
    // leave the totals uncalculated and let the Results pane keep showing its
    // manual trigger rather than presenting a plausible-looking total.
    if (Object.keys(areas).length === 0) {
      console.log('No effective areas resolved yet; skipping totals calculation');
      return;
    }

    try {
      setTotalsLoading(true);
      // The AAH thresholds are passed explicitly rather than left to the API
      // defaults: the user edits them in the Data pane, and the totals must
      // agree with the MAI/AAH table instead of silently using 75/60/40.
      const result = await fieldInventoryApi.getTotalInventory(
        inventoryId,
        areas,
        Object.keys(customMultipliers).length > 0 ? customMultipliers : undefined,
        aahMultipliers.good,
        aahMultipliers.moderate,
        aahMultipliers.weak
      );
      setTotalData(result);
      fetchedTotalsKey.current = totalsParamsKey;
      if (result?.blocks) {
        setBlockRates((prev) => {
          const updated = { ...prev };
          result.blocks.forEach((b: any) => {
            if (!updated[b.block_name]) {
              updated[b.block_name] = { timber: 5000, fuelwood: 1500, carbon: 1500 };
            }
          });
          return updated;
        });
      }
    } catch (err) {
      console.error('Error calculating total inventory:', err);
      if (showAlerts) {
        alert(t('totalInventory.msgCalcError'));
      }
    } finally {
      setTotalsLoading(false);
    }
  };

  const resultsLoadedFor = React.useRef<string | null>(null);

  const ensureResultsLoaded = React.useCallback(async () => {
    if (!calculationId) return;
    if (resultsLoadedFor.current === calculationId) return;
    resultsLoadedFor.current = calculationId;

    // Results can be the first pane opened, so the inventory record may still be
    // in flight and `handleCalculateTotals` would bail on a null id -- leaving a
    // calculation that does have an inventory showing the manual-calculate
    // fallback until the pane was remounted. Wait for the record instead.
    ensureLoaded();
    if (recordLoadRef.current) await recordLoadRef.current;

    if (!inventoryIdRef.current) {
      // Nothing to total. Clearing the guard lets a later pane switch retry in
      // case the record request is still settling.
      resultsLoadedFor.current = null;
      return;
    }

    // The areas the tree-cover step just resolved are handed to the totals call
    // rather than left for it to read from state: this callback is memoised on
    // the calculation id, so the state it closes over is the empty object the
    // provider started with.
    const areas = await loadTreeCoverAreas();
    if (areas) await handleCalculateTotals(false, areas);
    // `loadTreeCoverAreas`/`handleCalculateTotals` are re-created every render,
    // and this is invoked only on a pane's first mount -- once per calculation,
    // behind the ref above -- so depending on them would defeat the guard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId, ensureLoaded]);

  // Recompute when the AAH thresholds or per-unit multipliers change. The old
  // component kept its own copy of both, so a multiplier edited in the Data
  // pane never reached these tables; now that the state is shared, the tables
  // follow the edits. `fetchedTotalsKey` is null until the first successful
  // calculation, which keeps this from firing before there is anything to
  // recompute.
  React.useEffect(() => {
    if (resultsLoadedFor.current !== calculationId) return;
    if (fetchedTotalsKey.current === null) return;
    if (fetchedTotalsKey.current === totalsParamsKey) return;
    handleCalculateTotals(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalsParamsKey, calculationId]);

  // A field inventory imported from "Add data" (not through this tab): reload it, drop totals computed for the previous file, and tell the
  // workflow so Results unlocks - the same steps as after this tab's own upload.
  const reloadAfterImport = React.useRef<() => Promise<void>>(async () => {});
  reloadAfterImport.current = async () => {
    await checkFieldInventory();
    setFile(null);
    setValidationResult(null);
    resultsLoadedFor.current = null;
    fetchedTotalsKey.current = null;
    setTotalData(null);
    onStepDataChanged?.();
  };
  React.useEffect(
    () => onDataImported(({ purposes }) => {
      if (purposes.includes('field_inventory')) void reloadAfterImport.current();
    }),
    [],
  );

  // Handlers for AAH multiplier editing
  const handleStartInlineEdit = (blockName: string, currentValue: number) => {
    setEditingBlock(blockName);
    setEditingValue(currentValue.toString());
  };

  const handleSaveInlineEdit = async (blockName: string) => {
    const value = parseFloat(editingValue);
    if (!isNaN(value) && value >= 0 && value <= 100) {
      const newCustomMultipliers = { ...customMultipliers, [blockName]: value };
      setCustomMultipliers(newCustomMultipliers);

      // Recalculate AAH
      if (fieldInventory?.id) {
        const result = await fieldInventoryApi.getMaiAah(
          fieldInventory.id,
          aahMultipliers.good,
          aahMultipliers.moderate,
          aahMultipliers.weak,
          newCustomMultipliers
        );
        setMaiAahData(result);
      }
    }
    setEditingBlock(null);
    setEditingValue('');
  };

  const handleCancelInlineEdit = () => {
    setEditingBlock(null);
    setEditingValue('');
  };

  const handleOpenModal = (block: any) => {
    setModalBlock(block);
  };

  const handleCloseModal = () => {
    setModalBlock(null);
  };

  const handleSaveModal = async (multiplier: number) => {
    if (modalBlock && !isNaN(multiplier) && multiplier >= 0 && multiplier <= 100) {
      const newCustomMultipliers = { ...customMultipliers, [modalBlock.block_name]: multiplier };
      setCustomMultipliers(newCustomMultipliers);

      // Recalculate AAH
      if (fieldInventory?.id) {
        const result = await fieldInventoryApi.getMaiAah(
          fieldInventory.id,
          aahMultipliers.good,
          aahMultipliers.moderate,
          aahMultipliers.weak,
          newCustomMultipliers
        );
        setMaiAahData(result);
      }
    }
    setModalBlock(null);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setValidationResult(null);
      setError(null);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError(t('fieldInventory.msgSelectFile'));
      return;
    }

    try {
      setUploading(true);
      setError(null);
      setUploadFindings(null);

      // Step 1: Preview column mapping
      const previewData = await fieldInventoryApi.previewMapping(file);

      // Auto-detect mapping (exclude validation/check columns) - shared with "Add data"
      const autoMapping = autoMapFieldInventoryColumns(previewData.csv_columns);

      // Step 2: Upload with mapping
      const result = await fieldInventoryApi.upload(
        file,
        calculationId,
        autoMapping,
        sampleSizes
      );

      setValidationResult(result);

      // If validation passed, proceed to processing
      if (result.summary?.ready_for_processing && result.field_inventory_id) {
        await handleProcess(result.field_inventory_id, file);
      }

    } catch (err: any) {
      console.error('Upload error:', err);
      const findings = findingsFromError(err);
      setUploadFindings(findings);
      const errorMessage = readDetail(err.response?.data?.detail, err.response?.data?.correlation_id)
        || err.message
        || t('fieldInventory.uploadFailed');
      setError(findings ? null : errorMessage);
    } finally {
      setUploading(false);
    }
  };

  const handleProcess = async (inventoryId: string, fileToProcess: File) => {
    try {
      setProcessing(true);
      setError(null);

      await fieldInventoryApi.process(inventoryId, fileToProcess);

      // Reload data
      await checkFieldInventory();
      setFile(null);
      setValidationResult(null);

      // The inventory rows were just replaced, so totals computed for the
      // previous file are stale. Clear the guard, and recompute only if Results
      // was actually visited -- the tree-cover raster calculation is expensive
      // and a user who only uploads has no reason to pay for it.
      const resultsWereLoaded = resultsLoadedFor.current === calculationId;
      resultsLoadedFor.current = null;
      fetchedTotalsKey.current = null;
      setTotalData(null);
      if (resultsWereLoaded) {
        await ensureResultsLoaded();
      }

      // Processing is what makes the step complete, and the Results tab is
      // locked from that. Without this the tab the user just enabled by
      // uploading stays locked until a manual reload.
      onStepDataChanged?.();
    } catch (err: any) {
      console.error('Processing error:', err);
      const errorMessage = readDetail(err.response?.data?.detail, err.response?.data?.correlation_id)
        || err.message
        || t('fieldInventory.processingFailed');
      setError(errorMessage);
    } finally {
      setProcessing(false);
    }
  };

  const handleExportExcel = async () => {
    if (!fieldInventory?.id) return;
    try {
      const params: Record<string, string> = {
        aah_good: String(aahMultipliers.good),
        aah_moderate: String(aahMultipliers.moderate),
        aah_weak: String(aahMultipliers.weak),
      };
      if (Object.keys(customMultipliers).length > 0) {
        params.custom_multipliers = JSON.stringify(customMultipliers);
      }
      await downloadFromApi(
        `/api/field-inventory/${fieldInventory.id}/export-excel`,
        `field_inventory_${fieldInventory.id}.xlsx`,
        params
      );
    } catch (err: any) {
      console.error('Excel export failed:', err);
      setError('Failed to export Excel: ' + err.message);
    }
  };

  const handleDfoExport = async () => {
    if (!fieldInventory?.id || !calculationId) return;
    try {
      const blob = await fieldInventoryApi.exportDfoSummary(
        fieldInventory.id,
        calculationId,
        aahMultipliers.good,
        aahMultipliers.moderate,
        aahMultipliers.weak,
      );
      const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      downloadBlob(blob, `${forestName}_FieldInventory_DFOSummary_${dateStr}.xlsx`);
    } catch (err: any) {
      console.error('DFO summary export failed:', err);
      setError('Failed to export DFO summary: ' + err.message);
    }
  };

  const handleDelete = async (confirmText?: string) => {
    if (!fieldInventory?.id) return;

    if (!confirm(confirmText ?? t('fieldInventory.confirmDelete'))) {
      return;
    }

    try {
      setDeleting(true);
      await fieldInventoryApi.delete(fieldInventory.id);
      setFieldInventory(null);
      inventoryIdRef.current = null;
      setSummary(null);
      setSpeciesBreakdown(null);
      setSpeciesDbhData(null);
      setSpeciesDbhForestWide(null);
      setMaiAahData(null);
      setTotalData(null);
      setBlockRates({});
      // Let a re-upload recompute the totals instead of serving the deleted
      // inventory's numbers.
      resultsLoadedFor.current = null;
      fetchedTotalsKey.current = null;
      setError(null);
      // Deleting un-completes the step, so Results must lock again — the mirror
      // of the refresh after processing.
      onStepDataChanged?.();
    } catch (err: any) {
      setError(readDetail(err.response?.data?.detail, err.response?.data?.correlation_id)
        || t('fieldInventory.deleteFailed'));
    } finally {
      setDeleting(false);
    }
  };

  // Map field-inventory block names to current calculation block names
  const blockNameMap: Record<string, string> = {};
  if (summary?.blocks && blocks.length > 0) {
    // Sort summary blocks to match blocks prop order for consistent display
    const blockOrder = blocks.map((b: any) => b.block_name);
    summary.blocks.sort(
      (a: any, b: any) => blockOrder.indexOf(a.block_name) - blockOrder.indexOf(b.block_name)
    );
    summary.blocks.forEach((sb: any) => {
      const current = blocks.find((b: any) => b.block_name === sb.block_name);
      if (current && current.block_name !== sb.block_name) {
        blockNameMap[sb.block_name] = current.block_name;
      }
    });
  }
  const displayBlockName = (name: string): string => blockNameMap[name] || name;

  return {
    fieldInventory,
    summary,
    speciesBreakdown,
    maiAahData,
    hasCompartments,
    loading,
    initialized,
    speciesDbhData,
    speciesDbhForestWide,
    totalData,
    blockAreas,
    treeCoverAreas,
    polygonAreas,
    treeCoverLoading,
    treeCoverError,
    totalsLoading,
    blockRates,
    setBlockRates,
    file,
    uploading,
    processing,
    deleting,
    validationResult,
    error,
    uploadFindings,
    componentError,
    sampleSizes,
    setSampleSizes,
    aahMultipliers,
    setAahMultipliers,
    customMultipliers,
    setCustomMultipliers,
    setMaiAahData,
    setEditingValue,
    editingBlock,
    editingValue,
    handleStartInlineEdit,
    handleSaveInlineEdit,
    handleCancelInlineEdit,
    modalBlock,
    handleOpenModal,
    handleCloseModal,
    handleSaveModal,
    checkFieldInventory,
    ensureLoaded,
    ensureResultsLoaded,
    loadTreeCoverAreas,
    handleCalculateTotals,
    handleFileChange,
    handleUpload,
    handleProcess,
    handleExportExcel,
    handleDfoExport,
    handleDelete,
    setComponentError,
    setFieldInventory,
    setInitialized,
    setError,
    labels,
    displayBlockName,
    forestName,
  };
}

/**
 * The group provider. Rendered once per context, above `ContextTabHost`, so the
 * state survives every pane switch.
 */
export const FieldInventoryDataProvider: React.FC<{
  calculationId: string;
  blocks?: any[];
  forestName?: string;
  /** Re-reads the shell's workflow readiness; see `ContextPanelProps`. */
  onStepDataChanged?: () => void;
  children?: React.ReactNode;
}> = ({ calculationId, blocks, forestName, onStepDataChanged, children }) => (
  <FieldInventoryDataContext.Provider
    value={useFieldInventoryDataState(calculationId, blocks, forestName, onStepDataChanged)}
  >
    {children}
  </FieldInventoryDataContext.Provider>
);

/**
 * Read the shared state from inside a pane.
 *
 * Throws rather than returning null when there is no provider, because a pane
 * that silently rendered an empty page would look like "no inventory yet" —
 * indistinguishable from the real thing, and much harder to trace.
 */
export function useFieldInventoryData(): FieldInventoryData {
  const value = useContext(FieldInventoryDataContext);
  if (!value) {
    throw new Error(
      'useFieldInventoryData must be used inside <FieldInventoryDataProvider>. ' +
        'ContextTabHost mounts one pane at a time, so this state cannot live in a pane.',
    );
  }
  return value;
}
