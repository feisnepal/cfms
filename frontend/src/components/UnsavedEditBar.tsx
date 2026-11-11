import { Modal } from 'antd';
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';

/**
 * U02 — dirty-edit indicator + stale-server conflict modal.
 *
 * - While `dirty`, renders a non-dismissable "Unsaved edits — commit to update
 *   analysis" Tag with a Commit action (calls the injected `onCommit`).
 * - When `syncConflict === 'stale_server'`, surfaces a Modal offering either a
 *   hard reload ("Discard my changes & reload") or discarding the stale flag /
 *   continuing ("Continue & overwrite"). No auto-merge, no silent data loss.
 *
 * Props:
 * - `dirtyLabelSuffix`: extra text for the chip (layer/pane context).
 * - `onCommit`: callback invoked by the Commit button (wrapped by the caller so
 *   the actual geometry/attribute PUT happens, then bumpGeometryVersion()).
 */
export function UnsavedEditBar({
  dirtyLabelSuffix,
  onCommit,
}: {
  dirtyLabelSuffix?: string;
  onCommit?: () => void;
}) {
  const t = useT();
  const dirty = useWorkspaceStore((s) => s.dirty);
  const syncConflict = useWorkspaceStore((s) => s.syncConflict);
  const serverGeometryVersion = useWorkspaceStore((s) => s.serverGeometryVersion);

  // "Continue & overwrite" clears the conflict so a Commit stays enabled; the
  // backend 409 handler still enforces if the write would clobber newer data.
  const continueAndOverwrite = () => {
    useWorkspaceStore.setState({ syncConflict: 'none' });
  };

  return (
    <>
      {dirty && (
        <div className="unsaved-edit-bar" data-testid="unsaved-edit-bar" role="status">
          <span className="unsaved-tag" aria-live="polite">
            {t('workspace.unsaved.tag')}{dirtyLabelSuffix ? ` (${dirtyLabelSuffix})` : ''}
          </span>
          {onCommit && (
            <button
              type="button"
              className="unsaved-commit-btn"
              onClick={onCommit}
              aria-label={t('workspace.unsaved.commitLabel')}
            >
              {t('workspace.unsaved.commit')}
            </button>
          )}
        </div>
      )}

      <Modal
        open={syncConflict === 'stale_server'}
        closable={false}
        mask={{ closable: false }}
        keyboard={false}
        title={t('workspace.unsaved.modifiedElsewhere')}
        width={460}
        onOk={() => window.location.reload()}
        okText={t('workspace.unsaved.discardReload')}
        cancelText={t('workspace.unsaved.continueOverwrite')}
        onCancel={continueAndOverwrite}
      >
        <p>{t('workspace.unsaved.changedElsewhere')}</p>
        <p>{t('workspace.unsaved.noAutoMerge')}</p>
        <p className="sync-version-note" data-testid="server-version-note">
          {t('workspace.unsaved.serverVersion', { version: serverGeometryVersion })}
        </p>
      </Modal>
    </>
  );
}