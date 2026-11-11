import { useState, useEffect } from 'react';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';
import { Modal, Button, Tag, Spin, Table, Alert, Typography, Space } from 'antd';
import { WarningOutlined, CheckCircleOutlined } from '@ant-design/icons';
import type { GeoJSON } from 'geojson';

const { Text } = Typography;

interface BlockEditCollisionWarningProps {
  visible: boolean;
  blockId: string;
  blockName: string;
  calculationId: string;
  onContinue: () => void;
  onCancel: () => void;
}

interface IntersectingFeature {
  id: string;
  name: string;
  type: string;
  years: number[];
}

const TYPE_COLORS: Record<string, string> = {
  Point: 'blue',
  LineString: 'geekblue',
  Polygon: 'purple',
};

export function BlockEditCollisionWarning({
  visible, blockId, blockName, calculationId, onContinue, onCancel,
}: BlockEditCollisionWarningProps) {
  const t = useT();
  const [features, setFeatures] = useState<IntersectingFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !blockId) return;
    setLoading(true);
    setError(null);
    fetch(`/api/calculations/${calculationId}/drawn-features/intersecting?block_id=${blockId}`)
      .then(r => { if (!r.ok) throw new Error(t('editing.collision.fetchFailed')); return r.json(); })
      .then(data => setFeatures(data?.features || []))
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [visible, blockId, calculationId]);

  const columns = [
    {
      title: t('editing.collision.colType'),
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (type: string) => (
        <Tag color={TYPE_COLORS[type] || 'default'}>{type}</Tag>
      ),
    },
    {
      title: t('editing.collision.colName'),
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => name || t('editing.collision.unnamed'),
    },
    {
      title: t('editing.collision.colYears'),
      dataIndex: 'years',
      key: 'years',
      width: 120,
      render: (years: number[]) => years?.join(', ') || '-',
    },
  ];

  return (
    <Modal
      title={<Space><WarningOutlined style={{ color: '#faad14' }} />{t('editing.collision.title')}</Space>}
      open={visible}
      onCancel={onCancel}
      footer={
        <Space>
          <Button onClick={onCancel}>{t('common.cancel')}</Button>
          <Button type="primary" onClick={onContinue}>{t('editing.collision.continueEditing')}</Button>
        </Space>
      }
      width={520}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        {t('editing.collision.contains', {
          block: blockName,
          count: loading ? '…' : formatNumber(features.length),
        })}
      </div>

      <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 13 }}>
        {t('editing.collision.warning')}
      </Text>

      {loading && (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
          <div style={{ marginTop: 8 }}>{t('editing.collision.loadingFeatures')}</div>
        </div>
      )}

      {error && (
        <Alert message={t('editing.collision.loadError')} description={error} type="error" showIcon style={{ marginBottom: 12 }} />
      )}

      {!loading && !error && features.length > 0 && (
        <Table
          dataSource={features}
          columns={columns}
          rowKey="id"
          pagination={false}
          size="small"
          scroll={{ y: 200 }}
        />
      )}

      {!loading && !error && features.length === 0 && (
        <Alert
          icon={<CheckCircleOutlined />}
          message={t('editing.collision.noIntersecting')}
          type="success"
          showIcon
        />
      )}
    </Modal>
  );
}

export default BlockEditCollisionWarning;
