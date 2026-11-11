/**
 * Phase 3 — useTabChangeInterceptor pure-helper tests.
 * The hook itself wraps react-router's `useBlocker` (needs a Router provider);
 * we test the exported `shouldAllowTabChange` decision function.
 */
import { describe, it, expect } from 'vitest';
import { shouldAllowTabChange } from '../useTabChangeInterceptor';

describe('shouldAllowTabChange', () => {
  it('allows switching when there are no unsaved changes', () => {
    expect(shouldAllowTabChange(false)).toBe(true);
  });

  it('blocks switching when there are unsaved changes', () => {
    expect(shouldAllowTabChange(true)).toBe(false);
  });
});
