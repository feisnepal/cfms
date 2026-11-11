import { describe, it, expect } from 'vitest';
import { apiErrorText } from '../apiErrorText';

const err = (data: unknown) => ({ response: { data } });

describe('apiErrorText', () => {
  it('returns a plain text detail as it is', () => {
    expect(apiErrorText(err({ detail: 'Email already registered' }), 'x')).toBe('Email already registered');
  });

  it('turns a FastAPI validation list (the registration crash) into text', () => {
    const e = err({
      detail: [
        { type: 'value_error', loc: ['body', 'password'], msg: 'Value error, password needs a capital letter', input: 'abc', ctx: { error: {} } },
        { type: 'string_too_short', loc: ['body', 'full_name'], msg: 'String should have at least 2 characters', input: 'a', ctx: { min_length: 2 } },
      ],
    });
    const text = apiErrorText(e, 'x');
    expect(typeof text).toBe('string');
    expect(text).toBe('password: password needs a capital letter · full_name: String should have at least 2 characters');
  });

  it('reads the app\'s own error shape and a nested detail object', () => {
    expect(apiErrorText(err({ error_code: 'auth.invalid', message: 'Wrong password' }), 'x')).toBe('Wrong password');
    expect(apiErrorText(err({ detail: { message: 'Locked', code: 'structure_locked' } }), 'x')).toBe('Locked');
  });

  it('falls back when there is no usable text (no response, an HTML page, an empty list)', () => {
    expect(apiErrorText(new Error('Network Error'), 'fallback')).toBe('fallback');
    expect(apiErrorText(err('<html>502 Bad Gateway</html>'), 'fallback')).toBe('fallback');
    expect(apiErrorText(err({ detail: [] }), 'fallback')).toBe('fallback');
    expect(apiErrorText(err({ detail: { something: 1 } }), 'fallback')).toBe('fallback');
    expect(apiErrorText(undefined, 'fallback')).toBe('fallback');
  });

  it('always returns a string, whatever the server sent', () => {
    for (const data of [null, 42, true, { detail: 5 }, { detail: [null, 7, {}] }, { detail: { detail: { detail: ['x'] } } }]) {
      expect(typeof apiErrorText(err(data), 'f')).toBe('string');
    }
  });
});
