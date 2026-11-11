import { describe, it, expect, beforeEach } from 'vitest';
import { useCalcChromeStore } from '../calcChromeStore';

describe('calcChromeStore', () => {
  beforeEach(() => {
    localStorage.clear();
    useCalcChromeStore.setState({ headerCollapsed: false });
  });

  it('shape: chrome shown by default', () => {
    expect(useCalcChromeStore.getState().headerCollapsed).toBe(false);
  });

  it('toggleHeader flips headerCollapsed', () => {
    useCalcChromeStore.getState().toggleHeader();
    expect(useCalcChromeStore.getState().headerCollapsed).toBe(true);
    useCalcChromeStore.getState().toggleHeader();
    expect(useCalcChromeStore.getState().headerCollapsed).toBe(false);
  });

  it('setHeaderCollapsed is explicit', () => {
    useCalcChromeStore.getState().setHeaderCollapsed(true);
    expect(useCalcChromeStore.getState().headerCollapsed).toBe(true);
  });

  it('persists only headerCollapsed under cfms.calcChrome', () => {
    useCalcChromeStore.getState().setHeaderCollapsed(true);
    const raw = localStorage.getItem('cfms.calcChrome');
    expect(raw).toBeTruthy();
    const persisted = JSON.parse(raw as string).state;
    expect(persisted).toEqual({ headerCollapsed: true });
  });
});
