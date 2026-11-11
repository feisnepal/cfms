/**
 * The ActivityPicker (§4.11) on the REAL master list and the real English catalogue: searching, spelling
 * tolerance, English words, the browse tree, filter chips, reading cards, keyboard use and the promise that a
 * search is never a dead end.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import en from '../../../i18n/locales/en.json';
import { MASTER_LIST } from './masterList.fixture';

const lang = vi.hoisted(() => ({ current: 'en' }));

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return (values.defaultValue as string) ?? key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { get language() { return lang.current; } } }) };
});
vi.mock('../../../i18n/numberFormat', () => ({
  formatNumber: (n: number) => n.toLocaleString('en'),
  formatDecimal: (n: number) => String(n),
}));

import { ActivityPicker } from '../ActivityPicker';

const RECENT_KEY = 'cfms.yearlyPlan.recentActivities';

function setup(props: Partial<React.ComponentProps<typeof ActivityPicker>> = {}) {
  const onChoose = vi.fn();
  const onOpen = vi.fn();
  const utils = render(<ActivityPicker activities={MASTER_LIST} onChoose={onChoose} onOpen={onOpen} {...props} />);
  const search = screen.getByTestId('activity-search') as HTMLInputElement;
  const type = (value: string) => fireEvent.change(search, { target: { value } });
  return { ...utils, onChoose, onOpen, search, type };
}

const count = () => screen.getByTestId('activity-count').textContent;
const rowIds = () =>
  screen
    .queryAllByTestId(/^activity-row-/)
    .map((el) => Number(el.getAttribute('data-testid')?.replace('activity-row-', '')));

beforeEach(() => {
  window.localStorage.clear();
  lang.current = 'en';
});
afterEach(() => {
  window.localStorage.clear();
});

describe('the first view', () => {
  it('shows the finder, the hint, the chips and a browse tree with every activity counted', () => {
    setup();
    expect(screen.getByText('Find an activity')).toBeInTheDocument();
    expect(screen.getByText('You can type in Nepali or English.')).toBeInTheDocument();
    expect(count()).toBe('Showing 135 of 135 activities');
    expect(screen.getByTestId('browse-tree')).toBeInTheDocument();
    expect(screen.getByTestId('chip-map')).toBeInTheDocument();
    expect(rowIds()).toHaveLength(0); // groups start closed
  });

  it('a group shows its plain one-line description and its counts, and opens on click', () => {
    setup();
    const programmes = screen.getAllByTestId('tree-programme-toggle');
    // open the "forest protection" programme (the first project starts with the development programme)
    const first = programmes[0];
    expect(first.textContent).toContain('activities');
    expect(first.textContent).toContain('can be shown on the map');
    expect(first.textContent).toContain('Nurseries, planting, seeds and forest plans.');
    fireEvent.click(first);
    expect(rowIds()).toEqual(expect.arrayContaining([1, 2, 3, 4]));
    expect(first).toHaveAttribute('aria-expanded', 'true');
  });

  it('expands and collapses every group at once', () => {
    setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(rowIds()).toHaveLength(135);
    fireEvent.click(screen.getByTestId('collapse-all'));
    expect(rowIds()).toHaveLength(0);
  });
});

describe('typing', () => {
  it('narrows as you type, grouped by programme, with a live count', () => {
    const { type } = setup();
    type('nursery');
    expect(count()).toBe('Showing 5 of 135 activities');
    expect(rowIds()).toEqual([1, 2, 41, 62, 81]);
    expect(screen.getAllByTestId('result-group').length).toBeGreaterThan(1);
  });

  it('finds a Nepali activity by a spelling variant (वन for the list\'s बन)', () => {
    const { type } = setup();
    type('वन सिमांकन');
    expect(rowIds()[0]).toBe(10);
  });

  it('finds it through a one-letter typo', () => {
    const { type } = setup();
    type('nursary');
    expect(rowIds()).toContain(1);
  });

  it('highlights the matched word in the Nepali name and the English subtitle', () => {
    const { type } = setup();
    type('नर्स');
    const row = screen.getByTestId('activity-row-1');
    expect(within(row).getByText('नर्सरी').tagName).toBe('MARK');
    type('nursery');
    expect(within(screen.getByTestId('activity-row-1')).getByText('nursery').tagName).toBe('MARK');
  });

  it('shows the English name under the Nepali one in an English UI, and hides it in a Nepali UI', () => {
    setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(within(screen.getByTestId('activity-row-1')).getByText('Build a nursery')).toBeInTheDocument();
  });

  it('a Nepali UI does not repeat the English name', () => {
    lang.current = 'ne';
    setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(within(screen.getByTestId('activity-row-1')).queryByText('Build a nursery')).toBeNull();
  });

  it('clears with the ✕ button and with Esc', () => {
    const { type, search } = setup();
    type('nursery');
    fireEvent.click(screen.getByTestId('activity-search-clear'));
    expect(search.value).toBe('');
    expect(count()).toBe('Showing 135 of 135 activities');
    type('fire');
    fireEvent.keyDown(search, { key: 'Escape' });
    expect(search.value).toBe('');
  });
});

describe('reading an activity', () => {
  it('shows the full name, never cut, even the longest', () => {
    setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    const longest = MASTER_LIST.reduce((a, b) => ((a.activity?.length ?? 0) >= (b.activity?.length ?? 0) ? a : b));
    expect((longest.activity ?? '').length).toBeGreaterThan(200);
    const row = screen.getByTestId(`activity-row-${longest.id}`);
    expect(row.textContent).toContain(longest.activity as string);
  });

  it('says how it can be shown on the map, with its symbol', () => {
    setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(screen.getByTestId('map-badge-1').textContent).toContain('Can be shown on the map as a point');
    expect(screen.getByTestId('map-badge-1').textContent).toContain('Nursery');
    expect(screen.getByTestId('map-badge-4').textContent).toContain('as an area');
    expect(screen.getByTestId('map-badge-12').textContent).toContain('as a line');
    expect(screen.getByTestId('map-badge-102').textContent).toContain('No map needed');
  });

  it('says what it is measured in, in words', () => {
    setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(within(screen.getByTestId('activity-row-4')).getByText('Measured in hectares')).toBeInTheDocument();
    expect(within(screen.getByTestId('activity-row-10')).getByText('Measured in kilometres')).toBeInTheDocument();
    expect(within(screen.getByTestId('activity-row-102')).getByText('Counted as a number of items')).toBeInTheDocument();
  });

  it('two activities with the same name show their programme so they cannot be mistaken', () => {
    const { type } = setup();
    type('अन्य');
    const rows = [119, 132].map((id) => screen.getByTestId(`activity-row-${id}`));
    expect(rows[0].textContent).not.toEqual(rows[1].textContent);
    // grouped under two different programme headings
    expect(screen.getAllByTestId('result-group').length).toBeGreaterThanOrEqual(2);
  });

  it('tags an activity that is already in the plan, with its years', () => {
    setup({ inPlan: { 1: [1, 2, 3, 7], 4: [] } });
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(screen.getByTestId('in-plan-1').textContent).toBe('In your plan · Years 1–3, 7');
    expect(screen.getByTestId('in-plan-4').textContent).toBe('In your plan');
    expect(screen.queryByTestId('in-plan-2')).toBeNull();
  });
});

describe('choosing', () => {
  it('"Choose" adds an activity that is not in the plan', () => {
    const { onChoose, onOpen } = setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    fireEvent.click(within(screen.getByTestId('activity-row-2')).getByRole('button', { name: 'Choose' }));
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect(onChoose.mock.calls[0][0]).toMatchObject({ id: 2, name: 'नर्सरी मर्मत' });
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('an activity already in the plan is opened, never added twice', () => {
    const { onChoose, onOpen } = setup({ inPlan: { 1: [1] } });
    fireEvent.click(screen.getByTestId('expand-all'));
    fireEvent.click(within(screen.getByTestId('activity-row-1')).getByRole('button', { name: 'Open in plan' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onChoose).not.toHaveBeenCalled();
  });

  it('clicking the row does the same as its button, once', () => {
    const { onChoose } = setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    fireEvent.click(screen.getByTestId('activity-row-3'));
    expect(onChoose).toHaveBeenCalledTimes(1);
  });

  it('remembers what was chosen for the "Recently used" chip (in this browser only)', () => {
    const { onChoose } = setup();
    fireEvent.click(screen.getByTestId('expand-all'));
    fireEvent.click(screen.getByTestId('activity-row-30'));
    expect(onChoose).toHaveBeenCalled();
    expect(JSON.parse(window.localStorage.getItem(RECENT_KEY) as string)).toEqual([30]);
    fireEvent.click(screen.getByTestId('chip-recent'));
    expect(rowIds()).toEqual([30]);
  });

  it('a running "Choose" shows a spinner on that activity only', () => {
    setup({ busyId: 2 });
    fireEvent.click(screen.getByTestId('expand-all'));
    expect(within(screen.getByTestId('activity-row-2')).getByRole('button')).toHaveClass('ant-btn-loading');
    expect(within(screen.getByTestId('activity-row-3')).getByRole('button')).not.toHaveClass('ant-btn-loading');
  });
});

describe('keyboard', () => {
  it('↓ ↑ move through the results and Enter chooses the highlighted one', () => {
    const { type, search, onChoose } = setup();
    type('nursery');
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    expect(search.getAttribute('aria-activedescendant')).toBe('ap-opt-2');
    fireEvent.keyDown(search, { key: 'ArrowUp' });
    expect(search.getAttribute('aria-activedescendant')).toBe('ap-opt-1');
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChoose.mock.calls[0][0]).toMatchObject({ id: 1 });
  });

  it('a row appearing under a resting mouse does not steal the row reached with the arrow keys; moving the mouse does', () => {
    const { type, search } = setup();
    type('nursery');
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    const active = () => search.getAttribute('aria-activedescendant');
    const second = active();
    expect(second).toBeTruthy();
    const rows = screen.getAllByRole('option');
    // the browser reports "mouse enter" (and a move of zero distance) when a list re-renders beneath a resting pointer
    fireEvent.mouseEnter(rows[0]);
    fireEvent.mouseMove(rows[0], { movementX: 0, movementY: 0 });
    expect(active()).toBe(second);
    // a real movement over a row makes it the active one
    fireEvent.mouseMove(rows[0], { movementX: 3, movementY: 0 });
    expect(active()).toBe(rows[0].id);
  });

  it('Enter on a search with no highlighted row picks the best match', () => {
    const { type, search, onChoose } = setup();
    type('नर्सरी निर्माण');
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onChoose.mock.calls[0][0]).toMatchObject({ id: 1 });
  });

  it('the arrows cannot run past either end', () => {
    const { type, search } = setup();
    type('timber');
    fireEvent.keyDown(search, { key: 'ArrowUp' });
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    expect(search.getAttribute('aria-activedescendant')).toMatch(/^ap-opt-\d+$/);
  });
});

describe('filter chips', () => {
  it('"Can be shown on the map" and "Needs no map" split the list', () => {
    setup();
    fireEvent.click(screen.getByTestId('chip-map'));
    expect(count()).toBe('Showing 60 of 135 activities');
    expect(screen.getByTestId('chip-map')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByTestId('chip-map'));
    fireEvent.click(screen.getByTestId('chip-nomap'));
    expect(count()).toBe('Showing 75 of 135 activities');
  });

  it('filters combine with the typed search', () => {
    const { type } = setup();
    type('nursery');
    fireEvent.click(screen.getByTestId('chip-nomap'));
    expect(rowIds()).toEqual([41, 81]); // the two nursery activities that need no map... (training, enterprise)
  });

  it('the map-symbol chips list only symbols found, with counts', () => {
    setup();
    fireEvent.click(screen.getByTestId('toggle-symbols'));
    const nursery = screen.getByTestId('chip-kind-nursery');
    expect(nursery.textContent).toContain('Nursery (3)');
    fireEvent.click(nursery);
    expect(count()).toBe('Showing 3 of 135 activities');
  });

  it('the "measured in" chips carry counts and combine with each other', () => {
    setup();
    fireEvent.click(screen.getByTestId('toggle-units'));
    const chip = screen.getByTestId('chip-unit-हेक्टर');
    fireEvent.click(chip);
    const haOnly = count();
    fireEvent.click(screen.getByTestId('chip-unit-कि.मि.'));
    expect(count()).not.toBe(haOnly); // two units are alternatives: more results
  });

  it('"Already in my plan" / "Not in my plan yet" use the plan lines', () => {
    setup({ inPlan: { 1: [1], 4: [] } });
    fireEvent.click(screen.getByTestId('chip-inplan'));
    expect(rowIds()).toEqual([1, 4]);
    fireEvent.click(screen.getByTestId('chip-inplan'));
    fireEvent.click(screen.getByTestId('chip-notinplan'));
    expect(count()).toBe('Showing 133 of 135 activities');
  });

  it('"Clear filters" removes every chip at once', () => {
    setup();
    fireEvent.click(screen.getByTestId('chip-map'));
    fireEvent.click(screen.getByTestId('chip-inplan'));
    fireEvent.click(screen.getByTestId('clear-filters'));
    expect(count()).toBe('Showing 135 of 135 activities');
    expect(screen.queryByTestId('clear-filters')).toBeNull();
  });

  it('"Recently used" with nothing chosen yet says so, never a blank panel', () => {
    setup();
    fireEvent.click(screen.getByTestId('chip-recent'));
    expect(screen.getByTestId('recent-none')).toBeInTheDocument();
    expect(screen.getByTestId('no-match')).toBeInTheDocument();
    expect(screen.getByTestId('browse-tree')).toBeInTheDocument();
  });
});

describe('never a dead end', () => {
  it('when nothing matches: a friendly sentence, three suggestions and the browse tree opened', () => {
    const { type } = setup();
    type('xyzqq');
    expect(screen.getByTestId('no-match').textContent).toContain(
      'Nothing matches “xyzqq”. Try fewer letters or another word, or browse by group.',
    );
    expect(screen.getAllByTestId(/^suggestion-row-/)).toHaveLength(3);
    expect(screen.getByTestId('browse-tree')).toBeInTheDocument();
    expect(rowIds()).toHaveLength(135); // everything is listed, open
    expect(count()).toBe('Showing 0 of 135 activities');
  });

  it('a suggestion can be chosen straight away', () => {
    const { type, onChoose } = setup();
    type('xyzqq');
    fireEvent.click(screen.getAllByTestId(/^suggestion-row-/)[0]);
    expect(onChoose).toHaveBeenCalledTimes(1);
  });

  it('filters that leave nothing say so and keep the tree', () => {
    setup({ inPlan: {} });
    fireEvent.click(screen.getByTestId('chip-inplan')); // nothing is in the plan
    expect(screen.getByTestId('no-match').textContent).toContain('No activity matches these filters');
    expect(screen.getByTestId('browse-tree')).toBeInTheDocument();
  });

  it('the row ids stay unique when suggestions and the open tree show the same activity', () => {
    const { type } = setup();
    type('xyzqq');
    const ids = Array.from(document.querySelectorAll('[id]')).map((el) => el.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('loading, failing, empty', () => {
  it('shows a spinner while loading', () => {
    render(<ActivityPicker activities={[]} loading onChoose={vi.fn()} />);
    expect(screen.getByTestId('activity-picker-loading')).toBeInTheDocument();
  });

  it('says so and offers a retry when the list could not be loaded', () => {
    const onRetry = vi.fn();
    render(<ActivityPicker activities={[]} failed onRetry={onRetry} onChoose={vi.fn()} />);
    expect(screen.getByRole('alert').textContent).toContain('could not be loaded');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('an empty master list is explained, not blank', () => {
    render(<ActivityPicker activities={[]} onChoose={vi.fn()} />);
    expect(screen.getByTestId('activity-picker-empty').textContent).toContain('no activities');
  });
});
