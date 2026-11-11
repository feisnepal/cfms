/** PlanValidityModal -- "Check my document": what the owner's edits would leave wrong in the printed plan. Never blocks. */
import React from 'react';
import { Modal, Alert, List, Tag, Typography, Collapse } from 'antd';
import type { PlanValidity, PlanValidityIssue } from '../../services/api';
import { useT } from '../../i18n/hooks';

const { Text } = Typography;

// Codes that have a plain-language line in both languages (operationalPlan.validity.code.*); anything else shows the server's text.
const KNOWN_CODES = new Set([
  'unknown_token', 'broken_token', 'empty_section', 'chart_node_no_type', 'map_node_no_type', 'table_node_no_ref',
  'duplicate_title', 'table_id_unknown', 'chart_type_unknown', 'map_type_unknown', 'static_table_empty', 'too_deep', 'duplicate_id',
]);

interface Props {
  open: boolean;
  data: PlanValidity | null;
  onClose: () => void;
  /** Take the user to the section an issue is in. */
  onJump: (nodeId: string) => void;
}

export default function PlanValidityModal({ open, data, onClose, onJump }: Props) {
  const t = useT();
  const line = (i: PlanValidityIssue) =>
    KNOWN_CODES.has(i.code)
      ? t(`operationalPlan.validity.code.${i.code}`, { token: i.token ?? '', title: i.title ?? '' })
      : i.message;

  const list = (issues: PlanValidityIssue[]) => (
    <List
      size="small"
      dataSource={issues}
      renderItem={(i) => (
        <List.Item
          style={{ cursor: i.node_id ? 'pointer' : 'default' }}
          onClick={() => { if (i.node_id) { onClose(); onJump(i.node_id); } }}
          data-testid={`validity-${i.code}`}
        >
          <div>
            <div>{line(i)}</div>
            {i.title && <Text type="secondary" style={{ fontSize: 12 }}>{i.title}</Text>}
          </div>
        </List.Item>
      )}
    />
  );

  // A fresh plan has dozens of "empty section" lines; one kind of problem becomes one folded row so the few that matter stay visible.
  const GROUP_FROM = 4;
  const block = (issues: PlanValidityIssue[], tone: 'error' | 'warning') => {
    if (issues.length === 0) return null;
    const byCode = new Map<string, PlanValidityIssue[]>();
    issues.forEach((i) => byCode.set(i.code, [...(byCode.get(i.code) ?? []), i]));
    const small = issues.filter((i) => (byCode.get(i.code) ?? []).length < GROUP_FROM);
    const groups = [...byCode.entries()].filter(([, v]) => v.length >= GROUP_FROM);
    return (
      <div style={{ marginBottom: 16 }}>
        <Tag color={tone === 'error' ? 'red' : 'orange'}>
          {t(tone === 'error' ? 'operationalPlan.validity.errors' : 'operationalPlan.validity.warnings', { count: issues.length })}
        </Tag>
        {small.length > 0 && list(small)}
        {groups.length > 0 && (
          <Collapse
            size="small"
            ghost
            items={groups.map(([code, v]) => ({
              key: code,
              label: <span data-testid={`validity-group-${code}`}>{line(v[0])} <Tag>{v.length}</Tag></span>,
              children: list(v),
            }))}
          />
        )}
      </div>
    );
  };

  return (
    <Modal open={open} onCancel={onClose} onOk={onClose} cancelButtonProps={{ style: { display: 'none' } }}
      title={t('operationalPlan.validity.title')} width={620}>
      {!data ? null : data.errors.length + data.warnings.length === 0 ? (
        <Alert type="success" showIcon message={t('operationalPlan.validity.allGood')} />
      ) : (
        <>
          <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>{t('operationalPlan.validity.hint')}</Text>
          {block(data.errors, 'error')}
          {block(data.warnings, 'warning')}
        </>
      )}
    </Modal>
  );
}
