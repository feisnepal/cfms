/**
 * "User Group Analysis" from the map workspace's User Group Boundary layer.
 *
 * The full analysis + results flow (analyse, settlement statistics, land-cover
 * & biomass, OP-variable CopyTags, CSV/GeoJSON/PNG export, delete) is
 * `UserGroupMapTab`. This hosts it over the map instead of duplicating it, so
 * the workspace and the Data & Maps → User Group Map tab cannot drift apart.
 *
 * When an analysis finishes the modal closes so the extent + analysis are on
 * the map straight away; a delete leaves it open (the tab is what the user is
 * looking at) but still tells the workspace to refresh.
 */
import { Modal } from 'antd';
import UserGroupMapTab from './UserGroupMapTab';
import { useT } from '../i18n/hooks';

interface UserGroupModalProps {
  open: boolean;
  calculationId: string;
  forestName?: string;
  onClose: () => void;
  /** An analysis ran or the user group extent was deleted — refresh the layer. */
  onChanged: (change: 'analyzed' | 'deleted') => void;
}

export default function UserGroupModal({
  open,
  calculationId,
  forestName,
  onClose,
  onChanged,
}: UserGroupModalProps) {
  const t = useT();
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('workspace.userGroup.analysisTitle')}
      width="min(1100px, 96vw)"
      centered
      destroyOnHidden
      footer={null}
      styles={{ body: { maxHeight: '78vh', overflowY: 'auto' } }}
    >
      <UserGroupMapTab
        calculationId={calculationId}
        forestName={forestName}
        onChanged={(change) => {
          onChanged(change);
          if (change === 'analyzed') onClose();
        }}
      />
    </Modal>
  );
}