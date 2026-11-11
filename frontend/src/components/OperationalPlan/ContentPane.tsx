/** Main content editing pane for the operational plan document — supports rich text, variables, tables, and inline editing. */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Input, Button, message, Tag, Spin, Tooltip, Alert, InputNumber, Segmented } from 'antd';
import { SaveOutlined, CodeOutlined, EyeOutlined, EditOutlined, WarningOutlined, PlusOutlined, MinusOutlined, DeleteOutlined, ColumnHeightOutlined, ColumnWidthOutlined, TableOutlined } from '@ant-design/icons';
import { operationalPlanApi } from '../../services/api';
import { useCanDesignTemplates } from '../calculation/HazardVarChip';
import VariablePicker from './VariablePicker';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';
import { guardedDelete, brokenTokens } from '../../lib/tokenGuard';

interface MergeEntry {
  row: number;
  col: number;
  rowspan: number;
  colspan: number;
}

interface InlineTableData {
  caption?: string;
  columns: string[];
  rows: string[][];
  merges?: MergeEntry[];
}

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
  static_table?: { columns: string[]; rows: string[][]; merges?: MergeEntry[] } | null;
  inline_tables?: InlineTableData[] | null;
  children: TreeNodeData[];
  is_locked: boolean;
  hidden_in_export: boolean;
  deleted: boolean;
  last_modified?: string | null;
}

interface ContentPaneProps {
  node: TreeNodeData | null;
  planId: string;
  calculationId?: string;
  onContentChange?: (nodeId: string, content: string, updates?: Record<string, any>) => void;
  /** Template designer: no plan is bound, so preview renders the template's
   *  section against a chosen forest via the transient endpoint (T2). */
  templatePreview?: { templateId: string; calculationId?: string };
}

// Module scope, so the label is an i18n key resolved at render (rule 4).
const typeLabelKeys: Record<string, string> = {
  preamble: 'operationalPlan.content.preamble',
  toc: 'operationalPlan.content.toc',
  section: 'operationalPlan.content.section',
  subsection: 'operationalPlan.content.subsection',
  appendix: 'operationalPlan.content.appendix',
};

// node.content_type is a closed set, keyed statically so the scanner sees it.
const contentTypeKeys: Record<string, string> = {
  richtext: 'operationalPlan.content.ctRichtext',
  chart: 'operationalPlan.content.ctChart',
  table: 'operationalPlan.content.ctTable',
  map: 'operationalPlan.content.ctMap',
  static_table: 'operationalPlan.content.ctStaticTable',
};

const ContentPane: React.FC<ContentPaneProps> = ({ node, planId, calculationId, onContentChange, templatePreview }) => {
  const t = useT();
  // Nodes carry a title_ne/title_en pair; show the active language first.
  const isNe = i18n.language === 'ne';
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  // 'values' resolves {{tokens}}; 'tokens' keeps them verbatim (designers only).
  const [previewMode, setPreviewMode] = useState<'values' | 'tokens'>('values');
  const canDesign = useCanDesignTemplates();
  const [previewHtml, setPreviewHtml] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [tableColumns, setTableColumns] = useState<string[]>([]);
  const [tableRows, setTableRows] = useState<string[][]>([]);
  const [merges, setMerges] = useState<MergeEntry[]>([]);
  const [activeCell, setActiveCell] = useState<{ row: number; col: number } | null>(null);
  const [selectionStart, setSelectionStart] = useState<{ row: number; col: number } | null>(null);
  const [selectionEnd, setSelectionEnd] = useState<{ row: number; col: number } | null>(null);
  const tableColsRef = useRef(tableColumns);
  const tableRowsRef = useRef(tableRows);
  const mergesRef = useRef(merges);
  tableColsRef.current = tableColumns;
  tableRowsRef.current = tableRows;
  mergesRef.current = merges;

  const [inlineTables, setInlineTables] = useState<InlineTableData[]>([]);
  const [activeTableIndex, setActiveTableIndex] = useState<number | null>(null);
  const [inlineActiveCell, setInlineActiveCell] = useState<{ tableIndex: number; row: number; col: number } | null>(null);
  const inlineTablesRef = useRef(inlineTables);
  inlineTablesRef.current = inlineTables;

  const isCellMerged = useCallback((ri: number, ci: number): { master: boolean; entry?: MergeEntry } => {
    for (const m of merges) {
      if (ri >= m.row && ri < m.row + m.rowspan && ci >= m.col && ci < m.col + m.colspan) {
        return { master: ri === m.row && ci === m.col, entry: m };
      }
    }
    return { master: true };
  }, [merges]);

  const isInMergeRange = useCallback((ri: number, ci: number): boolean => {
    for (const m of merges) {
      if (ri >= m.row && ri < m.row + m.rowspan && ci >= m.col && ci < m.col + m.colspan) {
        return true;
      }
    }
    return false;
  }, [merges]);

  const rangesOverlap = (r1: number, c1: number, rs1: number, cs1: number,
                          r2: number, c2: number, rs2: number, cs2: number): boolean => {
    return !(r1 + rs1 <= r2 || r2 + rs2 <= r1 || c1 + cs1 <= c2 || c2 + cs2 <= c1);
  };

  const tmplCalcId = templatePreview?.calculationId;
  const canPreview = !!planId || !!tmplCalcId;

  const fetchPreview = useCallback(async (m: 'values' | 'tokens' = previewMode) => {
    if (!node) return;
    if (!planId && !(templatePreview?.templateId && tmplCalcId)) {
      // designer with no forest chosen yet
      setPreviewHtml(
        `<div style="padding:24px;color:#999;font-style:italic">${t('templates.designer.pickForestToPreview')}</div>`,
      );
      return;
    }
    setPreviewLoading(true);
    try {
      const html = planId
        ? await operationalPlanApi.previewOperationalPlanSection(planId, node.id, m)
        : await operationalPlanApi.previewTemplateWithForest(
            templatePreview!.templateId, tmplCalcId!, m, node.id,
          );
      setPreviewHtml(html);
    } catch {
      setPreviewHtml(`<div style="padding:24px;color:red">${t('operationalPlan.content.previewFailed')}</div>`);
    } finally {
      setPreviewLoading(false);
    }
  }, [node?.id, planId, previewMode, templatePreview?.templateId, tmplCalcId]);

  // Single source of truth for (re)loading the preview: whenever preview is the
  // active mode and any input changes (section, forest, values/tokens).
  useEffect(() => {
    if (mode === 'preview') fetchPreview(previewMode);
  }, [mode, previewMode, fetchPreview]);

  useEffect(() => {
    setContent(node?.content || '');
    if (node?.content_type === 'static_table' && node?.static_table) {
      setTableColumns(node.static_table.columns || ['Column 1']);
      setTableRows(node.static_table.rows || [['']]);
      setMerges(node.static_table.merges || []);
      setInlineTables([]);
      setActiveTableIndex(null);
    } else if (node?.content_type === 'richtext' && node?.inline_tables && node.inline_tables.length > 0) {
      setInlineTables(node.inline_tables);
      setActiveTableIndex(0);
      setTableColumns(['Column 1']);
      setTableRows([['']]);
      setMerges([]);
    } else {
      setInlineTables([]);
      setActiveTableIndex(null);
      setTableColumns(['Column 1', 'Column 2', 'Column 3']);
      setTableRows([['', '', ''], ['', '', ''], ['', '', '']]);
      setMerges([]);
    }
    setActiveCell(null);
    setInlineActiveCell(null);
    setSelectionStart(null);
    setSelectionEnd(null);
    setDirty(false);
    setMode('edit');
    setPreviewHtml('');
  }, [node?.id]);

  const propagateToParent = (content?: string, extra?: Record<string, any>) => {
    if (!planId && onContentChange && node) {
      onContentChange(node.id, content ?? '', extra);
    }
  };

  useEffect(() => {
    if (!dirty || planId) return;
    if (node?.content_type === 'static_table') {
      propagateToParent('', {
        static_table: {
          columns: tableColsRef.current,
          rows: tableRowsRef.current,
          merges: mergesRef.current,
        }
      });
    } else if (node?.content_type === 'richtext' && inlineTablesRef.current.length > 0) {
      propagateToParent(content, {
        inline_tables: inlineTablesRef.current,
      });
    } else {
      propagateToParent(content);
    }
  }, [content, tableColumns, tableRows, merges, inlineTables]);

  const handleSave = useCallback(async () => {
    if (!node || !planId || !dirty) return;
    setSaving(true);
    try {
      if (node.content_type === 'static_table') {
        const staticTableData = { static_table: { columns: tableColumns, rows: tableRows, merges } };
        await operationalPlanApi.updateNode(planId, node.id, staticTableData);
        setDirty(false);
        onContentChange?.(node.id, '', staticTableData);
      } else if (node.content_type === 'richtext' && inlineTablesRef.current.length > 0) {
        const payload = {
          content,
          inline_tables: inlineTablesRef.current,
        };
        await operationalPlanApi.updateNode(planId, node.id, payload);
        setDirty(false);
        onContentChange?.(node.id, content, { inline_tables: inlineTablesRef.current });
      } else {
        await operationalPlanApi.updateNode(planId, node.id, { content });
        setDirty(false);
        onContentChange?.(node.id, content);
      }
    } catch {
      message.error(t('operationalPlan.content.saveFailed'));
    } finally {
      setSaving(false);
    }
  }, [node, planId, content, dirty, onContentChange, tableColumns, tableRows, merges]);

  useEffect(() => {
    if (!dirty) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(handleSave, 2000);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [content, dirty, handleSave]);

  const handleChange = (val: string) => {
    setContent(val);
    setDirty(true);
  };

  const handleTableHeaderChange = (colIndex: number, val: string) => {
    setTableColumns(prev => { const c = [...prev]; c[colIndex] = val; return c; });
    setDirty(true);
  };

  const handleTableCellChange = (rowIndex: number, colIndex: number, val: string) => {
    const { master, entry } = isCellMerged(rowIndex, colIndex);
    if (!master && entry) {
      setTableRows(prev => {
        const r = prev.map(row => [...row]);
        r[entry.row][entry.col] = val;
        return r;
      });
    } else {
      setTableRows(prev => {
        const r = prev.map(row => [...row]);
        r[rowIndex][colIndex] = val;
        return r;
      });
    }
    setDirty(true);
  };

  const handleCellClick = (ri: number, ci: number, shiftKey: boolean) => {
    const { master, entry } = isCellMerged(ri, ci);
    const targetRow = master && entry ? entry.row : ri;
    const targetCol = master && entry ? entry.col : ci;
    setActiveCell({ row: targetRow, col: targetCol });
    if (shiftKey && selectionStart) {
      setSelectionEnd({ row: targetRow, col: targetCol });
    } else {
      setSelectionStart({ row: targetRow, col: targetCol });
      setSelectionEnd({ row: targetRow, col: targetCol });
    }
  };

  const getMergeRect = () => {
    if (!selectionStart || !selectionEnd) return null;
    const topRow = Math.min(selectionStart.row, selectionEnd.row);
    const bottomRow = Math.max(selectionStart.row, selectionEnd.row);
    const leftCol = Math.min(selectionStart.col, selectionEnd.col);
    const rightCol = Math.max(selectionStart.col, selectionEnd.col);
    return { row: topRow, col: leftCol, rowspan: bottomRow - topRow + 1, colspan: rightCol - leftCol + 1 };
  };

  const isCellSelected = (ri: number, ci: number): boolean => {
    if (!selectionStart || !selectionEnd) return false;
    const topRow = Math.min(selectionStart.row, selectionEnd.row);
    const bottomRow = Math.max(selectionStart.row, selectionEnd.row);
    const leftCol = Math.min(selectionStart.col, selectionEnd.col);
    const rightCol = Math.max(selectionStart.col, selectionEnd.col);
    return ri >= topRow && ri <= bottomRow && ci >= leftCol && ci <= rightCol;
  };

  const handleMerge = () => {
    const rect = getMergeRect();
    if (!rect) {
      message.warning(t('operationalPlan.content.msgSelectCells'));
      return;
    }
    if (rect.rowspan === 1 && rect.colspan === 1) {
      message.warning(t('operationalPlan.content.msgSelectTwo'));
      return;
    }
    for (const m of merges) {
      if (rangesOverlap(rect.row, rect.col, rect.rowspan, rect.colspan, m.row, m.col, m.rowspan, m.colspan)) {
        message.warning(t('operationalPlan.content.msgOverlap'));
        return;
      }
    }
    setMerges(prev => [...prev, rect]);
    setDirty(true);
    message.success(`Merged ${rect.rowspan}×${rect.colspan} cells`);
  };

  const handleUnmerge = () => {
    if (!activeCell) {
      message.warning(t('operationalPlan.content.msgClickMerged'));
      return;
    }
    const { master, entry } = isCellMerged(activeCell.row, activeCell.col);
    if (!entry) {
      message.warning(t('operationalPlan.content.msgNotMerged'));
      return;
    }
    const masterValue = tableRows[entry.row]?.[entry.col] || '';
    setTableRows(prev => {
      const r = prev.map(row => [...row]);
      for (let ri = entry.row; ri < entry.row + entry.rowspan; ri++) {
        for (let ci = entry.col; ci < entry.col + entry.colspan; ci++) {
          r[ri][ci] = masterValue;
        }
      }
      return r;
    });
    setMerges(prev => prev.filter(m => m !== entry));
    setDirty(true);
    message.success(t('operationalPlan.content.msgUnmerged'));
  };

  const adjustMergesOnRowRemove = (rowIndex: number) => {
    setMerges(prev => {
      const updated: MergeEntry[] = [];
      for (const m of prev) {
        const mc = { ...m };
        if (mc.row === rowIndex || (mc.row < rowIndex && rowIndex < mc.row + mc.rowspan)) {
          mc.rowspan -= 1;
        } else if (mc.row > rowIndex) {
          mc.row -= 1;
        }
        if (mc.rowspan >= 1) updated.push(mc);
      }
      return updated;
    });
  };

  const adjustMergesOnColRemove = (colIndex: number) => {
    setMerges(prev => {
      const updated: MergeEntry[] = [];
      for (const m of prev) {
        const mc = { ...m };
        if (mc.col === colIndex || (mc.col < colIndex && colIndex < mc.col + mc.colspan)) {
          mc.colspan -= 1;
        } else if (mc.col > colIndex) {
          mc.col -= 1;
        }
        if (mc.colspan >= 1) updated.push(mc);
      }
      return updated;
    });
  };

  const addColumn = () => {
    setTableColumns(prev => [...prev, `Column ${prev.length + 1}`]);
    setTableRows(prev => prev.map(row => [...row, '']));
    setDirty(true);
  };

  const removeColumn = (colIndex: number) => {
    if (tableColumns.length <= 1) return;
    setTableColumns(prev => prev.filter((_, i) => i !== colIndex));
    setTableRows(prev => prev.map(row => row.filter((_, i) => i !== colIndex)));
    adjustMergesOnColRemove(colIndex);
    setDirty(true);
  };

  const addRow = () => {
    setTableRows(prev => [...prev, tableColumns.map(() => '')]);
    setDirty(true);
  };

  const removeRow = (rowIndex: number) => {
    if (tableRows.length <= 1) return;
    setTableRows(prev => prev.filter((_, i) => i !== rowIndex));
    adjustMergesOnRowRemove(rowIndex);
    setDirty(true);
  };

  // --- Inline table helpers ---

  const updateInlineTable = (index: number, updater: (table: InlineTableData) => InlineTableData) => {
    setInlineTables(prev => {
      const next = [...prev];
      next[index] = updater(next[index]);
      return next;
    });
    setDirty(true);
  };

  const addInlineRow = (ti: number) => {
    updateInlineTable(ti, t => ({ ...t, rows: [...t.rows, t.columns.map(() => '')] }));
  };

  const addInlineColumn = (ti: number) => {
    updateInlineTable(ti, t => ({
      ...t,
      columns: [...t.columns, `Column ${t.columns.length + 1}`],
      rows: t.rows.map(row => [...row, '']),
    }));
  };

  const removeInlineRow = (ti: number, rowIndex: number) => {
    updateInlineTable(ti, t => {
      if (t.rows.length <= 1) return t;
      return { ...t, rows: t.rows.filter((_, i) => i !== rowIndex) };
    });
  };

  const removeInlineColumn = (ti: number, colIndex: number) => {
    updateInlineTable(ti, t => {
      if (t.columns.length <= 1) return t;
      return {
        ...t,
        columns: t.columns.filter((_, i) => i !== colIndex),
        rows: t.rows.map(row => row.filter((_, i) => i !== colIndex)),
      };
    });
  };

  const handleInlineCellChange = (ti: number, ri: number, ci: number, val: string) => {
    updateInlineTable(ti, t => {
      const rows = t.rows.map(row => [...row]);
      rows[ri][ci] = val;
      return { ...t, rows };
    });
  };

  const handleInlineHeaderChange = (ti: number, ci: number, val: string) => {
    updateInlineTable(ti, t => {
      const columns = [...t.columns];
      columns[ci] = val;
      return { ...t, columns };
    });
  };

  const handleInlineCaptionChange = (ti: number, val: string) => {
    updateInlineTable(ti, t => ({ ...t, caption: val }));
  };

  const removeInlineTable = async (tableIndex: number) => {
    if (!planId || !node) return;
    const updated = inlineTables.filter((_, i) => i !== tableIndex);
    try {
      await operationalPlanApi.updateNode(planId, node.id, { inline_tables: updated.length > 0 ? updated : null });
      setInlineTables(updated);
      setActiveTableIndex(updated.length > 0 ? 0 : null);
      onContentChange?.(node.id, content, { inline_tables: updated.length > 0 ? updated : null });
      message.success(t('operationalPlan.content.msgTableRemoved'));
    } catch {
      message.error(t('operationalPlan.content.removeTableFailed'));
    }
  };

  const handleVariableSelect = (varKey: string) => {
    if (node?.content_type === 'static_table') {
      if (!activeCell) {
        message.warning(t('operationalPlan.content.msgClickCellFirst'));
        return;
      }
      const targetRow = activeCell.row;
      const targetCol = activeCell.col;
      setTableRows(prev => {
        const r = prev.map(row => [...row]);
        r[targetRow][targetCol] = `{{${varKey}}}`;
        return r;
      });
      setDirty(true);
    } else if (node?.content_type === 'richtext' && inlineActiveCell) {
      const ti = inlineActiveCell.tableIndex;
      const { row, col } = inlineActiveCell;
      setInlineTables(prev => {
        const next = [...prev];
        const rows = next[ti].rows.map(r => [...r]);
        rows[row][col] = `{{${varKey}}}`;
        next[ti] = { ...next[ti], rows };
        return next;
      });
      setDirty(true);
    } else {
      const ta = textareaRef.current;
      if (!ta) return;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const before = content.substring(0, start);
      const after = content.substring(end);
      const newContent = `${before}{{${varKey}}}${after}`;
      handleChange(newContent);
      setTimeout(() => {
        ta.selectionStart = ta.selectionEnd = start + varKey.length + 4;
        ta.focus();
      }, 0);
    }
  };

  const renderTableCells = (ri: number, row: string[]) => {
    const cells: React.ReactNode[] = [];
    for (let ci = 0; ci < row.length; ci++) {
      const { master, entry } = isCellMerged(ri, ci);
      if (!master) continue;
      const visualRow = entry ? entry.row : ri;
      const visualCol = entry ? entry.col : ci;
      const isActive = activeCell?.row === visualRow && activeCell?.col === visualCol;
      const isSelected = isCellSelected(ri, ci);
      const rs = entry?.rowspan || 1;
      const cs = entry?.colspan || 1;
      const value = tableRows[visualRow]?.[visualCol] || '';
      cells.push(
        <td
          key={ci}
          rowSpan={rs}
          colSpan={cs}
          style={{
            border: '1px solid #d9d9d9',
            padding: 4,
            background: isSelected ? '#d6e4ff' : isActive ? '#e6f7ff' : undefined,
            verticalAlign: 'top',
          }}
        >
          <input
            value={value}
            onChange={e => handleTableCellChange(visualRow, visualCol, e.target.value)}
            onFocus={() => {
              setActiveCell({ row: visualRow, col: visualCol });
            }}
            onMouseDown={(e) => {
              e.stopPropagation();
              handleCellClick(visualRow, visualCol, e.shiftKey);
            }}
            onClick={(e) => {
              e.stopPropagation();
            }}
            style={{ width: '100%', border: 'none', outline: 'none', fontSize: 13, background: 'transparent' }}
          />
        </td>
      );
    }
    return cells;
  };

  if (!node) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#999' }}>
        {t('operationalPlan.content.selectSection')}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #f0f0f0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <Tag color="blue">{typeLabelKeys[node.type] ? t(typeLabelKeys[node.type]) : node.type}</Tag>
              {node.content_type !== 'richtext' && (
                <Tag color="geekblue">
                  {node.content_type && contentTypeKeys[node.content_type]
                    ? t(contentTypeKeys[node.content_type])
                    : node.content_type}
                </Tag>
              )}
              {node.hidden_in_export && <Tag color="orange">{t('operationalPlan.content.hidden')}</Tag>}
              {dirty && <Tag color="red">{t('operationalPlan.content.unsaved')}</Tag>}
            </div>
            <div style={{ fontWeight: 600, fontSize: 16 }}>
              {node.number ? `${node.number}. ` : ''}
              {(isNe ? node.title_ne : node.title_en) || node.title_ne || node.title_en}
            </div>
            <div style={{ fontSize: 12, color: '#999' }}>
              {isNe ? node.title_en : node.title_ne}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <Button
              size="small"
              type={mode === 'edit' ? 'primary' : 'default'}
              icon={<EditOutlined />}
              onClick={() => setMode('edit')}
            >
              {t('operationalPlan.content.edit')}
            </Button>
            <Button
              size="small"
              type={mode === 'preview' ? 'primary' : 'default'}
              icon={<EyeOutlined />}
              onClick={() => setMode('preview')}
              disabled={!node?.content && !['chart', 'table', 'map', 'static_table'].includes(node?.content_type || '')}
            >
              {t('operationalPlan.content.preview')}
            </Button>
            {mode === 'preview' && canDesign && (
              <Segmented
                size="small"
                value={previewMode}
                onChange={(v) => setPreviewMode(v as 'values' | 'tokens')}
                options={[
                  { label: t('operationalPlan.render.values'), value: 'values' },
                  { label: t('operationalPlan.render.tokens'), value: 'tokens' },
                ]}
              />
            )}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <Tooltip title={node?.content_type === 'static_table'
              ? t('operationalPlan.content.tipCellVariable')
              : t('operationalPlan.content.tipInsertVariable')}>
              <Button
                icon={<CodeOutlined />}
                size="small"
                onClick={() => setShowPicker(!showPicker)}
                type={showPicker ? 'primary' : 'default'}
              >
                {node?.content_type === 'static_table'
                  ? t('operationalPlan.content.cellVariables')
                  : t('operationalPlan.content.variables')}
              </Button>
            </Tooltip>
            <Button
              icon={<SaveOutlined />}
              size="small"
              onClick={handleSave}
              loading={saving}
              disabled={!dirty}
            >
              {saving ? t('common.saving') : t('common.save')}
            </Button>
          </div>
        </div>
      </div>

      {node.deleted && (
        <Alert
          message={t('operationalPlan.content.deletedNotice')}
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ margin: '8px 16px', borderRadius: 6 }}
        />
      )}

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {mode === 'preview' ? (
            <div style={{ flex: 1, overflow: 'auto', background: '#f5f5f5' }}>
              {previewLoading ? (
                <div style={{ textAlign: 'center', paddingTop: 80 }}>
                  <Spin size="large" />
                  <div style={{ marginTop: 12 }}>{t('operationalPlan.content.loadingPreview')}</div>
                </div>
              ) : (
                <iframe
                  srcDoc={previewHtml}
                  style={{ width: '100%', height: '100%', border: 'none', background: 'white' }}
                  title={t('operationalPlan.content.sectionPreview')}
                />
              )}
            </div>
          ) : node.content_type === 'richtext' ? (
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
              <textarea
                ref={textareaRef}
                value={content}
                onChange={e => handleChange(e.target.value)}
                onKeyDown={e => {
                  if (e.key !== 'Backspace' && e.key !== 'Delete') return;
                  const ta = e.currentTarget;
                  const r = guardedDelete(ta.value, ta.selectionStart, ta.selectionEnd, e.key);
                  if (!r) return;
                  e.preventDefault();
                  handleChange(r.text);
                  requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = r.caret; });
                }}
                style={{
                  flex: inlineTables.length > 0 ? '0 0 35%' : 1,
                  border: 'none',
                  outline: 'none',
                  padding: 16,
                  fontSize: 14,
                  lineHeight: 1.7,
                  resize: 'none',
                  fontFamily: "'Noto Sans', 'Segoe UI', sans-serif",
                  width: '100%',
                  borderBottom: inlineTables.length > 0 ? '1px solid #f0f0f0' : 'none',
                }}
                placeholder={t('operationalPlan.content.phContent', { code: '{{variable_name}}' })}
              />
              {brokenTokens(content).length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ margin: '0 16px 4px' }}
                  data-testid="op-broken-token"
                  message={t('operationalPlan.content.brokenToken', { token: brokenTokens(content)[0], code: '{{variable_name}}' })}
                />
              )}
              <div style={{ padding: '4px 16px', borderTop: '1px solid #f0f0f0', display: 'flex', gap: 8, alignItems: 'center', background: '#fafafa' }}>
                <Tooltip title={t('operationalPlan.content.tipAddTable')}>
                  <Button
                    size="small"
                    icon={<TableOutlined />}
                    onClick={() => {
                      const newTable: InlineTableData = {
                        caption: '',
                        columns: ['Column 1', 'Column 2', 'Column 3'],
                        rows: [['', '', ''], ['', '', ''], ['', '', '']],
                        merges: [],
                      };
                      setInlineTables(prev => [...prev, newTable]);
                      setActiveTableIndex(inlineTables.length);
                      setDirty(true);
                    }}
                    style={{ borderColor: '#722ed1', color: '#722ed1' }}
                  >
                    {t('operationalPlan.content.addTable')}
                  </Button>
                </Tooltip>
                {inlineTables.length > 0 && (
                  <span style={{ fontSize: 11, color: '#999' }}>
                    {t('operationalPlan.content.tablesInSection', { n: formatNumber(inlineTables.length) })}
                  </span>
                )}
              </div>
              {inlineTables.length > 0 && (
                <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                  {inlineTables.map((table, ti) => (
                    <div key={ti} style={{
                      marginBottom: 16,
                      border: activeTableIndex === ti ? '2px solid #1677ff' : '1px solid #d9d9d9',
                      borderRadius: 6,
                      padding: 12,
                      background: activeTableIndex === ti ? '#f6ffed' : '#fff',
                    }}
                    onClick={() => setActiveTableIndex(ti)}
                    >
                      <div style={{ marginBottom: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <Input
                          size="small"
                          value={table.caption || ''}
                          onChange={e => handleInlineCaptionChange(ti, e.target.value)}
                          placeholder={t('operationalPlan.content.phCaption', { n: formatNumber(ti + 1) })}
                          style={{ width: 260, fontWeight: 600 }}
                          onClick={e => e.stopPropagation()}
                        />
                        <span style={{ width: 1, height: 20, background: '#d9d9d9', margin: '0 4px' }} />
                        <Button size="small" icon={<PlusOutlined />} onClick={(e) => { e.stopPropagation(); addInlineRow(ti); }}>{t('operationalPlan.content.row')}</Button>
                        <Button size="small" icon={<PlusOutlined />} onClick={(e) => { e.stopPropagation(); addInlineColumn(ti); }}>{t('operationalPlan.content.col')}</Button>
                        <div style={{ flex: 1 }} />
                        {inlineActiveCell?.tableIndex === ti && (
                          <span style={{ fontSize: 11, color: '#1890ff', background: '#e6f7ff', padding: '2px 6px', borderRadius: 4 }}>
                            {t('operationalPlan.content.cellRef', {
                              row: formatNumber(inlineActiveCell.row + 1),
                              col: formatNumber(inlineActiveCell.col + 1),
                            })}
                          </span>
                        )}
                        <Tooltip title={t('operationalPlan.content.tipRemoveTable')}>
                          <Button size="small" danger icon={<DeleteOutlined />} onClick={(e) => { e.stopPropagation(); removeInlineTable(ti); }}>
                            {t('operationalPlan.content.remove')}
                          </Button>
                        </Tooltip>
                      </div>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                        <thead>
                          <tr>
                            {table.columns.map((col, ci) => (
                              <th key={ci} style={{ border: '1px solid #d9d9d9', padding: 4, background: '#fafafa', position: 'relative' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                  <input
                                    value={col}
                                    onChange={e => handleInlineHeaderChange(ti, ci, e.target.value)}
                                    onClick={e => e.stopPropagation()}
                                    style={{ flex: 1, border: 'none', outline: 'none', background: 'transparent', fontWeight: 600, textAlign: 'center', fontSize: 13 }}
                                  />
                                  <DeleteOutlined
                                    style={{ color: '#ff4d4f', fontSize: 11, cursor: table.columns.length > 1 ? 'pointer' : 'not-allowed', opacity: table.columns.length > 1 ? 1 : 0.3 }}
                                    onClick={(e) => { e.stopPropagation(); removeInlineColumn(ti, ci); }}
                                  />
                                </div>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {table.rows.map((row, ri) => (
                            <tr key={ri}>
                              <td style={{ textAlign: 'center', verticalAlign: 'top', paddingTop: 8, border: '1px solid #d9d9d9', width: 30 }}>
                                <DeleteOutlined
                                  style={{ color: '#ff4d4f', fontSize: 11, cursor: table.rows.length > 1 ? 'pointer' : 'not-allowed', opacity: table.rows.length > 1 ? 1 : 0.3 }}
                                  onClick={(e) => { e.stopPropagation(); removeInlineRow(ti, ri); }}
                                />
                              </td>
                              {row.map((cellVal, ci) => (
                                <td key={ci} style={{
                                  border: '1px solid #d9d9d9',
                                  padding: 2,
                                  background: inlineActiveCell?.tableIndex === ti && inlineActiveCell.row === ri && inlineActiveCell.col === ci ? '#e6f7ff' : undefined,
                                }}>
                                  <input
                                    value={cellVal}
                                    onChange={e => handleInlineCellChange(ti, ri, ci, e.target.value)}
                                    onFocus={() => setInlineActiveCell({ tableIndex: ti, row: ri, col: ci })}
                                    onClick={e => e.stopPropagation()}
                                    style={{ width: '100%', border: 'none', outline: 'none', fontSize: 13, background: 'transparent', padding: '2px 4px' }}
                                  />
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                  <div style={{ marginTop: 4, color: '#999', fontSize: 11 }}>
                    {t('operationalPlan.content.variableHintRichtext', { code: '{{variable_name}}', button: t('operationalPlan.content.addTable') })}
                  </div>
                </div>
              )}
            </div>
          ) : node.content_type === 'chart' ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{node.chart_type || node.title_en}</div>
              <div style={{ background: '#f9f9f9', borderRadius: 8, padding: 16, display: 'inline-block', textAlign: 'left', minWidth: 300 }}>
                <div style={{ marginBottom: 8 }}><strong>{t('operationalPlan.content.chartType')}</strong> {node.chart_type}</div>
                <div style={{ marginBottom: 8 }}><strong>{t('operationalPlan.content.source')}</strong> {
                  {species_pie: t('operationalPlan.content.srcSpecies'), forest_type_pie: t('operationalPlan.content.srcRaster'), block_area_bar: t('operationalPlan.content.srcBlockAreas'),
                   dbh_histogram: t('operationalPlan.content.srcInventory'), biomass_bar: t('operationalPlan.content.srcBiomass'), slope_pie: t('operationalPlan.content.srcSlope'),
                   canopy_pie: t('operationalPlan.content.srcCanopy'), landcover_pie: t('operationalPlan.content.srcLandcover')
                  }[node.chart_type || ''] || t('operationalPlan.content.srcSystem')
                }</div>
                <div style={{ color: '#999', fontSize: 12 }}>{t('operationalPlan.content.renderedPng')}</div>
                <div style={{ color: '#999', fontSize: 12 }}>{t('operationalPlan.content.livePreviewSoon')}</div>
              </div>
            </div>
          ) : node.content_type === 'table' ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>📋</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{node.table_id || node.title_en}</div>
              <div style={{ background: '#f9f9f9', borderRadius: 8, padding: 16, display: 'inline-block', textAlign: 'left', minWidth: 300 }}>
                <div style={{ marginBottom: 8 }}><strong>{t('operationalPlan.content.tableId')}</strong> {node.table_id}</div>
                <div style={{ color: '#999', fontSize: 12 }}>{t('operationalPlan.content.editInTablesTab')}</div>
              </div>
            </div>
          ) : node.content_type === 'map' ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>🗺️</div>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{(isNe ? node.title_ne : node.title_en) || t('operationalPlan.content.boundaryMapTitle')}</div>
              <div style={{ background: '#f9f9f9', borderRadius: 8, padding: 16, display: 'inline-block', textAlign: 'left', minWidth: 300 }}>
                <div style={{ marginBottom: 8 }}><strong>{t('operationalPlan.content.type')}</strong> {t('operationalPlan.content.boundaryMap')}</div>
                <div style={{ marginBottom: 8 }}><strong>{t('operationalPlan.content.source')}</strong> {t('operationalPlan.content.srcBoundaryGeometry')}</div>
                <div style={{ color: '#999', fontSize: 12 }}>{t('operationalPlan.content.previewInMapsTab')}</div>
                <div style={{ color: '#999', fontSize: 12 }}>{t('operationalPlan.content.renderedPng')}</div>
              </div>
            </div>
          ) : node.content_type === 'static_table' ? (
            <div style={{ padding: 16, overflow: 'auto', flex: 1 }}>
              <div style={{ marginBottom: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Button size="small" icon={<PlusOutlined />} onClick={addRow}>{t('operationalPlan.content.addRow')}</Button>
                <Button size="small" icon={<PlusOutlined />} onClick={addColumn}>{t('operationalPlan.content.addColumn')}</Button>
                <span style={{ width: 1, height: 20, background: '#d9d9d9', margin: '0 4px' }} />
                <Button size="small" icon={<ColumnWidthOutlined />} onClick={handleMerge}>{t('operationalPlan.content.mergeCells')}</Button>
                <Button size="small" icon={<ColumnHeightOutlined />} onClick={handleUnmerge}>{t('operationalPlan.content.unmerge')}</Button>
                <div style={{ flex: 1 }} />
                {activeCell && (
                  <span style={{ fontSize: 12, color: '#1890ff', background: '#e6f7ff', padding: '2px 8px', borderRadius: 4 }}>
                    {t('operationalPlan.content.cellRef', {
                      row: formatNumber(activeCell.row + 1),
                      col: formatNumber(activeCell.col + 1),
                    })}
                    {(() => {
                      const { entry } = isCellMerged(activeCell.row, activeCell.col);
                      return entry ? ' ' + t('operationalPlan.content.mergedRef', {
                        rows: formatNumber(entry.rowspan),
                        cols: formatNumber(entry.colspan),
                      }) : '';
                    })()}
                  </span>
                )}
                {!activeCell && node?.content_type === 'static_table' && showPicker && (
                  <span style={{ fontSize: 12, color: '#999' }}>{t('operationalPlan.content.clickCellToSelect')}</span>
                )}
                {dirty && <span style={{ color: '#ff4d4f', fontSize: 12 }}>{t('operationalPlan.content.unsavedChanges')}</span>}
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ width: 30, padding: 4 }}></th>
                    {tableColumns.map((col, ci) => {
                      const { master, entry } = isCellMerged(0, ci);
                      if (!master) return null;
                      const cs = entry?.colspan || 1;
                      return (
                        <th key={ci} colSpan={cs} style={{ border: '1px solid #d9d9d9', padding: 4, background: '#fafafa', position: 'relative' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <input
                              value={col}
                              onChange={e => handleTableHeaderChange(ci, e.target.value)}
                              style={{ flex: 1, border: 'none', outline: 'none', background: 'transparent', fontWeight: 600, textAlign: 'center', fontSize: 13 }}
                            />
                            <DeleteOutlined
                              style={{ color: '#ff4d4f', fontSize: 11, cursor: tableColumns.length > 1 ? 'pointer' : 'not-allowed', opacity: tableColumns.length > 1 ? 1 : 0.3 }}
                              onClick={() => removeColumn(ci)}
                            />
                          </div>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((row, ri) => {
                    const rowHasMaster = (() => {
                      for (let c = 0; c < row.length; c++) {
                        const { master } = isCellMerged(ri, c);
                        if (master) return true;
                      }
                      return false;
                    })();
                    if (!rowHasMaster) return null;
                    return (
                      <tr key={ri}>
                        <td style={{ textAlign: 'center', verticalAlign: 'top', paddingTop: 8 }}>
                          <DeleteOutlined
                            style={{ color: '#ff4d4f', fontSize: 11, cursor: tableRows.length > 1 ? 'pointer' : 'not-allowed', opacity: tableRows.length > 1 ? 1 : 0.3 }}
                            onClick={() => removeRow(ri)}
                          />
                        </td>
                        {renderTableCells(ri, row)}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div style={{ marginTop: 8, color: '#999', fontSize: 11 }}>
                {t('operationalPlan.content.tipMergeAndVariables', {
                  button: t('operationalPlan.content.mergeCells'),
                  code: '{{variable_name}}',
                })}
              </div>
            </div>
          ) : (
            <textarea
              value={content}
              onChange={e => handleChange(e.target.value)}
              style={{ flex: 1, border: 'none', outline: 'none', padding: 16, fontSize: 14, resize: 'none' }}
            />
          )}
        </div>

        {showPicker && (
          <div style={{ width: 320, borderLeft: '1px solid #f0f0f0', overflow: 'hidden' }}>
            <VariablePicker
              onSelect={handleVariableSelect}
              usedVariables={
                node?.content_type === 'static_table'
                  ? Array.from(tableRows.flat().join(' ').matchAll(/\{\{(\w+:?\w+)\}\}/g)).map(m => m[1])
                  : node?.content_type === 'richtext' && inlineTables.length > 0
                    ? Array.from(inlineTables.flatMap(t => t.rows.flat()).join(' ').matchAll(/\{\{(\w+:?\w+)\}\}/g)).map(m => m[1])
                    : Array.from(content.matchAll(/\{\{(\w+:?\w+)\}\}/g)).map(m => m[1])
              }
              calculationId={calculationId}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default ContentPane;
