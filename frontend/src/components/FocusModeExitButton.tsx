import { useWorkspaceStore } from '../store/workspaceStore';

/**
 * FocusModeExitButton — floating button to exit focus mode.
 * Only renders when focusMode is active.
 */
export function FocusModeExitButton(): React.ReactElement | null {
  const focusMode = useWorkspaceStore((s) => s.focusMode);
  const toggleFocusMode = useWorkspaceStore((s) => s.toggleFocusMode);

  if (!focusMode) return null;

  return (
    <button
      className="focus-mode-exit-btn"
      onClick={toggleFocusMode}
      aria-label="Exit focus mode"
      title="Exit focus mode (Esc)"
    >
      ⛶
    </button>
  );
}

export default FocusModeExitButton;