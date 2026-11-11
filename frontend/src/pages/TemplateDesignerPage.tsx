/** TemplateDesignerPage — template designer with section editing, versioning, and save/publish workflow. */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button, message, Spin, Tag, Input, Modal, Typography, Space, List, Tooltip, Descriptions, Divider, Popconfirm, Select } from 'antd';
import {
  SaveOutlined,
  CheckCircleOutlined,
  StopOutlined,
  CopyOutlined,
  EyeOutlined,
  ArrowLeftOutlined,
  HistoryOutlined,
  RollbackOutlined,
  CameraOutlined,
} from '@ant-design/icons';
import html2canvas from 'html2canvas';
import { operationalPlanApi, forestApi } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import TreeSidebar from '../components/OperationalPlan/TreeSidebar';
import ContentPane from '../components/OperationalPlan/ContentPane';
import VariablePicker from '../components/OperationalPlan/VariablePicker';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';

const CHART_TYPES = ['forest_type_pie', 'species_pie', 'block_area_bar', 'slope_pie', 'canopy_pie', 'landcover_pie', 'biomass_bar', 'dbh_histogram'];
const MAP_TYPES = ['boundary', 'forest_type', 'forest_health', 'slope', 'biomass', 'landcover', 'landcover_1984', 'soil_texture', 'dem', 'aspect', 'canopy'];
const PLAN_REGIMES = ['sustainable_fmp', 'brief_fmp', 'scientific_fmp'];
const PLAN_STAGES = ['new', 'revision'];

const { Text } = Typography;
const { TextArea } = Input;

interface TreeNodeData {
  id: string;
  type: string;
  title_ne: string;
  title_en: string;
  number?: string | null;
  level: number;
  content_type: string;
  content: string;
  chart_type?: string | null;
  table_id?: string | null;
  map_type?: string | null;
  static_table?: { columns: string[]; rows: string[][]; merges?: { row: number; col: number; rowspan: number; colspan: number }[] } | null;
  children: TreeNodeData[];
  is_locked: boolean;
  hidden_in_export: boolean;
  deleted: boolean;
  last_modified?: string | null;
}

const TemplateDesignerPage: React.FC = () => {

  const t = useT();  const { templateId } = useParams<{ templateId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isSuperAdmin = user?.role === 'super_admin';
  const isNew = templateId === 'new';

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [template, setTemplate] = useState<any>(null);
  const [tree, setTree] = useState<TreeNodeData[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [showVariablePicker, setShowVariablePicker] = useState(false);
  const [changelogModal, setChangelogModal] = useState(false);
  const [changelog, setChangelog] = useState('');
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<any[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [rollbacking, setRollbacking] = useState(false);
  const [categories, setCategories] = useState<any[]>([]);
  const [capturing, setCapturing] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<{ ok: boolean; errors: any[]; warnings: any[] } | null>(null);
  // Preview needs a forest to resolve against (there is no bound plan here).
  const [previewForests, setPreviewForests] = useState<Array<{ id: string; forest_name?: string; status: string }>>([]);
  const [previewCalcId, setPreviewCalcId] = useState<string | undefined>(undefined);

  useEffect(() => {
    forestApi.listCalculations()
      .then((cs) => setPreviewForests((cs || []).filter(
        (c: { status: string }) => c.status === 'completed' || c.status === 'processing',
      )))
      .catch(() => setPreviewForests([]));
  }, []);

  useEffect(() => {
    if (!isNew && templateId) {
      loadTemplate(templateId);
    } else {
      setTree([]);
      setLoading(false);
    }
  }, [templateId]);

  const loadTemplate = async (id: string) => {
    setLoading(true);
    try {
      const [tmpl, cats] = await Promise.all([
        operationalPlanApi.getTemplate(id),
        operationalPlanApi.listTemplateCategories().catch(() => []),
      ]);
      setTemplate(tmpl);
      setTree(tmpl.tree || []);
      setCategories(cats || []);
      if ((tmpl.tree || []).length > 0) {
        setActiveNodeId(tmpl.tree[0].id);
      }
    } catch {
      message.error(t('templates.designer.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  // A new template is created as "Untitled"; this is how it gets its real name (the backend always accepted a new name, the screen did
  // not offer one). An empty name is refused and the old one stays.
  const handleRename = async (value: string) => {
    if (!template) return;
    const name = value.trim();
    if (!name) {
      message.warning(t('templates.designer.renameEmpty'));
      return;
    }
    if (name === template.name) return;
    try {
      const updated = await operationalPlanApi.updateTemplate(template.id, { name });
      setTemplate(updated);
      message.success(t('templates.designer.msgRenamed'));
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.renameFailed'));
    }
  };

  const handleCategoryChange = async (categoryKey: string | undefined) => {
    if (!template) return;
    try {
      const updated = await operationalPlanApi.updateTemplate(template.id, { template_category: categoryKey || null });
      setTemplate(updated);
      message.success(t('templates.designer.msgCategoryUpdated'));
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.categoryUpdateFailed'));
    }
  };

  const handleSave = async () => {
    let id = templateId;
    setSaving(true);
    try {
      if (isNew) {
        const created = await operationalPlanApi.createTemplate({
          name: t('templates.designer.untitled'),
          description: '',
          tree,
          visibility: 'private',
        });
        id = created.id;
        setTemplate(created);
        navigate(`/templates/designer/${created.id}`, { replace: true });
        message.success(t('templates.designer.msgCreated'));
      } else {
        const payload: any = { tree };
        if (template?.status === 'published') {
          payload.changelog = changelog || `Updated ${new Date().toLocaleDateString()}`;
        }
        const updated = await operationalPlanApi.updateTemplate(id!, payload);
        setTemplate(updated);
        setChangelog('');
        setChangelogModal(false);
        message.success(t('templates.designer.msgSaved'));
      }
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveWithVersion = async () => {
    if (template?.status === 'published') {
      setChangelogModal(true);
    } else {
      await handleSave();
    }
  };

  const handlePublish = async () => {
    if (!template) return;
    setSaving(true);
    try {
      const updated = await operationalPlanApi.publishTemplate(template.id, template.status !== 'published');
      setTemplate(updated);
      message.success(updated.status === 'published' ? t('templates.designer.msgPublished') : t('templates.designer.msgUnpublished'));
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.publishFailed'));
    } finally {
      setSaving(false);
    }
  };

  // Per-kind defaults now live in op_plan_kinds.default_template_id (managed by
  // the super admin), not a per-template flag.

  const handleClone = async () => {
    if (!template) return;
    setSaving(true);
    try {
      const cloned = await operationalPlanApi.cloneTemplate(template.id);
      navigate(`/templates/designer/${cloned.id}`);
      message.success(t('templates.designer.msgCloned'));
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.cloneFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    if (!template) return;
    setValidating(true);
    try {
      const res = await operationalPlanApi.validateTemplate(template.id);
      setValidation(res);
      if (res.ok && res.warnings.length === 0) message.success(t('templates.designer.validationOk'));
    } catch {
      message.error(t('templates.designer.validateFailed'));
    } finally {
      setValidating(false);
    }
  };

  const handleKindChange = async (field: 'plan_regime' | 'plan_stage', value: string | undefined) => {
    if (!template) return;
    try {
      const updated = await operationalPlanApi.updateTemplate(template.id, { [field]: value || null });
      setTemplate(updated);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.kindUpdateFailed'));
    }
  };

  const handleOpenVersionHistory = async () => {
    if (!template) return;
    setVersionsLoading(true);
    setVersionHistoryOpen(true);
    try {
      const data = await operationalPlanApi.getTemplateVersions(template.id);
      setVersions(data || []);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.historyFailed'));
    } finally {
      setVersionsLoading(false);
    }
  };

  const handleRollback = async (version: number) => {
    if (!template) return;
    setRollbacking(true);
    try {
      const updated = await operationalPlanApi.rollbackTemplate(template.id, version);
      setTemplate(updated);
      setTree(updated.tree || []);
      message.success(`Rolled back to version ${version}`);
      setVersionHistoryOpen(false);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.designer.rollbackFailed'));
    } finally {
      setRollbacking(false);
    }
  };

  const handleCapturePreview = async () => {
    if (!template) return;
    setCapturing(true);
    try {
      const el = document.querySelector('.template-designer-content');
      if (!el) { message.warning(t('templates.designer.msgNoContentArea')); return; }
      const canvas = await html2canvas(el as HTMLElement, { background: '#ffffff', scale: 0.5 } as any);
      const dataUrl = canvas.toDataURL('image/png');
      await operationalPlanApi.updateTemplate(template.id, { preview_image_url: dataUrl });
      setTemplate((prev: any) => ({ ...prev, preview_image_url: dataUrl }));
      message.success(t('templates.designer.msgPreviewCaptured'));
    } catch {
      message.error(t('templates.designer.capturePreviewFailed'));
    } finally {
      setCapturing(false);
    }
  };

  const handleAddChild = async (
    _parentId: string | null, contentType?: string, chartType?: string, mapType?: string,
  ) => {
    const ct = contentType || 'richtext';
    const labelKey = ct === 'static_table' ? 'templates.designer.addTableTitlePrompt'
      : ct === 'chart' ? 'templates.designer.addChartTitlePrompt'
      : ct === 'map' ? 'templates.designer.addMapTitlePrompt'
      : 'templates.designer.addSectionTitlePrompt';
    const val = window.prompt(t(labelKey));
    if (!val) return;
    const newNode: any = {
      id: `node_${Date.now()}`,
      type: _parentId ? 'subsection' : 'section',
      title_ne: val,
      title_en: '',
      content: '',
      content_type: ct === 'static_table' ? 'static_table' : ct,
      chart_type: ct === 'chart' ? (chartType || CHART_TYPES[0]) : null,
      map_type: ct === 'map' ? (mapType || MAP_TYPES[0]) : null,
      level: 0,
      children: [],
      is_locked: false,
      hidden_in_export: false,
      deleted: false,
    };
    if (ct === 'static_table') {
      newNode.static_table = {
        columns: ['Column 1', 'Column 2', 'Column 3'],
        rows: [['', '', ''], ['', '', ''], ['', '', '']],
      };
    }
    setTree(prev => {
      const addNode = (nodes: TreeNodeData[]): TreeNodeData[] => {
        if (!_parentId) return [...nodes, newNode];
        return nodes.map(n => {
          if (n.id === _parentId) return { ...n, children: [...(n.children || []), newNode] };
          return { ...n, children: addNode(n.children || []) };
        });
      };
      return addNode(prev);
    });
  };

  const handleAddChartNode = async (parentId: string | null) => {
    const typeStr = window.prompt(`${t('templates.designer.promptChartType')}\n${CHART_TYPES.join(', ')}`);
    const chartType = typeStr && CHART_TYPES.includes(typeStr) ? typeStr : CHART_TYPES[0];
    await handleAddChild(parentId, 'chart', chartType);
  };
  const handleAddMapNode = async (parentId: string | null) => {
    const typeStr = window.prompt(`${t('templates.designer.promptMapType')}\n${MAP_TYPES.join(', ')}`);
    const mapType = typeStr && MAP_TYPES.includes(typeStr) ? typeStr : MAP_TYPES[0];
    await handleAddChild(parentId, 'map', undefined, mapType);
  };
  const handleToggleDelete = (nodeId: string) => {
    setTree(prev => {
      const toggle = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.map(n => {
          if (n.id === nodeId) return { ...n, deleted: !n.deleted };
          return { ...n, children: toggle(n.children || []) };
        });
      return toggle(prev);
    });
  };
  const handleHardDelete = async (nodeId: string) => {
    setTree(prev => {
      const remove = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.filter(n => {
          if (n.id === nodeId) return false;
          return { ...n, children: remove(n.children || []) };
        });
      return remove(prev);
    });
  };
  const handleReorderNode = (nodeId: string, newParentId: string | null, newPosition: number) => {
    setTree(prev => {
      const flat = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.flatMap(n => [n, ...flat(n.children || [])]);
      const all = flat(prev);
      const node = all.find(n => n.id === nodeId);
      if (!node) return prev;
      const without = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.filter(n => {
          if (n.id === nodeId) return false;
          return { ...n, children: without(n.children || []) };
        });
      const cleaned = without(prev);
      const addAt = (nodes: TreeNodeData[]): TreeNodeData[] => {
        if (!newParentId) {
          const pos = Math.min(newPosition, nodes.length);
          return [...nodes.slice(0, pos), node, ...nodes.slice(pos)];
        }
        return nodes.map(n => {
          if (n.id === newParentId) return { ...n, children: addAt(n.children || []) };
          return { ...n, children: addAt(n.children || []) };
        });
      };
      return addAt(cleaned);
    });
  };
  const handleUpdateTitle = (nodeId: string, title_ne: string) => {
    setTree(prev => {
      const update = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.map(n => {
          if (n.id === nodeId) return { ...n, title_ne };
          return { ...n, children: update(n.children || []) };
        });
      return update(prev);
    });
  };
  const handleToggleHidden = (nodeId: string) => {
    setTree(prev => {
      const toggle = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.map(n => {
          if (n.id === nodeId) return { ...n, hidden_in_export: !n.hidden_in_export };
          return { ...n, children: toggle(n.children || []) };
        });
      return toggle(prev);
    });
  };
  const handleContentChange = (nodeId: string, content: string, updates?: Record<string, any>) => {
    setTree(prev => {
      const update = (nodes: TreeNodeData[]): TreeNodeData[] =>
        nodes.map(n => {
          if (n.id === nodeId) return { ...n, content, ...(updates || {}) };
          return { ...n, children: update(n.children || []) };
        });
      return update(prev);
    });
  };

  const activeNode = activeNodeId
    ? (() => {
        const find = (nodes: TreeNodeData[]): TreeNodeData | null => {
          for (const n of nodes) {
            if (n.id === activeNodeId) return n;
            const found = find(n.children || []);
            if (found) return found;
          }
          return null;
        };
        return find(tree);
      })()
    : null;

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderBottom: '1px solid #f0f0f0', background: '#fafafa' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/templates?tab=manage&sub=mine')}
          />
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            {t('templates.designer.title')}
          </h2>
          {template && (
            <>
              {template.is_system && <Tag color="gold">{t('templates.designer.system')}</Tag>}
              {template.status && (
                <Tag color={{
                  draft: 'default', in_review: 'processing', rejected: 'error',
                  published: 'success', deprecated: 'warning', retired: 'default',
                }[template.status as string] || 'default'}>
                  {t(`templates.status.${template.status}`, { defaultValue: template.status })}
                  {template.published_version != null ? ` v${template.published_version}` : ''}
                </Tag>
              )}
              <Text
                strong
                style={{ fontSize: 14 }}
                data-testid="template-name"
                editable={{
                  onChange: handleRename,
                  tooltip: t('templates.designer.renameTooltip'),
                  maxLength: 120,
                  triggerType: ['icon', 'text'],
                }}
              >
                {template.name}
              </Text>
              <Select
                allowClear
                placeholder={t('templates.designer.regime')}
                style={{ width: 150 }}
                size="small"
                value={template.plan_regime || undefined}
                onChange={(v) => handleKindChange('plan_regime', v)}
                options={PLAN_REGIMES.map((r) => ({ value: r, label: t(`templates.regime.${r}`, { defaultValue: r }) }))}
              />
              <Select
                allowClear
                placeholder={t('templates.designer.stage')}
                style={{ width: 120 }}
                size="small"
                value={template.plan_stage || undefined}
                onChange={(v) => handleKindChange('plan_stage', v)}
                options={PLAN_STAGES.map((s) => ({ value: s, label: t(`templates.stage.${s}`, { defaultValue: s }) }))}
              />
              <Select
                allowClear
                placeholder={t('templates.designer.category')}
                style={{ width: 150 }}
                size="small"
                value={template.template_category || undefined}
                onChange={handleCategoryChange}
                options={categories.map((c: any) => ({ value: c.key, label: c.label_en }))}
              />
            </>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {!isNew && template && (
            <>
              <Tooltip title={t('templates.designer.previewForestHint')}>
                <Select
                  allowClear
                  size="small"
                  style={{ width: 190 }}
                  placeholder={t('templates.designer.previewForest')}
                  value={previewCalcId}
                  onChange={setPreviewCalcId}
                  options={previewForests.map((c) => ({
                    value: c.id, label: c.forest_name || c.id,
                  }))}
                />
              </Tooltip>
              <Button
                icon={<HistoryOutlined />}
                onClick={handleOpenVersionHistory}
                size="small"
              >
                {t('templates.designer.history')}
              </Button>
              <Tooltip title={t('templates.designer.capturePreview')}>
                <Button
                  icon={<CameraOutlined />}
                  onClick={handleCapturePreview}
                  size="small"
                  loading={capturing}
                >
                  {t('templates.designer.preview')}
                </Button>
              </Tooltip>
              <Button
                icon={<CheckCircleOutlined />}
                onClick={handleValidate}
                size="small"
                loading={validating}
              >
                {t('templates.designer.validate')}
              </Button>
              {isSuperAdmin && (
                <Button
                  icon={template.status === 'published' ? <StopOutlined /> : <CheckCircleOutlined />}
                  onClick={handlePublish}
                  size="small"
                  loading={saving}
                  type={template.status === 'published' ? 'default' : 'primary'}
                >
                  {template.status === 'published' ? t('templates.designer.unpublish') : t('templates.designer.publish')}
                </Button>
              )}
              <Button icon={<CopyOutlined />} onClick={handleClone} size="small" loading={saving}>
                {t('templates.designer.clone')}
              </Button>
            </>
          )}
          <Button
            size="small"
            onClick={() => window.open('/templates/map-variables', '_blank', 'noopener')}
          >
            {t('mapVars.title')}
          </Button>
          <Button
            icon={<SaveOutlined />}
            onClick={handleSaveWithVersion}
            size="small"
            type="primary"
            loading={saving}
          >
            {isNew ? t('templates.designer.createTemplate') : t('templates.designer.saveVersion')}
          </Button>
        </div>
      </div>

      {validation && (validation.errors.length > 0 || validation.warnings.length > 0) && (
        <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0', background: validation.errors.length ? '#fff2f0' : '#fffbe6', maxHeight: 160, overflow: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <Text strong style={{ fontSize: 13 }}>
              {validation.errors.length
                ? t('templates.designer.validationErrorsN', { n: formatNumber(validation.errors.length) })
                : t('templates.designer.validationWarningsN', { n: formatNumber(validation.warnings.length) })}
            </Text>
            <Button type="text" size="small" onClick={() => setValidation(null)}>{t('common.close')}</Button>
          </div>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {validation.errors.map((e: any, i: number) => (
              <li key={`e${i}`}><Text type="danger" style={{ fontSize: 12 }}>{e.message}{e.token ? ` — ${e.token}` : ''}</Text></li>
            ))}
            {validation.warnings.map((w: any, i: number) => (
              <li key={`w${i}`}><Text type="warning" style={{ fontSize: 12 }}>{w.message}</Text></li>
            ))}
          </ul>
        </div>
      )}

      <div className="template-designer-content" style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ width: 320, borderRight: '1px solid #f0f0f0', overflow: 'hidden', flexShrink: 0 }}>
          <TreeSidebar
            tree={tree}
            activeNodeId={activeNodeId}
            onSelectNode={setActiveNodeId}
            onAddChild={(pid) => handleAddChild(pid, 'richtext')}
            onAddChartNode={handleAddChartNode}
            onAddMapNode={handleAddMapNode}
            onAddStaticTable={(pid) => handleAddChild(pid, 'static_table')}
            onToggleDelete={handleToggleDelete}
            onToggleHidden={handleToggleHidden}
            onHardDelete={handleHardDelete}
            onUpdateTitle={handleUpdateTitle}
            onReorderNode={handleReorderNode}
          />
        </div>
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', position: 'relative' }}>
          <div style={{ position: 'absolute', top: 8, right: 8, zIndex: 10 }}>
            <Button
              size="small"
              icon={<EyeOutlined />}
              onClick={() => setShowVariablePicker(!showVariablePicker)}
            >
              {showVariablePicker ? t('templates.designer.hideVariables') : t('templates.designer.variables')}
            </Button>
          </div>
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: '8px 16px', borderBottom: '1px solid #f0f0f0', fontSize: 13, color: '#666' }}>
                {activeNode ? (
                  <span>
                    <strong>{activeNode.title_ne || activeNode.title_en || t('templates.designer.untitledNode')}</strong>
                    {activeNode.content_type === 'richtext' && ' — Rich Text'}
                    {activeNode.content_type === 'static_table' && ' — Static Table'}
                  </span>
                ) : (
                  <span style={{ color: '#bbb' }}>{t('templates.designer.selectSection')}</span>
                )}
              </div>
              <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <ContentPane
                  node={activeNode}
                  planId={''}
                  calculationId={template?.source_calculation_id || undefined}
                  onContentChange={handleContentChange}
                  templatePreview={template?.id
                    ? { templateId: template.id, calculationId: previewCalcId }
                    : undefined}
                />
              </div>
            </div>
            {showVariablePicker && activeNode && (
              <div style={{ width: 300, borderLeft: '1px solid #f0f0f0', overflow: 'auto', flexShrink: 0 }}>
                <VariablePicker
                  calculationId={template?.source_calculation_id || undefined}
                  onSelect={(key) => {
                    const textarea = document.querySelector('.content-pane-textarea') as HTMLTextAreaElement;
                    if (textarea) {
                      const start = textarea.selectionStart;
                      const end = textarea.selectionEnd;
                      const newContent = activeNode.content.slice(0, start) + `{{${key}}}` + activeNode.content.slice(end);
                      handleContentChange(activeNode.id, newContent);
                    } else {
                      handleContentChange(activeNode.id, activeNode.content + `{{${key}}}`);
                    }
                  }}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      <Modal
        title={<span><HistoryOutlined /> Version History: {template?.name}</span>}
        open={versionHistoryOpen}
        onCancel={() => setVersionHistoryOpen(false)}
        footer={null}
        width={640}
      >
        {versionsLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : versions.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>
            <HistoryOutlined style={{ fontSize: 32, marginBottom: 12 }} />
            <p>{t('templates.designer.noHistory')}</p>
          </div>
        ) : (
          <List
            dataSource={versions}
            renderItem={(v: any) => (
              <List.Item
                actions={[
                  <Popconfirm
                    key="rollback"
                    title={t('templates.designer.confirmRollback', { version: formatNumber(v.version) })}
                    onConfirm={() => handleRollback(v.version)}
                  >
                    <Button size="small" icon={<RollbackOutlined />} loading={rollbacking}>
                      {t('templates.designer.rollback')}
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <Tag color={v.version === template?.version ? 'green' : 'default'} style={{ fontSize: 14 }}>
                      v{v.version}
                    </Tag>
                  }
                  title={
                    <Space>
                      <Text strong>{v.version === template?.version ? t('templates.designer.currentVersion') : v.name}</Text>
                      {v.version === template?.version && <Tag color="green">{t('templates.designer.active')}</Tag>}
                    </Space>
                  }
                  description={
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {new Date(v.created_at).toLocaleString()}
                      </Text>
                      {v.changelog && (
                        <>
                          <Divider style={{ margin: '4px 0' }} />
                          <Text style={{ fontSize: 12, fontStyle: 'italic' }}>
                            {v.changelog}
                          </Text>
                        </>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Modal>

      <Modal
        title={t('templates.designer.saveNewVersion')}
        open={changelogModal}
        onOk={() => { setChangelogModal(false); handleSave(); }}
        onCancel={() => setChangelogModal(false)}
        okText={t('templates.designer.saveVersion')}
        confirmLoading={saving}
      >
        <div style={{ marginBottom: 12 }}>
          <Text>{t('templates.designer.changeNote')}</Text>
        </div>
        <TextArea
          value={changelog}
          onChange={(e) => setChangelog(e.target.value)}
          rows={3}
          placeholder={t('templates.designer.changeNoteHint')}
        />
      </Modal>
    </div>
  );
};

export default TemplateDesignerPage;