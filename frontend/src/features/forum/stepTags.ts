/**
 * Which forum tag a workflow step's question gets, and the starting tags themselves.
 *
 * `FORUM_TAGS` mirrors the tags migration 144 seeds (a backend test reads this file and checks every tag here is one of them, so a renamed tag
 * cannot leave a step pointing at nothing). The step ids are the context ids of `components/calculation/calcContexts.ts`; a frontend test checks
 * that every numbered step has an entry here.
 */
export const FORUM_TAGS = [
  'map', 'user-group', 'fieldbook', 'sampling', 'field-inventory', 'biodiversity', 'household', 'sfm',
  'cost-benefit', 'operational-plan', 'yearly-plan', 'ntfp', 'hazard', 'mobile', 'account',
] as const;

export type ForumTagName = (typeof FORUM_TAGS)[number];

export const STEP_TAGS: Record<string, ForumTagName> = {
  unified: 'map',
  usergroup: 'user-group',
  fieldbook: 'fieldbook',
  sampling: 'sampling',
  fieldinventory: 'field-inventory',
  forestmetadata: 'operational-plan',
  biodiversity: 'biodiversity',
  treemapping: 'field-inventory',
  ntfp: 'ntfp',
  treemodel: 'field-inventory',
  detaildescription: 'operational-plan',
  areadetail: 'map',
  analysis: 'map',
  hazarderosion: 'hazard',
  sustainablefm: 'sfm',
  cba: 'cost-benefit',
  yearly: 'yearly-plan',
  mgmtplan: 'operational-plan',
  issuesubmit: 'operational-plan',
};

/** The tag a question asked from this step starts with, or undefined for a step id the map does not know. */
export const tagForStep = (stepId: string | null | undefined): ForumTagName | undefined => (stepId ? STEP_TAGS[stepId] : undefined);
