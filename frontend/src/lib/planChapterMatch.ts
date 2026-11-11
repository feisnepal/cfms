/**
 * Which chapter of the Operational Plan holds the text of a report section?
 *
 * The report's section list and the plan's chapters are named separately and do not always agree word for word: the report says
 * "व्यवस्थापन कार्ययोजनाको पुनरावलोकन, अनुगमन, मूल्याङ्कन" where the plan's chapter is "पुनरावलोकन, अनुगमन, मूल्याङ्कन", and the report's long
 * "वन पैदावारमा आधारित आय-आर्जन, सिप विकास, उद्योग तथा पर्यापर्यटन सम्बन्धी व्यवस्था" is the plan's "वन पैदावारमा आधारित आय-आर्जन".
 * So an exact title match is tried first, and then the chapter whose title is contained in the section's (or contains it), the longest
 * such title winning - never a short generic title such as "समीक्षा", which sits inside many longer ones.
 */

export interface TitledNode {
  title_ne?: string | null;
  title_en?: string | null;
  children?: TitledNode[] | null;
}

/** A title with everything but letters, marks and digits taken out, in lower case: punctuation and spacing differ between the two lists. */
export function normalizeTitle(title: string | null | undefined): string {
  return String(title ?? '')
    .toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}]+/gu, '');
}

/** A chapter title shorter than this is too generic to be recognised inside a longer one. */
const MIN_CONTAINED = 10;

function walk<T extends TitledNode>(nodes: T[] | null | undefined, visit: (n: T) => void): void {
  for (const n of nodes ?? []) {
    visit(n);
    walk(n.children as T[] | null | undefined, visit);
  }
}

export function findChapterForSection<T extends TitledNode>(tree: T[], sectionTitle: string): T | null {
  const wanted = normalizeTitle(sectionTitle);
  if (!wanted) return null;
  const found = { exact: null as T | null, best: null as { node: T; length: number } | null };
  walk(tree, (node) => {
    for (const title of [node.title_ne, node.title_en]) {
      const t = normalizeTitle(title);
      if (!t) continue;
      if (t === wanted) {
        found.exact = found.exact ?? node;
      } else if (t.length >= MIN_CONTAINED && (wanted.includes(t) || (wanted.length >= MIN_CONTAINED && t.includes(wanted)))) {
        if (!found.best || t.length > found.best.length) found.best = { node, length: t.length };
      }
    }
  });
  return found.exact ?? found.best?.node ?? null;
}
