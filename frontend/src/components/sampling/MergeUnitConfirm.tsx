import { Alert, Modal, Typography } from 'antd';
import React from 'react';
import { useTranslation } from 'react-i18next';

import type { UnitSizeCandidate } from '../../services/api';

const { Text, Paragraph } = Typography;

interface MergeUnitConfirmProps {
  candidate: UnitSizeCandidate | null;
  open: boolean;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * The confirm step for a proposed merge. Per the plan this is deliberately the
 * *only* way a merge happens from this screen - no bulk action, no silent
 * application, and the dialog names both polygons and the resulting area before
 * anything is written.
 *
 * The consequence is stated up front rather than discovered afterwards: this is a
 * structural change, so the sampling design and the field inventory for the affected
 * units are invalidated by it.
 */
export const MergeUnitConfirm: React.FC<MergeUnitConfirmProps> = ({
  candidate,
  open,
  confirming,
  onConfirm,
  onCancel,
}) => {
  const { t } = useTranslation();

  if (!candidate) return null;
  const targetArea = candidate.neighbour_area_ha ?? 0;
  const resultArea = targetArea + candidate.area_ha;

  return (
    <Modal
      open={open}
      title={t('sampling.unitReview.mergeTitle')}
      onOk={onConfirm}
      onCancel={onCancel}
      okText={t('sampling.unitReview.mergeConfirm')}
      cancelText={t('sampling.unitReview.mergeCancel')}
      confirmLoading={confirming}
      okButtonProps={{ danger: true }}
    >
      <Paragraph style={{ marginTop: 12 }}>
        {t('sampling.unitReview.mergeQuestion', {
          source: candidate.block_name,
          target: candidate.neighbour ?? '',
        })}
      </Paragraph>
      <Paragraph>
        {t('sampling.unitReview.mergeAreas', {
          source: candidate.area_ha.toFixed(4),
          target: targetArea.toFixed(2),
          result: resultArea.toFixed(4),
        })}
      </Paragraph>
      {candidate.reason && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {candidate.reason}
        </Text>
      )}
      <Alert
        type="warning"
        showIcon
        style={{ marginTop: 12 }}
        message={t('sampling.unitReview.mergeConsequence')}
      />
    </Modal>
  );
};

export default MergeUnitConfirm;
