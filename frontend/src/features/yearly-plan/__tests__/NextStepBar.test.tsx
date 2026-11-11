/**
 * The Next-step bar on the map (P2): the same one step as the yearly-plan page, in the same words, with the
 * right button for where the step is done, and it can be folded away.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import en from '../../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../../i18n/numberFormat', () => ({ formatNumber: (n: number) => String(n), formatDecimal: (n: number) => String(n) }));
vi.mock('../../../services/api', () => ({ yearlyPlanApi: { getHealth: vi.fn() } }));

import { yearlyPlanApi } from '../../../services/api';
import { NextStepBar } from '../NextStepBar';

const getHealth = (yearlyPlanApi as unknown as { getHealth: ReturnType<typeof vi.fn> }).getHealth;

const health = (code: string, extra: Record<string, unknown> = {}, action = 'show_on_map') => ({
  summary: { ready: 0, needs_attention: 1, total: 1, total_budget: 5000 },
  next_step: { code, activity_id: 'L1', activity: 'Nursery', params: {}, action, ...extra },
  items: [],
  plan_issues: [],
});

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function setup(h: unknown) {
  getHealth.mockResolvedValue(h);
  const onShowLayer = vi.fn();
  const onOpenPlan = vi.fn();
  render(<NextStepBar calculationId="c1" onShowLayer={onShowLayer} onOpenPlan={onOpenPlan} />);
  return { onShowLayer, onOpenPlan };
}

describe('NextStepBar', () => {
  it('says the one next step in the same plain words as the plan page', async () => {
    setup(health('NO_LOCATION'));
    const bar = await screen.findByTestId('next-step-bar');
    expect(bar.textContent).toContain('“Nursery” has no place on the map yet');
    expect(bar).toHaveAttribute('data-step', 'NO_LOCATION');
  });

  it('a step done on the map turns the Activity Features layer on', async () => {
    const { onShowLayer, onOpenPlan } = setup(health('NO_LOCATION'));
    fireEvent.click(await screen.findByRole('button', { name: 'Show Activity Features' }));
    expect(onShowLayer).toHaveBeenCalledTimes(1);
    expect(onOpenPlan).not.toHaveBeenCalled();
  });

  it('a step that is not done on the map opens the yearly plan', async () => {
    const { onShowLayer, onOpenPlan } = setup(
      health('PLACEHOLDER_NUMBERS', { params: { fields: ['quantity', 'budget'] } }, 'enter_numbers'),
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Open the yearly plan' }));
    expect(onOpenPlan).toHaveBeenCalledTimes(1);
    expect(onShowLayer).not.toHaveBeenCalled();
  });

  it('an empty plan points at the layer where places are drawn', async () => {
    const h = health('EMPTY_PLAN', { activity_id: null, activity: null }, 'add_first_activity');
    h.summary = { ready: 0, needs_attention: 0, total: 0, total_budget: 0 };
    const { onShowLayer } = setup(h);
    fireEvent.click(await screen.findByRole('button', { name: 'Show Activity Features' }));
    expect(onShowLayer).toHaveBeenCalled();
  });

  it('when everything is ready it says so and offers no button', async () => {
    const h = health('ALL_READY', { activity_id: null, activity: null }, 'create_plan');
    h.summary = { ready: 1, needs_attention: 0, total: 1, total_budget: 5000 };
    setup(h);
    const bar = await screen.findByTestId('next-step-bar');
    expect(bar).toHaveAttribute('data-step', 'ALL_READY');
    expect(screen.queryByTestId('next-step-bar-action')).toBeNull();
  });

  it('can be folded away, comes back as a pill, and remembers the choice in this browser', async () => {
    setup(health('NO_LOCATION'));
    fireEvent.click(await screen.findByTestId('next-step-bar-hide'));
    expect(screen.queryByTestId('next-step-bar')).toBeNull();
    expect(window.localStorage.getItem('cfms.yearlyPlan.mapBarHidden')).toBe('1');
    fireEvent.click(screen.getByTestId('next-step-pill'));
    expect(screen.getByTestId('next-step-bar')).toBeInTheDocument();
    expect(window.localStorage.getItem('cfms.yearlyPlan.mapBarHidden')).toBeNull();
  });

  it('starts folded when the person folded it before', async () => {
    window.localStorage.setItem('cfms.yearlyPlan.mapBarHidden', '1');
    setup(health('NO_LOCATION'));
    expect(await screen.findByTestId('next-step-pill')).toBeInTheDocument();
    expect(screen.queryByTestId('next-step-bar')).toBeNull();
  });

  it('shows nothing until the plan has been read, and nothing when it cannot be read', async () => {
    getHealth.mockRejectedValue(new Error('offline'));
    render(<NextStepBar calculationId="c1" onShowLayer={vi.fn()} onOpenPlan={vi.fn()} />);
    await waitFor(() => expect(getHealth).toHaveBeenCalled());
    expect(screen.queryByTestId('next-step-bar')).toBeNull();
    expect(screen.queryByTestId('next-step-pill')).toBeNull();
  });
});

describe('NextStepBar — with the add-activity wizard', () => {
  function setupWizard(h: unknown) {
    getHealth.mockResolvedValue(h);
    const onShowLayer = vi.fn();
    const onOpenPlan = vi.fn();
    const onFixStep = vi.fn();
    const onAddActivity = vi.fn();
    render(<NextStepBar calculationId="c1" onShowLayer={onShowLayer} onOpenPlan={onOpenPlan} onFixStep={onFixStep} onAddActivity={onAddActivity} />);
    return { onShowLayer, onOpenPlan, onFixStep, onAddActivity };
  }

  it('"show it on the map" hands the step to the wizard instead of just turning the layer on', async () => {
    const { onFixStep, onShowLayer } = setupWizard(health('NO_LOCATION'));
    fireEvent.click(await screen.findByRole('button', { name: 'Show it on the map' }));
    expect(onFixStep).toHaveBeenCalledTimes(1);
    expect(onFixStep.mock.calls[0][0]).toMatchObject({ key: 'NO_LOCATION', action: 'show_on_map', activityId: 'L1' });
    expect(onShowLayer).not.toHaveBeenCalled();
  });

  it('always offers "Add activity" next to a step, and it opens the wizard', async () => {
    const { onAddActivity } = setupWizard(health('NO_LOCATION'));
    fireEvent.click(await screen.findByTestId('next-step-bar-add'));
    expect(onAddActivity).toHaveBeenCalledTimes(1);
  });

  it('an empty plan has ONE button, "Add activity" — not two', async () => {
    const h = health('EMPTY_PLAN', { activity_id: null, activity: null }, 'add_first_activity');
    h.summary = { ready: 0, needs_attention: 0, total: 0, total_budget: 0 };
    const { onFixStep } = setupWizard(h);
    const buttons = await screen.findAllByRole('button', { name: 'Add activity' });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onFixStep).toHaveBeenCalledTimes(1);
  });

  it('a step that is not done on the map still opens the yearly plan', async () => {
    const { onOpenPlan, onFixStep } = setupWizard(health('PLACEHOLDER_NUMBERS', { params: { fields: ['quantity', 'budget'] } }, 'enter_numbers'));
    fireEvent.click(await screen.findByRole('button', { name: 'Open the yearly plan' }));
    expect(onOpenPlan).toHaveBeenCalled();
    expect(onFixStep).not.toHaveBeenCalled();
  });
});
