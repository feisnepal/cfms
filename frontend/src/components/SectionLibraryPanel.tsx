/** SectionLibraryPanel -- the shared library of single chapters ("sections"): browse everyone's, manage mine, or pick one to insert
 *  into the plan being edited. A section is shared, licensed, credited, reported and withdrawn exactly like a template. */
import React, { useCallback, useEffect, useState } from 'react';
import { Card, Segmented, Input, List, Button, Tag, Space, Typography, Empty, Spin, Modal, message } from 'antd';
import { ShareAltOutlined, DeleteOutlined, FlagOutlined, PlusOutlined } from '@ant-design/icons';
import { operationalPlanApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import ShareTemplateModal from './ShareTemplateModal';
import { TierTag, AuthorLine, ReportTemplateModal } from './TemplateCredit';
import { useT } from '../i18n/hooks';

const { Text } = Typography;

interface Section {
  id: string;
  name: string;
  description: string;
  status: string;
  share_scope?: string;
  tier?: string;
  license?: string;
  author_name?: string | null;
  created_by?: string | null;
  sections_summary?: string[];
  variables_summary?: string[];
}

interface Props {
  /** 'insert' shows an Insert button (the plan editor's dialog); 'browse' shows share / delete / report. */
  mode: 'browse' | 'insert';
  onInsert?: (section: Section) => void;
  initialScope?: 'published' | 'mine';
}

export default function SectionLibraryPanel({ mode, onInsert, initialScope = 'published' }: Props) {
  const t = useT();
  const { user } = useAuth();
  const [scope, setScope] = useState<'published' | 'mine'>(initialScope);
  const [search, setSearch] = useState('');
  const [items, setItems] = useState<Section[] | null>(null);
  const [shareTarget, setShareTarget] = useState<Section | null>(null);
  const [reportTarget, setReportTarget] = useState<string | null>(null);

  const load = useCallback(async () => {
    setItems(null);
    try {
      const res = await operationalPlanApi.listSections(scope, search.trim() || undefined);
      setItems(res.sections as Section[]);
    } catch {
      setItems([]);
      message.error(t('sections.loadFailed'));
    }
  }, [scope, search, t]);

  useEffect(() => { void load(); }, [load]);

  const confirmDelete = (s: Section) => {
    Modal.confirm({
      title: t('sections.deleteTitle', { name: s.name }),
      content: t('sections.deleteBody'),
      okText: t('templates.delete.ok'),
      okButtonProps: { danger: true },
      cancelText: t('templates.gallery.close'),
      onOk: async () => {
        try {
          const res = await operationalPlanApi.deleteTemplate(s.id);
          message.success(t(res?.status === 'withdrawn' ? 'templates.delete.withdrawn' : 'templates.delete.deleted'));
          void load();
        } catch {
          message.error(t('templates.delete.failed'));
        }
      },
    });
  };

  return (
    <div data-testid="section-library">
      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented
          value={scope}
          onChange={(v) => setScope(v as 'published' | 'mine')}
          options={[
            { value: 'published', label: t('sections.everyones') },
            { value: 'mine', label: t('sections.mine') },
          ]}
        />
        <Input.Search
          allowClear
          placeholder={t('sections.search')}
          onSearch={setSearch}
          style={{ width: 260 }}
        />
      </Space>

      {mode === 'browse' && <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>{t('sections.howTo')}</Text>}

      {items === null ? (
        <Spin />
      ) : items.length === 0 ? (
        <Empty description={t(scope === 'mine' ? 'sections.emptyMine' : 'sections.empty')} />
      ) : (
        <List
          grid={{ gutter: 12, xs: 1, sm: 1, md: 2, lg: 2, xl: 3 }}
          dataSource={items}
          renderItem={(s) => {
            const own = s.created_by === user?.id;
            return (
              <List.Item>
                <Card size="small" data-testid={`section-${s.id}`}>
                  <Space wrap style={{ marginBottom: 4 }}>
                    <Text strong>{s.name}</Text>
                    {(s.status === 'published' || s.status === 'deprecated') && <TierTag tier={s.tier} />}
                    {scope === 'mine' && s.status === 'retired' && <Tag style={{ fontSize: 9 }}>{t('templates.delete.withdrawnTag')}</Tag>}
                    {scope === 'mine' && s.share_scope && s.share_scope !== 'private' && s.status !== 'retired' && (
                      <Tag color="green" style={{ fontSize: 9 }}>{t(`templates.share.${s.share_scope}`)}</Tag>
                    )}
                    {s.license && <Tag style={{ fontSize: 9 }}>{t(`templates.share.lic_${s.license}`)}</Tag>}
                  </Space>
                  <AuthorLine name={s.author_name} />
                  <Text type="secondary" style={{ display: 'block', fontSize: 12, margin: '4px 0' }}>
                    {s.description || t('templates.gallery.noDescription')}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {t('sections.counts', { s: s.sections_summary?.length ?? 0, v: s.variables_summary?.length ?? 0 })}
                  </Text>
                  <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {mode === 'insert' && (
                      <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => onInsert?.(s)} data-testid={`insert-${s.id}`}>
                        {t('sections.insert')}
                      </Button>
                    )}
                    {mode === 'browse' && own && s.status !== 'retired' && (
                      <>
                        <Button size="small" icon={<ShareAltOutlined />} onClick={() => setShareTarget(s)}>{t('templates.share.button')}</Button>
                        <Button size="small" danger icon={<DeleteOutlined />} onClick={() => confirmDelete(s)}>{t('templates.delete.menu')}</Button>
                      </>
                    )}
                    {mode === 'browse' && !own && (
                      <Button size="small" type="text" icon={<FlagOutlined />} onClick={() => setReportTarget(s.id)}>{t('templates.report.button')}</Button>
                    )}
                  </div>
                </Card>
              </List.Item>
            );
          }}
        />
      )}

      <ShareTemplateModal open={Boolean(shareTarget)} template={shareTarget} onClose={() => setShareTarget(null)} onShared={() => void load()} />
      <ReportTemplateModal templateId={reportTarget} open={Boolean(reportTarget)} onClose={() => setReportTarget(null)} />
    </div>
  );
}
