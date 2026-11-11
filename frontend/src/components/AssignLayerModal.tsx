import React, { useState } from 'react';
import { Modal, Select, message, Typography } from 'antd';
import { forestApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { readDetail } from '../hooks/useErrorHandler';
import { useBoundaryPreview } from '../contexts/BoundaryPreviewContext';
import { provisionalFromError } from '../lib/boundaryPreviewPending';

interface AssignLayerModalProps {
  visible: boolean;
  onClose: () => void;
  calculationId: string;
  layerId: number | null;
  layerName: string;
}

export default function AssignLayerModal({
  visible,
  onClose,
  calculationId,
  layerId,
  layerName,
}: AssignLayerModalProps) {
  const [targetLayer, setTargetLayer] = useState<string>('blocks');
  const [loading, setLoading] = useState(false);
  const bumpGeometryVersion = useWorkspaceStore((s) => s.bumpGeometryVersion);
  const t = useT();
  const { reviewBoundary } = useBoundaryPreview();

  const handleAssign = async () => {
    if (layerId == null || !calculationId) return;
    setLoading(true);
    try {
      // Boundary target must NOT bypass the provisional gate: call without
      // confirm so overlap/gap to a neighbour surfaces the preview instead of
      // silently writing. Other targets convert immediately (existing behavior).
      const opts = targetLayer === 'boundary' ? {} : { confirm: true };
      const resp: any = await forestApi.convertImportedToBuiltin(calculationId, layerId, targetLayer, opts);
      if (resp?.needs_overlap_review) {
        const geom = resp.preview_geometry;
        if (geom) {
          reviewBoundary({
            geometry: geom,
            forestName: layerName,
            method: 'upload',
            calculationId,
            onResolved: () => {
              message.success(t('assignLayer.success', { name: layerName, target: targetLayer }));
              bumpGeometryVersion();
            },
          });
          return;
        }
      }
      message.success(t('assignLayer.success', { name: layerName, target: targetLayer }));
      bumpGeometryVersion();
      onClose();
    } catch (err: any) {
      const prov = provisionalFromError(err);
      if (targetLayer === 'boundary' && prov?.needs_overlap_review) {
        const geom = (prov as any).preview_geometry;
        if (geom) {
          reviewBoundary({
            geometry: geom,
            forestName: layerName,
            method: 'upload',
            calculationId,
            onResolved: () => {
              message.success(t('assignLayer.success', { name: layerName, target: targetLayer }));
              bumpGeometryVersion();
            },
          });
          return;
        }
      }
      message.error(readDetail(err?.response?.data?.detail) || err?.message || t('assignLayer.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={t('assignLayer.title', { name: layerName })}
      open={visible}
      onOk={handleAssign}
      onCancel={onClose}
      confirmLoading={loading}
      okText={t('assignLayer.okText')}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '8px 0' }}>
        <Typography.Text>
          {t('assignLayer.description')}
        </Typography.Text>
        <Select
          value={targetLayer}
          onChange={setTargetLayer}
          style={{ width: '100%' }}
          options={[
            { value: 'boundary', label: t('assignLayer.targetBoundary') },
            { value: 'blocks', label: t('assignLayer.targetBlocks') },
            { value: 'compartments', label: t('assignLayer.targetCompartments') },
            { value: 'sub_areas', label: t('assignLayer.targetSubAreas') },
          ]}
        />
      </div>
    </Modal>
  );
}