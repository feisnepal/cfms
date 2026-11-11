/**
 * Feature Flags for Forest Management System
 *
 * Usage:
 *   import { isUnifiedMappingEnabled } from '../config/featureFlags';
 *
 *   if (isUnifiedMappingEnabled()) {
 *     // New unified mapping UI
 *   } else {
 *     // Old UI
 *   }
 */

export const isUnifiedMappingEnabled = (): boolean => {
  return import.meta.env.VITE_USE_UNIFIED_MAPPING === 'true';
};

export const isFeatureEnabled = (flagName: string): boolean => {
  const envKey = `VITE_${flagName}`;
  return import.meta.env[envKey] === 'true';
};

/** OP multi-template Phase 6 — ships dormant (VITE_* build flag, default off). */
export const isOpAutoStageEnabled = (): boolean =>
  import.meta.env.VITE_OP_AUTO_STAGE === 'true';

export const isOpKindMatchEnabled = (): boolean =>
  import.meta.env.VITE_OP_TEMPLATE_KIND_MATCH === 'true';

/**
 * Single Workspace (WORKSPACE_UNIFICATION_2_PLAN, Option A / task A4).
 * When on, `/calculations/:id` renders the tabbed shell and the `/tabbed` +
 * `/operational-plan` URLs redirect into it. Ships OFF; flip per deploy with
 * `VITE_SINGLE_WORKSPACE=true`. `?legacy=1` still opens the old page for one
 * release. Reused later by Option C.
 */
export const isSingleWorkspaceEnabled = (): boolean =>
  import.meta.env.VITE_SINGLE_WORKSPACE === 'true';

/**
 * Yearly-activities planner guidance (YEARLY_ACTIVITIES_WORKSPACE_PLAN P1): the Next-step card, the
 * plan checklist and the plain-words messages. **On by default** — this repository has no separate
 * staging audience — and switched off with `VITE_YEARLY_PLAN_GUIDANCE=false` if it ever needs to be.
 */
export const isYearlyPlanGuidanceEnabled = (): boolean =>
  import.meta.env.VITE_YEARLY_PLAN_GUIDANCE !== 'false';
