import { Alert, Button, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import React from 'react';
import { useTranslation } from 'react-i18next';

import {
  UnitBand,
  UnitSizeCandidate,
  UnitSizeSummary,
} from '../../services/api';

const { Text, Paragraph } = Typography;

interface UnitSizeTableProps {
  candidates: UnitSizeCandidate[];
  summary?: UnitSizeSummary;
  mmuHa?: number;
  reviewPct?: number;
  /** Rendered under the table - a hint about where the action actually happens. */
  footer?: React.ReactNode;
  onLinkToSampling?: () => void;
  /**
   * Called with a candidate the user asked to merge. The table NEVER merges on its
   * own - it hands the proposal up and the parent opens the confirm dialog, so a
   * structural change always passes through an explicit confirmation.
   */
  onMergeRequest?: (candidate: UnitSizeCandidate) => void;
  emptyText?: string;
  loading?: boolean;
  error?: string | null;
}

const BAND_COLOR: Record<UnitBand, string> = {
  sub_mmu: 'volcano',
  review: 'gold',
  ok: 'green',
};

/**
 * The band table, shared by the sampling review (tier 1) and the field-inventory
 * note, so the two surfaces can never present the same polygon differently.
 *
 * Read-only by construction: it shows a *proposal* and never applies one. Merging is
 * a structural change and belongs to the map workspace - the panel says so rather
 * than pretending otherwise.
 */
export const UnitSizeTable: React.FC<UnitSizeTableProps> = ({
  candidates,
  summary,
  mmuHa,
  reviewPct,
  footer,
  onLinkToSampling,
  onMergeRequest,
  emptyText,
  loading,
  error,
}) => {
  const { t } = useTranslation();

  const bandLabel = (band: UnitBand) => {
    if (band === 'sub_mmu') return t('sampling.unitReview.subMmu');
    if (band === 'review') return t('sampling.unitReview.reviewBand');
    return t('sampling.unitReview.ok');
  };

  const bandHelp = (band: UnitBand) => {
    if (band === 'sub_mmu') return t('sampling.unitReview.subMmuHelp');
    if (band === 'review') return t('sampling.unitReview.reviewBandHelp');
    return t('sampling.unitReview.okHelp');
  };

  if (loading) {
    return <Text type="secondary">{t('sampling.unitReview.loading')}</Text>;
  }

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        message={t('sampling.unitReview.error')}
        description={error}
      />
    );
  }

  if (!candidates || candidates.length === 0) {
    return (
      <Alert
        type="info"
        showIcon
        message={emptyText || t('sampling.unitReview.empty')}
      />
    );
  }

  const columns: ColumnsType<UnitSizeCandidate> = [
    {
      title: t('sampling.unitReview.unit'),
      dataIndex: 'block_name',
      key: 'block_name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: t('sampling.unitReview.area'),
      dataIndex: 'area_ha',
      key: 'area_ha',
      align: 'right',
      render: (ha: number) => `${Number(ha).toFixed(ha < 1 ? 4 : 2)} ha`,
    },
    {
      title: t('sampling.unitReview.band'),
      dataIndex: 'band',
      key: 'band',
      render: (band: UnitBand) => (
        <Tooltip title={bandHelp(band)}>
          <Tag color={BAND_COLOR[band]}>{bandLabel(band)}</Tag>
        </Tooltip>
      ),
    },
  ];

  // Only propose a merge where one is actually possible, and never for a unit that
  // has nothing to merge into - a proposal that cannot be acted on is worse than
  // saying so plainly.
  if (candidates.some((c) => c.action === 'merge_offer')) {
    columns.push({
      title: t('sampling.unitReview.proposal'),
      key: 'proposal',
      render: (_: unknown, row: UnitSizeCandidate) => {
        if (row.action !== 'merge_offer') return null;
        if (row.unmergeable || !row.neighbour) {
          return (
            <Text type="secondary">
              <ExclamationCircleOutlined style={{ marginInlineEnd: 6 }} />
              {t('sampling.unitReview.unmergeable')}
            </Text>
          );
        }
        return (
          <Text>
            {row.block_name} → <Text strong>{row.neighbour}</Text>
            {row.neighbour_area_ha != null && (
              <Text type="secondary">
                {' '}
                ({Number(row.neighbour_area_ha).toFixed(2)} ha)
              </Text>
            )}
          </Text>
        );
      },
    });
  }

  columns.push({
    title: t('sampling.unsampled.reason'),
    key: 'reason',
    render: (_: unknown, row: UnitSizeCandidate) => (
      <Text type="secondary">{row.reason}</Text>
    ),
  });

  // The action is per row, never per table: there is deliberately no "merge all",
  // because one stray click must not reshape a forest.
  if (onMergeRequest) {
    columns.push({
      title: '',
      key: 'merge',
      width: 110,
      render: (_: unknown, row: UnitSizeCandidate) => {
        // Only a real, complete proposal can be acted on. A proposal missing either
        // id, or the layer type, cannot be sent safely - so it is not offered.
        const actionable =
          row.action === 'merge_offer' &&
          !row.unmergeable &&
          Boolean(row.id) &&
          Boolean(row.neighbour_id) &&
          Boolean(row.layer_type);
        if (!actionable) return null;
        return (
          <Button size="small" onClick={() => onMergeRequest(row)}>
            {t('sampling.unitReview.mergeButton')}
          </Button>
        );
      },
    });
  }

  return (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      {summary && (
        <Text type="secondary">
          {t('sampling.unitReview.summaryLine', {
            total: summary.total,
            sub_mmu: summary.sub_mmu,
            review: summary.review,
            ok: summary.ok,
          })}
          {mmuHa != null && (
            <>
              {' · '}
              {t('sampling.unitReview.mmu')}: {mmuHa} ha
            </>
          )}
          {reviewPct != null && (
            <>
              {' · '}
              {t('sampling.unitReview.reviewScreen')}: {reviewPct}%
            </>
          )}
        </Text>
      )}
      <Table
        size="small"
        rowKey="block_name"
        columns={columns}
        dataSource={candidates}
        pagination={false}
        scroll={{ x: true }}
      />
      <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
        {t('sampling.unitReview.openHint')}
      </Paragraph>
      {footer}
      {onLinkToSampling && (
        <Button size="small" onClick={onLinkToSampling}>
          {t('sampling.unsampled.seeSampling')}
        </Button>
      )}
    </Space>
  );
};

export default UnitSizeTable;
