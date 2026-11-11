/**
 * The species list shows BOTH views: every species named, and the ones off the
 * policy list gathered under a visible "Other species" heading.
 *
 * POLICY_SPECIES_PLAN P3. The owner asked for exactly this after being shown the
 * choice: individual species, an "Other species" group, or both. Both.
 *
 * The tests below are mostly about what must NOT happen, because the failure
 * modes are all silent:
 *
 *  - a species disappearing (the original complaint),
 *  - a group announced with a count that does not match the rows beneath it,
 *  - a "% of total" that does not add to 100,
 *  - an "Other" group that quietly collapses when it is long,
 *  - and a genus capture rendered identically to a named match, so the
 *    asymmetric rule becomes invisible and unauditable.
 */
import React from 'react';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { SpeciesPolicyTable, SpeciesPolicyRow } from '../fieldInventory/SpeciesPolicyTable';
import en from '../../i18n/locales/en.json';

// A real interpolating `useT`, not the identity stub the neighbouring tests use.
// This suite is about what a reader actually sees -- whether the group headings
// state the right counts, whether the shares add to 100 -- and an identity stub
// renders every heading as its own key, which would make those assertions
// untestable rather than merely unverified.
vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, params?: Record<string, unknown>) => {
    const value = key
      .split('.')
      .reduce<any>((acc, part) => (acc == null ? undefined : acc[part]), en);
    if (typeof value !== 'string') return key;
    if (!params) return value;
    return value.replace(/\{\{(\w+)\}\}/g, (_m, name) => String(params[name] ?? ''));
  },
}));

const MEASURES = [
  { key: 'timber_m3', labelKey: 'x.timber', decimals: 2 },
  { key: 'volume_m3', labelKey: 'x.volume', decimals: 2, emphasis: true },
];

/** The real 17 species of the owner's forest, with the split the backend gives. */
const ROWS: SpeciesPolicyRow[] = [
  // reference, named outright
  { species_scientific: 'Shorea robusta', species_local: 'Sal, Sakhu', classification: 'reference', matched_by: 'Shorea robusta', matched_by_level: 'species', count: 240, timber_m3: 10, volume_m3: 30 },
  { species_scientific: 'Terminalia alata', species_local: 'Saj, Asna', classification: 'reference', matched_by: 'Terminalia alata', matched_by_level: 'species', count: 226, timber_m3: 9, volume_m3: 28 },
  { species_scientific: 'Bombax ceiba', species_local: 'Simal, Semal', classification: 'reference', matched_by: 'Bombax ceiba', matched_by_level: 'species', count: 179, timber_m3: 8, volume_m3: 24 },
  { species_scientific: 'Anogeissus latifolia', species_local: 'Dhairo', classification: 'reference', matched_by: 'Anogeissus latifolia', matched_by_level: 'species', count: 166, timber_m3: 7, volume_m3: 22 },
  // reference, captured by the genus entry
  { species_scientific: 'Albizia chinensis', species_local: 'Siris', classification: 'reference', matched_by: 'Albizia spp', matched_by_level: 'genus', count: 143, timber_m3: 6, volume_m3: 20 },
  { species_scientific: 'Albizia lebbeck', species_local: 'Siris', classification: 'reference', matched_by: 'Albizia spp', matched_by_level: 'genus', count: 139, timber_m3: 6, volume_m3: 19 },
  { species_scientific: 'Albizia procera', species_local: 'Siris', classification: 'reference', matched_by: 'Albizia spp', matched_by_level: 'genus', count: 104, timber_m3: 5, volume_m3: 17 },
  // other
  { species_scientific: 'Cassia fistula', species_local: 'Rajbriksha', classification: 'other', matched_by: null, matched_by_level: null, count: 206, timber_m3: 9, volume_m3: 26 },
  { species_scientific: 'Terminalia chebula', species_local: 'Harro', classification: 'other', matched_by: null, matched_by_level: null, count: 201, timber_m3: 9, volume_m3: 25 },
  { species_scientific: 'Spondias pinnata', species_local: 'Amaro', classification: 'other', matched_by: null, matched_by_level: null, count: 187, timber_m3: 8, volume_m3: 24 },
];

const TOTAL = ROWS.reduce((s, r) => s + Number(r.count), 0); // 1791

function renderTable(rows: SpeciesPolicyRow[] = ROWS, testId = 'species-absolute') {
  return render(
    <SpeciesPolicyTable
      testId={testId}
      rows={rows}
      measures={MEASURES}
      shareKey="count"
      title={<h4>By Species</h4>}
      note={<p>Absolute count and volume by species across compartments</p>}
    />
  );
}

describe('both views, nothing hidden', () => {
  it('names every species in the table', () => {
    renderTable();
    for (const r of ROWS) {
      expect(screen.getByText(String(r.species_scientific))).toBeTruthy();
    }
  });

  it('renders one row per species, with no row shared between groups', () => {
    renderTable();
    expect(screen.getAllByTestId('species-absolute-row')).toHaveLength(ROWS.length);
  });

  it('shows both group headings', () => {
    renderTable();
    expect(screen.getByTestId('species-absolute-reference-divider')).toBeTruthy();
    expect(screen.getByTestId('species-absolute-other-divider')).toBeTruthy();
  });

  it('the reference heading counts what is above it', () => {
    renderTable();
    // 7 reference species of the 10 in this fixture. The real forest has 17 with
    // 10 in Other; that split is asserted against the real data in
    // tests/test_species_policy_groups.py, so this suite keeps a fixture small
    // enough to read.
    const divider = screen.getByTestId('species-absolute-reference-divider');
    expect(within(divider).getByText(/7 of 10/)).toBeTruthy();
  });

  it('the other heading counts what is actually under it', () => {
    renderTable();
    const divider = within(screen.getByTestId('species-absolute-other-divider'));
    expect(divider.getByText(/3 of 10/)).toBeTruthy();
  });
});

describe('the other group is never collapsed', () => {
  it('shows every other species as its own row', () => {
    renderTable();
    const others = ROWS.filter((r) => r.classification === 'other');
    for (const r of others) {
      const cell = screen.getByText(String(r.species_scientific));
      expect(cell).toBeTruthy();
    }
    expect(others).toHaveLength(3);
  });

  it('does not gate the other group on a count threshold', () => {
    // The owner's "at least five" instinct is a prominence rule for the headline
    // group. Applied to Other it would hide exactly the species whose identity is
    // in question, so it must not be applied here.
    const many = Array.from({ length: 25 }, (_, i) => ({
      species_scientific: `Species ${i}`,
      // Left undefined on purpose: setting it to the same string would put that
      // text in two cells and make a name lookup ambiguous.
      classification: 'other' as const,
      count: 10 - i,
      timber_m3: 1,
      volume_m3: 2,
    }));
    renderTable([...ROWS.filter((r) => r.classification === 'reference'), ...many]);
    for (const r of many) {
      expect(screen.getByText(r.species_scientific)).toBeTruthy();
    }
    expect(screen.getAllByTestId('species-absolute-row')).toHaveLength(
      ROWS.filter((r) => r.classification === 'reference').length + 25
    );
  });
});

describe('the genus rule is auditable', () => {
  it('marks a genus capture with the entry that spoke for it', () => {
    renderTable();
    // *Albizia chinensis* is in the list because "Albizia spp" covers it, not
    // because it is named. Without the marker the two look identical.
    expect(screen.getAllByText(/via Albizia spp/).length).toBe(3);
  });

  it('does not mark a species that is named outright', () => {
    renderTable();
    // Shorea robusta matches itself, so it must carry no genus marker.
    const cell = screen.getByText('Shorea robusta');
    expect(cell.textContent).not.toMatch(/via /);
  });

  it('an other-species row carries no marker', () => {
    renderTable();
    const cell = screen.getByText('Terminalia chebula');
    expect(cell.textContent).not.toMatch(/via /);
  });
});

describe('shares and totals', () => {
  it('renders a share column and a totals row', () => {
    renderTable();
    expect(screen.getByTestId('species-absolute-totals')).toBeTruthy();
    expect(screen.getByText('100.0%')).toBeTruthy();
  });

  it('the totals row counts every species', () => {
    renderTable();
    const totals = screen.getByTestId('species-absolute-totals');
    expect(within(totals).getByText(/10 species/)).toBeTruthy();
  });

  it('the group shares sum to the total', () => {
    renderTable();
    // Reference stems 1197 of 1791 = 66.8%; Other 594 of 1791 = 33.2%.
    // The share is printed inside the divider's label cell as "· 66.8%", so read
    // it from there rather than from the whole row, which also holds figures.
    const shareOf = (testId: string): number => {
      const label = within(screen.getByTestId(testId)).getAllByRole('cell')[0];
      const match = (label.textContent || '').match(/(\d+(?:\.\d+)?)%/);
      expect(match).not.toBeNull();
      return parseFloat(match![1]);
    };
    const a = shareOf('species-absolute-reference-divider');
    const b = shareOf('species-absolute-other-divider');
    expect(a + b).toBeCloseTo(100, 1);
  });
});

describe('unclassified rows are not dropped', () => {
  it('shows a row the backend did not classify, in the other group', () => {
    const rows: SpeciesPolicyRow[] = [
      ...ROWS,
      { species_scientific: 'Mysteryus thing', species_local: '?', count: 5, timber_m3: 1, volume_m3: 1 },
    ];
    renderTable(rows);
    expect(screen.getByText('Mysteryus thing')).toBeTruthy();
    expect(screen.getAllByTestId('species-absolute-row')).toHaveLength(rows.length);
  });
});

describe('a short reference group collapses (D5)', () => {
  /** `n` reference species plus enough other species to make a realistic table. */
  function withReference(n: number): SpeciesPolicyRow[] {
    const ref = ROWS.filter((r) => r.classification === 'reference').slice(0, n);
    const oth = ROWS.filter((r) => r.classification === 'other');
    return [...ref, ...oth];
  }

  it('collapses at four reference species', () => {
    renderTable(withReference(4));
    expect(screen.getByTestId('species-absolute-reference-collapsed')).toBeTruthy();
    expect(screen.queryByTestId('species-absolute-reference-divider')).toBeNull();
  });

  it('collapses at one reference species', () => {
    renderTable(withReference(1));
    expect(screen.getByTestId('species-absolute-reference-collapsed')).toBeTruthy();
  });

  it('does not collapse at five', () => {
    // The boundary is "below five is not worth a section", so five is the first
    // size that gets one.
    renderTable(withReference(5));
    expect(screen.queryByTestId('species-absolute-reference-collapsed')).toBeNull();
    expect(screen.getByTestId('species-absolute-reference-divider')).toBeTruthy();
  });

  it('does not collapse at seven, the real forest count', () => {
    renderTable(ROWS);
    expect(screen.queryByTestId('species-absolute-reference-collapsed')).toBeNull();
    expect(screen.queryByTestId('species-absolute-reference-expand')).toBeNull();
  });

  it('expands and collapses on demand', () => {
    const { unmount } = renderTable(withReference(2));
    // Collapsed: the reference species are summarised, not listed.
    expect(screen.getByTestId('species-absolute-reference-collapsed')).toBeTruthy();
    expect(screen.queryByText('Shorea robusta')).toBeNull();

    fireEvent.click(screen.getByTestId('species-absolute-reference-expand'));
    // Expanded: every one of them appears, and a hide control appears.
    expect(screen.getByText('Shorea robusta')).toBeTruthy();
    expect(screen.getByTestId('species-absolute-reference-divider')).toBeTruthy();
    expect(screen.getByTestId('species-absolute-reference-collapse')).toBeTruthy();

    fireEvent.click(screen.getByTestId('species-absolute-reference-collapse'));
    expect(screen.getByTestId('species-absolute-reference-collapsed')).toBeTruthy();
    expect(screen.queryByText('Shorea robusta')).toBeNull();
    unmount();
  });

  it('the expand control is a real button, so it is keyboard reachable', () => {
    renderTable(withReference(2));
    const button = screen.getByTestId('species-absolute-reference-expand');
    expect(button.tagName).toBe('BUTTON');
    expect(button.getAttribute('type')).toBe('button');
  });

  it('the other group stays fully visible while the reference group is collapsed', () => {
    // The point of the collapse is prominence, not concealment. Other is the
    // section a reader came for.
    renderTable(withReference(2));
    for (const r of ROWS.filter((x) => x.classification === 'other')) {
      expect(screen.getByText(r.species_scientific!)).toBeTruthy();
    }
    expect(screen.getByTestId('species-absolute-other-divider')).toBeTruthy();
  });

  it('collapsing hides nothing from the totals', () => {
    const rows = withReference(2);
    renderTable(rows);
    // Every species is still counted, collapsed or not. This is the invariant
    // that makes the collapse a presentation choice rather than a data filter.
    const totals = screen.getByTestId('species-absolute-totals');
    expect(within(totals).getByText(new RegExp(`${rows.length} species`))).toBeTruthy();
    expect(within(totals).getByText('100.0%')).toBeTruthy();
  });
});

describe('the empty cases say something rather than nothing', () => {
  it('no reference species gets a sentence, not a blank section', () => {
    const others = ROWS.filter((r) => r.classification === 'other');
    renderTable(others);
    expect(screen.getByTestId('species-absolute-no-reference')).toBeTruthy();
    expect(screen.queryByTestId('species-absolute-reference-divider')).toBeNull();
    // And the species are all still there.
    for (const r of others) {
      expect(screen.getByText(r.species_scientific!)).toBeTruthy();
    }
  });

  it('no other species omits the group entirely rather than showing a zero row', () => {
    const refs = ROWS.filter((r) => r.classification === 'reference');
    renderTable(refs);
    expect(screen.queryByTestId('species-absolute-other-divider')).toBeNull();
    expect(screen.queryByTestId('species-absolute-no-reference')).toBeNull();
    expect(screen.getAllByTestId('species-absolute-row')).toHaveLength(refs.length);
  });

  it('no species at all shows neither note nor divider', () => {
    renderTable([]);
    expect(screen.queryByTestId('species-absolute-no-reference')).toBeNull();
    expect(screen.queryByTestId('species-absolute-reference-divider')).toBeNull();
    expect(screen.queryByTestId('species-absolute-other-divider')).toBeNull();
    expect(screen.getByTestId('species-absolute-totals')).toBeTruthy();
  });

  it('a single reference species and no others collapses and stays honest', () => {
    const rows: SpeciesPolicyRow[] = [
      { species_scientific: 'Shorea robusta', species_local: 'Sal', classification: 'reference', matched_by: 'Shorea robusta', matched_by_level: 'species', count: 10, timber_m3: 1, volume_m3: 2 },
    ];
    renderTable(rows);
    expect(screen.getByTestId('species-absolute-reference-collapsed')).toBeTruthy();
    expect(screen.queryByTestId('species-absolute-other-divider')).toBeNull();
    expect(within(screen.getByTestId('species-absolute-totals')).getByText(/1 species/)).toBeTruthy();
  });
});

describe('one-sided cases do not render nonsense', () => {
  it('omits the reference divider when nothing is on the list', () => {
    const others = ROWS.filter((r) => r.classification === 'other');
    renderTable(others);
    expect(screen.queryByTestId('species-absolute-reference-divider')).toBeNull();
    expect(screen.getByTestId('species-absolute-other-divider')).toBeTruthy();
  });

  it('omits the other divider when every species is on the list', () => {
    const refs = ROWS.filter((r) => r.classification === 'reference');
    renderTable(refs);
    expect(screen.queryByTestId('species-absolute-other-divider')).toBeNull();
    expect(screen.getByTestId('species-absolute-reference-divider')).toBeTruthy();
  });

  it('renders without crashing on an empty list', () => {
    renderTable([]);
    expect(screen.getByTestId('species-absolute-totals')).toBeTruthy();
  });
});

describe('sorting within a group', () => {
  it('orders the group by the share measure, descending', () => {
    renderTable();
    // Reference stems: 240, 226, 179, 166, 143, 139, 104 -> already descending.
    const names = screen
      .getAllByTestId('species-absolute-row')
      .map((r) => r.textContent || '');
    const firstSeven = names.slice(0, 7).join('|');
    const order = [
      'Shorea robusta',
      'Terminalia alata',
      'Bombax ceiba',
      'Anogeissus latifolia',
      'Albizia chinensis',
      'Albizia lebbeck',
      'Albizia procera',
    ];
    const positions = order.map((n) => firstSeven.indexOf(n));
    expect(positions.every((p) => p >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  });
});
