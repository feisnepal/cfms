/** The Field Inventory provider wrapper must forward `onStepDataChanged`, or the Results tab stays locked after processing. */
import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { CONTEXT_TABS } from '../contextComponents';

describe('Field Inventory tab provider', () => {
  it('forwards onStepDataChanged to the data provider (the Results tab unlocks from it)', () => {
    const provider = CONTEXT_TABS.fieldinventory.provider!;
    const onStepDataChanged = vi.fn();
    const element = (provider as unknown as (p: Record<string, unknown>) => React.ReactElement<Record<string, unknown>>)({
      calculationId: 'C1',
      onStepDataChanged,
      children: null,
    });
    expect(element.props.calculationId).toBe('C1');
    expect(element.props.onStepDataChanged).toBe(onStepDataChanged);
  });

  it('Tree Mapping and Biodiversity panes report data changes to the shell, so their Results tab unlocks without a reload', () => {
    const onStepDataChanged = vi.fn();
    const props = { calculationId: 'C1', onStepDataChanged } as never;
    for (const pane of ['data', 'results'] as const) {
      const tm = CONTEXT_TABS.treemapping.panes[pane].render(props) as React.ReactElement<Record<string, unknown>>;
      (tm.props.onChanged as () => void)();
      const bio = CONTEXT_TABS.biodiversity.panes[pane].render(props) as React.ReactElement<Record<string, unknown>>;
      expect(bio.props.onStepDataChanged).toBe(onStepDataChanged);
    }
    expect(onStepDataChanged).toHaveBeenCalledTimes(2); // once per Tree Mapping pane
  });
});
