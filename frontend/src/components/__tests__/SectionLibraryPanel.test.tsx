import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SectionLibraryPanel from '../SectionLibraryPanel';
import * as api from '../../services/api';

vi.mock('../../contexts/AuthContext', async (orig) => ({
  ...(await orig<typeof import('../../contexts/AuthContext')>()),
  useAuth: () => ({ user: { id: 'u1', role: 'user' } }),
}));

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, operationalPlanApi: { ...actual.operationalPlanApi, listSections: vi.fn(), deleteTemplate: vi.fn() } };
});

const op = api.operationalPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const sec = (over: Record<string, unknown> = {}) => ({
  id: 's1', name: 'Terai sal management', description: 'How the sal coppice is managed in the Terai.', status: 'published',
  share_scope: 'public', tier: 'community', license: 'cc_by', author_name: 'R. Sharma', created_by: 'someone',
  sections_summary: ['a', 'b'], variables_summary: ['x'], ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('SectionLibraryPanel', () => {
  it('lists shared sections with their author and licence', async () => {
    op.listSections.mockResolvedValue({ total: 1, sections: [sec()] });
    render(<SectionLibraryPanel mode="browse" />);
    expect(await screen.findByText('Terai sal management')).toBeInTheDocument();
    expect(screen.getByText(/by R\. Sharma/)).toBeInTheDocument();
    expect(op.listSections).toHaveBeenCalledWith('published', undefined);
  });

  it('in insert mode every card has an Insert button that hands the section back', async () => {
    op.listSections.mockResolvedValue({ total: 1, sections: [sec()] });
    const onInsert = vi.fn();
    render(<SectionLibraryPanel mode="insert" onInsert={onInsert} />);
    fireEvent.click(await screen.findByTestId('insert-s1'));
    expect(onInsert).toHaveBeenCalledWith(expect.objectContaining({ id: 's1' }));
  });

  it('my own sections can be shared or deleted; other people\'s can be reported', async () => {
    op.listSections.mockResolvedValue({ total: 2, sections: [sec({ id: 'mine', name: 'Mine', created_by: 'u1', status: 'draft', share_scope: 'private' }), sec({ id: 'theirs', name: 'Theirs' })] });
    render(<SectionLibraryPanel mode="browse" initialScope="mine" />);
    await screen.findByText('Mine');
    const mine = screen.getByTestId('section-mine');
    const theirs = screen.getByTestId('section-theirs');
    expect(mine.textContent).toMatch(/Share/);
    expect(mine.textContent).toMatch(/Delete/);
    expect(theirs.textContent).toMatch(/Report/);
    expect(theirs.textContent).not.toMatch(/Delete/);
  });

  it('says so when the library is empty', async () => {
    op.listSections.mockResolvedValue({ total: 0, sections: [] });
    render(<SectionLibraryPanel mode="browse" />);
    expect(await screen.findByText(/No shared sections yet/i)).toBeInTheDocument();
  });

  it('switching to My sections asks for the author\'s own', async () => {
    op.listSections.mockResolvedValue({ total: 0, sections: [] });
    render(<SectionLibraryPanel mode="browse" />);
    await screen.findByText(/No shared sections yet/i);
    fireEvent.click(screen.getByText('My sections'));
    await waitFor(() => expect(op.listSections).toHaveBeenLastCalledWith('mine', undefined));
  });
});
