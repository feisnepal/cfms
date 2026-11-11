import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';

vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, o?: Record<string, unknown>) => (o?.defaultValue as string) ?? key,
}));
vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({ canUndo: false, canRedo: false, undo: vi.fn(), redo: vi.fn(), pushOp: vi.fn(), pushAndExecute: vi.fn() }),
}));

import { OpacitySpinner, stepPercent, clampPercent } from '../OpacitySpinner';
import LayerContextMenu from '../LayerContextMenu';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { layerStyleKey } from '../../lib/layerStyles';
import { buildLayerMenu, type LayerMenuContext } from '../../lib/layerMenu';

describe('stepPercent / clampPercent', () => {
  it('steps to the next multiple of 10, so a value typed off the grid comes back onto it', () => {
    expect(stepPercent(85, 1)).toBe(90);
    expect(stepPercent(85, -1)).toBe(80);
    expect(stepPercent(80, 1)).toBe(90);
    expect(stepPercent(80, -1)).toBe(70);
    expect(stepPercent(95, 1)).toBe(100);
    expect(stepPercent(100, 1)).toBe(100);
    expect(stepPercent(5, -1)).toBe(0);
    expect(stepPercent(0, -1)).toBe(0);
  });
  it('clamps and rounds', () => {
    expect([clampPercent(-4), clampPercent(104), clampPercent(47.6)]).toEqual([0, 100, 48]);
  });
});

function Harness({ start = 80, onChange }: { start?: number; onChange?: (v: number) => void }) {
  const [v, setV] = useState(start);
  return <OpacitySpinner value={v} onChange={(n) => { setV(n); onChange?.(n); }} ariaLabel="Layer opacity" />;
}
const input = () => screen.getByRole('textbox', { name: 'Layer opacity' }) as HTMLInputElement;

describe('OpacitySpinner — 80% ▲▼', () => {
  it('the ▲ and ▼ buttons step by 10 and stop at the ends (the button is disabled there)', () => {
    render(<Harness start={90} />);
    fireEvent.click(screen.getByRole('button', { name: 'More opaque' }));
    expect(input().value).toBe('100');
    expect((screen.getByRole('button', { name: 'More opaque' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'More transparent' }));
    expect(input().value).toBe('90');
  });

  it('the keyboard ↑ and ↓ work in the field too, by 10, alongside the buttons', () => {
    const onChange = vi.fn();
    render(<Harness start={80} onChange={onChange} />);
    input().focus();
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(input().value).toBe('70');
    fireEvent.keyDown(input(), { key: 'ArrowUp' });
    fireEvent.keyDown(input(), { key: 'ArrowUp' });
    expect(input().value).toBe('90');
    fireEvent.click(screen.getByRole('button', { name: 'More transparent' })); // mixing both is fine
    expect(input().value).toBe('80');
    expect(onChange.mock.calls.map((c) => c[0])).toEqual([70, 80, 90, 80]);
  });

  it('typing is committed on Enter or on leaving the field, clamped to 0-100; junk keeps the old value', () => {
    const onChange = vi.fn();
    render(<Harness start={80} onChange={onChange} />);
    fireEvent.change(input(), { target: { value: '45' } });
    expect(onChange).not.toHaveBeenCalled(); // still typing
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith(45);
    fireEvent.change(input(), { target: { value: '250' } });
    fireEvent.blur(input());
    expect(onChange).toHaveBeenLastCalledWith(100);
    fireEvent.change(input(), { target: { value: '' } });
    fireEvent.blur(input());
    expect(input().value).toBe('100'); // nothing typed: the old value is back
  });

  it('only digits can be typed', () => {
    render(<Harness start={80} />);
    fireEvent.change(input(), { target: { value: '7a%5' } });
    expect(input().value).toBe('75');
  });

  it('Escape undoes typing first; with nothing typed it is left to close the menu', () => {
    render(<Harness start={80} />);
    fireEvent.change(input(), { target: { value: '33' } });
    const stopped = fireEvent.keyDown(input(), { key: 'Escape' });
    expect(input().value).toBe('80');
    expect(stopped).toBe(true);
  });
});

describe('the Opacity row in the layer menu', () => {
  const calc = 'calc-1';
  const props = {
    layerId: 'sub_areas', layerType: 'builtin' as const, layerName: 'Sub-Areas', visible: true, labelsShown: false, featureCount: 4,
    editable: true, locked: false, position: { x: 10, y: 10 }, onClose: vi.fn(), map: null,
  };
  const alpha = () => useWorkspaceStore.getState().layerAlpha[layerStyleKey('sub_areas', 'builtin', calc)];
  beforeEach(() => {
    props.onClose.mockReset();
    useWorkspaceStore.setState({ calculationId: calc, layerAlpha: {} });
  });

  it('is offered for a built-in layer, shows the current opacity, and changes it without closing the menu', () => {
    useWorkspaceStore.setState({ layerAlpha: { [layerStyleKey('sub_areas', 'builtin', calc)]: 0.8 } });
    render(<LayerContextMenu {...props} />);
    const row = screen.getByRole('group', { name: 'layerPanel.layerOpacity' });
    expect(row).toBeTruthy();
    const field = () => screen.getByRole('textbox', { name: 'layerPanel.layerOpacity' }) as HTMLInputElement;
    expect(field().value).toBe('80');
    fireEvent.click(screen.getByRole('button', { name: 'More transparent' }));
    expect(alpha()).toBeCloseTo(0.7);
    expect(field().value).toBe('70');
    expect(props.onClose).not.toHaveBeenCalled(); // a spinner is not an action
  });

  it('arrow keys in the field step the opacity and do NOT move the menu focus to another row', () => {
    useWorkspaceStore.setState({ layerAlpha: { [layerStyleKey('sub_areas', 'builtin', calc)]: 0.5 } });
    render(<LayerContextMenu {...props} />);
    const field = screen.getByRole('textbox', { name: 'layerPanel.layerOpacity' }) as HTMLInputElement;
    field.focus();
    fireEvent.keyDown(field, { key: 'ArrowUp' });
    expect(alpha()).toBeCloseTo(0.6);
    expect(document.activeElement).toBe(field);
    fireEvent.keyDown(field, { key: 'ArrowDown' });
    fireEvent.keyDown(field, { key: 'ArrowDown' });
    expect(alpha()).toBeCloseTo(0.4);
    expect(document.activeElement).toBe(field);
  });

  it('typing 35 sets 35%; a layer never touched reads 100', () => {
    render(<LayerContextMenu {...props} />);
    const field = screen.getByRole('textbox', { name: 'layerPanel.layerOpacity' }) as HTMLInputElement;
    expect(field.value).toBe('100');
    fireEvent.change(field, { target: { value: '35' } });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(alpha()).toBeCloseTo(0.35);
  });

  it('an imported layer has no whole-layer opacity row (it has none to change)', () => {
    render(<LayerContextMenu {...props} layerType="imported" layerId="imp1" />);
    expect(screen.queryByRole('group', { name: 'layerPanel.layerOpacity' })).toBeNull();
  });
});

describe('layerMenu data', () => {
  const ctx: LayerMenuContext = { layerId: 'blocks', kind: 'builtin', layerName: 'Blocks', visible: true, labelsShown: false, featureCount: 3, editable: true, readOnly: false, locked: false };
  it('carries the opacity row, with 0-100 in steps of 10, only when the host supplies a value', () => {
    const row = buildLayerMenu({ ...ctx, opacityPercent: 80 }).find((i) => i.id === 'opacity')!;
    expect(row.spinner).toEqual({ value: 80, min: 0, max: 100, step: 10 });
    expect(buildLayerMenu(ctx).some((i) => i.id === 'opacity')).toBe(false);
    expect(buildLayerMenu({ ...ctx, opacityPercent: 140 }).find((i) => i.id === 'opacity')!.spinner!.value).toBe(100);
  });
});
