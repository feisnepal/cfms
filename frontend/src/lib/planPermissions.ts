/**
 * Who may do what on the Operational Plan page (owner, 2026-10-16).
 *
 * The server lets only the forest's owner or a super admin reach a plan, so any signed-in user who gets to the page edits
 * its document: add, edit, reorder, hide and remove sections, tables, charts and maps. The tools that overwrite the whole
 * reconfigure the plan record (plan metadata) stays with the super admin. "Update values" (auto-populate) is open to every editor
 * because it refills only sections nobody has edited.
 */
export interface PlanTools {
  canEditDocument: boolean;
  canAutoPopulate: boolean;
  canEditPlanMetadata: boolean;
}

export function planTools(role: string | undefined | null, signedIn: boolean): PlanTools {
  const admin = role === 'super_admin';
  // "Update values" is safe for every editor: it only refills sections nobody has edited (plan_live.py).
  return { canEditDocument: signedIn, canAutoPopulate: signedIn, canEditPlanMetadata: admin };
}
