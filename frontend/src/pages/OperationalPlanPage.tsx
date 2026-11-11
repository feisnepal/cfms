/** OperationalPlanPage — operational plan editor with tabbed sections, saving, and export. */
import { findChapterForSection } from '../lib/planChapterMatch';
import React, { useState, useEffect } from 'react';
import { PLAN_STATUS_KEY, statusLabel } from '../lib/statusLabels';
import { planTools } from '../lib/planPermissions';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Button, message, Spin, Tag, Tabs, Tooltip, Alert, Modal, Select, Checkbox, Input, Dropdown } from 'antd';
import {
  SaveOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  DownloadOutlined,
  BranchesOutlined,
  PieChartOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  CheckCircleOutlined,
  EllipsisOutlined,
} from '@ant-design/icons';
import { operationalPlanApi } from '../services/api';
import { ExportRequirementsChecklist } from '../components/ExportRequirementsChecklist';
import { isOpAutoStageEnabled } from '../config/featureFlags';
import { useAuth } from '../contexts/AuthContext';
import TreeSidebar from '../components/OperationalPlan/TreeSidebar';
import ContentPane from '../components/OperationalPlan/ContentPane';
import DocumentOutline from '../components/OperationalPlan/DocumentOutline';
import MetadataForm from '../components/OperationalPlan/MetadataForm';
import PlanValidityModal from '../components/OperationalPlan/PlanValidityModal';
import ShareTemplateModal from '../components/ShareTemplateModal';
import SectionLibraryPanel from '../components/SectionLibraryPanel';
import type { PlanValidity } from '../services/api';
import TableEditor from '../components/OperationalPlan/TableEditor';
import ChartEditor from '../components/OperationalPlan/ChartEditor';
import MapPreview from '../components/OperationalPlan/MapPreview';
import PreviewDrawer from '../components/OperationalPlan/PreviewDrawer';
import HelpTooltip from '../components/HelpTooltip';
import GuideModal from '../components/GuideModal';
import i18n from '../i18n';
import { useT } from '../i18n/hooks';
import { usePlanCheck } from '../features/yearly-plan/PlanCheck';
import { formatDateTime } from '../i18n/numberFormat';

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
  inline_tables?: { caption?: string; columns: string[]; rows: string[][]; merges?: { row: number; col: number; rowspan: number; colspan: number }[] }[] | null;
  children: TreeNodeData[];
  is_locked: boolean;
  hidden_in_export: boolean;
  deleted: boolean;
  last_modified?: string | null;
}

type EditorTab = 'editor' | 'tables' | 'charts' | 'maps';

interface OperationalPlanPageProps {
  calculationId?: string;
}

const OperationalPlanPage: React.FC<OperationalPlanPageProps> = (props) => {
  const t = useT();
  const isNe = i18n.language === 'ne';
  const { id: routeId } = useParams<{ id: string }>();
  const calculationId = props.calculationId || routeId;
  const { user } = useAuth();
  const isSuperAdmin = user?.role === 'super_admin';
  const isDesigner = user?.role === 'template_designer';
  const canCreateDirect = isSuperAdmin || isDesigner;
  const tools = planTools(user?.role, Boolean(user));
  const isEditor = tools.canEditDocument;
  const navigate = useNavigate();
  // before the plan document is created, anything unfinished in the yearly plan is listed once (it never blocks)
  const planCheck = usePlanCheck({ onFix: (calcId) => navigate(`/calculations/${calcId}/yearly-activities`) });

  const [plan, setPlan] = useState<any>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [tree, setTree] = useState<TreeNodeData[]>([]);
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [showMetadata, setShowMetadata] = useState(false);
  const [validityOpen, setValidityOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [saveSecOpen, setSaveSecOpen] = useState(false);
  const [saveSecName, setSaveSecName] = useState('');
  const [saveSecDesc, setSaveSecDesc] = useState('');
  const [savingSec, setSavingSec] = useState(false);
  const [insertWhere, setInsertWhere] = useState<'after' | 'end'>('after');
  const [shareTpl, setShareTpl] = useState<{ id: string; name: string } | null>(null);
  const [validity, setValidity] = useState<PlanValidity | null>(null);
  const [checking, setChecking] = useState(false);
  const [saveTplOpen, setSaveTplOpen] = useState(false);
  const [saveTplName, setSaveTplName] = useState('');
  const [saveTplDesc, setSaveTplDesc] = useState('');
  const [savingTpl, setSavingTpl] = useState(false);
  const [activeTab, setActiveTab] = useState<EditorTab>('editor');
  const [showGuide, setShowGuide] = useState(false);
  const [tmplStatus, setTmplStatus] = useState<any>(null);
  const [upgradeModal, setUpgradeModal] = useState(false);
  const [upgradeDiff, setUpgradeDiff] = useState<any>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [createModal, setCreateModal] = useState(false);
  // This page is mounted (hidden) whenever the forest is open, so it must never pop a dialog or navigate by itself: with no plan it
  // shows a Start button instead and creating the plan is the user's own press.
  const [noPlan, setNoPlan] = useState(false);
  const [createRegime, setCreateRegime] = useState<string>('brief_fmp');
  const [createStage, setCreateStage] = useState<string>('new');
  const [createSuggestion, setCreateSuggestion] = useState<string>('');
  const [createAuthoring, setCreateAuthoring] = useState(false);
  const [creatingPlan, setCreatingPlan] = useState(false);
  const isAuthoringPlan = !!plan?.plan_metadata?.authoring;

  useEffect(() => {
    if (calculationId) {
      loadOrCreatePlan(calculationId);
    }
  }, [calculationId]);

  const loadOrCreatePlan = async (calcId: string) => {
    setLoading(true);
    try {
      let planData = await operationalPlanApi.getByCalculation(calcId);
      setPlan(planData);
      setPlanId(planData.id);
      setTree(planData.tree || []);
      if ((planData.tree || []).length > 0) {
        // `?node=<title>` (a report section's shortcut) opens the chapter of that title so the user can type in it directly
        const wanted = new URLSearchParams(window.location.search).get('node')?.trim();
        const hit = wanted ? findChapterForSection(planData.tree as TreeNodeData[], wanted) : null;
        setActiveNodeId((hit ?? planData.tree[0]).id);
        if (hit) setActiveTab('editor');
      }
      operationalPlanApi.getPlanTemplateStatus(planData.id)
        .then(setTmplStatus)
        .catch(() => setTmplStatus(null));
    } catch (err: any) {
      if (err.response?.status === 404) {
        await createWithDefault(calcId);
      } else {
        message.error(t('operationalPlan.page.loadFailed'));
      }
    } finally {
      setLoading(false);
    }
  };

  const createWithDefault = async (calcId: string) => {
    // Whoever can draw the forest boundary can prepare its plan (owner, 2026-10-11): everyone picks regime + stage here.
    // Pre-highlight the stage the forest's history suggests (advisory).
    setNoPlan(true);
    operationalPlanApi.suggestKind(calcId, createRegime)
      .then((s) => {
        setCreateSuggestion(s.reason || '');
        if (s.has_prior_plan) setCreateStage('revision');
      })
      .catch(() => {});
  };

  const doCreatePlan = () => (calculationId ? planCheck.guard(calculationId, createPlanNow, 'create') : undefined);

  const createPlanNow = async () => {
    if (!calculationId) return;
    setCreatingPlan(true);
    try {
      const newPlan = await operationalPlanApi.create(
        calculationId, undefined, undefined, undefined,
        createRegime, isOpAutoStageEnabled() ? undefined : createStage,
        createAuthoring,
      );
      setPlan(newPlan);
      setPlanId(newPlan.id);
      setTree(newPlan.tree || []);
      if ((newPlan.tree || []).length > 0) setActiveNodeId(newPlan.tree[0].id);
      setCreateModal(false);
      operationalPlanApi.getPlanTemplateStatus(newPlan.id).then(setTmplStatus).catch(() => {});
    } catch {
      message.error(t('operationalPlan.page.createFailed'));
    } finally {
      setCreatingPlan(false);
    }
  };

  const openUpgrade = async () => {
    if (!planId) return;
    setUpgradeModal(true);
    setUpgradeDiff(null);
    try {
      const res = await operationalPlanApi.upgradePlanTemplate(planId, false);
      setUpgradeDiff(res.diff);
    } catch {
      message.error(t('operationalPlan.upgrade.previewFailed'));
    }
  };

  const confirmUpgrade = async () => {
    if (!planId || !calculationId) return;
    setUpgrading(true);
    try {
      await operationalPlanApi.upgradePlanTemplate(planId, true);
      message.success(t('operationalPlan.upgrade.done'));
      setUpgradeModal(false);
      await loadOrCreatePlan(calculationId);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('operationalPlan.upgrade.failed'));
    } finally {
      setUpgrading(false);
    }
  };

  const handleSave = async () => {
    if (!planId) return;
    setSaving(true);
    try {
      const payload: any = { tree };
      const updated = await operationalPlanApi.update(planId, payload);
      setPlan(updated);
      message.success(t('operationalPlan.page.msgSaved'));
    } catch {
      message.error(t('operationalPlan.page.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleAutoPopulate = async () => {
    if (!planId) return;
    setLoading(true);
    try {
      const updated = await operationalPlanApi.autoPopulate(planId);
      setTree(updated.tree || []);
      message.success(t('operationalPlan.page.msgResolved'));
    } catch {
      message.error(t('operationalPlan.page.autoPopulateFailed'));
    } finally {
      setLoading(false);
    }
  };

  // "Export now" on a template card arrives with ?export=1: run the export once the plan has loaded, then drop the flag so a
  // reload or a second visit never exports again by itself.
  const autoExportDone = React.useRef(false);
  const [urlParams, setUrlParams] = useSearchParams();
  useEffect(() => {
    if (!planId || loading || autoExportDone.current) return;
    if (urlParams.get('export') !== '1') return;
    autoExportDone.current = true;
    setUrlParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete('export');
      return next;
    }, { replace: true });
    void handleExport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId, loading, urlParams]);

  const handleCheckDocument = async () => {
    if (!planId) return;
    setChecking(true);
    try {
      setValidity(await operationalPlanApi.getPlanValidity(planId));
      setValidityOpen(true);
    } catch {
      message.error(t('operationalPlan.page.loadFailed'));
    } finally {
      setChecking(false);
    }
  };

  // Where a library section goes: right after the selected chapter (same level), or at the end of the document.
  const placeFor = (): { parent_id: string | null; position: number } => {
    if (insertWhere === 'end' || !activeNodeId) return { parent_id: null, position: -1 };
    const walk = (nodes: TreeNodeData[], parent: string | null): { parent_id: string | null; position: number } | null => {
      for (let i = 0; i < nodes.length; i += 1) {
        if (nodes[i].id === activeNodeId) return { parent_id: parent, position: i + 1 };
        const hit = walk(nodes[i].children || [], nodes[i].id);
        if (hit) return hit;
      }
      return null;
    };
    return walk(tree, null) ?? { parent_id: null, position: -1 };
  };

  const handleInsertSection = async (section: { id: string; name: string }) => {
    if (!planId) return;
    try {
      const where = placeFor();
      const res = await operationalPlanApi.insertSection(planId, { section_id: section.id, ...where });
      setTree(res.tree || []);
      if (res.inserted[0]) setActiveNodeId(res.inserted[0]);
      setActiveTab('editor');
      setLibraryOpen(false);
      message.success(t(res.locked ? 'sections.insertedLocked' : 'sections.inserted', { name: section.name }));
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : t('sections.insertFailed'));
    }
  };

  const handleSaveSection = async () => {
    if (!planId || !activeNodeId || !saveSecName.trim()) return;
    setSavingSec(true);
    try {
      const res = await operationalPlanApi.saveSection(planId, { node_id: activeNodeId, name: saveSecName.trim(), description: saveSecDesc.trim() });
      setSaveSecOpen(false);
      const touched = res.report.edited.length;
      Modal.success({
        title: t('sections.saved'),
        content: touched > 0 ? t('sections.savedReview', { count: touched }) : t('sections.savedClean'),
        okText: t('sections.openLibrary'),
        onOk: () => navigate('/templates?tab=sections&scope=mine'),
      });
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : t('operationalPlan.page.saveFailed'));
    } finally {
      setSavingSec(false);
    }
  };

  const handleSaveAsTemplate = async () => {
    if (!planId || !saveTplName.trim()) return;
    setSavingTpl(true);
    try {
      const res = await operationalPlanApi.saveAsMyTemplate(planId, { name: saveTplName.trim(), description: saveTplDesc.trim() });
      setSaveTplOpen(false);
      const touched = res.report.edited.length + res.report.new.length;
      Modal.confirm({
        title: t('operationalPlan.page.templateSaved'),
        content: touched > 0
          ? t('operationalPlan.page.templateSavedReview', { count: touched })
          : t('operationalPlan.page.templateSavedClean'),
        okText: t('operationalPlan.page.shareItNow'),
        cancelText: t('operationalPlan.page.openMyTemplates'),
        onOk: () => setShareTpl({ id: res.template.id, name: res.template.name }),
        onCancel: () => navigate('/templates?scope=mine'),
      });
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : t('operationalPlan.page.saveFailed'));
    } finally {
      setSavingTpl(false);
    }
  };

  const handleExport = async () => {
    if (!planId) return;
    if (exporting) return;
    // Mandatory steps first (owner rule 2026-10-10): show what is missing instead of downloading.
    try {
      const req = await operationalPlanApi.getExportRequirements(planId);
      if (!req.ready) {
        Modal.warning({
          title: t('operationalPlan.page.exportDocx'),
          width: 560,
          content: (
            <ExportRequirementsChecklist
              data={req}
              calculationId={calculationId}
              onNavigate={(url) => {
                Modal.destroyAll();
                navigate(url);
              }}
            />
          ),
        });
        return;
      }
    } catch {
      // The checklist is advisory here; the server enforces the same rule and refuses the export itself.
    }
    // Parts of the plan with no data print "No data" in red bold: say how many, once, before the file is made. Never blocks.
    try {
      const [rd, vd] = await Promise.all([
        operationalPlanApi.getPlanReadiness(planId),
        operationalPlanApi.getPlanValidity(planId).catch(() => null),
      ]);
      const problems = vd ? vd.errors.length : 0;
      const labels = [
        ...rd.missing.map((m) => (isNe ? m.label_ne : m.label_en)),
        ...rd.unmet_maps.map((m) => m.token),
      ];
      if (labels.length > 0 || problems > 0) {
        const proceed = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: t('operationalPlan.page.noDataWarnTitle'),
            width: 560,
            content: (
              <div>
                {labels.length > 0 && <p>{t('operationalPlan.page.noDataWarnBody', { count: labels.length })}</p>}
                {problems > 0 && <p>{t('operationalPlan.page.validityWarnBody', { count: problems })}</p>}
                <ul style={{ maxHeight: 200, overflow: 'auto', paddingLeft: 18 }}>
                  {labels.slice(0, 30).map((l, i) => <li key={i}>{l}</li>)}
                  {labels.length > 30 && <li>…</li>}
                </ul>
              </div>
            ),
            okText: t('operationalPlan.page.noDataExportAnyway'),
            cancelText: t('operationalPlan.page.noDataGoBack'),
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        });
        if (!proceed) return;
      }
    } catch {
      // The warning is advisory; the export itself does not depend on it.
    }
    setExporting(true);
    // Keep the backend export lease alive while the DOCX builds. Without this,
    // exports longer than the 5-minute TTL expire the lock mid-export, letting
    // a second export take it over (or leaving it stranded as a false
    // "Export is already running" block for geometry writes).
    const heartbeat = setInterval(() => {
      operationalPlanApi.exportHeartbeat(planId).catch(() => {
        // Heartbeat failures are non-fatal; the initial acquire owns the lock.
      });
    }, 30000);
    try {
      await operationalPlanApi.exportDocx(planId, plan?.forest_name || 'CF');
      message.success(t('operationalPlan.page.msgExported'));
    } catch (err: any) {
      const msg: string = err?.message || err?.response?.data?.detail?.message || '';
      if (
        err?.response?.data?.detail?.code === 'EXPORT_RUNNING' ||
        /already running/i.test(msg) ||
        /Export is running/i.test(msg)
      ) {
        message.error(t('operationalPlan.page.exportRunning'));
      } else {
        message.error(msg || t('operationalPlan.page.exportFailed'));
      }
    } finally {
      clearInterval(heartbeat);
      setExporting(false);
    }
  };

  const handleHardDelete = async (nodeId: string) => {
    if (!planId) return;
    try {
      const result = await operationalPlanApi.deleteNode(planId, nodeId);
      setTree(result.tree || []);
      if (activeNodeId === nodeId) setActiveNodeId(null);
      message.success(t('operationalPlan.page.msgSectionDeleted'));
    } catch {
      message.error(t('operationalPlan.page.deleteSectionFailed'));
    }
  };

  const handleAddStaticTable = async (parentId: string | null) => {
    if (!planId) return;

    if (activeNode && activeNode.content_type === 'richtext') {
      const newTable = {
        caption: '',
        columns: ['Column 1', 'Column 2', 'Column 3'],
        rows: [['', '', ''], ['', '', ''], ['', '', '']],
        merges: [],
      };
      const existing = activeNode.inline_tables || [];
      const updated = [...existing, newTable];
      try {
        await operationalPlanApi.updateNode(planId, activeNode.id, { inline_tables: updated });
        setTree(prev => {
          const update = (nodes: TreeNodeData[]): TreeNodeData[] =>
            nodes.map(n => {
              if (n.id === activeNode.id) return { ...n, inline_tables: updated };
              return { ...n, children: update(n.children || []) };
            });
          return update(prev);
        });
        message.success(t('operationalPlan.page.msgTableAdded'));
      } catch {
        message.error(t('operationalPlan.page.addTableFailed'));
      }
      return;
    }

    const val = window.prompt(t('operationalPlan.page.promptTableTitle'));
    if (!val) return;
    try {
      const result = await operationalPlanApi.addNode(planId, {
        parent_id: parentId,
        type: parentId ? 'subsection' : 'section',
        title_ne: val,
        content: '',
        content_type: 'static_table',
        static_table: {
          columns: ['Column 1', 'Column 2', 'Column 3'],
          rows: [['', '', ''], ['', '', ''], ['', '', '']],
        },
      });
      setTree(result.tree || []);
      message.success(t('operationalPlan.page.msgStaticTableAdded'));
    } catch {
      message.error(t('operationalPlan.page.addStaticTableFailed'));
    }
  };

  const handleAddChild = async (parentId: string | null, contentType: string = 'richtext', chartType?: string, mapType?: string) => {
    if (!planId) return;
    const promptKey = contentType === 'chart'
      ? 'operationalPlan.page.promptChartTitle'
      : contentType === 'map'
        ? 'operationalPlan.page.promptMapTitle'
        : 'operationalPlan.page.promptSectionTitle';
    const val = window.prompt(t(promptKey));
    if (!val) return;
    try {
      const result = await operationalPlanApi.addNode(planId, {
        parent_id: parentId,
        type: parentId ? 'subsection' : 'section',
        title_ne: val,
        content: '',
        content_type: contentType,
        chart_type: contentType === 'chart' ? (chartType || 'forest_type_pie') : null,
        map_type: contentType === 'map' ? (mapType || 'boundary') : null,
      });
      setTree(result.tree || []);
      message.success(t(
        contentType === 'chart'
          ? 'operationalPlan.page.msgChartAdded'
          : contentType === 'map'
            ? 'operationalPlan.page.msgMapAdded'
            : 'operationalPlan.page.msgSectionAdded',
      ));
    } catch {
      message.error(t('operationalPlan.page.addSectionFailed'));
    }
  };

  const handleAddChartNode = async (parentId: string | null) => {
    if (!planId) return;
    const chartTypes = ['forest_type_pie', 'species_pie', 'block_area_bar', 'slope_pie', 'canopy_pie', 'landcover_pie', 'biomass_bar', 'dbh_histogram'];
    const typeStr = window.prompt(
      t('operationalPlan.page.promptChartType') + '\n' + chartTypes.join(', '),
    );
    const chartType = typeStr && chartTypes.includes(typeStr) ? typeStr : 'forest_type_pie';
    await handleAddChild(parentId, 'chart', chartType);
  };

  const handleAddMapNode = async (parentId: string | null) => {
    if (!planId) return;
    const mapTypes = ['boundary', 'forest_type', 'forest_health', 'slope', 'biomass', 'landcover', 'landcover_1984', 'soil_texture', 'dem', 'aspect', 'canopy'];
    const typeStr = window.prompt(
      t('operationalPlan.page.promptMapType') + '\n' + mapTypes.join(', '),
    );
    const mapType = typeStr && mapTypes.includes(typeStr) ? typeStr : 'boundary';
    await handleAddChild(parentId, 'map', undefined, mapType);
  };

  const handleToggleDelete = (nodeId: string) => {
    const toggleNode = (nodes: TreeNodeData[]): TreeNodeData[] =>
      nodes.map(n => {
        if (n.id === nodeId) {
          const newDeleted = !n.deleted;
          const cascade = (children: TreeNodeData[]): TreeNodeData[] =>
            children.map(c => ({ ...c, deleted: newDeleted, children: cascade(c.children) }));
          return { ...n, deleted: newDeleted, children: cascade(n.children) };
        }
        return { ...n, children: toggleNode(n.children) };
      });
    setTree(prev => toggleNode(prev));
  };

  const handleReorderNode = async (nodeId: string, newParentId: string | null, newPosition: number) => {
    if (!planId) return;
    try {
      const result = await operationalPlanApi.reorderTree(planId, {
        node_id: nodeId,
        new_parent_id: newParentId,
        new_position: newPosition,
      });
      setTree(result.tree || []);
      message.success(t('operationalPlan.page.msgSectionMoved'));
    } catch { message.error(t('operationalPlan.page.moveSectionFailed')); }
  };

  const handleUpdateTitle = async (nodeId: string, title_ne: string) => {
    if (!planId) return;
    try {
      await operationalPlanApi.updateNode(planId, nodeId, { title_ne });
      setTree(prev => {
        const update = (nodes: TreeNodeData[]): TreeNodeData[] =>
          nodes.map(n => {
            if (n.id === nodeId) return { ...n, title_ne };
            return { ...n, children: update(n.children || []) };
          });
        return update(prev);
      });
    } catch { message.error(t('operationalPlan.page.updateTitleFailed')); }
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

  const handleToggleHidden = async (nodeId: string) => {
    if (!planId) return;
    const findNode = (nodes: TreeNodeData[]): TreeNodeData | null => {
      for (const n of nodes) {
        if (n.id === nodeId) return n;
        const found = findNode(n.children || []);
        if (found) return found;
      }
      return null;
    };
    const node = findNode(tree);
    if (!node) return;
    try {
      await operationalPlanApi.updateNode(planId, nodeId, {
        hidden_in_export: !node.hidden_in_export,
      });
      setTree(prev => {
        const update = (nodes: TreeNodeData[]): TreeNodeData[] =>
          nodes.map(n => {
            if (n.id === nodeId) return { ...n, hidden_in_export: !n.hidden_in_export };
            return { ...n, children: update(n.children || []) };
          });
        return update(prev);
      });
    } catch {
      message.error(t('operationalPlan.page.updateNodeFailed'));
    }
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

  const createPlanModal = (
  <Modal
    title={t('operationalPlan.startPlan.title')}
    open={createModal}
    onCancel={() => setCreateModal(false)}
    onOk={doCreatePlan}
    okText={t('operationalPlan.startPlan.ok')}
    confirmLoading={creatingPlan}
    width={460}
  >
    <p style={{ marginBottom: 12 }}>{t('operationalPlan.startPlan.explain')}</p>
    <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('templates.designer.regime')}</div>
        <Select
          style={{ width: '100%' }}
          value={createRegime}
          onChange={setCreateRegime}
          options={['sustainable_fmp', 'brief_fmp', 'scientific_fmp'].map((r) => ({
            value: r, label: t(`templates.regime.${r}`, { defaultValue: r }),
          }))}
        />
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('templates.designer.stage')}</div>
        <Select
          style={{ width: '100%' }}
          value={createStage}
          onChange={setCreateStage}
          disabled={isOpAutoStageEnabled()}
          options={['new', 'revision'].map((s) => ({
            value: s, label: t(`templates.stage.${s}`, { defaultValue: s }),
          }))}
        />
        {isOpAutoStageEnabled() && (
          <div style={{ fontSize: 11, color: '#aaa', marginTop: 2 }}>
            {t('operationalPlan.startPlan.autoStage')}
          </div>
        )}
      </div>
    </div>
    {createSuggestion && (
      <Alert type="info" showIcon style={{ marginTop: 8 }} message={createSuggestion} />
    )}
    {canCreateDirect && (
      <Checkbox
        style={{ marginTop: 12 }}
        checked={createAuthoring}
        onChange={(e) => setCreateAuthoring(e.target.checked)}
      >
        {t('operationalPlan.startPlan.authoring')}
        <div style={{ fontSize: 11, color: '#999' }}>
          {t('operationalPlan.startPlan.authoringHint')}
        </div>
      </Checkbox>
    )}
  </Modal>
  );

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (noPlan && !plan) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, height: '100%', minHeight: 320, background: '#fff' }}>
        {planCheck.dialog}
        <div style={{ fontSize: 16, fontWeight: 600 }}>{t('operationalPlan.startPlan.title')}</div>
        <Button type="primary" onClick={() => navigate(`/templates?calculation_id=${calculationId}`)} data-testid="op-choose-template">
          {t('operationalPlan.startPlan.chooseTemplate')}
        </Button>
        <Button type="link" onClick={() => setCreateModal(true)} data-testid="op-start-plan">{t('operationalPlan.startPlan.ok')}</Button>
        {createPlanModal}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#fff' }}>
      {planCheck.dialog}
      {tmplStatus?.upgrade_available && (
        <Alert
          type="info"
          showIcon
          banner
          message={t('operationalPlan.upgrade.banner', {
            name: tmplStatus.template_name || '',
            v: tmplStatus.latest_published_version,
          })}
          action={
            <Button size="small" type="primary" onClick={openUpgrade}>
              {t('operationalPlan.upgrade.review')}
            </Button>
          }
        />
      )}
      {createPlanModal}
      <Modal
        title={t('sections.saveSelected')}
        open={saveSecOpen}
        onCancel={() => setSaveSecOpen(false)}
        onOk={handleSaveSection}
        okText={t('sections.saveSelected')}
        okButtonProps={{ disabled: !saveSecName.trim() }}
        confirmLoading={savingSec}
        width={520}
      >
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message={t('sections.saveNote')} />
        <div style={{ marginBottom: 8 }}>{t('sections.name')}</div>
        <Input value={saveSecName} onChange={(e) => setSaveSecName(e.target.value)} maxLength={255} style={{ marginBottom: 12 }} />
        <div style={{ marginBottom: 8 }}>{t('operationalPlan.page.saveAsTemplateDesc')}</div>
        <Input.TextArea value={saveSecDesc} onChange={(e) => setSaveSecDesc(e.target.value)} rows={3} />
      </Modal>
      <Modal
        title={t('sections.insertFromLibrary')}
        open={libraryOpen}
        onCancel={() => setLibraryOpen(false)}
        footer={null}
        width={900}
      >
        <div style={{ marginBottom: 12 }}>
          <span style={{ marginRight: 8 }}>{t('sections.where')}</span>
          <Select
            size="small"
            value={insertWhere}
            onChange={setInsertWhere}
            style={{ width: 260 }}
            options={[
              { value: 'after', label: t('sections.whereAfter') },
              { value: 'end', label: t('sections.whereEnd') },
            ]}
          />
        </div>
        <SectionLibraryPanel mode="insert" onInsert={handleInsertSection} />
      </Modal>
      <ShareTemplateModal
        open={Boolean(shareTpl)}
        template={shareTpl}
        onClose={() => setShareTpl(null)}
        onShared={() => navigate('/templates?scope=mine')}
      />
      <PlanValidityModal
        open={validityOpen}
        data={validity}
        onClose={() => setValidityOpen(false)}
        onJump={(nodeId) => { setActiveTab('editor'); setActiveNodeId(nodeId); }}
      />
      <Modal
        title={t('operationalPlan.page.saveAsTemplate')}
        open={saveTplOpen}
        onCancel={() => setSaveTplOpen(false)}
        onOk={handleSaveAsTemplate}
        okText={t('operationalPlan.page.saveAsTemplate')}
        okButtonProps={{ disabled: !saveTplName.trim() }}
        confirmLoading={savingTpl}
        width={520}
      >
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message={t('operationalPlan.page.saveAsTemplateNote')} />
        <div style={{ marginBottom: 8 }}>{t('operationalPlan.page.saveAsTemplateName')}</div>
        <Input value={saveTplName} onChange={(e) => setSaveTplName(e.target.value)} maxLength={255} style={{ marginBottom: 12 }} />
        <div style={{ marginBottom: 8 }}>{t('operationalPlan.page.saveAsTemplateDesc')}</div>
        <Input.TextArea value={saveTplDesc} onChange={(e) => setSaveTplDesc(e.target.value)} rows={3} />
      </Modal>
      <Modal
        title={t('operationalPlan.upgrade.title')}
        open={upgradeModal}
        onCancel={() => setUpgradeModal(false)}
        onOk={confirmUpgrade}
        okText={t('operationalPlan.upgrade.apply')}
        confirmLoading={upgrading}
        okButtonProps={{ disabled: !upgradeDiff }}
        width={560}
      >
        {!upgradeDiff ? (
          <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
        ) : (
          <div>
            <p>{t('operationalPlan.upgrade.explain')}</p>
            <ul style={{ fontSize: 13 }}>
              <li>{t('operationalPlan.upgrade.added', { n: upgradeDiff.added.length })}
                {upgradeDiff.added.length > 0 && <> — {upgradeDiff.added.slice(0, 6).join(', ')}</>}</li>
              <li>{t('operationalPlan.upgrade.removed', { n: upgradeDiff.removed.length })}
                {upgradeDiff.removed.length > 0 && <> — {upgradeDiff.removed.slice(0, 6).join(', ')}</>}</li>
              <li>{t('operationalPlan.upgrade.kept', { n: upgradeDiff.kept, c: upgradeDiff.content_preserved })}</li>
            </ul>
            <Alert type="warning" showIcon style={{ marginTop: 8 }}
              message={t('operationalPlan.upgrade.recoverable')} />
          </div>
        )}
      </Modal>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 16px', borderBottom: '1px solid #f0f0f0', background: '#fafafa' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            {isEditor ? t('operationalPlan.page.titleEditor') : t('operationalPlan.page.title')}
          </h2>
          {plan && (
            <Tag color={plan.status === 'draft' ? 'blue' : plan.status === 'submitted' ? 'orange' : 'green'}>
              {statusLabel(PLAN_STATUS_KEY, plan.status, t)}
            </Tag>
          )}
          {isAuthoringPlan && (
            <Tag color="purple">{t('operationalPlan.page.authoringBadge')}</Tag>
          )}
          {plan?.forest_name && (
            <span style={{ color: '#666', fontSize: 13 }}>{plan.forest_name}</span>
          )}
          {tmplStatus?.has_template && (
            <Tooltip title={t('operationalPlan.tmplBadge.tooltip', {
              name: tmplStatus.template_name || '', v: tmplStatus.pinned_version ?? '?',
            })}>
              <Tag color={tmplStatus.upgrade_available ? 'orange' : 'default'} style={{ fontSize: 11 }}>
                {t('operationalPlan.tmplBadge.label', { v: tmplStatus.pinned_version ?? '?' })}
              </Tag>
            </Tooltip>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {isEditor && (
            <Button icon={<SaveOutlined />} onClick={handleSave} size="small" type="primary" loading={saving}>
              {t('operationalPlan.page.saveAll')}
            </Button>
          )}
        </div>
        {planId && (
          <Tooltip title={t('operationalPlan.page.previewFull')}>
            <PreviewDrawer planId={planId} forestName={plan?.forest_name} />
          </Tooltip>
        )}
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              ...(isEditor && tools.canAutoPopulate && !isAuthoringPlan
                ? [{ key: 'update', icon: <ThunderboltOutlined />, label: t('operationalPlan.page.autoPopulate') }]
                : []),
              ...(isEditor ? [{ key: 'check', icon: <CheckCircleOutlined />, label: t('operationalPlan.validity.button') }] : []),
              ...(isEditor ? [{ key: 'saveTemplate', icon: <BranchesOutlined />, label: t('operationalPlan.page.saveAsTemplate') }] : []),
              ...(isEditor && activeNodeId ? [{ key: 'saveSection', icon: <FileTextOutlined />, label: t('sections.saveSelected') }] : []),
              ...(isEditor ? [{ key: 'insertSection', icon: <PlusOutlined />, label: t('sections.insertFromLibrary') }] : []),
              ...(isEditor && plan?.plan_metadata?.template_id
                ? [{
                    key: 'credit',
                    icon: plan?.plan_metadata?.show_template_credit ? <CheckCircleOutlined /> : <span style={{ display: 'inline-block', width: 14 }} />,
                    label: t('operationalPlan.page.creditLine'),
                  }]
                : []),
              ...(isEditor && tools.canEditPlanMetadata ? [{ key: 'metadata', icon: <SettingOutlined />, label: t('operationalPlan.page.metadata') }] : []),
              { key: 'guide', icon: <QuestionCircleOutlined />, label: t('operationalPlan.page.guide') },
            ],
            onClick: async ({ key }) => {
              if (key === 'update') handleAutoPopulate();
              else if (key === 'check') handleCheckDocument();
              else if (key === 'saveTemplate') {
                setSaveTplName(plan?.plan_metadata?.template_name ? `${plan.plan_metadata.template_name} (mine)` : '');
                setSaveTplDesc('');
                setSaveTplOpen(true);
              } else if (key === 'saveSection') {
                const node = activeNode;
                setSaveSecName(node ? (isNe ? node.title_ne : node.title_en) || node.title_ne || node.title_en : '');
                setSaveSecDesc('');
                setSaveSecOpen(true);
              } else if (key === 'insertSection') {
                setLibraryOpen(true);
              } else if (key === 'credit') {
                if (!planId) return;
                const on = !plan?.plan_metadata?.show_template_credit;
                try {
                  await operationalPlanApi.setPlanCreditLine(planId, on);
                  setPlan((prev: any) => prev && ({ ...prev, plan_metadata: { ...(prev.plan_metadata || {}), show_template_credit: on } }));
                } catch {
                  message.error(t('operationalPlan.page.saveFailed'));
                }
              } else if (key === 'metadata') setShowMetadata(true);
              else if (key === 'guide') setShowGuide(true);
            },
          }}
        >
          <Button size="small" icon={<EllipsisOutlined />} loading={checking} data-testid="op-more">
            {t('operationalPlan.page.more')}
          </Button>
        </Dropdown>
        <HelpTooltip tKey="tooltips.exportDocx" />
        <Button
          icon={<DownloadOutlined />}
          size="small"
          type={isEditor ? 'default' : 'primary'}
          onClick={handleExport}
          loading={exporting}
          disabled={exporting || loading}
        >
          {t('operationalPlan.page.exportDocx')}
        </Button>
      </div>

      {isEditor ? (
        <>
          <Tabs
            activeKey={activeTab}
            onChange={(k) => setActiveTab(k as EditorTab)}
            items={[
              { key: 'editor', label: <span><BranchesOutlined /> {t('operationalPlan.page.tabEditor')}</span> },
              { key: 'tables', label: <span><PlusOutlined /> {t('operationalPlan.page.tabTables')}</span> },
              { key: 'charts', label: <span><PieChartOutlined /> {t('operationalPlan.page.tabCharts')}</span> },
              { key: 'maps', label: <span><EnvironmentOutlined /> {t('operationalPlan.page.tabMaps')}</span> },
            ]}
            style={{ marginBottom: 0, padding: '0 16px' }}
            tabBarStyle={{ marginBottom: 0 }}
          />
          {activeTab === 'editor' ? (
            <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
              <div style={{ width: 320, borderRight: '1px solid #f0f0f0', overflow: 'hidden', flexShrink: 0 }}>
                <TreeSidebar
                  tree={tree}
                  activeNodeId={activeNodeId}
                  onSelectNode={setActiveNodeId}
                  onAddChild={handleAddChild}
                  onAddChartNode={handleAddChartNode}
                  onAddMapNode={handleAddMapNode}
                  onAddStaticTable={handleAddStaticTable}
                  onToggleDelete={handleToggleDelete}
                  onToggleHidden={handleToggleHidden}
                  onHardDelete={handleHardDelete}
                  onUpdateTitle={handleUpdateTitle}
                  onReorderNode={handleReorderNode}
                />
              </div>
              <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                {planId && <ContentPane node={activeNode} planId={planId} calculationId={calculationId} onContentChange={handleContentChange} />}
              </div>
            </div>
          ) : activeTab === 'tables' ? (
            <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
              {calculationId && <TableEditor calculationId={calculationId} />}
            </div>
          ) : activeTab === 'charts' ? (
            <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
              {planId && <ChartEditor planId={planId} />}
            </div>
          ) : (
            <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
              {planId && <MapPreview planId={planId} calculationId={calculationId} />}
            </div>
          )}
        </>
      ) : (
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          <div style={{ width: 280, borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '12px 14px', borderBottom: '1px solid #f0f0f0', fontWeight: 600, fontSize: 13 }}>
              <FileTextOutlined style={{ marginRight: 6 }} />{t('operationalPlan.page.contents')}
            </div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <DocumentOutline
                tree={tree}
                activeNodeId={activeNodeId}
                onSelectNode={setActiveNodeId}
              />
            </div>
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: '32px 48px' }}>
            {activeNode ? (
              <div style={{ maxWidth: 720 }}>
                {activeNode.number && (
                  <div style={{ color: '#1677ff', fontSize: 12, fontWeight: 500, marginBottom: 4, letterSpacing: '0.5px' }}>
                    {t('operationalPlan.page.sectionNumber', { number: activeNode.number })}
                  </div>
                )}
                <h2 style={{ margin: '0 0 4px 0', fontSize: 22, fontWeight: 700, color: '#1a1a1a' }}>
                  {(isNe ? activeNode.title_ne : activeNode.title_en)
                    || activeNode.title_ne || activeNode.title_en}
                </h2>
                {activeNode.title_ne && activeNode.title_en && activeNode.title_en !== activeNode.title_ne && (
                  <div style={{ fontSize: 13, color: '#888', marginBottom: 16 }}>
                    {isNe ? activeNode.title_en : activeNode.title_ne}
                  </div>
                )}
                <hr style={{ border: 'none', borderTop: '2px solid #e8e8e8', margin: '16px 0' }} />
                {activeNode.content_type === 'richtext' && (
                  <div style={{
                    fontSize: 15, lineHeight: 1.8, color: '#333',
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  }}>
                    {activeNode.content || <span style={{ color: '#bbb', fontStyle: 'italic' }}>{t('operationalPlan.page.noContent')}</span>}
                  </div>
                )}
                {activeNode.content_type === 'chart' && (
                  <div style={{ textAlign: 'center', padding: 40, background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                    <PieChartOutlined style={{ fontSize: 32, color: '#1677ff' }} />
                    <div style={{ marginTop: 8, color: '#666' }}>{t('operationalPlan.page.chartPlaceholder')}</div>
                  </div>
                )}
                {activeNode.content_type === 'map' && (
                  <div style={{ textAlign: 'center', padding: 40, background: '#fafafa', borderRadius: 8, border: '1px solid #f0f0f0' }}>
                    <EnvironmentOutlined style={{ fontSize: 32, color: '#52c41a' }} />
                    <div style={{ marginTop: 8, color: '#666' }}>{t('operationalPlan.page.mapPlaceholder')}</div>
                  </div>
                )}
                {activeNode.content_type === 'static_table' && activeNode.static_table && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                    <thead>
                      <tr>
                        {activeNode.static_table.columns.map((col: string, i: number) => (
                          <th key={i} style={{ border: '1px solid #d9d9d9', padding: '8px 12px', background: '#fafafa', fontWeight: 600, textAlign: 'left' }}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {activeNode.static_table.rows.map((row: string[], ri: number) => (
                        <tr key={ri}>
                          {row.map((cell: string, ci: number) => (
                            <td key={ci} style={{ border: '1px solid #d9d9d9', padding: '6px 12px' }}>{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <div style={{ marginTop: 40, paddingTop: 24, borderTop: '2px solid #e8e8e8', fontSize: 12, color: '#999' }}>
                  {t('operationalPlan.page.lastUpdated', {
                    when: plan?.updated_at ? formatDateTime(plan.updated_at) : t('common.notAvailable'),
                  })}
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 80, color: '#bbb' }}>
                <FileTextOutlined style={{ fontSize: 48, display: 'block', marginBottom: 16 }} />
                <span style={{ fontSize: 16 }}>{t('operationalPlan.page.selectSection')}</span>
              </div>
            )}
            {plan?.plan_metadata?.custom_notes && (
              <div style={{ maxWidth: 720, marginTop: 32, padding: 20, background: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 8 }}>
                <h4 style={{ margin: '0 0 8px 0', fontSize: 14, fontWeight: 600, color: '#ad6800' }}>{t('operationalPlan.page.customNotes')}</h4>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.6, color: '#666' }}>
                  {plan.plan_metadata.custom_notes}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {planId && (
        <MetadataForm
          planId={planId}
          visible={showMetadata}
          onClose={() => setShowMetadata(false)}
        />
      )}

      <GuideModal
        visible={showGuide}
        onClose={() => setShowGuide(false)}
        initialGuide="op-generation"
      />
    </div>
  );
};

export default OperationalPlanPage;