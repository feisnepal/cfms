/**
 * "Create sample plots…" from the map workspace's Sample Plots layer.
 *
 * The full Sampling design form (method, intensity, plot size, protected-zone sampling,
 * per-unit floors, area basis, slope filter, preview) is `SamplingTab`. This hosts it over
 * the map instead of duplicating it, so there is one form to keep right: the workspace and
 * the Sampling page cannot drift apart.
 *
 * It opens on the create form when the forest has no design yet. When a design is created
 * the modal closes so the new plots are on the map straight away; a delete leaves it open
 * (the form is what the user is looking at) but still tells the workspace to refresh.
 */
import { Modal } from 'antd';
import { SamplingTab } from './SamplingTab';
import { useT } from '../i18n/hooks';

interface SamplePlotCreateModalProps {
  open: boolean;
  calculationId: string;
  onClose: () => void;
  /** A design was created or deleted — refresh the Sample Plots layer. */
  onChanged: (change: 'created' | 'deleted' | 'updated') => void;
}

export default function SamplePlotCreateModal({
  open,
  calculationId,
  onClose,
  onChanged,
}: SamplePlotCreateModalProps) {
  const t = useT();
  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={t('sampling.createFromMapTitle')}
      width="min(1100px, 96vw)"
      centered
      destroyOnHidden
      footer={null}
      styles={{ body: { maxHeight: '78vh', overflowY: 'auto' } }}
    >
      <SamplingTab
        calculationId={calculationId}
        startInCreateForm
        onDesignChanged={(change) => {
          onChanged(change);
          if (change === 'created') onClose();
        }}
      />
    </Modal>
  );
}
