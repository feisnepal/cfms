/**
 * CFMG harvest classes on screen.
 *
 * The grouping is the server's, and that is the point of these tests: they check
 * the table *shows* what `get_total_inventory` sends, without recomputing or
 * reshaping it. If a future change starts deriving groups here, the assertions
 * about "no re-derivation" stop passing, which is the intended alarm.
 *
 * `useT` is the identity function, so a rendered word is the i18n key. That makes
 * these tests check the key mapping itself, not the English text -- a group whose
 * `group_key` is mapped to the wrong key shows up here as a wrong key rather than
 * silently as a plausible-looking label.
 */
import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { HarvestGroupTable } from '../HarvestGroupTable';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

afterEach(cleanup);

const group = (over: Record<string, any> = {}) => ({
  group_key: 'mature_tree',
  dbh_classes: ['40_50', '50_60', '60_plus'],
  harvestable: true,
  count_per_ha: 12.4,
  timber_m3_per_ha: 30.5,
  firewood_m3_per_ha: 4.25,
  total_volume_m3_per_ha: 34.75,
  ...over,
});

const block = (name: string, groups: any[]) => ({
  block_name: name,
  area_ha: 12.34,
  harvest_class_groups: groups,
});

describe('HarvestGroupTable', () => {
  it('renders a row per compartment per group', () => {
    render(
      <HarvestGroupTable
        blocks={[
          block('C-1', [group(), group({ group_key: 'regeneration', harvestable: false })]),
          block('C-2', [group({ group_key: 'advance_growth' })]),
        ]}
      />,
    );
    expect(screen.getAllByTestId('harvest-group-row')).toHaveLength(3);
  });

  it('maps each group_key to the right word', () => {
    render(
      <HarvestGroupTable
        blocks={[
          block('C-1', [
            group({ group_key: 'regeneration', harvestable: false }),
            group({ group_key: 'advance_growth' }),
            group({ group_key: 'mature_tree' }),
          ]),
        ]}
      />,
    );
    // The three groups the server defines. A fourth, unknown group_key falls back
    // to the raw key rather than rendering blank.
    expect(screen.getByText('harvestGroup.regeneration')).toBeTruthy();
    expect(screen.getByText('harvestGroup.advanceGrowth')).toBeTruthy();
    expect(screen.getByText('harvestGroup.matureTree')).toBeTruthy();
  });

  it('marks regeneration as not harvestable', () => {
    // D12: Regeneration is shown rather than dropped, and the marker matters
    // because it is the largest group on the owner's forest -- 90,418 stems
    // against 9,300 in the two harvestable groups combined. A reader who misses
    // the marker reads 0-10 cm as harvestable.
    render(
      <HarvestGroupTable
        blocks={[
          block('C-1', [
            group({ group_key: 'regeneration', harvestable: false }),
            group({ group_key: 'mature_tree', harvestable: true }),
          ]),
        ]}
      />,
    );
    const rows = screen.getAllByTestId('harvest-group-row');
    const regen = rows.find((r) => r.textContent?.includes('harvestGroup.regeneration'))!;
    const mature = rows.find((r) => r.textContent?.includes('harvestGroup.matureTree'))!;
    expect(regen.textContent).toContain('harvestGroup.notHarvestable');
    expect(mature.textContent).not.toContain('harvestGroup.notHarvestable');
  });

  it('shows the DBH classes the group is made of', () => {
    render(<HarvestGroupTable blocks={[block('C-1', [group()])]} />);
    expect(screen.getByText('40_50 · 50_60 · 60_plus')).toBeTruthy();
  });

  it('shows the per-hectare figures without multiplying by area', () => {
    // The absolute figures already exist in the DBH class tables, and this table
    // sits beside them. Multiplying here would double-count, so the area on the
    // compartment must have no effect on what is printed.
    const small = render(<HarvestGroupTable blocks={[block('C-1', [group()])]} />);
    const smallText = screen.getByTestId('harvest-group-row').textContent;
    expect(smallText).toContain('34.75');
    cleanup();

    render(
      <HarvestGroupTable
        blocks={[
          { block_name: 'C-1', area_ha: 9999, harvest_class_groups: [group()] },
        ]}
      />,
    );
    expect(screen.getByTestId('harvest-group-row').textContent).toBe(smallText);
  });

  it('labels every measure as per hectare', () => {
    render(<HarvestGroupTable blocks={[block('C-1', [group()])]} />);
    for (const key of [
      'harvestGroup.countPerHa',
      'harvestGroup.timberPerHa',
      'harvestGroup.firewoodPerHa',
      'harvestGroup.volumePerHa',
    ]) {
      expect(screen.getByText(key)).toBeTruthy();
    }
  });

  it('shows the forest rollup from forest_totals, not a block', () => {
    // The rollup is area-weighted by the server and arrives on `forest_totals`.
    // Deriving it from the block rows here would produce a plain sum and label it
    // as a forest rate.
    render(
      <HarvestGroupTable
        blocks={[block('C-1', [group()]), block('C-2', [group()])]}
        forestGroups={[group({ total_volume_m3_per_ha: 70.1 })]}
      />,
    );
    const forestRow = screen.getByTestId('harvest-group-forest');
    expect(forestRow.textContent).toContain('harvestGroup.forestTotal');
    expect(forestRow.textContent).toContain('70.1');
  });

  it('renders nothing when there is nothing to show', () => {
    const { container } = render(<HarvestGroupTable blocks={[block('C-1', [])]} />);
    // An empty table card is a question the reader has to answer. No data is not.
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing for an undefined block list', () => {
    const { container } = render(
      <HarvestGroupTable blocks={undefined as any} forestGroups={undefined} />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('tolerates a group with no measures', () => {
    // Defensive: a partial payload should show a zero, not `NaN` or a crash.
    render(
      <HarvestGroupTable
        blocks={[block('C-1', [{ group_key: 'mature_tree', dbh_classes: [] } as any])]}
      />,
    );
    expect(screen.getAllByTestId('harvest-group-row')).toHaveLength(1);
    expect(screen.getByTestId('harvest-group-row').textContent).not.toContain('NaN');
  });
});
