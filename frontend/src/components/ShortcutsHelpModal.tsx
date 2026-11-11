/**
 * ShortcutsHelpModal — documents the tabbed page keyboard shortcuts (Phase 6).
 * Mirrors `useTabKeyboardShortcuts` in `useFocusManagement`:
 *   - Ctrl/Cmd+1..4  switch to the N-th tab
 *   - Esc            closes an open modal dialog
 */
import { Modal } from 'antd';
import { useT } from '../i18n/hooks';
import { TABS, TAB_CONFIG, shortcutKeyForTab } from '../pages/calculationTabConfig';
import type { TabId } from '../pages/calculationTabConfig';

interface ShortcutsHelpModalProps {
  open: boolean;
  onClose: () => void;
  /** Labels for each tab, in tab order (defaults to config labels). */
  labels?: Record<TabId, string>;
}

export const ShortcutsHelpModal: React.FC<ShortcutsHelpModalProps> = ({
  open,
  onClose,
  labels,
}) => {
  const t = useT();
  const tabList = TABS.map((id, index) => ({
    id,
    // Resolved through i18n rather than a local table of English strings. That
    // table was a second source of truth for the group names, and it still named
    // the pre-P2b groups ("Forest Data", "Data & Maps"), so the help modal
    // documented a navigation that no longer exists.
    label: labels?.[id] || t(TAB_CONFIG[id].labelKey),
    key: shortcutKeyForTab(index) ?? index + 1,
  }));

  return (
    <Modal
      open={open}
      title={t('workspace.shortcuts.title')}
      onCancel={onClose}
      footer={null}
      className="shortcuts-help"
    >
      <div className="shortcuts-help__list">
        {tabList.map((tab) => (
          <div key={tab.id} className="shortcuts-help__row">
            <span>{tab.label}</span>
            <span className="shortcuts-help__keys">
              <kbd>Ctrl</kbd>
              <kbd>Cmd</kbd>
              <kbd>+</kbd>
              <kbd>{tab.key}</kbd>
            </span>
          </div>
        ))}
        <div className="shortcuts-help__row">
          <span>{t('workspace.shortcuts.closeDialog')}</span>
          <span className="shortcuts-help__keys">
            <kbd>Esc</kbd>
          </span>
        </div>
      </div>
    </Modal>
  );
};

export default ShortcutsHelpModal;