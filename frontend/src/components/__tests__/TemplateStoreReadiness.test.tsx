import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TemplateStoreReadiness from '../TemplateStoreReadiness';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, operationalPlanApi: { ...actual.operationalPlanApi, getExportRequirementsForCalculation: vi.fn() } };
});

const ask = (api.operationalPlanApi as unknown as { getExportRequirementsForCalculation: ReturnType<typeof vi.fn> })
  .getExportRequirementsForCalculation;

const item = (key: string, done: boolean) => ({
  key, step: 'x', done, label_en: key, label_ne: key, hint_en: `fix ${key}`, hint_ne: `fix ${key}`, detail: {},
});

const show = () => render(<MemoryRouter><TemplateStoreReadiness calculationId="c1" /></MemoryRouter>);

beforeEach(() => vi.clearAllMocks());

describe('TemplateStoreReadiness', () => {
  it('says so when every required step is done', async () => {
    ask.mockResolvedValue({ ready: true, items: [item('a', true), item('b', true)] });
    show();
    expect(await screen.findByTestId('store-readiness-ready')).toBeInTheDocument();
  });

  it('counts the open steps and never blocks', async () => {
    ask.mockResolvedValue({ ready: false, items: [item('a', true), item('b', false), item('c', false)] });
    show();
    const box = await screen.findByTestId('store-readiness-open');
    expect(box.textContent).toMatch(/2 of 3/);
  });

  it('shows nothing when the checklist cannot be loaded (the export enforces it anyway)', async () => {
    ask.mockRejectedValue(new Error('x'));
    const { container } = show();
    await new Promise((r) => setTimeout(r, 30));
    expect(container.querySelector('[data-testid^="store-readiness"]')).toBeNull();
  });
});
