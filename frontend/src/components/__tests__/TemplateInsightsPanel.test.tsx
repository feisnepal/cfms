import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import TemplateInsightsPanel from '../OperationalPlan/TemplateInsightsPanel';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, operationalPlanApi: { ...actual.operationalPlanApi, getTemplateAnalytics: vi.fn() } };
});

const ask = (api.operationalPlanApi as unknown as { getTemplateAnalytics: ReturnType<typeof vi.fn> }).getTemplateAnalytics;

const report = {
  min_owners: 2,
  templates: [{
    template_id: 't1', template_name: 'Brief FMP', plans: 4, owners: 4,
    sections: [
      { node_id: 'n2', title_en: 'Protection', title_ne: 'सुरक्षा', plans: 4, kept: 1, edited: 1, hidden: 1, removed: 1, no_data: 1, changed_pct: 75, no_data_pct: 25 },
      { node_id: 'n3', title_en: 'Monitoring', title_ne: 'अनुगमन', plans: 4, kept: 4, edited: 0, hidden: 0, removed: 0, no_data: 0, changed_pct: 0, no_data_pct: 0 },
    ],
    added_sections: [{ title: 'Fire lines', owners: 2 }],
    typed_variables: [{ variable: '{{district}}', owners: 2 }],
  }],
};

beforeEach(() => vi.clearAllMocks());

describe('TemplateInsightsPanel', () => {
  it('shows each section with what people did to it, the sections people add and the variables they type', async () => {
    ask.mockResolvedValue(report);
    render(<TemplateInsightsPanel />);
    expect(await screen.findByText('Protection')).toBeInTheDocument();
    expect(screen.getByText('Monitoring')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument(); // the No-data share of the Protection section
    expect(screen.getByTestId('insight-added').textContent).toMatch(/Fire lines/);
    expect(screen.getByTestId('insight-typed').textContent).toMatch(/\{\{district\}\}/);
    expect(ask).toHaveBeenCalledWith(2);
  });

  it('asks again when the "at least this many people" level changes', async () => {
    ask.mockResolvedValue(report);
    render(<TemplateInsightsPanel />);
    await screen.findByText('Protection');
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
    fireEvent.click(await screen.findByText('5', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(ask).toHaveBeenLastCalledWith(5));
  });

  it('says so when no plan has been built from a template yet', async () => {
    ask.mockResolvedValue({ min_owners: 2, templates: [] });
    render(<TemplateInsightsPanel />);
    expect(await screen.findByText(/No plans have been built from a template yet/i)).toBeInTheDocument();
  });
});
