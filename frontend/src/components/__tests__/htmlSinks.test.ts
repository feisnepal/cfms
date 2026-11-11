import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/**
 * Every `dangerouslySetInnerHTML` must sanitise (S4-46 / H6.11).
 *
 * The audit found one unsanitised sink, `GuideModal.tsx:101`, and was careful
 * about its severity: the guides are static files under `public/guides/`, so
 * it was **not** exploitable. It was reported because
 * `Report/ReportTab.tsx` already did the same thing correctly with
 * `DOMPurify.sanitize()`, so the difference between them was an accident
 * rather than a decision — and because the day guide content becomes remotely
 * sourced or admin-editable, an accident like that turns into stored XSS with
 * no code change to notice it happening.
 *
 * Which is exactly why fixing the one site is not the whole job. This scan is
 * the part that lasts: a new raw-HTML sink cannot arrive without either
 * sanitising or being named in ALLOWED, which forces the "where does this
 * string come from?" question to be asked and written down.
 *
 * It is a source scan rather than an ESLint rule for the same reason the i18n
 * guards in `src/i18n/__tests__/` are: it runs in the same `vitest` gate the
 * suite already enforces, with no new tooling to configure.
 */

const SRC = join(__dirname, '..', '..');
const SINK = 'dangerouslySetInnerHTML';

/**
 * Sinks that are deliberately unsanitised. Each entry needs a reason, and the
 * reason has to survive somebody reading it in a year.
 *
 * Empty today, and that is the point — the two real sinks both sanitise.
 */
const ALLOWED: Record<string, string> = {};

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '__tests__') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, out);
    } else if (/\.tsx?$/.test(entry) && !/\.(test|spec)\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

describe('raw HTML sinks', () => {
  const offenders: string[] = [];
  const sanitised: string[] = [];

  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, 'utf-8');
    if (!text.includes(SINK)) continue;
    const rel = relative(SRC, file).split(sep).join('/');
    if (rel in ALLOWED) continue;

    text.split('\n').forEach((line, i) => {
      if (!line.includes(SINK)) return;
      // The sanitiser may sit on the same line as the sink or, when the JSX is
      // wrapped across lines, on the one that carries `__html`.
      const window = [line, text.split('\n')[i + 1] ?? ''].join(' ');
      (window.includes('DOMPurify.sanitize') ? sanitised : offenders)
        .push(`${rel}:${i + 1}`);
    });
  }

  it('are all sanitised with DOMPurify', () => {
    expect(offenders, `Unsanitised ${SINK}:\n  ${offenders.join('\n  ')}\n\n` +
      `Wrap the value in DOMPurify.sanitize(), matching Report/ReportTab.tsx, ` +
      `or add the file to ALLOWED with a reason.`).toEqual([]);
  });

  it('still finds the sinks it is meant to be guarding', () => {
    // Anti-false-pass: if the scan silently stops matching anything — a rename,
    // a moved directory — it would report success while guarding nothing.
    expect(sanitised.length).toBeGreaterThanOrEqual(2);
  });
});
