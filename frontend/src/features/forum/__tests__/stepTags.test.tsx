import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { GROUP_CONTEXTS, SPINE_LENGTH } from '../../../components/calculation/calcContexts';
import { FORUM_TAGS, STEP_TAGS, tagForStep } from '../stepTags';
import StepForumLinks from '../StepForumLinks';

const allContexts = Object.values(GROUP_CONTEXTS).flat();

describe('step tags', () => {
  it('has a tag for every numbered step, and the tag is a starting tag', () => {
    const numbered = allContexts.filter((c) => c.step !== undefined);
    expect(numbered).toHaveLength(SPINE_LENGTH);
    for (const c of numbered) {
      const tag = tagForStep(c.id);
      expect(tag, `step ${c.step} (${c.id}) has no forum tag`).toBeDefined();
      expect(FORUM_TAGS as readonly string[]).toContain(tag);
    }
  });

  it('names no step the workflow does not have', () => {
    const ids = new Set(allContexts.map((c) => c.id));
    for (const id of Object.keys(STEP_TAGS)) expect(ids.has(id), `${id} is not a workflow context`).toBe(true);
  });

  it('uses only ids the forum accepts as a workflow step', () => {
    for (const c of allContexts) expect(c.id).toMatch(/^[a-z][a-z0-9_-]{0,39}$/);
  });

  it('knows nothing about an unknown step', () => {
    expect(tagForStep('nope')).toBeUndefined();
    expect(tagForStep(null)).toBeUndefined();
  });
});

describe('StepForumLinks', () => {
  it('opens the ask form for the step in a new tab', () => {
    const html = renderToStaticMarkup(<StepForumLinks stepId="fieldbook" />);
    expect(html).toContain('href="/forum/ask?step=fieldbook"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});
