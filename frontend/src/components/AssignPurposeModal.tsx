import React, { useState } from 'react';
import { Modal, Select, message, Typography } from 'antd';
import { forestApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { readDetail } from '../hooks/useErrorHandler';
import { PURPOSES } from '../lib/purposeGeometryRules';

interface AssignPurposeModalProps {
  visible: boolean;
  onClose: () => void;
  calculationId: string;
  layerId: number | null;
  layerName: string;
}

export default function AssignPurposeModal({
  visible,
  onClose,
  calculationId,
  layerId,
  layerName,
}: AssignPurposeModalProps) {
  const [targetPurpose, setTargetPurpose] = useState<string>('custom');
  const [loading, setLoading] = useState(false);
  const bumpGeometryVersion = useWorkspaceStore((s) => s.bumpGeometryVersion);
  const t = useT();

  const handleAssign = async () => {
    if (layerId == null || !calculationId) return;
    setLoading(true);
    try {
      // Update the imported layer's purpose
      await forestApi.updateImportLayer(calculationId, layerId, { purpose: targetPurpose });
      message.success(t('assignPurpose.success', { name: layerName, target: targetPurpose }));
      bumpGeometryVersion();
      onClose();
    } catch (err: any) {
      message.error(readDetail(err?.response?.data?.detail) || err?.message || t('assignPurpose.failed'));
    }
  };

  // Filter purposes: exclude 'boundary' (special handling) and admin purposes
  const assignablePurposes = PURPOSES.filter(
    (p) => p.id !== 'boundary' && !['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas', 'activity_features'].includes(p.id)
  ).map((p) => ({
    value: p.id,
    label: t(p.labelKey),
  }));

  return (
    <Modal
      title={t('assignPurpose.title', { name: layerName })}
      open={visible}
      onOk={handleAssign}
      onCancel={onClose}
      confirmLoading={loading}
      okText={t('common.save')}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '8px 0' }}>
        <Typography.Text>
          {t('assignPurpose.description', { name: layerName })}
        </Typography.Text>
        <p className="text-sm text-gray-500">
          {t('assignPurpose.note')}
        </p>
        <Select
          value={targetPurpose}
          onChange={setTargetPurpose}
          style={{ width: '100%' }}
          options={[
            { value: 'custom', label: t('purpose.custom') },
            { value: 'blocks', label: t('purpose.blocks') },
            { value: 'sub_blocks', label: t('purpose.sub_blocks') },
            { value: 'compartments', label: t('purpose.compartments') },
            { value: 'sub_compartments', label: t('purpose.sub_compartments') },
            { value: 'sub_areas', label: t('purpose.sub_areas') },
            { value: 'activity_features', label: t('purpose.activity_features') },
            { value: 'roads', label: t('purpose.roads') },
            { value: 'water', label: t('purpose.water') },
            { value: 'inventory', label: t('purpose.inventory') },
            { value: 'sample_plot', label: t('purpose.sample_plot') },
            { value: 'other', label: t('purpose.other') },
          ]}
        />
        <p className="text-xs text-gray-500 mt-2">
          {t('assignPurpose.note')}
        </p>
      </div>
    </Modal>
  );
}