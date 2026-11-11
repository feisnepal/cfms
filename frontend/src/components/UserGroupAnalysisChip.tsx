/**
 * The automatic user group analysis as a small status on the User Group Boundary layer (owner, 2026-10-12): Analysing… / Analysed /
 * Analysis failed / Not analysed. The reason (for example "too large" or the failing step) is in the tooltip. Nothing to press.
 */
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';

const LOOK: Record<string, { icon: string; color: string }> = {
  running: { icon: '⏳', color: '#b45309' },
  done: { icon: '✓', color: '#15803d' },
  failed: { icon: '⚠', color: '#b91c1c' },
  skipped: { icon: '⚠', color: '#b45309' },
};

export function UserGroupAnalysisChip() {
  const t = useT();
  const st = useWorkspaceStore((s) => s.userGroupAnalysis);
  if (!st || st.state === 'idle') return null;
  const look = LOOK[st.state];
  return (
    <span
      className="layer-analysis-chip"
      role="status"
      aria-live="polite"
      data-testid="user-group-analysis-chip"
      data-state={st.state}
      title={st.message || t(`workspace.userGroup.status.${st.state}`)}
      style={{ marginLeft: 6, fontSize: 11, fontWeight: 600, color: look.color, whiteSpace: 'nowrap' }}
    >
      {look.icon} {t(`workspace.userGroup.status.${st.state}`)}
    </span>
  );
}

export default UserGroupAnalysisChip;
