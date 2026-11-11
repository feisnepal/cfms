/**
 * DemoteProtectionUnitButton — merge a Protection Working Circle unit back into
 * the compartment(s) it was carved from, restoring the protected sub-area.
 *
 * PROTECTION_WORKING_CIRCLE_PLAN.md P5 — the inverse of
 * `PromoteToProtectionUnitButton`. Uses the snapshot the promote stashed on
 * `result_data`; a snapshot-less unit re-emits its geometry as a sub-area.
 */
import { useState } from 'react';
import { Modal, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { forestApi } from '../../services/api';

interface Props {
  calculationId: string;
  blockId: string;
  unitName?: string;
  onDone: () => void | Promise<void>;
  disabled?: boolean;
}

export function DemoteProtectionUnitButton({
  calculationId,
  blockId,
  unitName,
  onDone,
  disabled,
}: Props) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      await forestApi.demoteProtectionUnit(calculationId, blockId);
      await onDone();
      setOpen(false);
      message.success(t('protectionUnit.demoted', { name: unitName || 'P' }));
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: { code?: string; message?: string } | string } } })
        ?.response?.data?.detail;
      const code = typeof detail === 'object' ? detail?.code : undefined;
      const msg =
        code === 'STRUCTURE_LOCKED'
          ? t('protectionUnit.lockedError')
          : (typeof detail === 'object' ? detail?.message : detail) || t('protectionUnit.demoteFailed');
      message.error(msg);
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        className="text-xs text-amber-700 hover:text-amber-900 disabled:text-gray-400"
      >
        {t('protectionUnit.mergeBack')}
      </button>
      <Modal
        open={open}
        title={t('protectionUnit.mergeBackTitle')}
        onCancel={running ? undefined : () => setOpen(false)}
        onOk={run}
        okText={t('protectionUnit.mergeBack')}
        cancelText={t('common.cancel')}
        confirmLoading={running}
        cancelButtonProps={{ disabled: running }}
        mask={{ closable: !running }}
        keyboard={!running}
      >
        <p className="text-sm text-gray-700">
          {t('protectionUnit.mergeBackBody', { name: unitName || t('protectionUnit.thisUnit') })}
        </p>
      </Modal>
    </>
  );
}

export default DemoteProtectionUnitButton;
