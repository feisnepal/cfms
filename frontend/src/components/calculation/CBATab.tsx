/**
 * CBATab — container for the Cost-Benefit Analysis context in the calc shell
 * (CBA_MODULE_PLAN.md P4).
 *
 * P4 is the shell: load the scenario list, render `CBAScenarioList`, and the
 * empty-state that creates the base scenario. The scenario editor (params +
 * default-rates + Compute + results), the cost/benefit tables, the charts and
 * the compare view mount below in P5–P6.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Spin, Alert, Button, Result, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { cbaApi, type CbaScenario, type CbaScenarioListItem } from '../../services/api';
import CBAScenarioList from './CBAScenarioList';
import CBAScenarioEditor from './CBAScenarioEditor';
import CBALineItemEditor from './CBALineItemEditor';
import CBAChartPanel from './CBAChartPanel';
import CBASensitivityView from './CBASensitivityView';
import CBACompareTable from './CBACompareTable';
import CbaPlanDriftBanner from './CbaPlanDriftBanner';
import { isYearlyPlanGuidanceEnabled } from '../../config/featureFlags';

interface Props {
  calculationId: string;
}

export const CBATab: React.FC<Props> = ({ calculationId }) => {
  const t = useT();
  const [scenarios, setScenarios] = useState<CbaScenarioListItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<CbaScenario | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const rows = await cbaApi.listScenarios(calculationId);
      setScenarios(rows);
      setSelectedId((prev) => {
        if (prev && rows.some((r) => r.id === prev)) return prev;
        const base = rows.find((r) => r.is_base_scenario) ?? rows[0];
        return base ? base.id : null;
      });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  const loadSelected = useCallback(async () => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    try {
      setSelected(await cbaApi.getScenario(calculationId, selectedId));
    } catch {
      setSelected(null);
    }
  }, [calculationId, selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadSelected();
  }, [loadSelected]);

  const refreshAll = useCallback(async () => {
    await Promise.all([load(), loadSelected()]);
  }, [load, loadSelected]);

  const createBase = async () => {
    setCreating(true);
    try {
      const s = await cbaApi.createScenario(calculationId, { name: t('cba.list.baseName') });
      setSelectedId(s.id);
      await load();
    } catch {
      message.error(t('cba.list.actionFailed'));
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }

  if (error || scenarios === null) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          message={t('cba.loadFailed')}
          action={
            <Button size="small" onClick={load}>
              {t('common.retry')}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ padding: 20, maxWidth: 1100 }}>
      <div style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>{t('cba.title')}</h3>
        <span style={{ fontSize: 12, color: '#888' }}>{t('cba.subtitle')}</span>
      </div>

      {scenarios.length === 0 ? (
        <Result
          status="info"
          title={t('cba.empty.title')}
          subTitle={t('cba.empty.body')}
          extra={
            <Button type="primary" loading={creating} onClick={createBase}>
              {t('cba.empty.cta')}
            </Button>
          }
        />
      ) : (
        <>
          {isYearlyPlanGuidanceEnabled() && scenarios.some((sc) => sc.is_base_scenario) && (
            <CbaPlanDriftBanner
              calculationId={calculationId}
              baseScenarioId={(scenarios.find((sc) => sc.is_base_scenario) as { id: string }).id}
              onUpdated={refreshAll}
            />
          )}
          <CBAScenarioList
            calculationId={calculationId}
            scenarios={scenarios}
            selectedId={selectedId}
            onSelect={(id) => setSelectedId(id || null)}
            onChanged={refreshAll}
          />
          {selected && (
            <>
              <CBAScenarioEditor
                calculationId={calculationId}
                scenario={selected}
                onChanged={refreshAll}
              />
              <CBALineItemEditor
                cbaId={selected.id}
                kind="cost"
                items={selected.cost_items}
                onChanged={refreshAll}
              />
              <CBALineItemEditor
                cbaId={selected.id}
                kind="benefit"
                items={selected.benefit_items}
                onChanged={refreshAll}
              />
              {selected.result && (
                <>
                  <CBAChartPanel cbaId={selected.id} refreshKey={selected.updated_at} />
                  <CBASensitivityView
                    calculationId={calculationId}
                    scenario={selected}
                    onChanged={refreshAll}
                  />
                </>
              )}
              <CBACompareTable
                calculationId={calculationId}
                scenarios={scenarios}
                onChanged={refreshAll}
              />
            </>
          )}
        </>
      )}
    </div>
  );
};

export default CBATab;
