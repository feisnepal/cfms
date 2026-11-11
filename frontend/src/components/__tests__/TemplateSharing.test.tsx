import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ShareTemplateModal from '../ShareTemplateModal';
import TemplateReportsPanel from '../OperationalPlan/TemplateReportsPanel';
import { TierTag, AuthorLine } from '../TemplateCredit';
import * as api from '../../services/api';

let currentUser: any = { id: 'u1', role: 'user', organization_id: 'org1' };
vi.mock('../../contexts/AuthContext', async (orig) => ({
  ...(await orig<typeof import('../../contexts/AuthContext')>()),
  useAuth: () => ({ user: currentUser }),
}));

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      checkTemplateForSharing: vi.fn(),
      shareTemplate: vi.fn(),
      listTemplateReports: vi.fn(),
      handleTemplateReport: vi.fn(),
    },
  };
});

const op = api.operationalPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const tpl = { id: 't1', name: 'Hill plan', share_scope: 'private', license: 'cc_by' };

beforeEach(() => {
  vi.clearAllMocks();
  currentUser = { id: 'u1', role: 'user', organization_id: 'org1' };
});

describe('ShareTemplateModal', () => {
  it('checks the template and lets the author share when nothing is wrong', async () => {
    op.checkTemplateForSharing.mockResolvedValue({ ok: true, errors: [], warnings: [] });
    op.shareTemplate.mockResolvedValue({});
    const onShared = vi.fn();
    render(<ShareTemplateModal open template={tpl} onClose={() => {}} onShared={onShared} />);
    await screen.findByText(/Nothing stops this template/i);
    fireEvent.click(screen.getByTestId('share-ok'));
    await waitFor(() => expect(op.shareTemplate).toHaveBeenCalledWith('t1', 'public', 'cc_by'));
    expect(onShared).toHaveBeenCalled();
  });

  it('shows what must be fixed and blocks sharing', async () => {
    op.checkTemplateForSharing.mockResolvedValue({
      ok: false,
      errors: [{ severity: 'error', code: 'forest_name_inside', message: 'x', name: 'Sundar CF', title: 'Intro' }],
      warnings: [{ severity: 'warning', code: 'typed_numbers', message: 'y', numbers: ['250.5'] }],
    });
    render(<ShareTemplateModal open template={tpl} onClose={() => {}} onShared={() => {}} />);
    const err = await screen.findByTestId('share-issue-forest_name_inside');
    expect(err.textContent).toMatch(/Sundar CF/);
    expect(screen.getByTestId('share-issue-typed_numbers').textContent).toMatch(/250\.5/);
    expect(screen.getByTestId('share-ok')).toBeDisabled();
  });

  it('turns off "my office" for a user who has no office', async () => {
    currentUser = { id: 'u1', role: 'user' };
    op.checkTemplateForSharing.mockResolvedValue({ ok: true, errors: [], warnings: [] });
    render(<ShareTemplateModal open template={tpl} onClose={() => {}} onShared={() => {}} />);
    await screen.findByText(/not part of an office/i);
    const office = screen.getByRole('radio', { name: /my office/i });
    expect(office).toBeDisabled();
  });
});

describe('TemplateReportsPanel', () => {
  it('lists open reports and dismisses one', async () => {
    op.listTemplateReports.mockResolvedValue({
      total: 1,
      reports: [{ id: 'r1', template_id: 't1', template_name: 'Hill plan', template_status: 'published', share_scope: 'public',
        reason: 'wrong advice on slopes', status: 'open', reporter: 'Sita', created_at: '2026-10-17T00:00:00Z', handled_note: null }],
    });
    op.handleTemplateReport.mockResolvedValue({ id: 'r1', status: 'dismissed' });
    render(<MemoryRouter><TemplateReportsPanel /></MemoryRouter>);
    await screen.findByText('wrong advice on slopes');
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    await waitFor(() => expect(op.handleTemplateReport).toHaveBeenCalledWith('r1', 'dismiss'));
  });

  it('says so when there are no reports', async () => {
    op.listTemplateReports.mockResolvedValue({ total: 0, reports: [] });
    render(<MemoryRouter><TemplateReportsPanel /></MemoryRouter>);
    await screen.findByText(/No open reports/i);
  });
});

describe('credit pieces', () => {
  it('shows the trust level and the author', () => {
    render(<><TierTag tier="verified" /><AuthorLine name="R. Sharma" /></>);
    expect(screen.getByTestId('tier-tag').textContent).toBe('Verified');
    expect(screen.getByText(/by R\. Sharma/)).toBeInTheDocument();
  });
  it('shows nothing for an author nobody may name', () => {
    const { container } = render(<AuthorLine name={null} />);
    expect(container.textContent).toBe('');
  });
});
