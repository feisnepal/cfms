/**
 * Asks for a sub-area category when pasted features carry none (e.g. blocks or
 * compartments pasted into the Sub-areas layer). Asked once for the whole paste.
 */
import { Modal } from 'antd';
import { useT } from '../i18n/hooks';
import { SubAreaCategoryPicker } from './SubAreaCategoryPicker';

interface PasteCategoryModalProps {
  /** How many pasted features need a category; null = closed. */
  prompt: { count: number } | null;
  /** Called with the chosen category, or null when the user cancels. */
  onResolve: (category: string | null) => void;
}

export function PasteCategoryModal({ prompt, onResolve }: PasteCategoryModalProps) {
  const t = useT();
  return (
    <Modal
      open={prompt != null}
      title={t('editing.paste.categoryTitle')}
      footer={null}
      onCancel={() => onResolve(null)}
      destroyOnHidden
    >
      <p style={{ margin: '0 0 8px' }}>{t('editing.paste.categoryHint', { count: prompt?.count ?? 0 })}</p>
      <SubAreaCategoryPicker onChange={(category) => onResolve(category)} />
    </Modal>
  );
}

export default PasteCategoryModal;
