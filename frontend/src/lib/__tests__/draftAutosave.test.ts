/**
 * Phase 5 — draftAutosave pure-logic tests (jsdom localStorage).
 */
import { beforeEach, describe, expect, it } from 'vitest';
import {
  draftDataKey,
  draftTsKey,
  loadDraftSnapshot,
  saveDraftSnapshot,
  hasFreshDraft,
  clearDraftSnapshot,
  DRAFT_MAX_AGE_MS,
} from '../draftAutosave';

const point = { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 2] }, properties: {} } as GeoJSON.Feature;

describe('draftAutosave — keys', () => {
  it('uses calc-scoped storage keys', () => {
    expect(draftDataKey('abc')).toBe('calc_draft_abc');
    expect(draftTsKey('abc')).toBe('calc_draft_abc_ts');
  });
});

describe('draftAutosave — save/load', () => {
  beforeEach(() => localStorage.clear());

  it('saves a non-empty buffer and reads it back with timestamp', () => {
    const features = { 1: [point] };
    const ts = saveDraftSnapshot('abc', features);
    expect(ts).not.toBeNull();

    const loaded = loadDraftSnapshot('abc');
    expect(loaded).not.toBeNull();
    expect(loaded!.timestamp).toBe(ts);
    expect(loaded!.features).toEqual(features);
  });

  it('does not write when the draft buffer is empty', () => {
    const ts = saveDraftSnapshot('abc', {});
    expect(ts).toBeNull();
    expect(localStorage.getItem(draftDataKey('abc'))).toBeNull();
    expect(loadDraftSnapshot('abc')).toBeNull();
  });

  it('hasFreshDraft reflects saved state', () => {
    expect(hasFreshDraft('abc')).toBe(false);
    saveDraftSnapshot('abc', { 1: [point] });
    expect(hasFreshDraft('abc')).toBe(true);
  });
});

describe('draftAutosave — freshness / expiry', () => {
  beforeEach(() => localStorage.clear());

  it('expires the snapshot after the 7-day window', () => {
    saveDraftSnapshot('abc', { 1: [point] });
    expect(loadDraftSnapshot('abc')).not.toBeNull();

    // Rewrite the stored timestamp to be older than max age (real 'now' is
    // ~1.7e12ms; this synthetic value is much older).
    localStorage.setItem(draftTsKey('abc'), String(1_000));
    expect(loadDraftSnapshot('abc')).toBeNull();
  });

  it('rejects an unparseable timestamp', () => {
    localStorage.setItem(draftDataKey('abc'), JSON.stringify({ 1: [point] }));
    localStorage.setItem(draftTsKey('abc'), 'not-a-number');
    expect(loadDraftSnapshot('abc')).toBeNull();
  });

  it('rejects malformed JSON payload', () => {
    localStorage.setItem(draftDataKey('abc'), '{broken');
    localStorage.setItem(draftTsKey('abc'), String(Date.now()));
    expect(loadDraftSnapshot('abc')).toBeNull();
  });
});

describe('draftAutosave — clear', () => {
  beforeEach(() => localStorage.clear());

  it('removes both keys', () => {
    saveDraftSnapshot('abc', { 1: [point] });
    clearDraftSnapshot('abc');
    expect(localStorage.getItem(draftDataKey('abc'))).toBeNull();
    expect(localStorage.getItem(draftTsKey('abc'))).toBeNull();
  });
});