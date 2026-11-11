/**
 * Keeps a `{{variable}}` in plan text whole (owner, 2026-10-16: the editor must not let a variable be damaged by accident).
 *
 * The text area is plain text, so the guard works on key presses: Backspace/Delete next to or inside a variable removes the whole
 * variable, and a selection that cuts through one is widened to cover it. Typing inside a variable is still possible, so
 * `brokenTokens` names what would no longer be a variable; the editor shows it under the box and "Check my document" lists it.
 */
const VALID = /\{\{\w+(?::\w+)*\}\}/g;

export interface TokenSpan {
  start: number;
  end: number;
}

export function tokenSpans(text: string): TokenSpan[] {
  const out: TokenSpan[] = [];
  for (const m of text.matchAll(VALID)) out.push({ start: m.index ?? 0, end: (m.index ?? 0) + m[0].length });
  return out;
}

export interface GuardResult {
  text: string;
  caret: number;
}

/** The text after Backspace/Delete if it touches a variable (so the default would damage it), else null (let the browser act). */
export function guardedDelete(text: string, selStart: number, selEnd: number, key: 'Backspace' | 'Delete'): GuardResult | null {
  const spans = tokenSpans(text);
  let from = selStart;
  let to = selEnd;
  if (selStart === selEnd) {
    const hit = spans.find((s) => (key === 'Backspace' ? s.start < selStart && selStart <= s.end : s.start <= selStart && selStart < s.end));
    if (!hit) return null;
    from = hit.start;
    to = hit.end;
  } else {
    let changed = false;
    for (const s of spans) {
      const overlaps = s.start < to && s.end > from;
      if (overlaps && (s.start < from || s.end > to)) {
        from = Math.min(from, s.start);
        to = Math.max(to, s.end);
        changed = true;
      }
    }
    if (!changed) return null;
  }
  return { text: text.slice(0, from) + text.slice(to), caret: from };
}

/** Pieces that look like a variable but are not written correctly (spaces inside, one brace, a lone `{{`). */
export function brokenTokens(text: string): string[] {
  const rest = text.replace(VALID, '');
  return (rest.match(/\{\{[^{}]{0,60}\}?\}?|\{[^{}\s]{1,60}\}\}|\{\{|\}\}/g) ?? []).filter(Boolean);
}
