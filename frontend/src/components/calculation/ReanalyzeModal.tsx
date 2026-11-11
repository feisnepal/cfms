/**
 * ReanalyzeModal — "Re-run Analysis" for the tabbed calculation shell.
 *
 * Single Workspace task A5a: the legacy page (`CalculationDetail.tsx`) was the
 * only place `forestApi.reanalyze` could be triggered. Lifted here so the legacy
 * shell can be deleted (A5b). Same `AnalysisOptionsPanel`; existing results are
 * preserved, only newly selected analyses are added.
 */
import { useWorkspaceStore } from '../../store/workspaceStore';
import { useState } from 'react';
import { Modal, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { forestApi } from '../../services/api';
import AnalysisOptionsPanel from '../AnalysisOptionsPanel';
import { DEFAULT_ANALYSIS_OPTIONS } from '../../constants/analysisPresets';
import type { AnalysisOptions } from '../../constants/analysisPresets';

interface ReanalyzeModalProps {
  open: boolean;
  calculationId: string;
  onClose: () => void;
  /** refresh the calculation after a successful re-run */
  onDone: () => void | Promise<void>;
}

export function ReanalyzeModal({ open, calculationId, onClose, onDone }: ReanalyzeModalProps) {
  const t = useT();
  const [options, setOptions] = useState<AnalysisOptions>(DEFAULT_ANALYSIS_OPTIONS);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      await forestApi.reanalyze(calculationId, options);
      await onDone();
      // The unit layers' attribute tables read the per-unit analysis; reload them so the new values show without a page refresh.
      useWorkspaceStore.getState().bumpGeometryVersion();
      onClose();
      message.success(t('calc.reanalyze.done'));
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } } | undefined)?.response?.data
        ?.detail;
      message.error(detail || t('calc.reanalyze.failed'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal
      open={open}
      title={t('calc.reanalyze.title')}
      onCancel={running ? undefined : onClose}
      onOk={run}
      okText={t('calc.reanalyze.action')}
      cancelText={t('common.cancel')}
      confirmLoading={running}
      cancelButtonProps={{ disabled: running }}
      mask={{ closable: !running }}
      keyboard={!running}
      width={760}
    >
      <p className="text-sm text-gray-600" style={{ marginBottom: 16 }}>
        {t('calc.reanalyze.hint')}
      </p>
      <AnalysisOptionsPanel options={options} onChange={setOptions} disabled={running} />
    </Modal>
  );
}

export default ReanalyzeModal;
