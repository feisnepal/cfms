/**
 * "Import Stem Mapping" from the map workspace's Stem Mapping layer.
 *
 * The full Tree Mapping process (upload → column mapping → validation → boundary
 * corrections → processing → summary/export/delete) is `TreeMappingTab`. This
 * hosts it over the map instead of duplicating it, so the workspace and the
 * Tree Mapping page cannot drift apart — one component, both hosts.
 *
 * It lands on the upload form when the forest has no tree mapping yet. When one
 * is created the modal closes so the census is on the map straight away; a
 * delete leaves it open (the form is what the user is looking at) but still
 * tells the workspace to refresh.
 */
import { Modal } from 'antd';
import { TreeMappingTab } from './TreeMappingTab';
import { useT } from '../i18n/hooks';

interface StemMappingModalProps {
  open: boolean;
  calculationId: string;
  onClose: () => void;
  /** Tree-mapping data was created / processed / deleted / updated — refresh the stem-mapping layer. */
  onChanged: (change: 'created' | 'deleted' | 'processed' | 'updated') => void;
}

export default function StemMappingModal({
  open,
  calculationId,
  onClose,
  onChanged,
}: StemMappingModalProps) {
  const t = useT();
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('treeMapping.manageFromMapTitle')}
      width="min(1100px, 96vw)"
      centered
      destroyOnHidden
      footer={null}
      styles={{ body: { maxHeight: '78vh', overflowY: 'auto' } }}
    >
      <TreeMappingTab
        calculationId={calculationId}
        onChanged={(change) => {
          onChanged(change);
          if (change === 'created') onClose();
        }}
      />
    </Modal>
  );
}