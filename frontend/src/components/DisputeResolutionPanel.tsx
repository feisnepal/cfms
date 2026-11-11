import React, { useEffect, useState } from 'react'
import { Card, Typography, Tag, Button, Select, Input, Space, Spin, message, Descriptions } from 'antd'
import { useT } from '../i18n/hooks'
import { formatDateTime, formatNumber } from '../i18n/numberFormat'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

interface DisputeDetail {
  id: number
  forest_id_1: string
  forest_id_2: string
  dispute_reason_np: string
  status: string
  forest_1_boundary?: any
  forest_2_proposed?: any
  forest_2_clipped?: any
  overlap_area?: any
  created_at: string
  resolution_type?: string
  resolution_notes_np?: string
}

export default function DisputeResolutionPanel() {
  const t = useT()
  const [disputes, setDisputes] = useState<DisputeDetail[]>([])
  const [selectedDispute, setSelectedDispute] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<DisputeDetail | null>(null)
  const [targetForestId, setTargetForestId] = useState<string>('')
  const [resolutionType, setResolutionType] = useState<string>('edit_forest_2')
  const [reasonNp, setReasonNp] = useState('')
  const [resolving, setResolving] = useState(false)

  useEffect(() => {
    loadDisputes()
  }, [])

  async function loadDisputes() {
    setLoading(true)
    try {
      const resp = await fetch('/api/admin/boundary-disputes')
      const data = await resp.json()
      setDisputes(data || [])
    } catch {
      message.error(t('boundary.dispute.loadFailed'))
    } finally {
      setLoading(false)
    }
  }

  async function loadDetail(id: number) {
    setSelectedDispute(id)
    setLoading(true)
    try {
      const resp = await fetch(`/api/admin/boundary-disputes/${id}`)
      const data = await resp.json()
      setDetail(data)
      setTargetForestId('')
    } catch {
      message.error(t('boundary.dispute.loadDetailFailed'))
    } finally {
      setLoading(false)
    }
  }

  async function handleResolve() {
    if (!selectedDispute || !targetForestId) {
      message.warning(t('boundary.dispute.selectTarget'))
      return
    }
    if (reasonNp.length < 10) {
      message.warning(t('boundary.dispute.reasonTooShort'))
      return
    }
    setResolving(true)
    try {
      const resp = await fetch(`/api/admin/boundary-disputes/${selectedDispute}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          forest_id: targetForestId,
          new_boundary: {},
          reason_np: reasonNp,
          resolution_type: resolutionType,
        }),
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || t('boundary.dispute.resolveFailed'))
      }
      message.success(t('boundary.dispute.msgResolved'))
      loadDisputes()
      setDetail(null)
      setSelectedDispute(null)
      setReasonNp('')
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setResolving(false)
    }
  }

  if (loading && !detail) {
    return (
      <div style={{ textAlign: 'center', margin: '40px auto' }}>
        <Spin />
        <div style={{ marginTop: 8 }}>{t('common.loading')}</div>
      </div>
    )
  }

  return (
    <Card title={t('boundary.dispute.title')} style={{ maxWidth: 800, margin: '0 auto' }}>
      {!detail ? (
        <div>
          <Text strong>{t('boundary.dispute.openDisputes', { count: formatNumber(disputes.length) })}</Text>
          {disputes.map(d => (
            <Card
              key={d.id}
              size="small"
              style={{ marginTop: 8, cursor: 'pointer' }}
              onClick={() => loadDetail(d.id)}
            >
              <Descriptions size="small" column={2}>
                <Descriptions.Item label={t('boundary.dispute.disputeNo')}>{d.id}</Descriptions.Item>
                <Descriptions.Item label={t('boundary.dispute.status')}>
                  <Tag color={d.status === 'open' ? 'orange' : 'green'}>{d.status}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label={t('boundary.dispute.forest1')}>{d.forest_id_1.slice(0, 8)}...</Descriptions.Item>
                <Descriptions.Item label={t('boundary.dispute.forest2')}>{d.forest_id_2.slice(0, 8)}...</Descriptions.Item>
              </Descriptions>
            </Card>
          ))}
          {disputes.length === 0 && <Text type="secondary">{t('boundary.dispute.noDisputes')}</Text>}
        </div>
      ) : (
        <div>
          <Title level={5}>{t('boundary.dispute.disputeNumber', { id: detail.id })}</Title>
          <Descriptions column={2} size="small">
            <Descriptions.Item label={t('boundary.dispute.status')}>
              <Tag color={detail.status === 'open' ? 'orange' : 'green'}>{detail.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('boundary.dispute.forest1Id')}>{detail.forest_id_1.slice(0, 12)}...</Descriptions.Item>
            <Descriptions.Item label={t('boundary.dispute.forest2Id')}>{detail.forest_id_2.slice(0, 12)}...</Descriptions.Item>
            <Descriptions.Item label={t('boundary.dispute.filedAt')}>
              {formatDateTime(detail.created_at, { year: 'numeric', month: 'numeric', day: 'numeric' })}
            </Descriptions.Item>
          </Descriptions>

          <Paragraph style={{ marginTop: 12 }}>
            <Text strong>{t('boundary.dispute.reasonLabel')}</Text>
            <br />
            {detail.dispute_reason_np}
          </Paragraph>

          <Space direction="vertical" style={{ width: '100%', marginTop: 16 }}>
            <Text strong>{t('boundary.dispute.resolution')}</Text>
            <Select
              style={{ width: '100%' }}
              placeholder={t('boundary.dispute.phWhichForest')}
              value={resolutionType}
              onChange={setResolutionType}
              options={[
                { value: 'edit_forest_1', label: t('boundary.dispute.editForest1') },
                { value: 'edit_forest_2', label: t('boundary.dispute.editForest2') },
                { value: 'dismiss', label: t('boundary.dispute.dismiss') },
              ]}
            />
            <TextArea
              placeholder={t('boundary.dispute.phReason')}
              rows={3}
              value={reasonNp}
              onChange={e => setReasonNp(e.target.value)}
            />
            <Button
              type="primary"
              onClick={handleResolve}
              loading={resolving}
              disabled={!targetForestId && resolutionType !== 'dismiss'}
            >
              {t('boundary.dispute.resolve')}
            </Button>
            <Button onClick={() => { setDetail(null); setSelectedDispute(null) }}>
              {t('boundary.dispute.backToList')}
            </Button>
          </Space>
        </div>
      )}
    </Card>
  )
}
