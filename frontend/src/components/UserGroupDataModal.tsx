/**
 * The user group's data, over the map (owner, 2026-10-11): reached from the User Group Boundary layer's menu. Household information
 * (a list or just the totals) and the executive committee are mandatory; the advisory and financial committees are optional. The
 * reminder at the top of the household screen shows what is still missing.
 */
import React from 'react';
import { Modal } from 'antd';
import HouseholdInfoTab from './HouseholdInfo/HouseholdInfoTab';
import { useT } from '../i18n/hooks';

export interface UserGroupDataModalProps {
  open: boolean;
  calculationId: string;
  /** `households` opens the household screens, `committee` opens the committee screen. */
  section: 'households' | 'committee';
  onClose: () => void;
}

export function UserGroupDataModal({ open, calculationId, section, onClose }: UserGroupDataModalProps) {
  const t = useT();
  return (
    <Modal open={open} onCancel={onClose} footer={null} width={1000} destroyOnClose title={t('workspace.userGroup.dataTitle')} data-testid="user-group-data-modal">
      <HouseholdInfoTab calculationId={calculationId} initialTab={section === 'committee' ? '5' : '2'} />
    </Modal>
  );
}

export default UserGroupDataModal;
