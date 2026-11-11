import React, { useState } from 'react';
import { Button, Dropdown, Modal, message } from 'antd';
import { DownOutlined, FileTextOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { downloadPlanFile, planExportLang, type PlanExportKind } from './planExport';
import { usePlanCheck } from './PlanCheck';

interface Props {
  calculationId: string;
  /** The screen has changes that are not saved: an exported file holds saved data only, so ask first. */
  unsaved?: boolean;
  /** Save the screen's changes; resolves true when everything was saved. */
  onSave?: () => Promise<boolean>;
  disabled?: boolean;
  size?: 'small' | 'middle';
  /** the person chose to fix something the plan check listed: take them to that activity */
  onFixIssue?: (activityId: string) => void;
}

/**
 * The Export button of both yearly-activities screens: a small menu with the two named files (the yearly plan
 * and the activity features). When the screen has unsaved changes it first asks whether to save them.
 */
export const PlanExportMenu: React.FC<Props> = ({ calculationId, unsaved, onSave, disabled, size = 'middle', onFixIssue }) => {
  const { t, i18n } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<PlanExportKind | null>(null);
  // before a file is made: anything still unfinished is listed once — it warns, it never blocks (D24)
  const check = usePlanCheck({ onFix: (_id, activityId) => onFixIssue?.(activityId) });

  const run = async (kind: PlanExportKind) => {
    setBusy(true);
    try {
      await downloadPlanFile(calculationId, kind, planExportLang(i18n.language));
      message.success(t('yearlyPlan.export.done'));
    } catch {
      message.error(t('yearlyPlan.export.failed'));
    } finally {
      setBusy(false);
    }
  };

  const go = (kind: PlanExportKind) => check.guard(calculationId, () => run(kind), 'export');

  const choose = (kind: PlanExportKind) => {
    if (unsaved) setAsking(kind);
    else void go(kind);
  };

  const saveThenExport = async () => {
    const kind = asking;
    setAsking(null);
    if (!kind) return;
    if (onSave && !(await onSave())) return; // the page has already said what could not be saved
    await go(kind);
  };

  const exportSaved = () => {
    const kind = asking;
    setAsking(null);
    if (kind) void go(kind);
  };

  return (
    <>
      <Dropdown
        disabled={disabled}
        menu={{
          items: [
            { key: 'plan', label: t('yearlyPlan.export.plan') },
            { key: 'features', label: t('yearlyPlan.export.features') },
          ],
          onClick: ({ key }) => choose(key as PlanExportKind),
        }}
      >
        <Button size={size} icon={<FileTextOutlined />} loading={busy} disabled={disabled} data-testid="plan-export">
          {t('yearlyPlan.export.menu')} <DownOutlined />
        </Button>
      </Dropdown>
      <Modal
        open={asking !== null}
        title={t('yearlyPlan.export.saveFirstTitle')}
        onCancel={() => setAsking(null)}
        footer={[
          <Button key="cancel" onClick={() => setAsking(null)} data-testid="export-cancel">
            {t('common.cancel')}
          </Button>,
          <Button key="saved" onClick={exportSaved} data-testid="export-saved">
            {t('yearlyPlan.export.exportSaved')}
          </Button>,
          <Button key="save" type="primary" onClick={() => void saveThenExport()} data-testid="export-save-first">
            {t('yearlyPlan.export.saveAndExport')}
          </Button>,
        ]}
      >
        {t('yearlyPlan.export.saveFirstBody')}
      </Modal>
      {check.dialog}
    </>
  );
};

export default PlanExportMenu;
