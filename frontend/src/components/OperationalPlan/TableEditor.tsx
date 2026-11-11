/** Inline table editor for managing structured tabular data within the operational plan document. */
import React, { useState, useEffect, useCallback } from 'react';
import { Button, message, Spin, Select, Tag, Input, Popconfirm } from 'antd';
import { ReloadOutlined, SaveOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { operationalPlanApi } from '../../services/api';
import { LocaleInputNumber } from '../LocaleInputNumber';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';

interface TableEditorProps {
  calculationId: string;
}

interface TableDef {
  table_id: string;
  title_ne: string;
  title_en: string;
  auto_populatable: boolean;
}

const CELL_STYLE: React.CSSProperties = {
  border: '1px solid #e8e8e8',
  padding: '4px 8px',
  verticalAlign: 'top',
};

const TableEditor: React.FC<TableEditorProps> = ({ calculationId }) => {

  const t = useT();  const [tables, setTables] = useState<TableDef[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [rows, setRows] = useState<Record<string, any>[]>([]);
  const [originalRows, setOriginalRows] = useState<Record<string, any>[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [autoPopulated, setAutoPopulated] = useState(false);

  useEffect(() => { loadTableList(); }, []);

  useEffect(() => {
    if (selectedTable) loadTableData(selectedTable);
  }, [selectedTable]);

  const loadTableList = async () => {
    try {
      const data = await operationalPlanApi.listTables();
      setTables(data.tables || []);
      if (data.tables?.length > 0 && !selectedTable) {
        setSelectedTable(data.tables[0].table_id);
      }
    } catch { message.error(t('operationalPlan.table.loadFailed')); }
  };

  const loadTableData = async (tableId: string) => {
    setLoading(true);
    try {
      const data = await operationalPlanApi.getTableData(tableId, calculationId);
      const loaded = data.rows || [];
      setRows(JSON.parse(JSON.stringify(loaded)));
      setOriginalRows(JSON.parse(JSON.stringify(loaded)));
      setAutoPopulated(data.auto_populated || false);
    } catch {
      setRows([]);
      setOriginalRows([]);
      setAutoPopulated(false);
    } finally { setLoading(false); }
  };

  const isDirty = JSON.stringify(rows) !== JSON.stringify(originalRows);

  const handleAutoPopulate = async () => {
    if (!selectedTable) return;
    setLoading(true);
    try {
      const data = await operationalPlanApi.autoPopulateTable(selectedTable, calculationId);
      const loaded = data.rows || [];
      setRows(JSON.parse(JSON.stringify(loaded)));
      setOriginalRows(JSON.parse(JSON.stringify(loaded)));
      setAutoPopulated(true);
      message.success(`Table ${selectedTable} auto-populated`);
    } catch { message.error(t('operationalPlan.table.autoPopulateFailed')); }
    finally { setLoading(false); }
  };

  const handleSave = async () => {
    if (!selectedTable) return;
    setSaving(true);
    try {
      await operationalPlanApi.updateTableData(selectedTable, calculationId, {
        rows,
        auto_populated: false,
      });
      setOriginalRows(JSON.parse(JSON.stringify(rows)));
      setAutoPopulated(false);
      message.success(t('operationalPlan.table.msgSaved'));
    } catch { message.error(t('operationalPlan.table.saveFailed')); }
    finally { setSaving(false); }
  };

  const updateCell = (rowIdx: number, key: string, value: any) => {
    setRows(prev => {
      const next = [...prev];
      next[rowIdx] = { ...next[rowIdx], [key]: value };
      return next;
    });
  };

  const addRow = () => {
    const keys = rows.length > 0
      ? Object.keys(rows[0])
      : ['column_1', 'column_2'];
    const newRow: Record<string, any> = {};
    keys.forEach(k => { newRow[k] = ''; });
    setRows(prev => [...prev, newRow]);
  };

  const deleteRow = (idx: number) => {
    setRows(prev => prev.filter((_, i) => i !== idx));
  };

  const isNe = i18n.language === 'ne';
  const selectedDef = tables.find(t => t.table_id === selectedTable);
  const columns = rows.length > 0 ? Object.keys(rows[0]) : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <Select
          style={{ width: 400 }}
          value={selectedTable}
          onChange={setSelectedTable}
          options={tables.map(t => ({
            value: t.table_id,
            label: `${t.table_id.toUpperCase()}: ${t.title_ne} (${t.title_en})`,
          }))}
        />
        {selectedDef?.auto_populatable && (
          <Button icon={<ReloadOutlined />} onClick={handleAutoPopulate} loading={loading}>
            {t('operationalPlan.table.autoPopulate')}
          </Button>
        )}
        {autoPopulated && <Tag color="green">{t('operationalPlan.table.autoPopulated')}</Tag>}
        {isDirty && (
          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
            {t('operationalPlan.table.save')}
          </Button>
        )}
        <Button icon={<PlusOutlined />} onClick={addRow} size="small">
          {t('operationalPlan.table.addRow')}
        </Button>
      </div>

      {selectedDef && (
        <div style={{ marginBottom: 8, color: '#666', fontSize: 13 }}>
          {isNe ? selectedDef.title_ne || selectedDef.title_en : selectedDef.title_en} — {selectedDef.auto_populatable ? t('operationalPlan.table.systemDataAvailable') : t('operationalPlan.table.manualEntry')}
        </div>
      )}

      <div style={{ flex: 1, overflow: 'auto' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : rows.length > 0 ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {columns.map(col => (
                  <th key={col} style={{ ...CELL_STYLE, background: '#fafafa', fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {col.replace(/_/g, ' ')}
                  </th>
                ))}
                <th style={{ ...CELL_STYLE, background: '#fafafa', width: 50 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {columns.map(col => (
                    <td key={col} style={CELL_STYLE}>
                      {typeof row[col] === 'number' || (!isNaN(Number(row[col])) && row[col] !== '') ? (
                        <LocaleInputNumber
                          value={row[col]}
                          onChange={v => updateCell(rIdx, col, v)}
                          style={{ width: '100%' }}
                          bordered={false}
                        />
                      ) : (
                        <Input
                          value={row[col] ?? ''}
                          onChange={e => updateCell(rIdx, col, e.target.value)}
                          bordered={false}
                          style={{ width: '100%' }}
                        />
                      )}
                    </td>
                  ))}
                  <td style={CELL_STYLE}>
                    <Popconfirm title={t('operationalPlan.table.confirmDeleteRow')} onConfirm={() => deleteRow(rIdx)}>
                      <Button type="link" danger size="small" icon={<DeleteOutlined />} />
                    </Popconfirm>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            No data. {selectedDef?.auto_populatable ? 'Click "Auto-Populate" to fill from system, or "Add Row" to enter manually.' : 'Click "Add Row" to start entering data.'}
          </div>
        )}
      </div>
    </div>
  );
};

export default TableEditor;
