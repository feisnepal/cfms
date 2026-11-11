import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// the real keys come back as text, so assertions name the message that is shown
vi.mock('../../../i18n/hooks', () => ({
  useT: () => (key: string, o?: Record<string, unknown>) => {
    const d = (o?.defaultValue as string) ?? key;
    return d.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''));
  },
}));

import { SamplingUnitTable, legalRange, perPlotPct, plotCountProblem, plotCountWarning, intensityWarning, stepIntensity } from '../SamplingUnitTable';
import type { SamplingUnitRow } from '../../../services/api';

const row = (over: Partial<SamplingUnitRow>): SamplingUnitRow => ({
  unit_id: 'u', name: 'SC1', area_ha: 10, slope_band: 2, stratum: 'production', stratum_source: 'default', management_orientation: null,
  floor_pct: 2, plot_size_sqm: 500, sampled_plots: 0, ...over,
});

const ROWS = [
  row({ unit_id: 'u1', name: 'SC1' }),
  row({ unit_id: 'u2', name: 'SC2', stratum: 'conservation', stratum_source: 'slope', floor_pct: 1 }),
  row({ unit_id: 'u3', name: 'SC3', sampled_plots: 7 }),
];

const handlers = () => ({
  onToggle: vi.fn(), onTickAll: vi.fn(), onTickNone: vi.fn(), onTickFromMap: vi.fn(), onIntensity: vi.fn(), onStratum: vi.fn(), onDeletePlots: vi.fn(),
});

const mount = (over: Record<string, unknown> = {}) => {
  const h = handlers();
  render(
    <SamplingUnitTable rows={ROWS} fieldDataExists={false} ticked={new Set()} intensities={{}} stratumLabel={(s) => s} {...h} {...over} />,
  );
  return h;
};

describe('SamplingUnitTable', () => {
  it('has one row per polygon with its stratum, the reason and the legal minimum', () => {
    mount();
    expect(screen.getByTestId('unit-row-SC1')).toBeTruthy();
    expect((screen.getByTestId('unit-stratum-SC2') as HTMLSelectElement).value).toBe('conservation');
    expect(screen.getByTestId('unit-source-SC2').textContent).toContain('unitTable.source.slope');
    expect(screen.getByTestId('unit-row-SC2').textContent).toContain('1%');
  });

  it('shows the workspace Name of the unit, not the key plots are filed under', () => {
    mount({ rows: [row({ unit_id: 'u1', name: 'CODE-1', display_name: 'North slope' })] });
    expect(screen.getByTestId('unit-row-CODE-1').textContent).toContain('North slope');
    expect(screen.getByTestId('unit-row-CODE-1').textContent).not.toContain('CODE-1');
  });

  it('says what is going to be sampled: everything without plots when nothing is ticked, only the ticked ones otherwise', () => {
    mount();
    expect(screen.getByTestId('unit-selection-note').textContent).toContain('every polygon without plots will be sampled');
    mount({ ticked: new Set(['SC1']) });
    expect(screen.getAllByTestId('unit-selection-note')[1].textContent).toContain('Only the ticked polygons');
  });

  it('a polygon that already has plots: checkbox disabled, written advice in the row, and the hover tells what to do next', () => {
    mount();
    const box = screen.getByTestId('unit-tick-SC3') as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(box.checked).toBe(false);
    expect(box.title).toContain('already has 7 sample plots');
    expect(box.title).toContain('first delete its plots');
    expect(screen.getByTestId('unit-sampled-SC3').textContent).toContain('To sample it again, first delete its plots');
    expect((screen.getByTestId('unit-tick-SC1') as HTMLInputElement).disabled).toBe(false);
  });

  it('the intensity of a polygon that already has plots cannot be edited', () => {
    mount();
    const inputs = screen.getAllByLabelText('sampling.stratumTableIntensityFor') as HTMLInputElement[];
    expect(inputs.map((i) => i.disabled)).toEqual([false, false, true]);
  });

  it('"Delete this polygon\'s plots" is offered, and calls back with the row', () => {
    const h = mount();
    fireEvent.click(screen.getByTestId('unit-delete-plots-SC3'));
    expect(h.onDeletePlots).toHaveBeenCalledWith(expect.objectContaining({ name: 'SC3' }));
  });

  it('once field inventory exists the plots cannot be deleted: the button is disabled and the hover explains the way out', () => {
    mount({ fieldDataExists: true });
    const btn = screen.getByTestId('unit-delete-plots-SC3') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain('field inventory data now exists');
    expect(btn.title).toContain('delete the field inventory first');
    expect((screen.getByTestId('unit-tick-SC3') as HTMLInputElement).title).toContain('field inventory data now exists');
  });

  it('Tick all / Clear / ticking a row call back; "from the map" appears only when polygons are selected there', () => {
    const h = mount({ mapSelectedIds: ['u2'] });
    fireEvent.click(screen.getByTestId('unit-tick-all'));
    fireEvent.click(screen.getByTestId('unit-tick-none'));
    fireEvent.click(screen.getByTestId('unit-tick-SC1'));
    fireEvent.click(screen.getByTestId('unit-tick-map'));
    expect(h.onTickAll).toHaveBeenCalled();
    expect(h.onTickNone).toHaveBeenCalled();
    expect(h.onToggle).toHaveBeenCalledWith('SC1');
    expect(h.onTickFromMap).toHaveBeenCalled();
    expect(screen.getByTestId('unit-tick-map').textContent).toContain('1 polygon');
  });

  it('a map selection that is only polygons which already have plots offers nothing', () => {
    mount({ mapSelectedIds: ['u3'] });
    expect(screen.queryByTestId('unit-tick-map')).toBeNull();
  });

  it('changing the stratum calls back with the row and the new stratum', () => {
    const h = mount();
    fireEvent.change(screen.getByTestId('unit-stratum-SC1'), { target: { value: 'protection' } });
    expect(h.onStratum).toHaveBeenCalledWith(expect.objectContaining({ name: 'SC1' }), 'protection');
  });

  it('flags an intensity below the minimum only for a polygon that will be sampled', () => {
    mount({ intensities: { SC1: 1.5, SC2: 0.5 }, ticked: new Set(['SC1']) });
    expect(screen.getByTestId('unit-row-SC1').textContent).toContain('sampling.stratumBelowFloor');
    expect(screen.getByTestId('unit-row-SC2').textContent).not.toContain('sampling.stratumBelowFloor'); // not ticked: not sampled
  });
});


describe('the legal range of plots for a polygon', () => {
  // a 10 ha polygon with 500 m2 plots: one plot is 0.5 % of it
  const r = row({ area_ha: 10, plot_size_sqm: 500, floor_pct: 2 });

  it('is the minimum intensity of the stratum up to the 5 % ceiling', () => {
    expect(perPlotPct(r)).toBeCloseTo(0.5, 6);
    expect(legalRange(r)).toEqual({ min: 4, max: 10 });
    expect(legalRange(row({ area_ha: 10, plot_size_sqm: 500, floor_pct: 1 }))).toEqual({ min: 2, max: 10 });
    expect(legalRange(row({ area_ha: 100, plot_size_sqm: 500, floor_pct: 2 }))).toEqual({ min: 40, max: 100 });
  });

  it('allows fewer than 5, rejects what is below the minimum or above the ceiling, and lets 0 leave the polygon out', () => {
    expect(plotCountProblem(r, 4)).toBeNull(); // fewer than the usual 5, still legal
    expect(plotCountProblem(r, 3)).toBe('low');
    expect(plotCountProblem(r, 11)).toBeNull(); // above the usual 5 %: a warning, not a problem
    expect(plotCountWarning(r, 11)).toBe(true);
    expect(plotCountWarning(r, 6)).toBe(false);
    expect(intensityWarning(5.1)).toBe(true);
    expect(intensityWarning(5)).toBe(false);
    expect(plotCountProblem(r, 0)).toBeNull();
    expect(plotCountProblem(r, undefined)).toBeNull();
  });

  it('the up and down arrows change the intensity by 0.1, from the number shown (the floor when nothing was typed)', () => {
    const h = mount({ intensities: { SC1: 2.5 } });
    const sc1 = screen.getByTestId('unit-intensity-SC1');
    fireEvent.keyDown(sc1, { key: 'ArrowUp' });
    expect(h.onIntensity).toHaveBeenLastCalledWith('SC1', 2.6);
    fireEvent.keyDown(sc1, { key: 'ArrowDown' });
    expect(h.onIntensity).toHaveBeenLastCalledWith('SC1', 2.4);
    // SC2 has nothing typed: it shows its floor (1) and steps from it
    fireEvent.keyDown(screen.getByTestId('unit-intensity-SC2'), { key: 'ArrowUp' });
    expect(h.onIntensity).toHaveBeenLastCalledWith('SC2', 1.1);
    // other keys do nothing here
    h.onIntensity.mockClear();
    fireEvent.keyDown(sc1, { key: 'a' });
    expect(h.onIntensity).not.toHaveBeenCalled();
  });

  it('an intensity raised above the usual 5 % is only warned about, never marked as a violation', () => {
    mount({ intensities: { SC1: 6.2 } });
    expect(screen.getByTestId('unit-intensity-above-SC1').textContent).toContain('intensityAboveUsual');
    expect(screen.queryByTestId('unit-intensity-above-SC2')).toBeNull();
    expect((screen.getByTestId('unit-intensity-SC1') as HTMLInputElement).className).not.toContain('border-red-500');
  });

  it('a polygon that already has plots cannot be stepped: its field is disabled (a browser sends no key to it)', () => {
    mount();
    expect((screen.getByTestId('unit-intensity-SC3') as HTMLInputElement).disabled).toBe(true);
  });
})

describe('stepIntensity', () => {
  it('steps by exactly 0.1 with no floating-point residue', () => {
    let v = 0;
    for (let i = 0; i < 3; i += 1) v = stepIntensity(v, 1);
    expect(v).toBe(0.3);
    expect(stepIntensity(0.3, -1)).toBe(0.2);
    expect(stepIntensity(1.7, 1)).toBe(1.8);
  })

  it('never goes below 0, has no upper stop (above 5 % is only a warning), and starts from 0 on a non-number', () => {
    expect(stepIntensity(0, -1)).toBe(0);
    expect(stepIntensity(5, 1)).toBe(5.1);
    expect(stepIntensity(7.4, 1)).toBe(7.5);
    expect(stepIntensity(NaN, 1)).toBe(0.1);
  })

});
