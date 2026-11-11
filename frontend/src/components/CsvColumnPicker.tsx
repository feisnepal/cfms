/**
 * CSV column picker for user-group boundary import (UP-3.2).
 *
 * Shows the file's columns with auto-detected lat/lon pre-selected, lets the
 * user override, and returns the chosen pair. Used before importing a CSV/Excel
 * file as a user-group boundary.
 */
import { useEffect, useState } from 'react';
import { Modal, Select, Table, Tag, message } from 'antd';
import { useT } from '../i18n/hooks';
import { uploadApi } from '../services/api';

interface CsvColumnPickerProps {
  open: boolean;
  file: File;
  onConfirm: (latCol: string, lonCol: string) => void;
  onCancel: () => void;
}

interface ColumnInfo {
  columns: string[];
  sample_rows: string[][];
  lat_col: string | null;
  lon_col: string | null;
  total_rows: number;
}

export function CsvColumnPicker({ open, file, onConfirm, onCancel }: CsvColumnPickerProps) {
  const t = useT();
  const [info, setInfo] = useState<ColumnInfo | null>(null);
  const [latCol, setLatCol] = useState<string | null>(null);
  const [lonCol, setLonCol] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setInfo(null);
    uploadApi
      .getCsvColumns(file)
      .then((data) => {
        setInfo(data);
        setLatCol(data.lat_col);
        setLonCol(data.lon_col);
      })
      .catch((err) => {
        message.error(t('csvColumnPicker.loadFailed'));
        onCancel();
      })
      .finally(() => setLoading(false));
  }, [open, file]);

  const handleConfirm = () => {
    if (!latCol || !lonCol) {
      message.warning(t('csvColumnPicker.pickBoth'));
      return;
    }
    onConfirm(latCol, lonCol);
  };

  const columns = [
    { title: t('csvColumnPicker.column'), dataIndex: 'col', key: 'col' },
    ...(info?.sample_rows[0]?.map((_, i) => ({
      title: `${t('csvColumnPicker.sample')} ${i + 1}`,
      dataIndex: `row_${i}`,
      key: `row_${i}`,
      render: (v: string) => <span className="text-xs">{v}</span>,
    })) ?? []),
  ];

  const tableData =
    info?.sample_rows.map((row, i) => ({
      key: i,
      col: info.columns[i] ?? '',
      ...row.reduce((acc: Record<string, string>, v, j) => {
        acc[`row_${j}`] = String(v ?? '');
        return acc;
      }, {}),
    })) ?? [];

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      title={t('csvColumnPicker.title')}
      onOk={handleConfirm}
      okText={t('csvColumnPicker.confirm')}
      cancelText={t('common.cancel')}
      width={640}
      centered
      destroyOnHidden
    >
      {loading ? (
        <div className="py-8 text-center">{t('csvColumnPicker.loading')}</div>
      ) : info ? (
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <label className="block text-sm font-medium mb-1">{t('csvColumnPicker.latitude')}</label>
              <Select
                style={{ width: '100%' }}
                value={latCol}
                onChange={setLatCol}
                options={info.columns.map((c) => ({ value: c, label: c }))}
                placeholder={t('csvColumnPicker.pickColumn')}
              />
            </div>
            <div className="flex-1">
              <label className="block text-sm font-medium mb-1">{t('csvColumnPicker.longitude')}</label>
              <Select
                style={{ width: '100%' }}
                value={lonCol}
                onChange={setLonCol}
                options={info.columns.map((c) => ({ value: c, label: c }))}
                placeholder={t('csvColumnPicker.pickColumn')}
              />
            </div>
          </div>

          {info.lat_col && info.lon_col && (
            <div className="text-xs text-green-600">
              {t('csvColumnPicker.autoDetected', { lat: info.lat_col, lon: info.lon_col })}
            </div>
          )}

          <div className="text-xs text-gray-500">
            {t('csvColumnPicker.totalRows', { count: info.total_rows })}
          </div>

          <Table
            dataSource={tableData}
            columns={columns}
            pagination={false}
            size="small"
            scroll={{ x: 400 }}
          />
        </div>
      ) : null}
    </Modal>
  );
}
