/**
 * useFeatureClipboard — the toolbar's Copy / Paste / Paste-as-layer / Delete.
 *
 * Copy takes the selected features of the active layer (the whole layer when
 * nothing is selected) with their attributes. Paste puts them into the active
 * layer at exactly the same coordinates; Paste-as-layer turns them into a new
 * imported layer. Delete removes every selected feature behind one confirm.
 *
 * The rules for what a target accepts live in `lib/featureClipboard.ts`; this
 * hook is the orchestration: read the selection, ask the user only what it
 * cannot infer, call the server, record ONE undo step, tell the user what
 * happened (including what the server trimmed or refused).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { message, Modal } from 'antd';
import type { GeoJSON } from 'geojson';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useFeatureClipboardStore } from '../store/featureClipboardStore';
import { useT } from '../i18n/hooks';
import { getLayerConfig, type LayerTypeId } from '../lib/layerRegistry';
import {
  areaHectares,
  buildSubAreaBodies,
  newLayerName,
  pasteTargetIssue,
  prepareImportedFeatures,
  sourceName,
  subAreaCategoryOf,
  toClipboardFeatures,
  wasTrimmed,
  type PasteIssue,
  type PasteTarget,
} from '../lib/featureClipboard';
import {
  PasteRejectedError,
  appendFeaturesToImportedLayer,
  createSubAreaFromPaste,
  fetchImportedFeatures,
  importClipboardAsLayer,
} from '../lib/featurePasteApi';
import {
  deleteFeatureRow,
  fetchDeleteGuard,
  snapshotFeature,
  type FeatureDeleteLayerType,
  type FeatureRowContext,
} from '../lib/featureRowOps';
import {
  createBatchOperation,
  createDigitizeAddOperation,
  createDigitizeDeleteByIdOperation,
  createFeatureDeleteOperation,
  createFeaturePasteOperation,
} from '../lib/operationFactories';
import type { GeometryOperation } from '../lib/editOperations';

/** Built-in layers whose rows the toolbar Delete may remove (same set the row menu serves). */
const DELETABLE_BUILTIN: ReadonlySet<string> = new Set([
  'boundary', 'blocks', 'compartments', 'sub_compartments', 'sub_areas', 'activity_features',
  'user_group',
]);

const USER = 'user';

/** The id the attribute table and the map both use to key a row's selection. */
function rowId(f: GeoJSON.Feature): string {
  const p = (f.properties ?? {}) as Record<string, unknown>;
  return String(p.id || p.featureId || (f as { id?: unknown }).id || '');
}

interface ActiveSource {
  /** Selection / clipboard key: `blocks`, `imported:12`. */
  key: string;
  label: string;
  features: GeoJSON.Feature[];
  target: PasteTarget;
  layerType: FeatureDeleteLayerType | null;
  imported?: { id: number; isDraft: boolean };
}

function confirmAsync(opts: { title: string; content: string; okText: string; danger?: boolean }): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: opts.title,
      content: opts.content,
      okText: opts.okText,
      okType: opts.danger ? 'danger' : 'primary',
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}

export interface UseFeatureClipboardArgs {
  calculationId: string;
  getLayerFeatures: (layerId: LayerTypeId) => GeoJSON.Feature[] | null;
  pushOp: (op: GeometryOperation) => void;
  pushAndExecute: (op: GeometryOperation, execute: () => void) => void;
  /** Shortcuts only act while the workspace is actually on screen. */
  rootRef: React.RefObject<HTMLElement | null>;
}

export function useFeatureClipboard({
  calculationId, getLayerFeatures, pushOp, pushAndExecute, rootRef,
}: UseFeatureClipboardArgs) {
  const t = useT();
  const store = useWorkspaceStore();
  const clipboard = useFeatureClipboardStore((s) => s.clipboard);
  const setClipboard = useFeatureClipboardStore((s) => s.setClipboard);

  // ── a layer, as a source and as a paste target ────────────────────────────
  // Keyed like the selection is: a built-in id (`blocks`) or `imported:<id>`. The
  // toolbar acts on the ACTIVE layer; a layer's context menu names its own.
  const resolveSource = useCallback((key: string | null): ActiveSource | null => {
    if (!key) return null;
    if (key.startsWith('imported:')) {
      const id = Number(key.slice('imported:'.length));
      const layer = store.importedLayers.find((l) => l.id === id);
      if (!layer) return null;
      const features = layer.isDraft
        ? (store.digitizeDraftFeatures[id] ?? store.importedLayerFeatures[id] ?? [])
        : (store.importedLayerFeatures[id] ?? []);
      return {
        key,
        label: layer.name,
        features,
        target: { kind: 'imported', id, purpose: layer.purpose },
        layerType: `import_${id}`,
        imported: { id, isDraft: !!layer.isDraft },
      };
    }
    const id = key as LayerTypeId;
    return {
      key: id,
      label: getLayerConfig(id)?.label ?? id,
      features: getLayerFeatures(id) ?? [],
      target: { kind: 'builtin', id },
      layerType: DELETABLE_BUILTIN.has(id) ? (id as FeatureDeleteLayerType) : null,
    };
    // getLayerFeatures reads react-query results that change identity with data
  }, [store.importedLayers, store.importedLayerFeatures, store.digitizeDraftFeatures, getLayerFeatures]);

  const activeKey = store.activeLayerId
    ?? (store.activeImportedLayerId != null ? `imported:${store.activeImportedLayerId}` : null);
  const source = useMemo(() => resolveSource(activeKey), [resolveSource, activeKey]);

  /** The rows of `src` that are selected (nothing selected in another layer counts). */
  const entriesFor = useCallback((src: ActiveSource | null) => {
    if (!src || store.selection.layerId !== src.key || store.selection.featureIds.length === 0) return [];
    const wanted = new Set(store.selection.featureIds);
    return src.features
      .map((feature, index) => ({ feature, index }))
      .filter(({ feature }) => wanted.has(rowId(feature)));
  }, [store.selection]);
  const selectedEntries = useMemo(() => entriesFor(source), [entriesFor, source]);

  const lockedFor = useCallback((src: ActiveSource | null) => (
    src
      ? !!store.layerLocks[src.target.kind === 'imported' ? `imported:${src.target.id}` : src.key]
      : false
  ), [store.layerLocks]);
  const layerLocked = lockedFor(source);

  const sameCalc = clipboard?.calcId === calculationId;
  const clipboardFeatures = useMemo(() => (sameCalc && clipboard ? clipboard.features : []), [sameCalc, clipboard]);

  const pasteIssueFor = useCallback((src: ActiveSource | null): PasteIssue | null => (
    pasteTargetIssue(src?.target ?? null, clipboardFeatures, {
      structureLocked: store.structureLocked, layerLocked: lockedFor(src),
    })
  ), [clipboardFeatures, store.structureLocked, lockedFor]);
  const pasteIssue: PasteIssue | null = pasteIssueFor(source);

  const pasteAsLayerIssue: PasteIssue | null = clipboardFeatures.length === 0
    ? { code: 'empty_clipboard' }
    : null;

  // ── sub-area category prompt (only when a pasted feature carries none) ────
  const [categoryPrompt, setCategoryPrompt] = useState<{ count: number } | null>(null);
  const categoryResolver = useRef<((c: string | null) => void) | null>(null);
  const askCategory = useCallback((count: number) => new Promise<string | null>((resolve) => {
    categoryResolver.current = resolve;
    setCategoryPrompt({ count });
  }), []);
  const resolveCategoryPrompt = useCallback((category: string | null) => {
    categoryResolver.current?.(category);
    categoryResolver.current = null;
    setCategoryPrompt(null);
  }, []);

  // ── Copy ──────────────────────────────────────────────────────────────────
  /**
   * Copy the selected features of a layer (the whole layer when none is selected).
   * `layerKey` names a layer other than the active one (its context menu);
   * `features` copies exactly those (a single row's menu).
   */
  const copy = useCallback((opts?: { layerKey?: string; features?: GeoJSON.Feature[] }) => {
    const src = typeof opts?.layerKey === 'string' ? resolveSource(opts.layerKey) : source;
    if (!src) { message.info(t('editing.copy.noLayer')); return; }
    const explicit = Array.isArray(opts?.features) ? opts?.features : undefined;
    const entries = entriesFor(src);
    const wholeLayer = !explicit && entries.length === 0;
    const chosen = explicit ?? (wholeLayer ? src.features : entries.map((e) => e.feature));
    const { features, dropped } = toClipboardFeatures(chosen);
    if (features.length === 0) { message.warning(t('editing.copy.nothing')); return; }
    setClipboard({
      calcId: calculationId,
      sourceLayerKey: src.key,
      sourceLabel: src.label,
      wholeLayer,
      features,
      copiedAt: Date.now(),
    });
    const key = wholeLayer ? 'editing.copy.doneWhole' : 'editing.copy.done';
    message.success(t(key, { count: features.length, layer: src.label }));
    if (dropped > 0) message.warning(t('editing.copy.droppedNoGeometry', { count: dropped }));
  }, [source, resolveSource, entriesFor, setClipboard, calculationId, t]);

  // ── Paste into the active layer ───────────────────────────────────────────
  const reportRejected = useCallback((err: unknown) => {
    message.error(err instanceof PasteRejectedError || err instanceof Error
      ? err.message
      : t('editing.paste.failed'));
  }, [t]);

  const pasteIntoSubAreas = useCallback(async (features: GeoJSON.Feature[], src: ActiveSource) => {
    const existing = new Set(
      (getLayerFeatures('sub_areas') ?? [])
        .map((f) => String((f.properties as Record<string, unknown> | null)?.name ?? '').toLowerCase())
        .filter(Boolean),
    );
    const lacking = features.filter((f) => !subAreaCategoryOf(f.properties as Record<string, unknown>));
    let chosen: string | null = null;
    if (lacking.length > 0) {
      chosen = await askCategory(lacking.length);
      if (!chosen) return; // cancelled — nothing was created
    }
    const bodies = buildSubAreaBodies(
      features, existing,
      (f) => subAreaCategoryOf(f.properties as Record<string, unknown>) ?? chosen,
      t('editing.paste.defaultName'),
    );

    const createdIds: string[] = [];
    const persisted: GeoJSON.Feature[] = [];
    const persistedBodies: Record<string, unknown>[] = [];
    let trimmed = 0;
    const rejected: string[] = [];
    let stopReason: string | null = null;

    for (let i = 0; i < bodies.length; i++) {
      const body = bodies[i];
      try {
        const created = await createSubAreaFromPaste(calculationId, body);
        createdIds.push(created.id);
        persisted.push({ type: 'Feature', geometry: created.geometry ?? body.geometry, properties: { name: body.name } });
        persistedBodies.push({ ...body });
        if (wasTrimmed(areaHectares({ type: 'Feature', geometry: body.geometry, properties: {} }), created.area_hectares)) {
          trimmed += 1;
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        rejected.push(`${body.name}: ${msg}`);
        // A lock or a missing forest fails every remaining feature the same way.
        if (err instanceof PasteRejectedError && (err.status === 423 || err.status === 422)) {
          stopReason = msg;
          break;
        }
      }
    }

    if (createdIds.length > 0) {
      pushOp(createFeaturePasteOperation(calculationId, 'sub_areas', persisted, createdIds, USER, {
        payloads: persistedBodies,
        label: `Paste ${createdIds.length} sub-area(s)`,
      }));
      store.bumpGeometryVersion();
      store.selectFeatures('sub_areas', createdIds);
    }

    const skipped = features.length - bodies.length;
    if (createdIds.length > 0 && rejected.length === 0 && trimmed === 0 && skipped === 0) {
      message.success(t('editing.paste.doneAll', { count: createdIds.length, layer: src.label }));
      return;
    }
    if (createdIds.length === 0) {
      message.error(stopReason ?? t('editing.paste.noneCreated'));
    } else {
      message.warning(t('editing.paste.doneSome', {
        done: createdIds.length, total: features.length, trimmed, rejected: rejected.length + skipped,
      }));
    }
    if (rejected.length > 0) {
      Modal.info({
        title: t('editing.paste.rejectedTitle'),
        content: rejected.slice(0, 10).join('\n') + (rejected.length > 10 ? `\n… +${rejected.length - 10}` : ''),
        okText: t('common.ok'),
      });
    }
  }, [askCategory, calculationId, getLayerFeatures, pushOp, store, t]);

  const pasteIntoImported = useCallback(async (features: GeoJSON.Feature[], src: ActiveSource) => {
    if (!src.imported) return;
    const { id, isDraft } = src.imported;
    const prepared = prepareImportedFeatures(features);
    const label = `Paste ${prepared.length} feature(s) into ${src.label}`;

    if (isDraft) {
      // A draft keeps its features in the local buffer until Finish & Save.
      const ops = prepared.map((f) => createDigitizeAddOperation(id, f, USER));
      pushAndExecute(
        ops.length === 1 ? ops[0] : createBatchOperation(ops, { label }),
        () => prepared.forEach((f) => store.enqueueDigitizeFeature(id, f)),
      );
      message.success(t('editing.paste.doneAll', { count: prepared.length, layer: src.label }));
      return;
    }

    try {
      const before = store.importedLayerFeatures[id]?.length ?? 0;
      await appendFeaturesToImportedLayer(calculationId, id, prepared, 'append');
      const fresh = await fetchImportedFeatures(calculationId, id);
      store.setImportedLayerFeatures(id, fresh);
      // The server's list is the truth: the pasted rows are its tail.
      const baseIndex = Math.max(0, fresh.length - prepared.length);
      pushOp(createFeaturePasteOperation(
        calculationId, `import_${id}`, prepared,
        prepared.map((f) => String((f.properties as Record<string, unknown>).featureId)), USER,
        { importLayerId: id, baseIndex: baseIndex || before, label },
      ));
      store.bumpGeometryVersion();
      store.selectFeatures(`imported:${id}`, fresh.slice(baseIndex).map(rowId).filter(Boolean));
      message.success(t('editing.paste.doneAll', { count: prepared.length, layer: src.label }));
    } catch (err) {
      reportRejected(err);
    }
  }, [calculationId, pushAndExecute, pushOp, store, t, reportRejected]);

  /** Paste into the active layer, or into `layerKey` (a layer's context menu). */
  const paste = useCallback(async (layerKey?: string) => {
    const src = typeof layerKey === 'string' ? resolveSource(layerKey) : source;
    const issue = pasteIssueFor(src);
    if (issue) {
      message.warning(t(`editing.paste.reason.${issue.code}`, issue.params));
      return;
    }
    if (!src) return;
    try {
      if (src.target.kind === 'builtin') await pasteIntoSubAreas(clipboardFeatures, src);
      else await pasteIntoImported(clipboardFeatures, src);
    } catch (err) {
      reportRejected(err);
    }
  }, [source, resolveSource, pasteIssueFor, clipboardFeatures, pasteIntoSubAreas, pasteIntoImported, reportRejected, t]);

  // ── Paste as a new imported layer ─────────────────────────────────────────
  const pasteAsLayer = useCallback(async () => {
    if (pasteAsLayerIssue) {
      message.warning(t(`editing.paste.reason.${pasteAsLayerIssue.code}`));
      return;
    }
    const cb = clipboard;
    if (!cb) return;
    const name = newLayerName(cb.sourceLabel, store.importedLayers.map((l) => l.name), t('editing.paste.layerSuffix'));
    try {
      // Purpose `other` holds any mix of points, lines and polygons and carries
      // no topology rule, so the copy is exact and cannot be refused for shape.
      // Every feature stays its own row (see importClipboardAsLayer).
      const created = await importClipboardAsLayer(calculationId, cb.features, name);
      store.addImportedLayer({
        id: created.id,
        name: created.name,
        purpose: 'other',
        format: 'geojson',
        featureCount: created.featureCount,
        geometryTypes: created.geometryTypes,
        visible: true,
        order: store.importedLayers.length,
      });
      store.setImportedLayerFeatures(created.id, await fetchImportedFeatures(calculationId, created.id));
      store.setActiveImportedLayer(created.id);
      store.bumpGeometryVersion();
      message.success(t('editing.paste.layerCreated', { count: created.featureCount, name: created.name }));
    } catch (err) {
      reportRejected(err);
    }
  }, [pasteAsLayerIssue, clipboard, store, calculationId, reportRejected, t]);

  // ── Delete the selection, one confirm ─────────────────────────────────────
  const canDelete = !!source && selectedEntries.length > 0 && (source.imported != null || source.layerType != null)
    && !store.structureLocked && !layerLocked;

  const deleteSelected = useCallback(async () => {
    if (!source) return;
    if (selectedEntries.length === 0) { message.info(t('editing.delete.nothingSelected')); return; }
    if (!source.imported && !source.layerType) { message.warning(t('editing.delete.notDeletable', { layer: source.label })); return; }
    const count = selectedEntries.length;

    // Draft layer: the features exist only in the local buffer — no server row.
    if (source.imported?.isDraft) {
      const ok = await confirmAsync({
        title: t('editing.delete.confirmTitle', { count, layer: source.label }),
        content: t('editing.delete.confirmContent'), okText: t('common.delete'), danger: true,
      });
      if (!ok) return;
      const layerId = source.imported.id;
      const ops = selectedEntries.map(({ feature }) =>
        createDigitizeDeleteByIdOperation(layerId, rowId(feature), feature, USER));
      pushAndExecute(
        ops.length === 1 ? ops[0] : createBatchOperation(ops, { label: `Delete ${count} feature(s) from ${source.label}` }),
        () => selectedEntries.forEach(({ feature }) => store.removeDigitizeFeature(layerId, rowId(feature))),
      );
      store.clearSelection();
      return;
    }

    const ctxOf = (feature: GeoJSON.Feature, index: number): FeatureRowContext => ({
      calcId: calculationId,
      layerType: source.layerType as FeatureDeleteLayerType,
      featureId: rowId(feature),
      importLayerId: source.imported?.id,
      featureIndex: source.imported ? index : undefined,
    });

    // 1. Inventory guard for every builtin row. One blocked row refuses the
    //    whole batch — a half-deleted selection is harder to reason about (and
    //    to undo) than one clear "these can't go" list.
    if (!source.imported && source.layerType !== 'activity_features') {
      const blocked: string[] = [];
      for (const { feature, index } of selectedEntries) {
        try {
          const guard = await fetchDeleteGuard(ctxOf(feature, index));
          if (guard.blocked) {
            const why = (guard.reasons || []).map((r) => `${r.type.replace(/_/g, ' ')}: ${r.count}`).join(' · ');
            blocked.push(`${sourceName(feature.properties as Record<string, unknown>, rowId(feature))}${why ? ` — ${why}` : ''}`);
          }
        } catch {
          // legacy layers without a guard endpoint: rely on the confirm.
        }
      }
      if (blocked.length > 0) {
        Modal.error({
          title: t('editing.delete.blockedTitle', { count: blocked.length, total: count }),
          content: blocked.slice(0, 12).join('\n') + (blocked.length > 12 ? `\n… +${blocked.length - 12}` : ''),
        });
        return;
      }
    }

    // 2. One confirm for the lot.
    const ok = await confirmAsync({
      title: t('editing.delete.confirmTitle', { count, layer: source.label }),
      content: t('editing.delete.confirmContent'), okText: t('common.delete'), danger: true,
    });
    if (!ok) return;

    // 3. Delete. Imported layers go highest index first so every recorded
    //    `featureIndex` is still valid when its turn comes (and undo, which
    //    walks the list backwards, re-inserts them lowest first).
    const ordered = [...selectedEntries].sort((a, b) => b.index - a.index);
    const ops: GeometryOperation[] = [];
    const removedIndices = new Set<number>();
    let failure: string | null = null;

    for (const { feature, index } of ordered) {
      const ctx = ctxOf(feature, index);
      try {
        let snapshot: Record<string, unknown> = {};
        if (source.imported) snapshot = { feature };
        else if (ctx.layerType === 'boundary') {
          snapshot = { geometry: feature.geometry, area_hectares: (feature.properties as Record<string, unknown> | null)?.area_hectares };
        } else {
          try { snapshot = (await snapshotFeature(ctx)).snapshot; } catch { snapshot = { feature }; }
        }
        await deleteFeatureRow(ctx);
        ops.push(createFeatureDeleteOperation(calculationId, ctx.layerType, ctx.featureId, snapshot, USER, {
          importLayerId: ctx.importLayerId, featureIndex: ctx.featureIndex,
        }));
        removedIndices.add(index);
      } catch (err) {
        failure = err instanceof Error ? err.message : String(err);
        break;
      }
    }

    if (ops.length > 0) {
      const importedId = source.imported?.id;
      pushAndExecute(
        ops.length === 1 ? ops[0] : createBatchOperation(ops, { label: `Delete ${ops.length} feature(s) from ${source.label}` }),
        () => {
          if (importedId != null) {
            const list = useWorkspaceStore.getState().importedLayerFeatures[importedId] ?? [];
            store.setImportedLayerFeatures(importedId, list.filter((_, i) => !removedIndices.has(i)));
          }
          store.bumpGeometryVersion();
        },
      );
      store.clearSelection();
    }
    if (failure) {
      message.error(t('editing.delete.partial', { done: ops.length, total: count, reason: failure }));
    } else {
      message.success(t('editing.delete.done', { count: ops.length, layer: source.label }));
    }
  }, [source, selectedEntries, calculationId, pushAndExecute, store, t]);

  // ── keyboard: Ctrl/⌘+C, Ctrl/⌘+V, Ctrl/⌘+Shift+V, Delete ─────────────────
  const latest = useRef({ copy, paste, pasteAsLayer, deleteSelected, canDelete, hasClipboard: clipboardFeatures.length > 0 });
  latest.current = { copy, paste, pasteAsLayer, deleteSelected, canDelete, hasClipboard: clipboardFeatures.length > 0 };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const root = rootRef.current;
      // The workspace stays mounted behind other tabs: act only while it shows.
      if (!root || root.offsetParent === null) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))) return;
      if (document.querySelector('.ant-modal-mask')) return; // a dialog is open
      const mode = useWorkspaceStore.getState().toolbarMode;
      if (mode && mode !== 'select') return; // drawing / cutting own these keys

      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === 'c') {
        if (window.getSelection()?.toString()) return; // let the browser copy text
        e.preventDefault();
        latest.current.copy();
      } else if (mod && k === 'v') {
        if (!latest.current.hasClipboard) return;
        e.preventDefault();
        if (e.shiftKey) void latest.current.pasteAsLayer();
        else void latest.current.paste();
      } else if (!mod && !e.shiftKey && !e.altKey && e.key === 'Delete') {
        if (!latest.current.canDelete) return;
        e.preventDefault();
        void latest.current.deleteSelected();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rootRef]);

  /**
   * Can a paste land in `layerKey`? null = yes now; 'never' = this layer can never
   * take one (its menu omits the command); else why not right now.
   */
  const pasteStateFor = (layerKey: string): null | 'never' | { reasonKey: string; params?: Record<string, string> } => {
    const issue = pasteIssueFor(resolveSource(layerKey));
    if (!issue) return null;
    if (issue.code === 'layer_not_pastable' || issue.code === 'purpose_not_pastable') return 'never';
    return { reasonKey: `editing.paste.reason.${issue.code}`, params: issue.params };
  };

  return {
    copy,
    paste,
    pasteAsLayer,
    deleteSelected,
    canCopy: !!source && source.features.length > 0,
    /** How many features Copy would take right now, and whether that is the whole layer. */
    copyCount: selectedEntries.length > 0 ? selectedEntries.length : (source?.features.length ?? 0),
    copyIsWholeLayer: selectedEntries.length === 0,
    clipboardCount: clipboardFeatures.length,
    pasteIssue,
    pasteAsLayerIssue,
    /** Selected features in `layerKey` (0 = Copy would take the whole layer). */
    selectedCountFor: (layerKey: string) => (
      store.selection.layerId === layerKey ? store.selection.featureIds.length : 0
    ),
    pasteStateFor,
    /** The same, for the ACTIVE layer (the attribute table's row menu). */
    activePasteState: (activeKey ? pasteStateFor(activeKey) : 'never') as
      null | 'never' | { reasonKey: string; params?: Record<string, string> },
    canDelete,
    categoryPrompt,
    resolveCategoryPrompt,
  };
}
