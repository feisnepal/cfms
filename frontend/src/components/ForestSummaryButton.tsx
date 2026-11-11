/** The layer panel's Forest summary button: a toolbar icon (owner, 2026-10-27) instead of a row that took the top of the panel. */
import { BarChart3 } from 'lucide-react';
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';

export function ForestSummaryButton() {
  const t = useT();
  const open = useWorkspaceStore((s) => s.forestSummaryOpen);
  const setOpen = useWorkspaceStore((s) => s.setForestSummaryOpen);
  const label = t('forestSummary.title', { defaultValue: 'Forest summary' });
  return (
    <button type="button" data-testid="open-forest-summary" aria-pressed={open} aria-label={label} title={label} onClick={() => setOpen(true)}>
      <BarChart3 size={14} />
    </button>
  );
}
