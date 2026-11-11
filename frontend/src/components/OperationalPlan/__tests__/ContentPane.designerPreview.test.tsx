import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuthContext } from '../../../contexts/AuthContext';
import ContentPane from '../ContentPane';
import * as api from '../../../services/api';

vi.mock('../VariablePicker', () => ({ default: () => <div data-testid="varpicker" /> }));
vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      previewTemplateWithForest: vi.fn().mockResolvedValue('<html><body>section</body></html>'),
      previewOperationalPlanSection: vi.fn(),
    },
  };
});

const mockOp = api.operationalPlanApi as unknown as {
  previewTemplateWithForest: ReturnType<typeof vi.fn>;
};

const NODE = {
  id: 'n_intro', type: 'section', title_ne: 'परिचय', title_en: 'Intro', level: 0,
  content_type: 'richtext', content: '{{forest_name}} परिचय', children: [],
  is_locked: false, hidden_in_export: false, deleted: false,
} as never;

const withRole = (role: string, ui: React.ReactNode) => (
  <AuthContext.Provider value={{ user: { role } } as never}>{ui}</AuthContext.Provider>
);

beforeEach(() => mockOp.previewTemplateWithForest.mockClear());

describe('ContentPane — template designer preview', () => {
  it('previews the section against the chosen forest via the transient endpoint', async () => {
    render(withRole('super_admin', (
      <ContentPane
        node={NODE}
        planId=""
        templatePreview={{ templateId: 't1', calculationId: 'c1' }}
      />
    )));
    fireEvent.click(screen.getByRole('button', { name: /preview/i }));
    await waitFor(() =>
      expect(mockOp.previewTemplateWithForest).toHaveBeenCalledWith('t1', 'c1', 'values', 'n_intro'),
    );
  });

  it('renders a hint and calls nothing when no forest is chosen', async () => {
    const { container } = render(withRole('super_admin', (
      <ContentPane node={NODE} planId="" templatePreview={{ templateId: 't1' }} />
    )));
    fireEvent.click(screen.getByRole('button', { name: /preview/i }));
    // the hint lands in the preview iframe's srcDoc
    await waitFor(() => {
      const iframe = container.querySelector('iframe');
      expect(iframe?.getAttribute('srcdoc') || '').toMatch(/pick a forest/i);
    });
    expect(mockOp.previewTemplateWithForest).not.toHaveBeenCalled();
  });
});
