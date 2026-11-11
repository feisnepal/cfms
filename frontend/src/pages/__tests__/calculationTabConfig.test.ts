/**
 * CalculationDetailTabbed pure-helper tests (repo logic-only pattern).
 * Validates group URL resolution, disabled-group computation, and the unsaved
 * guard decision without mounting the page.
 *
 * WORKSPACE_FLOW_NAV_PLAN P2b: the four groups are now the phases of the work
 * (`base`, `field`, `analysis`, `plan`) rather than topics. See the plan for why
 * `requiresEdit` is a role gate and not a workflow gate.
 */
import { describe, it, expect } from 'vitest';
import {
  TABS,
  TAB_CONFIG,
  isValidTab,
  resolveActiveTab,
  tabRequiresEdit,
  computeDisabledTabs,
  canSwitchTab,
  shortcutKeyForTab,
  type TabId,
} from '../calculationTabConfig';
import { GROUP_CONTEXTS, SPINE_LENGTH, isSpineItem, findContext } from '../../components/calculation/calcContexts';

describe('calculationTabConfig — group URL resolution', () => {
  it('exposes the four phase groups in workflow order', () => {
    expect([...TABS]).toEqual(['base', 'field', 'analysis', 'plan']);
  });

  it('isValidTab accepts only known group ids', () => {
    expect(isValidTab('base')).toBe(true);
    expect(isValidTab('field')).toBe(true);
    expect(isValidTab('analysis')).toBe(true);
    expect(isValidTab('plan')).toBe(true);
    expect(isValidTab('analysis/hazarderosion')).toBe(false);
    expect(isValidTab(null)).toBe(false);
    expect(isValidTab(undefined)).toBe(false);
    expect(isValidTab('')).toBe(false);
  });

  it('rejects the pre-P2b group ids as current ids', () => {
    // They still RESOLVE, via LEGACY_SURFACE_ALIASES — but they are not group
    // ids any more, and `isValidTab` must not pretend otherwise or the alias
    // table becomes unreachable.
    for (const old of ['forest-data', 'sampling-model', 'data-maps', 'reports-outputs']) {
      expect(isValidTab(old)).toBe(false);
    }
  });

  it('resolveActiveTab defaults to base', () => {
    expect(resolveActiveTab(null)).toBe('base');
    expect(resolveActiveTab(undefined)).toBe('base');
    expect(resolveActiveTab('garbage')).toBe('base');
    expect(resolveActiveTab('field')).toBe('field');
  });
});

describe('calculationTabConfig — group labels are i18n keys', () => {
  it('every group label is a key, not a display string', () => {
    // These were hardcoded English ('Forest Data', 'Data & Maps') rendered with
    // no t() call, while the Nepali translations sat unused in the bundles.
    for (const tab of TABS) {
      expect(TAB_CONFIG[tab].labelKey).toMatch(/^[a-z]+\.[A-Za-z.]+$/);
    }
  });
});

describe('calculationTabConfig — disabled groups', () => {
  it('marks field and plan as edit-required; base and analysis stay open', () => {
    // A read-only user must still be able to review the map and every analysis.
    const req = tabRequiresEdit();
    expect(req.field).toBe(true);
    expect(req.plan).toBe(true);
    expect(req.base).toBe(false);
    expect(req.analysis).toBe(false);
  });

  it('disables edit-required groups only when the gate says so', () => {
    const req = tabRequiresEdit();
    expect(computeDisabledTabs(req, () => true)).toEqual(['field', 'plan']);
    expect(computeDisabledTabs(req, () => false)).toEqual([]);
  });
});

describe('calculationTabConfig — unsaved-changes guard', () => {
  it('allows switching when clean, blocks when dirty', () => {
    expect(canSwitchTab(false)).toBe(true);
    expect(canSwitchTab(true)).toBe(false);
  });
});

describe('calculationTabConfig — keyboard shortcut mapping (Ctrl/Cmd+digit)', () => {
  it('maps each group index to its 1-based digit', () => {
    expect(TABS.map((_, i) => shortcutKeyForTab(i))).toEqual(['1', '2', '3', '4']);
  });

  it('returns undefined out of range', () => {
    expect(shortcutKeyForTab(-1)).toBeUndefined();
    expect(shortcutKeyForTab(TABS.length)).toBeUndefined();
  });

  it('shortcut digits cover exactly the group count (help modal contract)', () => {
    const digits = TABS.map((_, i) => shortcutKeyForTab(i));
    expect(new Set(digits).size).toBe(TABS.length);
    expect(digits.every((d) => /^[1-9]$/.test(d!))).toBe(true);
  });

  it('addresses GROUPS, never steps', () => {
    // 16 step shortcuts would collide with 4 group shortcuts; the stepper has
    // Back/Next instead (plan 8.8).
    expect(TABS).toHaveLength(4);
    expect(SPINE_LENGTH).toBe(16);
  });
});

describe('calcContexts — the workflow spine', () => {
  const allItems = TABS.flatMap((t) => GROUP_CONTEXTS[t]);

  it('has 16 numbered steps and 3 off-spine optional items (the Trial page and the two Advanced pages)', () => {
    expect(SPINE_LENGTH).toBe(16);
    expect(allItems).toHaveLength(19);
    const optional = allItems.filter((c) => c.optional);
    expect(optional.map((c) => c.id)).toEqual(['treemodel', 'analysis', 'hazarderosion']);
    expect(optional.every((c) => c.step === undefined)).toBe(true);
  });

  it('step numbers are 1..16 with no gaps or duplicates', () => {
    const steps = allItems
      .map((c) => c.step)
      .filter((s): s is number => s !== undefined)
      .sort((a, b) => a - b); // numeric: a bare sort() orders 10 before 2
    expect(steps).toEqual(Array.from({ length: 16 }, (_, i) => i + 1));
  });

  it('step order follows the work, not the alphabet', () => {
    const byStep = [...allItems]
      .filter((c) => c.step !== undefined)
      .sort((a, b) => a.step! - b.step!)
      .map((c) => c.id);
    expect(byStep).toEqual([
      'unified', // map first — everything derives from it
      'usergroup',
      'fieldbook', // generated and printed before going out
      'sampling', // designed from the map
      'fieldinventory',
      'forestmetadata', // the forest's own record: its own step since 2026-10-11
      'biodiversity', // collected during the inventory visit
      'treemapping', // tree inventory follows forest inventory
      'ntfp', // the optional NTFP resource survey (owner, 2026-10-22)
      'detaildescription',
      'areadetail',
      'sustainablefm',
      'cba',
      'yearly', // the owner says Done when the list is finished (2026-10-15)
      'mgmtplan', // desktop work, after all data is in
      'issuesubmit', // the terminal deliverable
    ]);
  });

  it('every `needs` entry names a context that exists', () => {
    const ids = new Set(allItems.map((c) => c.id));
    for (const item of allItems) {
      for (const need of item.needs ?? []) {
        expect(ids, `${item.id} needs unknown context "${need}"`).toContain(need);
      }
    }
  });

  it('no `needs` points at an optional page', () => {
    // The Trial page is optional; making it a prerequisite would make the flow
    // require something the user may never use (D13).
    const optionalIds = new Set(allItems.filter((c) => c.optional).map((c) => c.id));
    for (const item of allItems) {
      for (const need of item.needs ?? []) {
        expect(optionalIds.has(need)).toBe(false);
      }
    }
  });

  it('nothing depends on Issue & Submit — it is the last step', () => {
    for (const item of allItems) {
      expect(item.needs ?? []).not.toContain('issuesubmit');
    }
  });

  it('`needs` only ever points backwards, so no forward references render', () => {
    // The plan removed a forward dependency three times over (Yearly Activities
    // before Operational Plan); this makes it impossible to reintroduce one.
    const stepOf = new Map(allItems.map((c) => [c.id, c.step]));
    for (const item of allItems) {
      for (const need of item.needs ?? []) {
        const needStep = stepOf.get(need);
        if (needStep === undefined || item.step === undefined) continue;
        expect(needStep, `${item.id} (step ${item.step}) needs ${need} (step ${needStep})`)
          .toBeLessThan(item.step);
      }
    }
  });

  it('the plan document is produced by the plan, not consumed by analysis', () => {
    // CBA reads inventory + analysis. The plan document CONSUMES CBA's output.
    // An earlier draft had this inverted, which would make the flow circular.
    expect(findContext('cba')!.item.needs).not.toContain('mgmtplan');
    expect(findContext('mgmtplan')!.item.step).toBeGreaterThan(findContext('cba')!.item.step!);
  });

  it('every entry declares a type, and types are the four agreed values', () => {
    for (const item of allItems) {
      expect(['input', 'run', 'view', 'trial']).toContain(item.type);
    }
  });

  it('classifies by who does the work, not by topic', () => {
    // The two cases that motivated PageType: Biodiversity reads like analysis but
    // is the most input-heavy page in the system, and Analysis reads like data
    // but the user only presses Run.
    expect(findContext('biodiversity')!.item.type).toBe('input');
    expect(findContext('analysis')!.item.type).toBe('run');
    // Autogenerated, no manual input (D14).
    expect(findContext('detaildescription')!.item.type).toBe('view');
  });

  it('isSpineItem is exactly "has a step"', () => {
    for (const item of allItems) {
      expect(isSpineItem(item)).toBe(item.step !== undefined);
    }
  });

  it('findContext locates a context in whichever group holds it', () => {
    expect(findContext('unified')).toEqual({ tab: 'base', item: expect.anything() });
    expect(findContext('cba')!.tab).toBe('analysis');
    expect(findContext('issuesubmit')!.tab).toBe('plan');
    expect(findContext('nope')).toBeNull();
  });
});
