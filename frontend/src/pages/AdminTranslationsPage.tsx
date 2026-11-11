/** AdminTranslationsPage — super-admin DB-backed translation editor (Phase 3).

Searchable/filterable table over the `translations` table; inline NE/EN
editing, per-row Save (PUT -> overlay refresh), and a Reviewed toggle.
Saved changes become overrides visible to every user on their next page load.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Table, Input, Space, Button, Tag, Typography, Spin, Empty, Alert, Select, message, InputNumber } from 'antd';
import { SaveOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../i18n/hooks';
import { refreshTranslations } from '../i18n/index';
import { translationAdminApi, type AdminTranslationRow } from '../services/api';

import { readDetail } from '../hooks/useErrorHandler';
const { Text } = Typography;
const { TextArea } = Input;

interface FilterState {
  search: string;
  filter: 'all' | 'untranslated_ne' | 'overrides' | 'unreviewed';
  category?: string;
}

export const AdminTranslationsPage: React.FC = () => {
  const t = useT();
  const [rows, setRows] = useState<AdminTranslationRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, { en: string; ne: string }>>({});
  const [filters, setFilters] = useState<FilterState>({ search: '', filter: 'all' });
  const [category, setCategory] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [categories, setCategories] = useState<string[]>([]);

  const fetchRows = useCallback(async (f: FilterState, pg: number, pp: number, cat?: string) => {
    setLoading(true);
    try {
      const params: Record<string, string | number | boolean> = {};
      if (f.search) params.search = f.search;
      if (f.filter === 'untranslated_ne') params.lang_is_empty = 'ne';
      if (f.filter === 'overrides') params.override_only = true;
      if (f.filter === 'unreviewed') params.reviewed = false;
      if (cat) params.category = cat;
      params.page = pg;
      params.per_page = pp;
      const data = await translationAdminApi.list(params);
      setRows(data.items);
      setTotal(data.total);
    } catch (err) {
      message.error(t('adminTranslations.saveFailed'));
      console.error('[admin-translations] list failed', err);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchRows(filters, page, perPage, category);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, perPage]);

  useEffect(() => {
    (async () => {
      try {
        const data = await translationAdminApi.list({ per_page: 1, page: 1 });
        setCategories(Array.from(new Set(data.items.map((r) => r.key.split('.')[0]))).sort());
      } catch {
        // categories dropdown is non-critical
      }
    })();
  }, []);

  const searchSubmit = () => {
    setPage(1);
    fetchRows(filters, 1, perPage, category);
  };

  const handleSave = async (row: AdminTranslationRow) => {
    const draft = drafts[row.key];
    if (!draft) return;
    setSavingKey(row.key);
    try {
      await translationAdminApi.upsert(row.key, {
        en: draft.en.trim() || null,
        ne: draft.ne.trim() || null,
      });
      message.success(t('adminTranslations.saved'));
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[row.key];
        return next;
      });
      await refreshTranslations();
      fetchRows(filters, page, perPage, category);
    } catch (err) {
      // A refused edit (for example one that drops a {{placeholder}}) carries its own reason, in the
      // reviewer's language; show it instead of a bare "save failed".
      const reason = readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail);
      message.error(reason ?? t('adminTranslations.saveFailed'));
      console.error('[admin-translations] upsert failed', err);
    } finally {
      setSavingKey(null);
    }
  };

  const handleReviewedToggle = async (row: AdminTranslationRow, reviewed: boolean) => {
    try {
      await translationAdminApi.upsert(row.key, { note: reviewed ? 'Marked reviewed' : 'Flagged for review' });
      setRows((prev) => prev.map((r) => (r.key === row.key ? { ...r, reviewed } : r)));
      await refreshTranslations();
    } catch (err) {
      message.error(t('adminTranslations.saveFailed'));
      console.error('[admin-translations] review toggle failed', err);
    }
  };

  const setDraft = (row: AdminTranslationRow, field: 'en' | 'ne', value: string) => {
    setDrafts((prev) => ({
      ...prev,
      [row.key]: {
        en: field === 'en' ? value : (prev[row.key]?.en ?? row.en ?? ''),
        ne: field === 'ne' ? value : (prev[row.key]?.ne ?? row.ne ?? ''),
      },
    }));
  };

  const columns: ColumnsType<AdminTranslationRow> = useMemo(() => [
    {
      title: t('adminTranslations.key'),
      dataIndex: 'key',
      key: 'key',
      width: 280,
      fixed: 'left',
      render: (value: string, row) => (
        <div>
          <Text strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{value}</Text>
          <div>
            {row.is_override && <Tag color="gold" style={{ fontSize: 10 }}>{t('adminTranslations.overrides')}</Tag>}
            {row.reviewed && <Tag color="green" style={{ fontSize: 10 }}>{t('adminTranslations.reviewed')}</Tag>}
          </div>
          {row.context && (
            <div data-testid="translation-context" title={t('adminTranslations.context')}>
              <Text type="secondary" style={{ fontSize: 11 }}>{row.context}</Text>
            </div>
          )}
        </div>
      ),
    },
    {
      title: t('adminTranslations.en'),
      dataIndex: 'en',
      key: 'en',
      width: 300,
      render: (_: string, row) => (
        <TextArea
          rows={2}
          value={drafts[row.key]?.en ?? row.en ?? ''}
          onChange={(e) => setDraft(row, 'en', e.target.value)}
          placeholder={t('adminTranslations.en')}
        />
      ),
    },
    {
      title: t('adminTranslations.ne'),
      dataIndex: 'ne',
      key: 'ne',
      width: 300,
      render: (_: string, row) => (
        <TextArea
          rows={2}
          value={drafts[row.key]?.ne ?? row.ne ?? ''}
          onChange={(e) => setDraft(row, 'ne', e.target.value)}
          placeholder={t('adminTranslations.ne')}
        />
      ),
    },
    {
      title: t('adminTranslations.updatedBy'),
      dataIndex: 'updated_by',
      key: 'updated_by',
      width: 110,
      render: (v?: string | null) => (v ? <Text type="secondary" style={{ fontSize: 11 }}>{v.slice(0, 8)}</Text> : <Text type="secondary" style={{ fontSize: 11 }}>—</Text>),
    },
    {
      title: t('adminTranslations.actions'),
      key: 'actions',
      width: 200,
      render: (_: unknown, row) => {
        const isDirty = Boolean(drafts[row.key]);
        return (
          <Space>
            <Button
              type="primary"
              size="small"
              icon={<SaveOutlined />}
              disabled={!isDirty}
              loading={savingKey === row.key}
              onClick={() => handleSave(row)}
            >
              {t('adminTranslations.save')}
            </Button>
            <Button
              size="small"
              type={row.reviewed ? 'default' : 'primary'}
              ghost={!row.reviewed}
              onClick={() => handleReviewedToggle(row, !row.reviewed)}
            >
              {row.reviewed ? t('adminTranslations.reviewed') : t('adminTranslations.unreviewed')}
            </Button>
          </Space>
        );
      },
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [drafts, savingKey, t]);

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Alert
          message={t('adminTranslations.superAdminOnly')}
          description={t('adminTranslations.superAdminOnlyDesc')}
          type="info"
          showIcon
        />
        <Space wrap>
          <Input
            prefix={<SearchOutlined />}
            placeholder={t('adminTranslations.search')}
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            onPressEnter={searchSubmit}
            style={{ width: 320 }}
            allowClear
          />
          <Select
            value={filters.filter}
            style={{ width: 200 }}
            onChange={(value) => { setFilters({ ...filters, filter: value }); setPage(1); fetchRows({ ...filters, filter: value }, 1, perPage, category); }}
            options={[
              { value: 'all', label: t('adminTranslations.all') },
              { value: 'untranslated_ne', label: t('adminTranslations.untranslatedNe') },
              { value: 'overrides', label: t('adminTranslations.overrideOnly') },
              { value: 'unreviewed', label: t('adminTranslations.unreviewed') },
            ]}
          />
          {categories.length > 0 && (
            <Select
              allowClear
              placeholder={t('adminTranslations.category')}
              style={{ width: 200 }}
              value={category}
              onChange={(value) => { setCategory(value); setPage(1); fetchRows(filters, 1, perPage, value); }}
              options={categories.map((c) => ({ value: c, label: c }))}
            />
          )}
          <Button icon={<ReloadOutlined />} onClick={() => fetchRows(filters, page, perPage, category)}>
            {t('adminTranslations.refresh')}
          </Button>
        </Space>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
        ) : rows.length === 0 ? (
          <Empty description={t('adminTranslations.empty')} />
        ) : (
          <Table<AdminTranslationRow>
            rowKey="key"
            columns={columns}
            dataSource={rows}
            scroll={{ x: 1350 }}
            pagination={{
              current: page,
              pageSize: perPage,
              total,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100, 200],
              onChange: (pg, ps) => { setPage(pg); setPerPage(ps); },
            }}
          />
        )}
      </Space>
    </div>
  );
};

export default AdminTranslationsPage;