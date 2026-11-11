/**
 * "Download data template" (owner, 2026-10-13): one click gives a zip with an Excel and a CSV template for every kind of data the system reads, each with a
 * guideline sheet, cell comments, validation and the required coordinate-system column. Generic (no forest needed); the household workbook defaults to ropani
 * and the menu offers kaththa.
 */
import { useState } from 'react';
import { Button, Dropdown, Space, message } from 'antd';
import { DownOutlined, DownloadOutlined } from '@ant-design/icons';
import { useT } from '../i18n/hooks';
import { uploadApi } from '../services/api';

interface DownloadTemplateButtonProps {
  size?: 'small' | 'middle' | 'large';
  /** antd Button type - default `default`. */
  buttonType?: 'primary' | 'default' | 'dashed' | 'text' | 'link';
}

export default function DownloadTemplateButton({ size = 'small', buttonType = 'default' }: DownloadTemplateButtonProps) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  const download = async (unit: 'ropani' | 'kaththa') => {
    setBusy(true);
    try {
      await uploadApi.downloadTemplates(unit);
    } catch {
      message.error(t('addData.templateFailed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Space.Compact size={size} data-testid="download-template">
      <Button type={buttonType} size={size} icon={<DownloadOutlined />} loading={busy} title={t('addData.downloadTemplateTitle')} onClick={() => download('ropani')}>
        {t('addData.downloadTemplate')}
      </Button>
      <Dropdown
        trigger={['click']}
        menu={{
          items: [
            { key: 'ropani', label: t('addData.templateRopani'), onClick: () => download('ropani') },
            { key: 'kaththa', label: t('addData.templateKaththa'), onClick: () => download('kaththa') },
          ],
        }}
      >
        <Button type={buttonType} size={size} icon={<DownOutlined />} aria-label={t('addData.templateOptions')} />
      </Dropdown>
    </Space.Compact>
  );
}
