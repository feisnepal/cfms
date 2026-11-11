import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CloseOutlined, FileTextOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { operationalPlanApi } from '../../services/api';
import { useT } from '../../i18n/hooks';

interface Props {
  calculationId?: string;
  /** every required step of the workflow is done (the same list the export gate uses) */
  ready: boolean;
  loading?: boolean;
}

const KEY = (id: string) => `tsb-dismissed-${id}`;

/**
 * "Your data is ready: choose a template." Shown once every required step is done and the forest has no plan yet. It is the
 * hand-off from data entry to the Template Store, where the user picks a template and either exports at once or customises it
 * (owner, 2026-10-18). It informs and offers a button; it never moves the user by itself, because steps such as household
 * data or cost-benefit may still be in progress. Closing it is remembered for this forest in this browser.
 */
export const TemplateStoreBanner: React.FC<Props> = ({ calculationId, ready, loading }) => {
  const t = useT();
  const navigate = useNavigate();
  const [noPlan, setNoPlan] = useState(false);
  const [closed, setClosed] = useState(() => {
    try {
      return !!calculationId && window.localStorage.getItem(KEY(calculationId)) === '1';
    } catch {
      return false; // storage can be blocked; the banner then simply shows again
    }
  });

  useEffect(() => {
    if (!calculationId || !ready || loading) {
      setNoPlan(false);
      return;
    }
    let alive = true;
    operationalPlanApi
      .getByCalculation(calculationId)
      .then(() => alive && setNoPlan(false)) // a plan exists: the user has already chosen
      .catch((e: any) => alive && setNoPlan(e?.response?.status === 404));
    return () => {
      alive = false;
    };
  }, [calculationId, ready, loading]);

  if (!calculationId || !ready || loading || !noPlan || closed) return null;

  const close = () => {
    setClosed(true);
    try {
      window.localStorage.setItem(KEY(calculationId), '1');
    } catch {
      /* not remembered; harmless */
    }
  };

  return (
    <div
      role="status"
      data-testid="template-store-banner"
      className="flex items-center gap-3 px-3 py-2 border-b border-green-200 bg-green-50 text-green-900 text-sm"
    >
      <FileTextOutlined />
      <span className="flex-1">{t('workflow.store.banner')}</span>
      <Button
        type="primary"
        size="small"
        data-testid="template-store-banner-go"
        onClick={() => navigate(`/templates?calculation_id=${calculationId}`)}
      >
        {t('workflow.store.bannerButton')}
      </Button>
      <button
        type="button"
        onClick={close}
        aria-label={t('workflow.store.dismiss')}
        className="text-green-700 hover:text-green-900"
      >
        <CloseOutlined />
      </button>
    </div>
  );
};

export default TemplateStoreBanner;
