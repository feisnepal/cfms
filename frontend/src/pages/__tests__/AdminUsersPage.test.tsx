import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const get = vi.fn();
const patch = vi.fn();
const post = vi.fn();
vi.mock('../../services/api', () => ({ default: { get: (...a: unknown[]) => get(...a), patch: (...a: unknown[]) => patch(...a), post: (...a: unknown[]) => post(...a) } }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'me', role: 'super_admin' } }) }));
vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, o?: Record<string, unknown>) => {
    const d = (o?.defaultValue as string) ?? key;
    return d.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''));
  },
}));

import AdminUsersPage from '../AdminUsersPage';

const USERS = [
  { id: 'me', email: 'super@forest.com', full_name: 'Super', role: 'super_admin', status: 'active', created_at: '2026-01-01', last_login: null },
  { id: 'u1', email: 'ram@example.com', full_name: 'Ram', role: 'user', status: 'active', created_at: '2026-01-02', last_login: null },
  { id: 'u2', email: 'sita@example.com', full_name: 'Sita', role: 'user', status: 'pending', created_at: '2026-01-03', last_login: null },
];
const ROLES = [
  { value: 'user', label: 'User', description: '' },
  { value: 'template_designer', label: 'Template Designer', description: 'Authors templates' },
  { value: 'super_admin', label: 'Super Admin', description: '' },
];

describe('Users and roles (super admin panel)', () => {
  beforeEach(() => {
    get.mockReset(); patch.mockReset(); post.mockReset();
    get.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/roles') ? ROLES : USERS }));
    patch.mockResolvedValue({ data: {} });
    post.mockResolvedValue({ data: {} });
  });

  it('lists the accounts with their status', async () => {
    render(<AdminUsersPage />);
    await waitFor(() => expect(screen.getByText('ram@example.com')).toBeTruthy());
    expect(screen.getByText('Waiting for approval')).toBeTruthy();
    expect(screen.getByText('super@forest.com')).toBeTruthy();
  });

  it('cannot change your own role: the dropdown is disabled on your row and offered on the others', async () => {
    render(<AdminUsersPage />);
    await waitFor(() => expect(screen.getByTestId('role-select-super@forest.com')).toBeTruthy());
    expect(screen.getByTestId('role-select-super@forest.com').className).toContain('ant-select-disabled');
    expect(screen.getByTestId('role-select-ram@example.com').className).not.toContain('ant-select-disabled');
    expect(screen.queryByTestId('suspend-super@forest.com')).toBeNull(); // nor suspend yourself
  });

  it('a pending account is approved with one click', async () => {
    render(<AdminUsersPage />);
    await waitFor(() => expect(screen.getByTestId('approve-sita@example.com')).toBeTruthy());
    fireEvent.click(screen.getByTestId('approve-sita@example.com'));
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/auth/users/u2/approve'));
    expect(screen.getByTestId('suspend-ram@example.com')).toBeTruthy(); // an active account offers Suspend
  });

  it('asks the server for the role list and the users (the roles are not hard-coded here)', async () => {
    render(<AdminUsersPage />);
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/admin/users/roles'));
    expect(get).toHaveBeenCalledWith('/api/admin/users', { params: { q: undefined, role: undefined } });
  });
});
