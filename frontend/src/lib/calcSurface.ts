/**
 * calcSurface — the single `?surface=` navigation id for the tabbed calc shell,
 * plus the legacy compatibility layer. WORKSPACE_FLOW_NAV_PLAN §6.
 *
 *   surface = "<group>/<context>"   e.g. "analysis/hazarderosion"
 *
 * Both URL shapes are accepted. A URL arriving with `?surface=` keeps writing
 * `?surface=`; `?tab=&context=` is still read for old bookmarks and redirect
 * wrappers, and is composed into the same `group/context` string so it runs
 * through the identical resolution pipeline (§6.1). Roughly half the e2e specs
 * use the legacy pair.
 *
 * Resolution is fail-closed to the Map, which is a change: the previous
 * `parseSurfaceId` deliberately did not validate the context segment, so a typo
 * produced a well-formed-but-unknown surface that rendered a **blank panel**,
 * and `isKnownSurfaceId` existed but the shell never called it.
 */
import { TABS, type TabId } from '../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from '../components/calculation/calcContexts';

export interface CalcSurface {
  tab: TabId;
  ctx: string;
}

/** Where an unresolvable surface lands. The Map is the one page always present. */
export const FALLBACK_SURFACE: CalcSurface = { tab: 'base', ctx: 'unified' };

/** `"<group>/<context>"` — the value that goes in `?surface=`. */
export function toSurfaceId(tab: TabId, ctx: string): string {
  return `${tab}/${ctx}`;
}

/**
 * Every pre-P2b surface id, mapped to its replacement.
 *
 * All 21 are listed, including the five that are *removed* rather than moved —
 * those point at the surface that now does the work:
 *
 * - `forest-data/subareas`, `forest-data/compartments`, `data-maps/maps` → Map
 *   (D3: the Map workspace already owns the layer tree and all geometry work)
 * - `data-maps/totalinventory` → Field Inventory's Results tab (D4: same data,
 *   second state)
 * - `reports-outputs/reports` → Field Inventory's Forest Metadata tab (D6: base
 *   data about the forest, not a report)
 * - `reports-outputs/yearlyactivities` → Operational Plan (D9: merged as a tab)
 */
export const LEGACY_SURFACE_ALIASES: Readonly<Record<string, string>> = {
  // forest-data
  'forest-data/unified': 'base/unified',
  'forest-data/subareas': 'base/unified',
  'forest-data/compartments': 'base/unified',
  'forest-data/areadetail': 'analysis/areadetail',
  'forest-data/analysis': 'analysis/analysis',
  // sampling-model
  'sampling-model/sampling': 'field/sampling',
  'sampling-model/treemodel': 'field/treemodel',
  'sampling-model/treemapping': 'field/treemapping',
  'sampling-model/fieldbook': 'field/fieldbook',
  // data-maps
  'data-maps/mgmtplan': 'plan/mgmtplan',
  'data-maps/fieldinventory': 'field/fieldinventory',
  'data-maps/totalinventory': 'field/fieldinventory',
  'data-maps/biodiversity': 'field/biodiversity',
  'data-maps/maps': 'base/unified',
  'data-maps/usergroup': 'base/usergroup',
  'data-maps/hazarderosion': 'analysis/hazarderosion',
  'data-maps/sustainablefm': 'analysis/sustainablefm',
  'data-maps/cba': 'analysis/cba',
  // reports-outputs
  'reports-outputs/reports': 'field/fieldinventory',
  'reports-outputs/detaildescription': 'analysis/detaildescription',
  'reports-outputs/yearlyactivities': 'plan/yearly',
};

/**
 * Legacy context ids that stay addressable without a registry entry, and the
 * group each resolves into.
 *
 * These four are reachable only through old deep links, are not in
 * `GROUP_CONTEXTS`, and are kept deliberately: `boundary` / `blocks` /
 * `subcompartments` all render the Map workspace on a different view, and
 * `block_naming` is asserted by `tabbed-detail.spec.ts` as a preserved context.
 * All four are map-workspace views, so they resolve into `base`.
 *
 * Keyed by context id rather than `group/context` because the *group* they
 * arrive under is itself a legacy id and no longer parses. Everything not
 * aliased and not listed here falls back to the Map.
 */
export const LEGACY_PASSTHROUGH_ALLOWLIST: Readonly<Record<string, TabId>> = {
  boundary: 'base',
  blocks: 'base',
  subcompartments: 'base',
  block_naming: 'base',
};

/**
 * Parse a `?surface=` value into `{ tab, ctx }`, or `null` when it is
 * structurally not a surface at all (missing, no slash, empty context, two
 * segments after the group, or an unknown group).
 *
 * This function does **not** decide whether the context is real. That is
 * {@link resolveSurface}'s job, because "parseable" and "resolvable" are
 * different questions and conflating them is what produced blank panels.
 */
export function parseSurfaceId(id: string | null | undefined): CalcSurface | null {
  if (!id) return null;
  const slash = id.indexOf('/');
  if (slash <= 0 || slash === id.length - 1) return null;
  const tab = id.slice(0, slash);
  const ctx = id.slice(slash + 1);
  if (!(TABS as readonly string[]).includes(tab)) return null;
  if (ctx.includes('/')) return null; // exactly one segment after the group
  return { tab: tab as TabId, ctx };
}

/**
 * Resolve any surface id to a surface that actually renders something.
 *
 * Order (plan §6.1):
 *  1. an exact current `group/context`
 *  2. {@link LEGACY_SURFACE_ALIASES}
 *  3. {@link LEGACY_PASSTHROUGH_ALLOWLIST}
 *  4. otherwise {@link FALLBACK_SURFACE} (the Map)
 *
 * **The alias lookup runs on the raw string, before any group validation.**
 * That ordering is the whole point: a legacy id's *group* (`forest-data`) is not
 * a current group id, so parsing it first fails and every old bookmark would
 * fall through to the Map. Checking the table first is what makes
 * `?surface=forest-data/unified` still open the map.
 *
 * Step 4 is the behaviour change. `onFallback` lets the shell log which stale
 * links it is absorbing, so a wrong link is visible rather than silently
 * swallowed.
 */
export function resolveSurface(
  id: string | null | undefined,
  onFallback?: (requested: string) => void,
): CalcSurface {
  if (id) {
    // 2. Exact legacy id — before parsing, because its group is a legacy id.
    const aliased = LEGACY_SURFACE_ALIASES[id];
    if (aliased) {
      const target = parseSurfaceId(aliased);
      if (target) return target;
    }

    const parsed = parseSurfaceId(id);
    if (parsed) {
      // 1. A current surface.
      if (GROUP_CONTEXTS[parsed.tab].some((c) => c.id === parsed.ctx)) return parsed;
      // 3. A legacy context under a current group.
      const viaGroup = LEGACY_PASSTHROUGH_ALLOWLIST[parsed.ctx];
      if (viaGroup) return { tab: viaGroup, ctx: parsed.ctx };
    } else {
      // 3. A legacy *group* with a passthrough context: `forest-data/boundary`.
      // parseSurfaceId rejected the group, so match the context alone.
      const slash = id.indexOf('/');
      if (slash > 0 && slash < id.length - 1) {
        const ctx = id.slice(slash + 1);
        if (!ctx.includes('/')) {
          const viaLegacyGroup = LEGACY_PASSTHROUGH_ALLOWLIST[ctx];
          if (viaLegacyGroup) return { tab: viaLegacyGroup, ctx };
        }
      }
    }
  }

  if (id) onFallback?.(id);
  return FALLBACK_SURFACE;
}

/**
 * Compose the legacy `?tab=&context=` pair into a surface id so it runs through
 * {@link resolveSurface} unchanged (plan §6.1 — one resolver, two URL shapes).
 */
export function surfaceFromLegacyParams(
  tabParam: string | null | undefined,
  contextParam: string | null | undefined,
): string | null {
  if (!tabParam || !contextParam) return null;
  return `${tabParam}/${contextParam}`;
}

/** True when `id` names a group and a context that is in the registry today. */
export function isKnownSurfaceId(id: string | null | undefined): boolean {
  const s = parseSurfaceId(id);
  return !!s && GROUP_CONTEXTS[s.tab].some((c) => c.id === s.ctx);
}

/** Every valid surface id — for the palette / any exhaustive lister. */
export function allSurfaceIds(): string[] {
  return TABS.flatMap((tab) => GROUP_CONTEXTS[tab].map((c) => toSurfaceId(tab, c.id)));
}

/** Every legacy surface id, for the compatibility test. */
export const ALL_LEGACY_SURFACE_IDS: readonly string[] = Object.keys(LEGACY_SURFACE_ALIASES);
