/**
 * H3.7 — one refresh per expiry, however many requests are waiting.
 *
 * Before H2.5 a refresh stampede was merely wasteful. After it, it logs the user
 * out: refresh tokens are single-use and rotated, and presenting a spent one is
 * treated as theft, so the server revokes the whole family. Three requests that
 * 401 together all read the same token, the first rotates it, and the other two
 * are read as an attack.
 *
 * That is not a hypothesis. On 2026-08-24 the live database held six browser
 * token families revoked with `reuse_detected` and no other revocation reason
 * anywhere — six sessions ended by their own client racing itself.
 *
 * So the property under test is a count: **exactly one network call**, no matter
 * how many callers arrive at once.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import axios from 'axios';

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  return {
    ...actual,
    default: {
      ...actual.default,
      post: vi.fn(),
      create: actual.default.create,
      interceptors: actual.default.interceptors,
    },
  };
});

const tokenResponse = (n: number) => ({
  data: {
    access_token: `access-${n}`,
    refresh_token: `refresh-${n}`,
    token_type: 'bearer',
    expires_in: 1800,
  },
});

describe('refreshTokenOnce', () => {
  let refreshTokenOnce: typeof import('../api')['refreshTokenOnce'];
  let __resetRefreshInFlight: typeof import('../api')['__resetRefreshInFlight'];

  beforeEach(async () => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem('refresh_token', 'the-only-token');
    const mod = await import('../api');
    refreshTokenOnce = mod.refreshTokenOnce;
    __resetRefreshInFlight = mod.__resetRefreshInFlight;
    __resetRefreshInFlight();
  });

  afterEach(() => __resetRefreshInFlight?.());

  it('makes ONE network call for ten concurrent callers', async () => {
    let resolve!: (v: unknown) => void;
    (axios.post as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((r) => { resolve = r; }),
    );

    const callers = Array.from({ length: 10 }, () => refreshTokenOnce());
    resolve(tokenResponse(1));
    const results = await Promise.all(callers);

    expect(axios.post).toHaveBeenCalledTimes(1);
    // Every caller gets the same rotated pair — nobody is left holding a token
    // the server has already consumed.
    for (const r of results) expect(r.access_token).toBe('access-1');
  });

  it('stores the rotated pair once', async () => {
    (axios.post as ReturnType<typeof vi.fn>).mockResolvedValue(tokenResponse(2));
    await Promise.all([refreshTokenOnce(), refreshTokenOnce(), refreshTokenOnce()]);
    expect(localStorage.getItem('refresh_token')).toBe('refresh-2');
    expect(localStorage.getItem('access_token')).toBe('access-2');
  });

  it('allows a NEW refresh after the first settles', async () => {
    (axios.post as ReturnType<typeof vi.fn>).mockResolvedValue(tokenResponse(3));
    await refreshTokenOnce();
    await refreshTokenOnce();
    // Two separate expiries are two refreshes; only concurrent ones share.
    expect(axios.post).toHaveBeenCalledTimes(2);
  });

  it('does not cache a rejection — one bad moment must not break the session', async () => {
    (axios.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('network blip'));
    await expect(refreshTokenOnce()).rejects.toThrow('network blip');

    (axios.post as ReturnType<typeof vi.fn>).mockResolvedValue(tokenResponse(4));
    const ok = await refreshTokenOnce();
    expect(ok.access_token).toBe('access-4');
  });

  it('shares the failure with everyone waiting on it', async () => {
    (axios.post as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('revoked'));
    const results = await Promise.allSettled([
      refreshTokenOnce(), refreshTokenOnce(), refreshTokenOnce(),
    ]);
    expect(axios.post).toHaveBeenCalledTimes(1);
    expect(results.every((r) => r.status === 'rejected')).toBe(true);
  });

  it('refuses when there is no refresh token, without calling the network', async () => {
    localStorage.removeItem('refresh_token');
    await expect(refreshTokenOnce()).rejects.toThrow('No refresh token');
    expect(axios.post).not.toHaveBeenCalled();
  });
});
