import React from 'react'
import { Modal, Button, Statistic, Space, Typography } from 'antd'
import { useT } from '../i18n/hooks'

const { Text } = Typography

interface PreviewDiffModalProps {
  open: boolean
  origAreaHa: number
  resolvedAreaHa: number
  removedPct: number
  overlappingForests: Array<{ name?: string; overlap_ha: number }>
  onAccept: () => void
  onCancel: () => void
  loading?: boolean
}

export default function PreviewDiffModal({
  open,
  origAreaHa,
  resolvedAreaHa,
  removedPct,
  overlappingForests,
  onAccept,
  onCancel,
  loading,
}: PreviewDiffModalProps) {
  const t = useT()
  return (
    <Modal
      title={t('editing.boundaryOverlapDetected')}
      open={open}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t('common.cancel')}
        </Button>,
        <Button key="accept" type="primary" onClick={onAccept} loading={loading}>
          {t('editing.acceptClippedBoundary')}
        </Button>,
      ]}
      width={480}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Text>
          {t('editing.overlapClipExplanation')}
        </Text>

        <div style={{ display: 'flex', gap: 16, marginTop: 12 }}>
          <Statistic title={t('editing.originalArea')} value={origAreaHa.toFixed(2)} suffix="ha" />
          <Statistic
            title={t('editing.clippedArea')}
            value={resolvedAreaHa.toFixed(2)}
            suffix="ha"
            valueStyle={{ color: removedPct > 40 ? '#faad14' : undefined }}
          />
          <Statistic
            title={t('editing.removed')}
            value={removedPct.toFixed(1)}
            suffix="%"
            valueStyle={{ color: removedPct > 40 ? '#ff4d4f' : undefined }}
          />
        </div>

        {overlappingForests.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <Text strong>{t('editing.overlappingWith')}</Text>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {overlappingForests.map((f, i) => (
                <li key={i}>
                  {f.name || t('editing.forestNum', { num: i + 1 })} — {f.overlap_ha.toFixed(2)} ha
                </li>
              ))}
            </ul>
          </div>
        )}

        {removedPct > 40 && (
          <Text type="warning" style={{ marginTop: 8 }}>
            {t('editing.removedOver40Warning')}
          </Text>
        )}
      </Space>
    </Modal>
  )
}