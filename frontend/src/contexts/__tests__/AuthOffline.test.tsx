/**
 * A field team working offline must not be signed out for want of a signal: a failed "who am I" call with no answer at all keeps the session, and the server's own refusal still
 * ends it. (The idle and expired-token checks also skip their logout while offline; they are not tested here because those timers read `user` from the first render, when it is still
 * null, so they never fire at all: an existing defect, noted in NTFP_INVENTORY_TRACKER.md.)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AuthProvider, useAuth } from '../AuthContext';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, authApi: { ...actual.authApi, me: vi.fn(), logout: vi.fn().mockResolvedValue(undefined), refresh: vi.fn() } };
});
const me = api.authApi.me as unknown as ReturnType<typeof vi.fn>;
const logoutApi = api.authApi.logout as unknown as ReturnType<typeof vi.fn>;

const USER = { id: 'u1', email: 'a@b.c', full_name: 'Field Worker', role: 'user' };

function Who() {
  const { user, isLoading } = useAuth();
  return <div data-testid="who">{isLoading ? 'loading' : user ? `in:${user.email}` : 'out'}</div>;
}
const renderAuth = () => render(<AuthProvider><Who /></AuthProvider>);
const setOnline = (v: boolean) => Object.defineProperty(navigator, 'onLine', { configurable: true, value: v });

beforeEach(() => {
  localStorage.clear();
  me.mockReset();
  logoutApi.mockClear();
  localStorage.setItem('access_token', 'tok');
  setOnline(true);
});
afterEach(() => { setOnline(true); localStorage.clear(); });

describe('opening the app', () => {
  it('remembers who is signed in when the call succeeds', async () => {
    me.mockResolvedValue(USER);
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('in:a@b.c'));
    expect(JSON.parse(localStorage.getItem(api.LAST_USER_KEY)!)).toMatchObject({ email: 'a@b.c' });
  });

  it('keeps the person signed in when there is no answer at all (no signal), using the remembered user', async () => {
    localStorage.setItem(api.LAST_USER_KEY, JSON.stringify(USER));
    me.mockRejectedValue({ message: 'Network Error' });
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('in:a@b.c'));
    expect(localStorage.getItem('access_token')).toBe('tok');
  });

  it('signs out when the server itself refuses', async () => {
    localStorage.setItem(api.LAST_USER_KEY, JSON.stringify(USER));
    me.mockRejectedValue({ response: { status: 401 } });
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('out'));
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem(api.LAST_USER_KEY)).toBeNull();           // the remembered user goes with the session
  });

  it('has nobody to show when there is no signal and nobody was remembered', async () => {
    me.mockRejectedValue({ message: 'Network Error' });
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('who')).toHaveTextContent('out'));
  });
});
