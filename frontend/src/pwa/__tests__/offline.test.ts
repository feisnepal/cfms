import { describe, it, expect, vi, afterEach } from 'vitest';
import { clearOfflineApiCache, loadedAssetUrls, offlineReadiness, registerOfflineSupport } from '../offline';

afterEach(() => { vi.restoreAllMocks(); });

describe('in development and in tests (no production build)', () => {
  it('registers nothing, sends nothing and says it is unsupported', () => {
    const register = vi.fn();
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { register, ready: Promise.resolve({}), controller: null, addEventListener: vi.fn() } });
    registerOfflineSupport();
    clearOfflineApiCache();
    expect(register).not.toHaveBeenCalled();
    expect(offlineReadiness()).toBe('unsupported');
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: undefined });
  });
});

describe('loadedAssetUrls', () => {
  it('lists the built files the page has loaded, by path, and nothing else', () => {
    vi.spyOn(performance, 'getEntriesByType').mockReturnValue([
      { name: 'https://app.test/assets/index-a1.js' }, { name: 'https://app.test/assets/NtfpPage-b2.js' },
      { name: 'https://app.test/api/calculations/c1' }, { name: 'https://fonts.gstatic.com/x.woff2' }, { name: 'not a url' },
    ] as unknown as PerformanceEntryList);
    expect(loadedAssetUrls()).toEqual(['/assets/index-a1.js', '/assets/NtfpPage-b2.js']);
  });
});
