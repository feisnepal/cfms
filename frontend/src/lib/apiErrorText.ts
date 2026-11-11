/**
 * One readable sentence from whatever the server sent back.
 *
 * FastAPI answers a request it rejects in more than one shape, and putting the raw value into the page crashes React ("Objects are not
 * valid as a React child") the moment it is not text:
 *
 *   - `{ detail: "text" }`                                      -> the text
 *   - `{ detail: [{ type, loc, msg, input, ctx }, ...] }` (422)  -> each `msg`, with the field name in front ("password: ...")
 *   - `{ detail: { message | msg | detail | error } }`           -> that text
 *   - `{ message: "text" }` / `{ error_code, message }`          -> the text (the app's own errors)
 *
 * Anything else (no response, a network error, an HTML error page) gives the fallback the caller supplied. Always returns a string.
 */

const VALUE_ERROR = /^value error,\s*/i;

const clean = (s: string): string => s.replace(VALUE_ERROR, '').trim();

const fieldOf = (loc: unknown): string | null => {
  if (!Array.isArray(loc)) return null;
  const parts = loc.filter((p) => typeof p === 'string' && p !== 'body' && p !== 'query') as string[];
  return parts.length ? parts[parts.length - 1] : null;
};

function fromValue(v: unknown): string | null {
  if (typeof v === 'string') return clean(v) || null;
  if (Array.isArray(v)) {
    const lines = v
      .map((item) => {
        if (typeof item === 'string') return clean(item);
        if (item && typeof item === 'object') {
          const o = item as Record<string, unknown>;
          const msg = typeof o.msg === 'string' ? clean(o.msg) : typeof o.message === 'string' ? clean(o.message) : '';
          const field = fieldOf(o.loc);
          return msg ? (field ? `${field}: ${msg}` : msg) : '';
        }
        return '';
      })
      .filter(Boolean);
    return lines.length ? lines.join(' · ') : null;
  }
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    for (const key of ['message', 'msg', 'detail', 'error']) {
      const got = fromValue(o[key]);
      if (got) return got;
    }
  }
  return null;
}

export function apiErrorText(err: unknown, fallback: string): string {
  const data = (err as { response?: { data?: unknown } } | null | undefined)?.response?.data;
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    return fromValue(d.detail) ?? fromValue(d.message) ?? fromValue(d.error) ?? fallback;
  }
  if (typeof data === 'string' && data.length < 300 && !data.trim().startsWith('<')) return clean(data) || fallback;
  return fallback;
}
