import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttributeTable } from '../AttributeTable';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

// A forest carved via the canopy Auto-Block source: every block has
// dominant_canopy_class populated; dominant_slope_band/dominant_aspect/
// dominant_nasa_quality are null (no forest is ever carved by two sources at
// once). This is the exact shape that used to make three headers vanish.
const CANOPY_ONLY_FEATS = [
  {
    type: 'Feature' as const,
    geometry: { type: 'Polygon' as const, coordinates: [] },
    properties: {
      id: 'b1', name: 'Compartment-1', block_name: 'Compartment-1',
      dominant_slope_band: null, dominant_aspect: null, dominant_canopy_class: 3,
      dominant_nasa_quality: null,
    },
  },
  {
    type: 'Feature' as const,
    geometry: { type: 'Polygon' as const, coordinates: [] },
    properties: {
      id: 'b2', name: 'Compartment-2', block_name: 'Compartment-2',
      dominant_slope_band: null, dominant_aspect: null, dominant_canopy_class: 1,
      dominant_nasa_quality: null,
    },
  },
];

function seedStore() {
  useWorkspaceStore.setState({
    activeLayerId: 'blocks',
    activeImportedLayerId: null,
    calculationId: 'c1',
    customLayerStyles: {},
    columnVisibility: {},
    columnOrder: {},
    columnWidths: {},
    columnLabels: {},
    importedLayers: [],
    selection: { layerId: null, featureIds: [] },
    editHistory: [],
    editFuture: [],
  } as never);
}

const headers = () => screen.getAllByRole('columnheader').map((h) => h.textContent);

function renderTable(features = CANOPY_ONLY_FEATS) {
  return render(
    <AttributeTable
      isLoading={false} error={null} onRetry={() => {}} features={features}
    />,
  );
}

async function openChooser() {
  // Owner request, 2026-09-24: hidden behind "more tools" by default.
  await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
  await userEvent.click(screen.getByRole('button', { name: 'attributeTable.columnsChooser' }));
  return screen.getByRole('dialog', { name: 'attributeTable.columnsChooser' });
}

describe('AttributeTable — every value is presented (owner report, 2026-09-30)', () => {
  beforeEach(seedStore);

  it('shows ALL FOUR class columns even though only one is populated', () => {
    renderTable();
    // Previously the three unpopulated ones were `hideIfEmpty` and their
    // HEADERS disappeared -- a field that looked nonexistent, with no
    // dropdown to set it. An empty cell is the truthful state; a missing
    // column is not.
    expect(headers()).toContain('attributeTable.col.canopyClass');
    expect(headers()).toContain('attributeTable.col.slopeBand');
    expect(headers()).toContain('attributeTable.col.aspect');
    expect(headers()).toContain('attributeTable.col.nasaQuality');
  });

  it('the NASA column is present with an empty cell when nothing is classified', () => {
    // The owner's exact report: "NASA is working fine but no value in attribute
    // name and value." -- and the corollary that matters, that the cell must be
    // an editable dropdown rather than a dash you cannot fill in.
    renderTable();
    const nasaHeader = screen.getByRole('columnheader', { name: /nasaQuality/i });
    expect(nasaHeader).toBeDefined();
    const selects = screen.getAllByRole('combobox');
    // one editable dropdown per class column per row is not the contract; the
    // contract is that the column's cell offers NASA's own 1-3 choices.
    const nasaSelects = selects.filter((s) =>
      Array.from(s.querySelectorAll('option')).some((o) => o.value === '1' && /Primary/i.test(o.textContent || '')),
    );
    expect(nasaSelects.length).toBe(CANOPY_ONLY_FEATS.length);
  });

  it('an unset class cell reads "Not set", not blank and not a bare dash', () => {
    // Owner decision, 2026-09-30: "The attribute table must not have blank which
    // is now occuring." `AttributeTable` must inject an empty-valued option into
    // every `select` (otherwise a value cannot be cleared), and on a class column
    // that option used to read "-", which says nothing. Guarded here at the
    // render, because the registry-side test cannot see the injected option.
    renderTable();
    // Identify NASA's dropdown by its own option, not by a bare value: slope
    // bands are 1-4 and canopy classes are 1-4, so "has an option 3" matches
    // all three columns (and canopy is the one carrying a value here).
    const nasaSelects = screen.getAllByRole('combobox').filter((s) =>
      Array.from(s.querySelectorAll('option')).some(
        (o) => o.value === '1' && /Primary/i.test(o.textContent || ''),
      ),
    );
    expect(nasaSelects.length).toBeGreaterThan(0);
    for (const s of nasaSelects) {
      const unset = Array.from(s.querySelectorAll('option')).find((o) => o.value === '');
      expect(unset, 'every select must keep a clearable empty option').toBeDefined();
      expect(unset!.textContent).toBe('attributeTable.notSet');
      // ... and it is still the *selected* value when nothing is classified,
      // which is why the text has to be meaningful rather than decorative.
      // Asserted on the select's value, not `option.selected`, which jsdom
      // does not reliably derive.
      expect((s as HTMLSelectElement).value).toBe('');
    }
  });

  it('a select with no emptyLabelKey still renders the plain dash', () => {
    // Scoped deliberately: the owner limited this to the class columns. Anything
    // else keeps "-", so this change cannot leak across every table.
    renderTable();
    const opts = Array.from(
      screen.getAllByRole('combobox').flatMap((s) => Array.from(s.querySelectorAll('option'))),
    ).filter((o) => o.value === '');
    expect(opts.length).toBeGreaterThan(0);
    expect(opts.some((o) => o.textContent === '-')).toBe(true);
  });

  it('every column in the chooser is checked by default, and hiding still works', () => {
    // The reversal is one-directional by design: nothing is hidden until the
    // user hides it. The chooser is now the ONLY way to hide a column, so it
    // must be able to hide a column that used to be gated away.
    renderTable();
    return openChooser().then(async (dialog) => {
      const slopeRow = within(dialog).getByText('attributeTable.col.slopeBand').closest('label')!;
      const nasaRow = within(dialog).getByText('attributeTable.col.nasaQuality').closest('label')!;
      expect(within(slopeRow).getByRole('checkbox')).toBeChecked();
      expect(within(nasaRow).getByRole('checkbox')).toBeChecked();

      // hiding works, and the chooser's state is what drives the table
      await userEvent.click(within(nasaRow).getByRole('checkbox'));
      expect(within(nasaRow).getByRole('checkbox')).not.toBeChecked();
      expect(headers()).not.toContain('attributeTable.col.nasaQuality');

      // ...and it can be brought back
      await userEvent.click(within(nasaRow).getByRole('checkbox'));
      expect(within(nasaRow).getByRole('checkbox')).toBeChecked();
      expect(headers()).toContain('attributeTable.col.nasaQuality');
    });
  });
});
