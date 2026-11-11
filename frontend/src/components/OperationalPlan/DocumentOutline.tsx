/** Document outline sidebar showing the hierarchical tree of sections/charts/maps/tables in the operational plan. */
import React from 'react';
import { FileTextOutlined, PieChartOutlined, EnvironmentOutlined, TableOutlined } from '@ant-design/icons';
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
  hidden_in_export: boolean;
  deleted: boolean;
}

interface DocumentOutlineProps {
  tree: TreeNodeData[];
  activeNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

const typeIcons: Record<string, string> = {
  preamble: '\u{1F4C4}',
  toc: '\u{1F4D1}',
  section: '\u{1F4D8}',
  subsection: '\u{1F4DD}',
  appendix: '\u{1F4CE}',
};

const contentTypeIcon = (type: string) => {
  switch (type) {
    case 'chart': return <PieChartOutlined style={{ fontSize: 11, color: '#1677ff' }} />;
    case 'map': return <EnvironmentOutlined style={{ fontSize: 11, color: '#52c41a' }} />;
    case 'static_table': return <TableOutlined style={{ fontSize: 11, color: '#722ed1' }} />;
    default: return null;
  }
};

const TreeNodeComponent: React.FC<{
  node: TreeNodeData;
  activeNodeId: string | null;
  depth: number;
  onSelectNode: (id: string) => void;
}> = ({ node, activeNodeId, depth, onSelectNode }) => {

  const t = useT();  const isDeleted = node.deleted;
  const isHidden = node.hidden_in_export;

  return (
    <div>
      <div
        onClick={() => onSelectNode(node.id)}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '4px 8px', paddingLeft: 12 + depth * 16,
          cursor: 'pointer', borderRadius: 4, fontSize: 13,
          background: activeNodeId === node.id ? '#e6f4ff' : 'transparent',
          borderLeft: activeNodeId === node.id ? '3px solid #1677ff' : '3px solid transparent',
          marginBottom: 1,
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
        <span>{typeIcons[node.type] || '\u{1F4C4}'}</span>
        <span
          style={{
            fontWeight: node.level === 0 ? 600 : 400,
            flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {node.number ? `${node.number}. ` : ''}{node.title_ne || node.title_en}
        </span>
        <span style={{ marginLeft: 4, display: 'flex', alignItems: 'center', gap: 2 }}>
          {contentTypeIcon(node.content_type)}
          {isHidden && !isDeleted && (
            <span style={{ fontSize: 10, color: '#faad14' }}>{t('operationalPlan.outline.hidden')}</span>
          )}
        </span>
      </div>
      {node.children?.map(child =>
        <TreeNodeComponent key={child.id} node={child} activeNodeId={activeNodeId} depth={depth + 1} onSelectNode={onSelectNode} />
      )}
    </div>
  );
};

const DocumentOutline: React.FC<DocumentOutlineProps> = ({ tree, activeNodeId, onSelectNode }) => {

  const t = useT();  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', fontWeight: 600, fontSize: 14 }}>
        {t('operationalPlan.outline.title')}
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {tree.map(node =>
          <TreeNodeComponent key={node.id} node={node} activeNodeId={activeNodeId} depth={0} onSelectNode={onSelectNode} />
        )}
        {tree.length === 0 && (
          <div style={{ textAlign: 'center', padding: 20, color: '#999' }}>
            {t('operationalPlan.outline.empty')}
          </div>
        )}
      </div>
    </div>
  );
};

export default DocumentOutline;