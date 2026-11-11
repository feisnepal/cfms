/**
 * workflowSteps — the walking rules for the spine.
 *
 * The rule under most scrutiny here is that `nextStep` **prefers input steps**.
 * That is what delivers the owner's requirement — a crew that only enters data
 * should be walked through the data steps without hunting — and it is exactly
 * the kind of preference that degrades into "hide the other steps" if the
 * fallbacks are wrong. So each fallback is asserted, including the case where
 * every input step is already done.
 */
import { describe, it, expect } from 'vitest';
import {
  OFF_SPINE,
  SPINE,
  SPINE_LENGTH,
  TYPE_BADGE,
  locate,
  nextStep,
  prevStep,
  stepAt,
  stepById,
} from '../workflowSteps';
import { TABS } from '../../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from '../calcContexts';

const never = () => false;
const always = () => true;

describe('workflowSteps — the spine', () => {
  it('is 16 steps, numbered 1..16 with no gaps', () => {
    expect(SPINE_LENGTH).toBe(16);
    expect(SPINE.map((s) => s.step)).toEqual(Array.from({ length: 16 }, (_, i) => i + 1));
  });

  it('every registry step appears exactly once', () => {
    const registrySteps = TABS.flatMap((t) =>
      GROUP_CONTEXTS[t].filter((c) => c.step !== undefined),
    );
    expect(SPINE).toHaveLength(registrySteps.length);
    expect(new Set(SPINE.map((s) => s.id)).size).toBe(SPINE.length);
  });

  it('puts the map first and the submission last', () => {
    expect(SPINE[0].id).toBe('unified');
    expect(SPINE[SPINE.length - 1].id).toBe('issuesubmit');
  });

  it('holds the Trial page and the Advanced pages outside the spine', () => {
    // D13: optional, so "done" is not a state the workflow waits for. Analysis and Hazard & Erosion are Advanced (owner,
    // 2026-10-17): the plan builds them by itself, so they are pages for tuning and looking, not steps.
    expect(OFF_SPINE.map((o) => o.item.id)).toEqual(['treemodel', 'analysis', 'hazarderosion']);
    expect(stepById('treemodel')).toBeUndefined();
    expect(stepById('analysis')).toBeUndefined();
    expect(stepById('hazarderosion')).toBeUndefined();
  });

  it('locates a context whether or not it is a step', () => {
    expect(locate('cba')?.step).toBe(13);
    expect(locate('ntfp')?.step).toBe(9);          // the NTFP inventory is an (optional) numbered step since 2026-10-22
    expect(locate('analysis')?.step).toBeUndefined();
    expect(locate('analysis')?.item).toBeDefined();
    expect(locate('treemodel')?.step).toBeUndefined();
    expect(locate('treemodel')?.item).toBeDefined();
    expect(locate('nope')).toBeNull();
  });

  it('stepAt and stepById agree', () => {
    for (const s of SPINE) {
      expect(stepAt(s.step)?.id).toBe(s.id);
      expect(stepById(s.id)?.step).toBe(s.step);
    }
  });
});

describe('nextStep — preferring required steps', () => {
  const requiredDone = (id: string) => SPINE.find((s) => s.id === id)?.item.need === 'required';

  it('prefers the next INCOMPLETE required step', () => {
    expect(nextStep(1, never).id).toBe('usergroup');
  });

  it('skips completed required steps', () => {
    const done = (id: string) => ['unified', 'usergroup', 'fieldbook', 'sampling'].includes(id);
    expect(nextStep(2, done).id).toBe('fieldinventory');
  });

  it('walks a data-entry crew through the required steps in workflow order, past the steps the system fills in', () => {
    const visited: string[] = [];
    let cursor = -1; // before the first step, so nothing is done yet
    for (let i = 0; i < 9; i += 1) {
      const done = (id: string) => {
        const at = SPINE.findIndex((s) => s.id === id);
        return at >= 0 && at <= cursor;
      };
      const next = nextStep(cursor, done);
      visited.push(next.id);
      cursor = SPINE.findIndex((s) => s.id === next.id);
    }
    // Tree mapping, detail description, area, analysis, hazard, SFM and cost-benefit are not stops: the system fills them in.
    expect(visited).toEqual([
      'unified', 'usergroup', 'fieldbook', 'sampling', 'fieldinventory', 'forestmetadata', 'biodiversity', 'yearly', 'mgmtplan',
    ]);
  });

  it('only reaches an optional or review step when asked, or when no required step is left', () => {
    expect(nextStep(1, never, false).id).toBe('usergroup');
    // the default never returns a non-required step while a required one exists
    for (let step = 1; step <= SPINE_LENGTH; step += 1) {
      expect(nextStep(step, never).item.need, `from step ${step}`).toBe('required');
    }
  });

  it('still moves when every required step is already done', () => {
    const nxt = nextStep(1, requiredDone);
    expect(nxt.step).not.toBe(1);
    expect(nxt.item.need).toBe('required');
  });

  it('reaches an optional step when the caller does not restrict to required ones', () => {
    expect(nextStep(1, requiredDone, false).id).toBe('treemapping');
  });

  it('marks each step as required, optional or review as the owner decided (2026-10-11)', () => {
    const need = Object.fromEntries(SPINE.map((s) => [s.id, s.item.need]));
    expect(need).toEqual({
      unified: 'required', usergroup: 'required', fieldbook: 'required', sampling: 'required', fieldinventory: 'required',
      forestmetadata: 'required', biodiversity: 'required', treemapping: 'optional', ntfp: 'optional', detaildescription: 'optional',
      areadetail: 'optional', sustainablefm: 'optional', cba: 'review',
      yearly: 'required', mgmtplan: 'required', issuesubmit: 'required',
    });
  });

  it('never dead-ends when everything is done', () => {
    expect(nextStep(13, always).step).not.toBe(13);
  });

  it('wraps to the first step', () => {
    // D7: the plan feeds the next cycle, so the flow is a loop, not a corridor.
    expect(nextStep(17, always).step).toBe(1);
  });

  it('never returns an off-spine page', () => {
    for (let step = 1; step <= SPINE_LENGTH; step += 1) {
      for (const isDone of [never, always]) {
        expect(stepById(nextStep(step, isDone).id), `from ${step}`).toBeDefined();
      }
    }
  });
});

describe('prevStep', () => {
  it('walks backwards and stops at 1', () => {
    expect(prevStep(5)?.step).toBe(4);
    expect(prevStep(1)).toBeUndefined();
  });
});

describe('TYPE_BADGE', () => {
  it('has a distinct glyph per type', () => {
    const glyphs = Object.values(TYPE_BADGE).map((b) => b.glyph);
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });

  it('fills input and hollows view, so the two read apart without colour', () => {
    // Read at a glance or by a screen reader, where a four-way colour code
    // would not survive.
    expect(TYPE_BADGE.input.glyph).toBe('■');
    expect(TYPE_BADGE.view.glyph).toBe('□');
  });
});
