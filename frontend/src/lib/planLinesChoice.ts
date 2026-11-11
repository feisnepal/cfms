import { Modal } from 'antd';
import type { TFunction } from 'i18next';

/** The server refuses to remove a sub-area that has yearly-plan lines until the user says what happens to them. */
export const PLAN_LINES_CODE = 'yearly_plan.sub_area_has_plan_lines';

export interface PlanLinesDetail {
  count?: number;
  names?: string;
  message?: string;
  message_np?: string;
}

export class PlanLinesChoiceError extends Error {
  readonly detail: PlanLinesDetail;

  constructor(detail: PlanLinesDetail) {
    super(detail.message || 'This sub-area is tied to the yearly plan');
    this.name = 'PlanLinesChoiceError';
    this.detail = detail;
  }
}

/** The detail of a 409 "choose what happens to the plan lines" answer (an axios error or a fetch body), else null. */
export function planLinesDetail(source: unknown): PlanLinesDetail | null {
  const err = source as { response?: { status?: number; data?: { detail?: unknown } } } | undefined;
  const detail = (err?.response ? err.response.data?.detail : source) as (PlanLinesDetail & { code?: string }) | undefined;
  return detail && typeof detail === 'object' && detail.code === PLAN_LINES_CODE ? detail : null;
}

/** Ask the user. Resolves 'delete' (the lines go with the sub-area), 'keep' (they stay as forest-wide lines) or null (cancel). */
export function chooseWhatHappensToPlanLines(detail: PlanLinesDetail, t: TFunction): Promise<'delete' | 'keep' | null> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v: 'delete' | 'keep' | null) => {
      if (!done) {
        done = true;
        resolve(v);
      }
    };
    Modal.confirm({
      title: t('subAreaPlan.deleteTitle') as string,
      content: t('subAreaPlan.deleteContent', { count: detail.count ?? 0, names: detail.names ?? '' }) as string,
      okText: t('subAreaPlan.deleteWithIt') as string,
      okType: 'danger',
      cancelText: t('subAreaPlan.keepAsForestWide') as string,
      closable: true,
      maskClosable: true,
      onOk: () => finish('delete'),
      onCancel: () => finish('keep'),
      afterClose: () => finish(null),
    });
  });
}
