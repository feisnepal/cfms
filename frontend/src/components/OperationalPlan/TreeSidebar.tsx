/** Sidebar tree view of the operational plan document structure — supports add/delete/hide/reorder of nodes. */
import React, { useState, useRef, useEffect } from 'react';
import { Button, Tooltip, Input, Modal } from 'antd';
import type { InputRef } from 'antd';
import { PlusOutlined, DeleteOutlined, EyeOutlined, EyeInvisibleOutlined, PieChartOutlined, EnvironmentOutlined, FileTextOutlined, UndoOutlined, CloseCircleOutlined, TableOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';

interface TreeNodeData {
  id: string;
  type: string;
  title_ne: string;
  title_en: string;
  number?: string | null;
  level: number;
  content_type: string;
  children: TreeNodeData[];
  is_locked: boolean;
  hidden_in_export: boolean;
  deleted: boolean;
}

type TreeSidebarProps = {
  tree: TreeNodeData[];
  activeNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onAddChild: (parentId: string | null) => void;
  onAddChartNode?: (parentId: string | null) => void;
  onAddMapNode?: (parentId: string | null) => void;
  onAddStaticTable?: (parentId: string | null) => void;
  onToggleDelete: (nodeId: string) => void;
  onToggleHidden: (nodeId: string) => void;
  onHardDelete: (nodeId: string) => void;
  onUpdateTitle?: (nodeId: string, title_ne: string) => void;
  onReorderNode?: (nodeId: string, newParentId: string | null, newPosition: number) => void;
};

const BetweenDropZone: React.FC<{
  parentId: string | null;
  position: number;
  onReorderNode?: (nodeId: string, newParentId: string | null, newPosition: number) => void;
}> = ({ parentId, position, onReorderNode }) => {
  const [isOver, setIsOver] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setIsOver(true);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsOver(false);
    const draggedId = e.dataTransfer.getData('text/plain');
    if (draggedId && onReorderNode) {
      onReorderNode(draggedId, parentId, position);
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={() => setIsOver(false)}
      onDrop={handleDrop}
      style={{
        height: 6,
        margin: '1px 0',
        background: isOver ? '#1677ff' : 'transparent',
        borderRadius: 3,
        transition: 'background 0.15s',
      }}
    />
  );
};

const typeIcons: Record<string, string> = {
  preamble: '📄',
  toc: '📑',
  section: '📘',
  subsection: '📝',
  appendix: '📎',
};

const TreeNodeComponent: React.FC<{
  node: TreeNodeData;
  activeNodeId: string | null;
  depth: number;
  parentDeleted: boolean;
  editingId: string | null;
  editValue: string;
  setEditingId: (id: string | null) => void;
  setEditValue: (v: string) => void;
  onSelectNode: (id: string) => void;
  onAddChild: (id: string | null) => void;
  onAddChartNode?: (id: string | null) => void;
  onAddMapNode?: (id: string | null) => void;
  onAddStaticTable?: (id: string | null) => void;
  onToggleDelete: (id: string) => void;
  onToggleHidden: (id: string) => void;
  onHardDelete: (id: string) => void;
  onUpdateTitle?: (id: string, title: string) => void;
  onReorderNode?: (nodeId: string, newParentId: string | null, newPosition: number) => void;
  dragOverId: string | null;
  setDragOverId: (id: string | null) => void;
}> = ({ node, activeNodeId, depth, parentDeleted, editingId, editValue, setEditingId, setEditValue, onSelectNode, onAddChild, onAddChartNode, onAddMapNode, onAddStaticTable, onToggleDelete, onToggleHidden, onHardDelete, onUpdateTitle, onReorderNode, dragOverId, setDragOverId }) => {

  const t = useT();  const inputRef = useRef<InputRef>(null);

  const isDeleted = parentDeleted || node.deleted;

  useEffect(() => {
    if (editingId === node.id && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingId, node.id]);

  const handleSave = () => {
    const val = editValue.trim();
    if (val && val !== node.title_ne && onUpdateTitle) {
      onUpdateTitle(node.id, val);
    }
    setEditingId(null);
  };

  const handleDragStart = (e: React.DragEvent) => {
    if (isDeleted) { e.preventDefault(); return; }
    e.dataTransfer.setData('text/plain', node.id);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (isDeleted) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverId(node.id);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOverId(null);
    const draggedId = e.dataTransfer.getData('text/plain');
    if (draggedId && draggedId !== node.id && onReorderNode) {
      onReorderNode(draggedId, node.id, -1);
    }
  };

  const isDragOver = dragOverId === node.id;

  return (
    <div>
      <div
        draggable={!node.is_locked && !isDeleted}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragLeave={() => setDragOverId(null)}
        onDrop={handleDrop}
        onClick={() => { if (editingId !== node.id) onSelectNode(node.id); }}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '4px 8px', paddingLeft: 12 + depth * 16,
          cursor: node.is_locked ? 'pointer' : 'grab', borderRadius: 4, fontSize: 13,
          background: isDragOver ? '#e6f7ff' : activeNodeId === node.id ? '#e6f4ff' : 'transparent',
          borderLeft: activeNodeId === node.id ? '3px solid #1677ff' : '3px solid transparent',
          marginBottom: 1,
          outline: isDragOver ? '2px dashed #1890ff' : 'none',
          outlineOffset: -2,
          opacity: isDeleted ? 0.5 : 1,
          textDecoration: isDeleted ? 'line-through' : 'none',
          color: isDeleted ? '#bbb' : 'inherit',
        }}
        onMouseEnter={(e) => {
          if (activeNodeId !== node.id) (e.currentTarget as HTMLElement).style.background = '#f5f5f5';
        }}
        onMouseLeave={(e) => {
          if (activeNodeId !== node.id) (e.currentTarget as HTMLElement).style.background = 'transparent';
        }}
      >
        <span>{typeIcons[node.type] || '📄'}</span>
        {editingId === node.id ? (
          <Input
            ref={inputRef}
            size="small"
            value={editValue}
            onChange={e => setEditValue(e.target.value)}
            onPressEnter={handleSave}
            onBlur={handleSave}
            onClick={e => e.stopPropagation()}
            style={{ flex: 1, minWidth: 60, height: 24, fontSize: 13 }}
          />
        ) : (
          <span
            style={{ fontWeight: node.level === 0 ? 600 : 400, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            onDoubleClick={(e) => { e.stopPropagation(); if (!node.is_locked) { setEditValue(node.title_ne); setEditingId(node.id); } }}
            title={t('operationalPlan.tree.editHint')}
          >
            {node.number ? `${node.number}. ` : ''}{node.title_ne || node.title_en}
          </span>
        )}
        <span style={{ fontSize: 11, color: '#999', marginRight: 4 }}>
          {node.content_type === 'chart' ? '📊' : node.content_type === 'table' ? '📋' : node.content_type === 'map' ? '🗺️' : ''}
        </span>
        {isDeleted && (
          <Tooltip title={t('operationalPlan.tree.removedFromExport')}>
            <span style={{ fontSize: 10, color: '#999' }}>{t('operationalPlan.tree.removed')}</span>
          </Tooltip>
        )}
        {!isDeleted && node.hidden_in_export && (
          <Tooltip title={t('operationalPlan.tree.hiddenInExport')}>
            <EyeInvisibleOutlined style={{ fontSize: 11, color: '#faad14' }} />
          </Tooltip>
        )}
      </div>
      <div style={{ display: 'flex', gap: 2, paddingLeft: 12 + depth * 16 + 20, marginBottom: 2, flexWrap: 'wrap' }}>
        {!isDeleted && (
          <>
            <Tooltip title={t('operationalPlan.tree.addSection')}>
              <Button type="text" size="small" icon={<FileTextOutlined style={{ fontSize: 10 }} />}
                onClick={(e) => { e.stopPropagation(); onAddChild(node.id); }}
                style={{ width: 20, height: 20 }} />
            </Tooltip>
            {onAddChartNode && (
              <Tooltip title={t('operationalPlan.tree.addChart')}>
                <Button type="text" size="small" icon={<PieChartOutlined style={{ fontSize: 10, color: '#1677ff' }} />}
                  onClick={(e) => { e.stopPropagation(); onAddChartNode(node.id); }}
                  style={{ width: 20, height: 20 }} />
              </Tooltip>
            )}
            {onAddMapNode && (
              <Tooltip title={t('operationalPlan.tree.addMap')}>
                <Button type="text" size="small" icon={<EnvironmentOutlined style={{ fontSize: 10, color: '#52c41a' }} />}
                  onClick={(e) => { e.stopPropagation(); onAddMapNode(node.id); }}
                  style={{ width: 20, height: 20 }} />
              </Tooltip>
            )}
            {onAddStaticTable && (
              <Tooltip title={t('operationalPlan.tree.addTable')}>
                <Button type="text" size="small" icon={<TableOutlined style={{ fontSize: 10, color: '#722ed1' }} />}
                  onClick={(e) => { e.stopPropagation(); onAddStaticTable(node.id); }}
                  style={{ width: 20, height: 20 }} />
              </Tooltip>
            )}
            <Tooltip title={t('operationalPlan.tree.hideFromExport')}>
              <Button type="text" size="small"
                icon={node.hidden_in_export ? <EyeOutlined style={{ fontSize: 10 }} /> : <EyeInvisibleOutlined style={{ fontSize: 10 }} />}
                onClick={(e) => { e.stopPropagation(); onToggleHidden(node.id); }}
                style={{ width: 20, height: 20 }} />
            </Tooltip>
            {!isDeleted && (
              <Tooltip title={t('operationalPlan.tree.deletePermanently')}>
                <Button type="text" size="small" danger
                  icon={<CloseCircleOutlined style={{ fontSize: 10 }} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    Modal.confirm({
                      title: t('operationalPlan.tree.confirmDelete'),
                      content: `"${node.number ? node.number + '. ' : ''}${node.title_ne || node.title_en}" and all its children will be permanently removed. This cannot be undone.`,
                      okText: t('operationalPlan.tree.delete'),
                      okType: 'danger',
                      cancelText: t('operationalPlan.tree.cancel'),
                      onOk: () => onHardDelete(node.id),
                    });
                  }}
                  style={{ width: 20, height: 20 }} />
              </Tooltip>
            )}
          </>
        )}
        {!node.is_locked && (
          <Tooltip title={isDeleted ? t('operationalPlan.tree.restoreSection') : t('operationalPlan.tree.removeFromExport')}>
            <Button type="text" size="small"
              icon={isDeleted ? <UndoOutlined style={{ fontSize: 10 }} /> : <DeleteOutlined style={{ fontSize: 10 }} />}
              onClick={(e) => { e.stopPropagation(); onToggleDelete(node.id); }}
              style={{ width: 20, height: 20, color: isDeleted ? '#52c41a' : '#ff4d4f' }} />
          </Tooltip>
        )}
      </div>
      {(node.children || []).map((child, index) => (
        <React.Fragment key={child.id}>
          <BetweenDropZone parentId={node.id} position={index} onReorderNode={onReorderNode} />
          <TreeNodeComponent node={child} activeNodeId={activeNodeId} depth={depth + 1}
            parentDeleted={isDeleted}
            editingId={editingId} editValue={editValue} setEditingId={setEditingId} setEditValue={setEditValue}
            onSelectNode={onSelectNode} onAddChild={onAddChild} onToggleDelete={onToggleDelete}
            onAddChartNode={onAddChartNode} onAddMapNode={onAddMapNode} onAddStaticTable={onAddStaticTable}
            onToggleHidden={onToggleHidden} onHardDelete={onHardDelete} onUpdateTitle={onUpdateTitle} onReorderNode={onReorderNode}
            dragOverId={dragOverId} setDragOverId={setDragOverId} />
        </React.Fragment>
      ))}
      <BetweenDropZone parentId={node.id} position={(node.children || []).length} onReorderNode={onReorderNode} />
    </div>
  );
};

const TreeSidebar: React.FC<TreeSidebarProps> = ({ tree, activeNodeId, onSelectNode, onAddChild, onAddChartNode, onAddMapNode, onAddStaticTable, onToggleDelete, onToggleHidden, onHardDelete, onUpdateTitle, onReorderNode }) => {

  const t = useT();  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const shared = { activeNodeId, editingId, editValue, setEditingId, setEditValue, onSelectNode, onAddChild, onAddChartNode, onAddMapNode, onAddStaticTable, onToggleDelete, onToggleHidden, onHardDelete, onUpdateTitle, onReorderNode, dragOverId, setDragOverId };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', fontWeight: 600, fontSize: 14 }}>
        {t('operationalPlan.tree.title')}
      </div>
      <div style={{ padding: 8, borderBottom: '1px solid #f0f0f0', display: 'flex', gap: 4 }}>
        <Button size="small" icon={<FileTextOutlined />} onClick={() => onAddChild(null)} style={{ flex: 1 }}>
          {t('operationalPlan.tree.section')}
        </Button>
        {onAddChartNode && (
          <Button size="small" icon={<PieChartOutlined />} onClick={() => onAddChartNode(null)} type="primary" ghost>
            {t('operationalPlan.tree.chart')}
          </Button>
        )}
        {onAddMapNode && (
          <Button size="small" icon={<EnvironmentOutlined />} onClick={() => onAddMapNode(null)} style={{ borderColor: '#52c41a', color: '#52c41a' }}>
            {t('operationalPlan.tree.map')}
          </Button>
        )}
        {onAddStaticTable && (
          <Button size="small" icon={<TableOutlined />} onClick={() => onAddStaticTable(null)} style={{ borderColor: '#722ed1', color: '#722ed1' }}>
            {t('operationalPlan.tree.table')}
          </Button>
        )}
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {tree.map((node, index) => (
          <React.Fragment key={node.id}>
            <BetweenDropZone parentId={null} position={index} onReorderNode={onReorderNode} />
            <TreeNodeComponent node={node} depth={0} parentDeleted={false} {...shared} />
          </React.Fragment>
        ))}
        <BetweenDropZone parentId={null} position={tree.length} onReorderNode={onReorderNode} />
        {tree.length === 0 && (
          <div style={{ textAlign: 'center', padding: 20, color: '#999' }}>
            {t('operationalPlan.tree.empty')}
          </div>
        )}
      </div>
    </div>
  );
};

export default TreeSidebar;
