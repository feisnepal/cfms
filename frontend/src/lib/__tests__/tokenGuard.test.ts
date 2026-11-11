import { describe, it, expect } from 'vitest';
import { guardedDelete, brokenTokens, tokenSpans } from '../tokenGuard';

const T = 'Area {{area_ha}} of {{forest_name}}.';

describe('guardedDelete', () => {
  it('Backspace right after a variable removes the whole variable', () => {
    const end = T.indexOf('{{area_ha}}') + '{{area_ha}}'.length;
    expect(guardedDelete(T, end, end, 'Backspace')).toEqual({ text: 'Area  of {{forest_name}}.', caret: 5 });
  });
  it('Backspace inside a variable removes the whole variable', () => {
    const mid = T.indexOf('area_ha') + 3;
    expect(guardedDelete(T, mid, mid, 'Backspace')?.text).toBe('Area  of {{forest_name}}.');
  });
  it('Delete right before a variable removes the whole variable', () => {
    const start = T.indexOf('{{forest_name}}');
    expect(guardedDelete(T, start, start, 'Delete')).toEqual({ text: 'Area {{area_ha}} of .', caret: start });
  });
  it('plain text is left to the browser', () => {
    expect(guardedDelete(T, 2, 2, 'Backspace')).toBeNull();
    expect(guardedDelete(T, 3, 3, 'Delete')).toBeNull();
  });
  it('Backspace at the start of a variable does not eat it', () => {
    const start = T.indexOf('{{area_ha}}');
    expect(guardedDelete(T, start, start, 'Backspace')).toBeNull();
  });
  it('a selection that cuts through a variable is widened to cover it', () => {
    const a = T.indexOf('area_ha') + 2;
    const b = T.indexOf(' of ') + 2;
    const r = guardedDelete(T, a, b, 'Backspace');
    // from the start of the variable (not from its middle) up to the end of the selection
    expect(r?.text).toBe('Area f {{forest_name}}.');
  });
  it('a selection that covers a variable exactly or lies in plain text is left alone', () => {
    const s = tokenSpans(T)[0];
    expect(guardedDelete(T, s.start, s.end, 'Delete')).toBeNull();
    expect(guardedDelete(T, 0, 3, 'Delete')).toBeNull();
  });
});

describe('brokenTokens', () => {
  it('finds spaced, one-brace and lone-brace variables', () => {
    expect(brokenTokens('{{ area_ha }}').length).toBeGreaterThan(0);
    expect(brokenTokens('{{area_ha}').length).toBeGreaterThan(0);
    expect(brokenTokens('see {{ here').length).toBeGreaterThan(0);
  });
  it('accepts good variables and ordinary braces', () => {
    expect(brokenTokens('{{area_ha}} {{chart:biomass}} {a, b}')).toEqual([]);
  });
});
