import { describe, expect, it } from 'vitest';
import { findChapterForSection, normalizeTitle, type TitledNode } from '../planChapterMatch';

// the chapters of the default plan that matter here, with the generic children that sit inside longer titles
const TREE: TitledNode[] = [
  { title_ne: 'विगतका वन व्यवस्थापन कार्ययोजनाको समीक्षा', title_en: 'Previous Plan Review', children: [{ title_ne: 'व्यवस्थापनको संक्षिप्त समीक्षा' }] },
  { title_ne: 'वन पैदावारमा आधारित आय-आर्जन', title_en: 'Income generation' },
  {
    title_ne: 'पुनरावलोकन, अनुगमन, मूल्याङ्कन',
    title_en: 'Monitoring and Evaluation',
    children: [{ title_ne: 'अनुगमन र लेखापरिक्षण' }, { title_ne: 'समीक्षा' }, { title_ne: 'अनुगमनमा सहयोग' }],
  },
  { title_ne: 'अन्य आवश्यक कुरा', title_en: 'Other necessary matters' },
];

const titleOf = (n: TitledNode | null) => n?.title_ne ?? null;

describe('finding the chapter of a hand-written report section', () => {
  it('takes an exact title first', () => {
    expect(titleOf(findChapterForSection(TREE, 'विगतका वन व्यवस्थापन कार्ययोजनाको समीक्षा'))).toBe('विगतका वन व्यवस्थापन कार्ययोजनाको समीक्षा');
    expect(titleOf(findChapterForSection(TREE, 'अन्य आवश्यक कुरा'))).toBe('अन्य आवश्यक कुरा');
  });

  it('finds "पुनरावलोकन, अनुगमन, मूल्याङ्कन" inside the report\'s longer "व्यवस्थापन कार्ययोजनाको पुनरावलोकन, अनुगमन, मूल्याङ्कन"', () => {
    const hit = findChapterForSection(TREE, 'व्यवस्थापन कार्ययोजनाको पुनरावलोकन, अनुगमन, मूल्याङ्कन');
    expect(titleOf(hit)).toBe('पुनरावलोकन, अनुगमन, मूल्याङ्कन');
  });

  it('finds the plan\'s shorter chapter for the report\'s long income / skills / ecotourism title', () => {
    const hit = findChapterForSection(TREE, 'वन पैदावारमा आधारित आय-आर्जन, सिप विकास, उद्योग तथा पर्यापर्यटन सम्बन्धी व्यवस्था');
    expect(titleOf(hit)).toBe('वन पैदावारमा आधारित आय-आर्जन');
  });

  it('matches by the English title too', () => {
    expect(titleOf(findChapterForSection(TREE, 'Monitoring and Evaluation'))).toBe('पुनरावलोकन, अनुगमन, मूल्याङ्कन');
  });

  it('never picks a short generic chapter such as "समीक्षा" for a longer section title', () => {
    // the section is about monitoring; the child "समीक्षा" (7 letters) sits inside many titles and must not win
    const hit = findChapterForSection(TREE, 'योजनाको समीक्षा तथा अनुगमन');
    expect(titleOf(hit)).not.toBe('समीक्षा');
  });

  it('prefers the longest chapter title when several are contained', () => {
    const tree: TitledNode[] = [{ title_ne: 'अनुगमन तथा मूल्याङ्कन प्रणाली' }, { title_ne: 'अनुगमन तथा मूल्याङ्कन प्रणाली र प्रतिवेदन' }];
    expect(titleOf(findChapterForSection(tree, 'योजनाको अनुगमन तथा मूल्याङ्कन प्रणाली र प्रतिवेदन व्यवस्था'))).toBe('अनुगमन तथा मूल्याङ्कन प्रणाली र प्रतिवेदन');
  });

  it('finds a chapter inside another and ignores spacing and punctuation', () => {
    expect(titleOf(findChapterForSection(TREE, 'पुनरावलोकन अनुगमन मूल्याङ्कन'))).toBe('पुनरावलोकन, अनुगमन, मूल्याङ्कन');
  });

  it('gives nothing when no chapter fits, so the page opens on its first chapter as before', () => {
    expect(findChapterForSection(TREE, 'कुनै अर्को शीर्षक जुन योजनामा छैन')).toBeNull();
    expect(findChapterForSection(TREE, '')).toBeNull();
  });

  it('normalises titles: only letters, marks and digits count', () => {
    expect(normalizeTitle('पुनरावलोकन, अनुगमन — मूल्याङ्कन')).toBe(normalizeTitle('पुनरावलोकन अनुगमन मूल्याङ्कन'));
    expect(normalizeTitle(null)).toBe('');
  });
});
