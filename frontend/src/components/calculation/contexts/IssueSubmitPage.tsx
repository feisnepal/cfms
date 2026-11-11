/**
 * IssueSubmitPage — step 15, the terminal deliverable of a cycle.
 *
 * WORKSPACE_FLOW_NAV_PLAN D7/D8: the operational plan is exported to .docx,
 * printed, and submitted to the District Forest Office, and that submission is
 * how a cycle closes. This page exists in P2b — earlier than its full design —
 * because the nav item is the last step (15) and a registry entry with no component
 * renders a blank panel for the four phases before P6.
 *
 * What is here now, built on P0 and P1:
 *   - plan readiness (P0) — which of this plan's variables have no data
 *   - the existing DOCX export
 *   - the submission record and its history (P1)
 *
 * What P6 adds, and what is deliberately NOT here yet:
 *   - a dedicated Issue action, separated from the draft export, which today
 *     records an issuance as a side effect of *every* export
 *   - the verification code displayed back to the user
 *   - `plan.status` becoming a derived projection of the submission (D17)
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Descriptions, Empty, Space, Spin, Table, message } from 'antd';
import { useT } from '../../../i18n/hooks';
import { operationalPlanApi, subAreaPlanApi, type ExportRequirements, type SubAreaPlanItem } from '../../../services/api';
import { ExportRequirementsChecklist } from '../../ExportRequirementsChecklist';
import { SubAreaPlanDialog } from '../../../features/yearly-plan/SubAreaPlanDialog';
import { YearlyDoneBar } from '../../YearlyActivities/YearlyDoneBar';
import { requirementUrl } from '../../../lib/exportRequirementLinks';

interface Props {
  calculationId: string;
}

interface Readiness {
  total: number;
  resolved: number;
  ready: boolean;
  unverified: number;
  missing: { key: string; known: boolean; label_en: string; label_ne: string; reason_en: string; reason_ne: string }[];
  empty_lists: { key: string; label_en: string; label_ne: string; reason_en: string; reason_ne: string }[];
  unmet_maps: { token: string; status: string; reason_en: string; reason_ne: string; hint_en: string; hint_ne: string }[];
}

interface Submission {
  id: string;
  submitted_to: string;
  submitted_at: string | null;
  channel: string;
  reference_no: string | null;
}

const IssueSubmitPage: React.FC<Props> = ({ calculationId }) => {
  const t = useT();
  const [planId, setPlanId] = useState<string | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Sub-areas must be tied to the yearly plan before the plan can be issued (the server refuses otherwise).
  const [unplanned, setUnplanned] = useState<SubAreaPlanItem[]>([]);
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const [exportReq, setExportReq] = useState<ExportRequirements | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const plan = await operationalPlanApi.getByCalculation(calculationId);
      setPlanId(plan?.id ?? null);
      if (plan?.id) {
        const [r, s] = await Promise.all([
          fetch(`/api/operational-plans/${plan.id}/readiness`).then((res) =>
            res.ok ? res.json() : null,
          ),
          fetch(`/api/operational-plans/${plan.id}/submissions`)
            .then((res) => (res.ok ? res.json() : null))
            .catch(() => null),
        ]);
        setReadiness(r);
        setSubmissions(s?.submissions ?? []);
        // null on failure: the button is then left to the server's own refusal.
        setExportReq(await operationalPlanApi.getExportRequirements(plan.id).catch(() => null));
        try {
          const status = await subAreaPlanApi.status(calculationId);
          setUnplanned(status.sub_areas.filter((i) => ['needs_plan', 'no_unit', 'no_id'].includes(i.state)));
        } catch {
          setUnplanned([]); // the server still refuses an unplanned sub-area; this is only the explanation
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="p-6">
        <Spin />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <Alert type="error" message={error} />
      </div>
    );
  }

  if (!planId) {
    return (
      <div className="p-6">
        <Empty description={t('workspace.issueSubmit.noPlan')} />
      </div>
    );
  }

  const blocking = (readiness?.missing.length ?? 0) + (readiness?.unmet_maps.length ?? 0);

  return (
    <div className="p-6 space-y-4">
      <h2 className="text-lg font-semibold">{t('workspace.issueSubmit.title')}</h2>

      {/* the yearly activities are not finished until the owner says so; it never blocks the submission */}
      <YearlyDoneBar
        calculationId={calculationId}
        quietWhenDone
        onAddMore={() => {
          const url = requirementUrl(calculationId, 'yearly_activities');
          if (url) window.location.assign(url);
        }}
      />

      {readiness && (
        <Alert
          type={blocking === 0 ? 'success' : 'warning'}
          showIcon
          message={
            blocking === 0
              ? t('workspace.issueSubmit.readyMessage', {
                  total: readiness.total,
                  unverified: readiness.unverified,
                })
              : t('workspace.issueSubmit.blockedMessage', { count: blocking })
          }
          description={
            blocking > 0 ? (
              <ul className="list-disc pl-5 space-y-1">
                {readiness.missing.map((m) => (
                  <li key={m.key}>{m.reason_en}</li>
                ))}
                {readiness.unmet_maps.map((m) => (
                  <li key={m.token}>{m.reason_en}</li>
                ))}
              </ul>
            ) : null
          }
        />
      )}

      {/* ND-7: an empty list is allowed — the plan prints a grey note for it, so it never blocks issue */}
      {(readiness?.empty_lists?.length ?? 0) > 0 && (
        <p className="text-xs text-gray-500" data-testid="issue-empty-lists">
          {t('workspace.issueSubmit.emptyListsNote', { count: readiness!.empty_lists.length })}
        </p>
      )}

      {unplanned.length > 0 && (
        <Alert
          type="error"
          showIcon
          data-testid="issue-sub-areas-unplanned"
          message={t('subAreaPlan.issueBlocked', { count: unplanned.length })}
          description={
            <div>
              <ul className="list-disc pl-5 space-y-1">
                {unplanned.map((u) => (
                  <li key={u.id}>{u.name || u.id}</li>
                ))}
              </ul>
              <Button size="small" type="primary" style={{ marginTop: 8 }} onClick={() => setPlanDialogOpen(true)} data-testid="issue-plan-sub-areas">
                {t('subAreaPlan.planThem')}
              </Button>
            </div>
          }
        />
      )}
      <SubAreaPlanDialog
        open={planDialogOpen}
        calculationId={calculationId}
        onClose={() => {
          setPlanDialogOpen(false);
          void load();
        }}
        onChanged={() => undefined}
      />

      {exportReq && !exportReq.ready && <ExportRequirementsChecklist data={exportReq} calculationId={calculationId} />}

      <Space>
        <Button
          type="primary"
          disabled={!planId || unplanned.length > 0 || (exportReq !== null && !exportReq.ready)}
          onClick={() => {
            void operationalPlanApi.exportDocx(planId, 'CF').then(() => {
              message.success(t('operationalPlan.page.msgExported'));
            });
          }}
        >
          {t('operationalPlan.page.exportDocx')}
        </Button>
      </Space>

      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label={t('workspace.issueSubmit.exportNote')}>
          {t('workspace.issueSubmit.exportNoteBody')}
        </Descriptions.Item>
      </Descriptions>

      <Table<Submission>
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={submissions}
        locale={{ emptyText: t('workspace.issueSubmit.noSubmissions') }}
        columns={[
          {
            title: t('workspace.issueSubmit.colOffice'),
            dataIndex: 'submitted_to',
          },
          {
            title: t('workspace.issueSubmit.colDate'),
            dataIndex: 'submitted_at',
          },
          {
            title: t('workspace.issueSubmit.colChannel'),
            dataIndex: 'channel',
          },
          {
            title: t('workspace.issueSubmit.colReference'),
            dataIndex: 'reference_no',
          },
        ]}
      />
    </div>
  );
};

export default IssueSubmitPage;
