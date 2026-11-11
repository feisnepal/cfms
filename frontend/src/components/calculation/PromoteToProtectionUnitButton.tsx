/**
 * PromoteToProtectionUnitButton — turn a protected sub-area into a standalone
 * Protection Working Circle unit (numbered P-N), carved out of whatever
 * production compartment(s) it overlapped.
 *
 * PROTECTION_WORKING_CIRCLE_PLAN.md P3. The reverse ("Merge back into
 * compartment") is `demoteProtectionUnit` — wired where protection units are
 * listed. Self-contained so it drops into any sub-area row.
 */
import { useState } from 'react';
import { Modal, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { forestApi } from '../../services/api';

interface Props {
  calculationId: string;
  subAreaId: string;
  subAreaName?: string;
  /** refetch the calculation after a successful promote */
  onDone: () => void | Promise<void>;
  disabled?: boolean;
}

export function PromoteToProtectionUnitButton({
  calculationId,
  subAreaId,
  subAreaName,
  onDone,
  disabled,
}: Props) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      const res = await forestApi.promoteSubAreaToUnit(calculationId, subAreaId);
      await onDone();
      setOpen(false);
      message.success(t('protectionUnit.promoted', { name: res?.name || 'P' }));
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: { code?: string; message?: string } | string } } })
        ?.response?.data?.detail;
      const code = typeof detail === 'object' ? detail?.code : undefined;
      const msg =
        code === 'STRUCTURE_LOCKED'
          ? t('protectionUnit.lockedError')
          : (typeof detail === 'object' ? detail?.message : detail) || t('protectionUnit.promoteFailed');
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
        className="text-xs text-emerald-700 hover:text-emerald-900 disabled:text-gray-400"
      >
        {t('protectionUnit.makeUnit')}
      </button>
      <Modal
        open={open}
        title={t('protectionUnit.makeUnitTitle')}
        onCancel={running ? undefined : () => setOpen(false)}
        onOk={run}
        okText={t('protectionUnit.makeUnit')}
        cancelText={t('common.cancel')}
        confirmLoading={running}
        cancelButtonProps={{ disabled: running }}
        mask={{ closable: !running }}
        keyboard={!running}
      >
        <p className="text-sm text-gray-700">
          {t('protectionUnit.confirmBody', { name: subAreaName || t('protectionUnit.thisSubArea') })}
        </p>
      </Modal>
    </>
  );
}

export default PromoteToProtectionUnitButton;
