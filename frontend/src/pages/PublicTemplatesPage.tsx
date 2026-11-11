/** PublicTemplatesPage — browse and search published operational plan templates with category filters. */
import React, { useState, useEffect } from 'react';
import { Card, Input, Tag, Typography, Space, Spin, Empty, Row, Col, Button, message, Modal, Descriptions, Collapse, Select, List, Alert, Drawer, Segmented, Dropdown } from 'antd';
import { SearchOutlined, FileTextOutlined, EyeOutlined, TagsOutlined, AppstoreOutlined, CheckCircleOutlined, LoadingOutlined, ExperimentOutlined, ShareAltOutlined, FlagOutlined, MoreOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { operationalPlanApi, forestApi } from '../services/api';
import { useCanDesignTemplates } from '../components/calculation/HazardVarChip';
import { useT } from '../i18n/hooks';
import { usePlanCheck } from '../features/yearly-plan/PlanCheck';
import TemplateStoreReadiness from '../components/TemplateStoreReadiness';
import ShareTemplateModal from '../components/ShareTemplateModal';
import { TierTag, AuthorLine, TemplateLineage, ReportTemplateModal, TierControl } from '../components/TemplateCredit';
import { useAuth } from '../contexts/AuthContext';

const { Text, Title } = Typography;
const { Panel } = Collapse;
const { TextArea } = Input;

interface PublicTemplate {
  id: string;
  name: string;
  description: string;
  tags: string[];
  sections_summary: string[];
  variables_summary: string[];
  created_by?: string | null;
  updated_at: string;
  template_category?: string | null;
  version?: number;
  published_version?: number | null;
  is_active?: boolean;
  status?: string;
  plan_kind?: string | null;
  plan_regime?: string | null;
  plan_stage?: string | null;
  is_kind_default?: boolean;
  share_scope?: string;
  tier?: string;
  license?: string;
  author_name?: string | null;
  source_template_id?: string | null;
}

interface Calculation {
  id: string;
  forest_name?: string;
  status: string;
  created_at: string;
}

const PublicTemplatesPage: React.FC = () => {

  const t = useT();  const [searchParams] = useSearchParams();
  const preselectedCalcId = searchParams.get('calculation_id');
  const [templates, setTemplates] = useState<PublicTemplate[]>([]);
  // 'mine' = the signed-in user's own templates (drafts included), 'published' = everyone's live ones
  const [scope, setScope] = useState<'published' | 'mine'>(searchParams.get('scope') === 'mine' ? 'mine' : 'published');
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [activeTag, setActiveTag] = useState<string | undefined>(undefined);
  const [category, setCategory] = useState<string>('');
  const [allTags, setAllTags] = useState<string[]>([]);
  const [categoriesList, setCategoriesList] = useState<any[]>([]);
  const [kinds, setKinds] = useState<any[]>([]);
  const [kindHint, setKindHint] = useState<string>('');
  const [detailTemplate, setDetailTemplate] = useState<PublicTemplate | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [calcModalOpen, setCalcModalOpen] = useState(false);
  // what the user pressed on the card: take the document as it is, or open it in the builder to edit
  const [intent, setIntent] = useState<'export' | 'customize'>('customize');
  const [selectedTemplate, setSelectedTemplate] = useState<PublicTemplate | null>(null);
  const [calculations, setCalculations] = useState<Calculation[]>([]);
  const [loadingCalcs, setLoadingCalcs] = useState(false);
  const [creating, setCreating] = useState(false);
  const [customNotes, setCustomNotes] = useState('');
  const [regimeFilter, setRegimeFilter] = useState<string>('');
  const [stageFilter, setStageFilter] = useState<string>('');
  const navigate = useNavigate();
  const { user } = useAuth();
  const isSuper = user?.role === 'super_admin';
  const [shareTarget, setShareTarget] = useState<PublicTemplate | null>(null);
  // my copies whose original has published new sections: template id -> titles of the sections that would be added
  const [parentNews, setParentNews] = useState<Record<string, string[]>>({});
  const [reportTarget, setReportTarget] = useState<string | null>(null);
  // before the plan document is created, anything unfinished in the yearly plan is listed once (it never blocks)
  const planCheck = usePlanCheck({ onFix: (calcId) => navigate(`/calculations/${calcId}/yearly-activities`) });
  const canDesign = useCanDesignTemplates();

  // "Preview with my forest" — renders the template against a real forest via
  // the transient endpoint (no plan created). T6.
  const [pvOpen, setPvOpen] = useState(false);
  const [pvTmpl, setPvTmpl] = useState<PublicTemplate | null>(null);
  const [pvCalcId, setPvCalcId] = useState<string | undefined>(undefined);
  const [pvCalcs, setPvCalcs] = useState<Array<{ id: string; forest_name?: string; status: string }>>([]);
  const [pvMode, setPvMode] = useState<'values' | 'tokens'>('values');
  const [pvHtml, setPvHtml] = useState('');
  const [pvLoading, setPvLoading] = useState(false);

  const pvRun = async (calcId: string, mode: 'values' | 'tokens', tmplId?: string) => {
    const id = tmplId ?? pvTmpl?.id;
    if (!id) return;
    setPvLoading(true);
    try {
      setPvHtml(await operationalPlanApi.previewTemplateWithForest(id, calcId, mode));
    } catch {
      message.error(t('templates.gallery.previewFailed'));
    } finally {
      setPvLoading(false);
    }
  };

  const openPreview = async (tmpl: PublicTemplate) => {
    setPvTmpl(tmpl);
    setPvHtml('');
    setPvOpen(true);
    if (preselectedCalcId) {
      setPvCalcId(preselectedCalcId);
      pvRun(preselectedCalcId, pvMode, tmpl.id);
      return;
    }
    setPvCalcId(undefined);
    try {
      const calcs = await forestApi.listCalculations();
      setPvCalcs((calcs || []).filter(
        (c: { status: string }) => c.status === 'completed' || c.status === 'processing',
      ));
    } catch {
      setPvCalcs([]);
    }
  };

  useEffect(() => {
    fetchTemplates();
    operationalPlanApi.listTemplateCategories().then(data => {
      setCategoriesList(data || []);
    }).catch(() => {});
  }, [activeTag, category, scope]);

  useEffect(() => {
    if (!preselectedCalcId) return;
    operationalPlanApi.suggestKind(preselectedCalcId)
      .then(s => { if (s.has_prior_plan) setKindHint(s.reason || ''); })
      .catch(() => {});
  }, [preselectedCalcId]);

  const fetchTemplates = async (searchTerm?: string) => {
    setLoading(true);
    try {
      const term = (searchTerm ?? search ?? '').trim().toLowerCase();
      const res = scope === 'mine'
        ? await operationalPlanApi.listTemplates('mine', activeTag)
        : await operationalPlanApi.listPublicTemplates(activeTag, searchTerm || search || undefined);
      let items = res.templates || [];
      if (scope === 'mine' && term) {
        items = items.filter((x: PublicTemplate) => `${x.name} ${x.description ?? ''}`.toLowerCase().includes(term));
      }
      if (category) {
        items = items.filter((t: any) => t.template_category === category);
      }
      setTemplates(items);
      if (scope === 'mine') {
        const copies = items.filter((x: PublicTemplate) => x.source_template_id && x.created_by === user?.id && x.status !== 'retired');
        const found: Record<string, string[]> = {};
        await Promise.all(copies.map(async (x: PublicTemplate) => {
          try {
            const st = await operationalPlanApi.templateParentStatus(x.id);
            if (st.update_available) found[x.id] = st.added || [];
          } catch { /* the notice is optional; a failed check just shows no tag */ }
        }));
        setParentNews(found);
      } else {
        setParentNews({});
      }
      setKinds(res.kinds || []);
      const tags = new Set<string>();
      items.forEach((t: PublicTemplate) => (t.tags || []).forEach((tag: string) => tags.add(tag)));
      setAllTags(Array.from(tags).sort());
    } catch {
      message.error(t('templates.gallery.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => {
    fetchTemplates(search);
  };

  const handleUseTemplate = async (tmpl: PublicTemplate, wanted: 'export' | 'customize' = 'customize') => {
    setSelectedTemplate(tmpl);
    setIntent(wanted);
    if (preselectedCalcId) {
      handleCreatePlan(preselectedCalcId, tmpl, wanted);
      return;
    }
    setLoadingCalcs(true);
    setCalcModalOpen(true);
    try {
      const calcs = await forestApi.listCalculations();
      const completed = calcs.filter((c: Calculation) => c.status === 'completed' || c.status === 'processing');
      setCalculations(completed);
    } catch {
      message.error(t('templates.gallery.loadForestsFailed'));
      setCalculations([]);
    } finally {
      setLoadingCalcs(false);
    }
  };

  // Two actions, and both are answers, never questions (owner, 2026-10-18). Export always ends in a downloaded
  // document: one that already exists is exported as it is, a missing one is made from the chosen template first.
  // "Open in builder" always ends in the builder with the chosen template's ToC; an existing document is replaced
  // by that click — the user chose the template knowing they have a document, so nothing is asked.
  const handleCreatePlan = async (calcId: string, tmplOverride?: PublicTemplate, wanted?: 'export' | 'customize') => {
    const tmpl = tmplOverride || selectedTemplate;
    const goal = wanted ?? intent;
    if (!tmpl) return;
    if (goal === 'export') {
      try {
        const st = await operationalPlanApi.planReplaceStatus(calcId);
        if (st.exists) {
          setCalcModalOpen(false);
          message.info(t('templates.gallery.exportingExisting'));
          navigate(`/calculations/${calcId}?surface=plan/mgmtplan&export=1`);
          return;
        }
      } catch {
        // the create call below answers the same question, so a failed look-up changes nothing
      }
    }
    planCheck.guard(calcId, () => createPlanNow(calcId, tmpl, goal, goal === 'customize'), 'create');
  };

  // `wanted` is passed along when the choice was made in the same tick (state would still hold the previous one)
  const createPlanNow = async (calcId: string, tmplOverride?: PublicTemplate, wanted?: 'export' | 'customize', replace = false) => {
    const goal = wanted ?? intent;
    const tmpl = tmplOverride || selectedTemplate;
    if (!tmpl) return;
    setCreating(true);
    try {
      const notes = preselectedCalcId ? '' : customNotes;
      await operationalPlanApi.create(
        calcId, undefined, tmpl.id, notes,
        tmpl.plan_regime || undefined, tmpl.plan_stage || undefined, undefined, replace,
      );
      setCalcModalOpen(false);
      setCreating(false);
      message.success(t('templates.gallery.msgPlanCreated'));
      navigate(`/calculations/${calcId}?surface=plan/mgmtplan${goal === 'export' ? '&export=1' : ''}`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail?.code === 'PLAN_EXISTS') {
        setCalcModalOpen(false);
        setCreating(false);
        if (goal === 'export') {
          // Export never replaces: the existing document is the one that gets exported
          message.info(t('templates.gallery.exportingExisting'));
          navigate(`/calculations/${calcId}?surface=plan/mgmtplan&export=1`);
        } else {
          // "Open in builder" may be refused (submitted to an office, no longer a draft): say why and open it as it is
          message.warning(detail.blocked_reason || t('templates.exists.blocked'));
          navigate(`/calculations/${calcId}?surface=plan/mgmtplan`);
        }
        return;
      }
      message.error(
        detail?.code === 'KIND_MISMATCH'
          ? detail.message
          : (typeof detail === 'string' ? detail : t('templates.gallery.createPlanFailed')),
      );
      setCreating(false);
    }
  };

  // Deleting a template that was shared or copied withdraws it instead (the server decides): its name and author stay on the copies.
  const confirmParentUpdates = (tmpl: PublicTemplate) => {
    const added = parentNews[tmpl.id] || [];
    Modal.confirm({
      title: t('templates.parent.confirmTitle', { name: tmpl.name }),
      content: (
        <div>
          <div>{t('templates.parent.confirmBody')}</div>
          <ul style={{ marginTop: 8 }}>{added.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      ),
      okText: t('templates.parent.ok'),
      cancelText: t('templates.gallery.close'),
      onOk: async () => {
        try {
          const res = await operationalPlanApi.addParentUpdates(tmpl.id);
          message.success(t('templates.parent.done', { n: res.added.length }));
          fetchTemplates();
        } catch {
          message.error(t('templates.parent.failed'));
        }
      },
    });
  };

  const confirmDelete = (tmpl: PublicTemplate) => {
    Modal.confirm({
      title: t('templates.delete.confirmTitle', { name: tmpl.name }),
      content: t('templates.delete.confirmBody'),
      okText: t('templates.delete.ok'),
      okButtonProps: { danger: true },
      cancelText: t('templates.gallery.close'),
      onOk: async () => {
        try {
          const res = await operationalPlanApi.deleteTemplate(tmpl.id);
          message.success(t(res?.status === 'withdrawn' ? 'templates.delete.withdrawn' : 'templates.delete.deleted'));
          fetchTemplates();
        } catch {
          message.error(t('templates.delete.failed'));
        }
      },
    });
  };

  // Super admin only: delete for good. The copies keep working but their credit chain then starts at the copy.
  const confirmDeletePermanently = (tmpl: PublicTemplate) => {
    Modal.confirm({
      title: t('templates.delete.permanentTitle', { name: tmpl.name }),
      content: t('templates.delete.permanentBody'),
      okText: t('templates.delete.permanentOk'),
      okButtonProps: { danger: true },
      cancelText: t('templates.gallery.close'),
      onOk: async () => {
        try {
          await operationalPlanApi.deleteTemplate(tmpl.id, { permanent: true });
          message.success(t('templates.delete.permanentDone'));
          setDetailOpen(false);
          fetchTemplates();
        } catch {
          message.error(t('templates.delete.failed'));
        }
      },
    });
  };

  const handleShowDetail = (tmpl: PublicTemplate) => {
    setDetailTemplate(tmpl);
    setDetailOpen(true);
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {planCheck.dialog}
      <ShareTemplateModal open={Boolean(shareTarget)} template={shareTarget} onClose={() => setShareTarget(null)} onShared={() => fetchTemplates()} />
      <ReportTemplateModal templateId={reportTarget} open={Boolean(reportTarget)} onClose={() => setReportTarget(null)} />
      <Title level={3}><FileTextOutlined /> {t('templates.gallery.title')}</Title>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        {t('templates.admin.galleryIntro')}
      </Text>

      {preselectedCalcId && <TemplateStoreReadiness calculationId={preselectedCalcId} />}

      {kindHint && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message={t('templates.gallery.revisionHint', { reason: kindHint })} />
      )}

      <Space style={{ marginBottom: 16, width: '100%' }} direction="vertical">
        <Segmented
          value={scope}
          onChange={(v) => setScope(v as 'published' | 'mine')}
          options={[
            { value: 'published', label: t('templates.gallery.scopePublished') },
            { value: 'mine', label: t('templates.gallery.scopeMine') },
          ]}
        />
        <Space wrap>
          <Input
            placeholder={t('templates.gallery.searchPlaceholder')}
            prefix={<SearchOutlined />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 250 }}
            allowClear
          />
          <Button type="primary" onClick={handleSearch} icon={<SearchOutlined />}>{t('templates.gallery.search')}</Button>
          <Select
            value={category}
            onChange={(val) => setCategory(val)}
            style={{ width: 200 }}
            placeholder={t('templates.gallery.allRegimes')}
          >
            <Select.Option value="">{t('templates.gallery.allRegimes')}</Select.Option>
            {categoriesList.map(c => (
              <Select.Option key={c.key} value={c.key}>{c.label_en}</Select.Option>
            ))}
          </Select>
          <Select
            value={regimeFilter}
            onChange={setRegimeFilter}
            style={{ width: 200 }}
            options={[
              { value: '', label: t('templates.gallery.allCategories') },
              ...['sustainable_fmp', 'brief_fmp', 'scientific_fmp'].map((r) => ({
                value: r, label: t(`templates.regime.${r}`, { defaultValue: r }),
              })),
            ]}
          />
          <Select
            value={stageFilter}
            onChange={setStageFilter}
            style={{ width: 150 }}
            options={[
              { value: '', label: t('templates.gallery.planType') },
              ...['new', 'revision'].map((s) => ({
                value: s, label: t(`templates.stage.${s}`, { defaultValue: s }),
              })),
            ]}
          />
        </Space>

        {allTags.length > 0 && (
          <Space wrap>
            <TagsOutlined />
            <Tag
              color={!activeTag ? 'blue' : 'default'}
              style={{ cursor: 'pointer' }}
              onClick={() => setActiveTag(undefined)}
            >
              {t('templates.gallery.all')}
            </Tag>
            {allTags.map(tag => (
              <Tag
                key={tag}
                color={activeTag === tag ? 'blue' : 'default'}
                style={{ cursor: 'pointer' }}
                onClick={() => setActiveTag(tag)}
              >
                {tag}
              </Tag>
            ))}
          </Space>
        )}
      </Space>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : (() => {
        const shown = templates.filter((x) =>
          (!regimeFilter || x.plan_regime === regimeFilter) &&
          (!stageFilter || x.plan_stage === stageFilter));
        if (shown.length === 0) return <Empty description={t('templates.gallery.empty')} />;
        return (
          (() => {
          const renderCard = (tmpl: PublicTemplate) => (
            <Col key={tmpl.id} xs={24} sm={12} md={8} lg={6}>
              <Card hoverable>
                <Card.Meta
                  title={
                    <Space wrap>
                      <Text strong ellipsis style={{ maxWidth: 150 }}>{tmpl.name}</Text>
                      {tmpl.published_version != null && (
                        <Tag color="green" style={{ fontSize: 9 }}>v{tmpl.published_version}</Tag>
                      )}
                      {scope === 'mine' && tmpl.status && tmpl.status !== 'published' && (
                        <Tag style={{ fontSize: 9 }}>
                          {tmpl.status === 'retired' ? t('templates.delete.withdrawnTag') : t(`templates.status.${tmpl.status}`, { defaultValue: tmpl.status })}
                        </Tag>
                      )}
                      {tmpl.status && (tmpl.status === 'published' || tmpl.status === 'deprecated') && <TierTag tier={tmpl.tier} />}
                      {scope === 'mine' && tmpl.share_scope && tmpl.share_scope !== 'private' && (
                        <Tag color="green" style={{ fontSize: 9 }}>{t(`templates.share.${tmpl.share_scope}`)}</Tag>
                      )}
                      {parentNews[tmpl.id] && (
                        <Tag color="orange" style={{ fontSize: 9 }}>{t('templates.parent.tag')}</Tag>
                      )}
                      {tmpl.is_kind_default && (
                        <Tag color="blue" style={{ fontSize: 9 }}>{t('templates.gallery.recommended')}</Tag>
                      )}
                    </Space>
                  }
                  description={
                    <div>
                      <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                        {tmpl.description || t('templates.gallery.noDescription')}
                      </Text>
                      <AuthorLine name={tmpl.author_name} />
                      {tmpl.template_category && (
                        <Tag color={categoriesList.find(c => c.key === tmpl.template_category)?.color || 'purple'} style={{ fontSize: 10, marginTop: 4 }}>
                          {categoriesList.find(c => c.key === tmpl.template_category)?.label_en || tmpl.template_category}
                        </Tag>
                      )}
                      {tmpl.tags?.length > 0 && (
                        <div style={{ marginTop: 4 }}>
                          {tmpl.tags.slice(0, 3).map(t => <Tag key={t} style={{ fontSize: 10, marginBottom: 2 }}>{t}</Tag>)}
                        </div>
                      )}
                      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
                        {t('templates.gallery.sectionsVariables', {
                          s: tmpl.sections_summary?.length || 0,
                          v: tmpl.variables_summary?.length || 0,
                        })}
                      </Text>
                    </div>
                  }
                />
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
                  <Button type="primary" size="small" onClick={() => handleUseTemplate(tmpl, 'export')}>
                    {t('templates.gallery.exportNow')}
                  </Button>
                  <Button size="small" onClick={() => handleUseTemplate(tmpl, 'customize')}>
                    {t('templates.gallery.customize')}
                  </Button>
                  <Dropdown
                    trigger={['click']}
                    menu={{
                      items: [
                        { key: 'detail', icon: <EyeOutlined />, label: t('templates.gallery.details') },
                        { key: 'pv', icon: <ExperimentOutlined />, label: t('templates.gallery.previewWithForest') },
                        ...(scope === 'mine' && tmpl.created_by === user?.id && tmpl.status !== 'retired'
                          ? [
                              ...(parentNews[tmpl.id] ? [{ key: 'parent', icon: <ReloadOutlined />, label: t('templates.parent.menu'), 'data-testid': `parent-${tmpl.id}` }] : []),
                              { key: 'share', icon: <ShareAltOutlined />, label: t('templates.share.button'), 'data-testid': `share-${tmpl.id}` },
                              { key: 'delete', icon: <DeleteOutlined />, danger: true, label: t('templates.delete.menu') },
                            ]
                          : []),
                      ],
                      onClick: ({ key }) => {
                        if (key === 'detail') handleShowDetail(tmpl);
                        else if (key === 'pv') openPreview(tmpl);
                        else if (key === 'share') setShareTarget(tmpl);
                        else if (key === 'parent') confirmParentUpdates(tmpl);
                        else if (key === 'delete') confirmDelete(tmpl);
                      },
                    }}
                  >
                    <Button type="text" size="small" icon={<MoreOutlined />} data-testid={`more-${tmpl.id}`} aria-label={t('templates.gallery.more')} />
                  </Dropdown>
                </div>
              </Card>
            </Col>
          );

          // Group by regime -> stage (visual headers only; user may pick across groups).
          const REGIMES = ['sustainable_fmp', 'brief_fmp', 'scientific_fmp'];
          const STAGES = ['new', 'revision'];
          const groups: Array<{ key: string; label: string; items: PublicTemplate[] }> = [];
          for (const rk of REGIMES) {
            for (const sk of STAGES) {
              const items = shown.filter(x => x.plan_regime === rk && x.plan_stage === sk);
              if (items.length) {
                const kd = kinds.find(k => k.plan_regime === rk && k.plan_stage === sk);
                groups.push({
                  key: `${rk}_${sk}`,
                  label: kd?.label_en || `${t(`templates.regime.${rk}`, { defaultValue: rk })} — ${t(`templates.stage.${sk}`, { defaultValue: sk })}`,
                  items,
                });
              }
            }
          }
          const ungrouped = shown.filter(x => !x.plan_regime || !x.plan_stage);
          if (ungrouped.length) {
            groups.push({ key: 'other', label: t('templates.gallery.uncategorised'), items: ungrouped });
          }

          return (
            <div>
              {groups.map(g => (
                <div key={g.key} style={{ marginBottom: 24 }}>
                  <Title level={5} style={{ marginBottom: 12 }}>{g.label}</Title>
                  <Row gutter={[16, 16]}>{g.items.map(renderCard)}</Row>
                </div>
              ))}
            </div>
          );
        })()
        );
      })()}

      <Modal
        title={t('templates.gallery.detail')}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={[
          <Button key="close" onClick={() => setDetailOpen(false)}>{t('templates.gallery.close')}</Button>,
          detailTemplate && isSuper && !(detailTemplate as any).is_system && (
            <Button key="permanent" danger icon={<DeleteOutlined />} onClick={() => confirmDeletePermanently(detailTemplate)} data-testid="delete-permanently">
              {t('templates.delete.permanentOk')}
            </Button>
          ),
          detailTemplate && detailTemplate.created_by !== user?.id && detailTemplate.status !== undefined && (
            <Button key="report" danger type="link" icon={<FlagOutlined />} onClick={() => { setDetailOpen(false); setReportTarget(detailTemplate.id); }} data-testid="report-open">
              {t('templates.report.button')}
            </Button>
          ),
          detailTemplate && (
            <Button key="pv" icon={<ExperimentOutlined />} onClick={() => { setDetailOpen(false); openPreview(detailTemplate); }}>
              {t('templates.gallery.previewWithForest')}
            </Button>
          ),
          detailTemplate && (
            <Space key="use">
              <Button onClick={() => { setDetailOpen(false); handleUseTemplate(detailTemplate, 'customize'); }}>
                {t('templates.gallery.customize')}
              </Button>
              <Button type="primary" onClick={() => { setDetailOpen(false); handleUseTemplate(detailTemplate, 'export'); }}>
                {t('templates.gallery.exportNow')}
              </Button>
            </Space>
          ),
        ]}
        width={640}
      >
        {detailTemplate && (
          <div>
            <Title level={4}>{detailTemplate.name}</Title>
            <Space style={{ marginBottom: 8 }}>
              {detailTemplate.is_active && <Tag color="green">Published v{detailTemplate.version || 1}</Tag>}
              {!detailTemplate.is_active && <Tag>{t('templates.gallery.draft')}</Tag>}
            </Space>
            <Space style={{ marginBottom: 8 }} wrap>
              <TierTag tier={detailTemplate.tier} />
              {detailTemplate.license && <Tag>{t(`templates.share.lic_${detailTemplate.license}`)}</Tag>}
              <AuthorLine name={detailTemplate.author_name} />
            </Space>
            {isSuper && (
              <TierControl templateId={detailTemplate.id} tier={detailTemplate.tier}
                onChanged={() => { setDetailOpen(false); fetchTemplates(); }} />
            )}
            <Text style={{ display: 'block', marginBottom: 12 }}>{detailTemplate.description || t('templates.gallery.noDescription')}</Text>
            <TemplateLineage templateId={detailTemplate.id} />
            <Space wrap style={{ marginBottom: 12 }}>
              {detailTemplate.template_category && (
                <Tag color={categoriesList.find(c => c.key === detailTemplate.template_category)?.color || 'purple'}>{categoriesList.find(c => c.key === detailTemplate.template_category)?.label_en || detailTemplate.template_category}</Tag>              )}
              {detailTemplate.tags?.map(t => <Tag key={t}>{t}</Tag>)}
            </Space>
            <Collapse ghost>
              <Panel header={`Sections (${detailTemplate.sections_summary?.length || 0})`} key="sections">
                {detailTemplate.sections_summary?.length > 0 ? (
                  <ol style={{ fontSize: 13, maxHeight: 250, overflow: 'auto' }}>
                    {detailTemplate.sections_summary.map((s, i) => <li key={i}>{s}</li>)}
                  </ol>
                ) : <Text type="secondary">{t('templates.gallery.noSections')}</Text>}
              </Panel>
              <Panel header={`Variables used (${detailTemplate.variables_summary?.length || 0})`} key="vars">
                {detailTemplate.variables_summary?.length > 0 ? (
                  <ul style={{ fontSize: 13, maxHeight: 250, overflow: 'auto' }}>
                    {detailTemplate.variables_summary.map((v, i) => <li key={i}>{v}</li>)}
                  </ul>
                ) : <Text type="secondary">{t('templates.gallery.noVariables')}</Text>}
              </Panel>
            </Collapse>
          </div>
        )}
      </Modal>

      <Modal
        title={t('templates.gallery.selectForest')}
        open={calcModalOpen}
        onCancel={() => { if (!creating) setCalcModalOpen(false); }}
        footer={null}
        width={520}
      >
        {loadingCalcs ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : calculations.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 20 }}>
            <Empty description={t('templates.gallery.noForests')} />
            <Button type="primary" onClick={() => navigate('/my-uploads')} style={{ marginTop: 12 }}>
              {t('templates.gallery.goToUploads')}
            </Button>
          </div>
        ) : (
          <>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              {t('templates.gallery.chooseForest', { name: selectedTemplate?.name ?? '' })}
            </Text>
            <Alert type="info" showIcon style={{ marginBottom: 12 }} data-testid="intent-note"
              message={t(intent === 'export' ? 'templates.gallery.intentExport' : 'templates.gallery.intentCustomize')} />
            <div style={{ marginBottom: 12 }}>
              <TextArea
                placeholder={t('templates.gallery.phNotes')}
                rows={2}
                value={customNotes}
                onChange={(e) => setCustomNotes(e.target.value)}
                style={{ fontSize: 12 }}
              />
            </div>
            <List
              dataSource={calculations}
              loading={creating}
              renderItem={(calc) => (
                <List.Item
                  actions={[
                    <Button
                      key="select"
                      type="primary"
                      size="small"
                      onClick={() => handleCreatePlan(calc.id)}
                      loading={creating}
                      icon={<CheckCircleOutlined />}
                    >
                      {t('templates.gallery.select')}
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={calc.forest_name || t('templates.gallery.unnamedForest')}
                    description={
                      <span>
                        Status: <Tag color={calc.status === 'completed' ? 'green' : 'orange'}>{calc.status}</Tag>
                        &nbsp; Created: {new Date(calc.created_at).toLocaleDateString()}
                      </span>
                    }
                  />
                </List.Item>
              )}
            />
          </>
        )}
      </Modal>

      <Drawer
        title={t('templates.gallery.previewTitle', { name: pvTmpl?.name ?? '' })}
        placement="right"
        size="large"
        open={pvOpen}
        onClose={() => setPvOpen(false)}
        extra={canDesign && (
          <Segmented
            size="small"
            value={pvMode}
            onChange={(v) => {
              const m = v as 'values' | 'tokens';
              setPvMode(m);
              if (pvCalcId) pvRun(pvCalcId, m);
            }}
            options={[
              { label: t('operationalPlan.render.values'), value: 'values' },
              { label: t('operationalPlan.render.tokens'), value: 'tokens' },
            ]}
          />
        )}
      >
        {!preselectedCalcId && (
          <Select
            style={{ width: '100%', marginBottom: 12 }}
            placeholder={t('templates.gallery.pickForest')}
            value={pvCalcId}
            onChange={(v) => { setPvCalcId(v); pvRun(v, pvMode); }}
            options={pvCalcs.map((c) => ({ value: c.id, label: c.forest_name || c.id }))}
          />
        )}
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message={t('templates.gallery.previewNote')}
        />
        {pvLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : pvHtml ? (
          <iframe
            srcDoc={pvHtml}
            title={t('templates.gallery.previewWithForest')}
            style={{ width: '100%', height: '70vh', border: '1px solid #f0f0f0' }}
          />
        ) : (
          <Empty description={t('templates.gallery.pickForest')} />
        )}
      </Drawer>
    </div>
  );
};

export default PublicTemplatesPage;