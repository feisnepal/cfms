/**
 * Template Download Section
 * Allows users to configure and download Excel template
 */
import React, { useState } from 'react';
import { Button, Card, Radio, Checkbox, Alert, Space, message } from 'antd';
import { DownloadOutlined, FileExcelOutlined } from '@ant-design/icons';
import * as api from '../../services/api';
import { downloadFromApi } from '../../utils/download';
import { useT } from '../../i18n/hooks';

interface TemplateDownloadSectionProps {
  calculationId: string;
  hasExistingData: boolean;
}

const TemplateDownloadSection: React.FC<TemplateDownloadSectionProps> = ({
  calculationId,
  hasExistingData,
}) => {

  const t = useT();  const [landUnit, setLandUnit] = useState<'ropani' | 'kaththa'>('ropani');
  const [includeCoordinates, setIncludeCoordinates] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const dateStr = new Date().toISOString().split('T')[0].replace(/-/g, '');
      await downloadFromApi(
        `/api/household/calculations/${calculationId}/template`,
        `household_template_${landUnit}_${dateStr}.xlsx`,
        undefined,
        { method: 'POST', body: { land_unit: landUnit, include_coordinates: includeCoordinates } }
      );
      message.success(t('household.msgTemplateDownloaded'));
    } catch (error) {
      console.error('Error downloading template:', error);
      message.error(error instanceof Error ? error.message : t('household.msgTemplateFailed'));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div>
      {hasExistingData && (
        <Alert
          message="Data Already Exists"
          description="You already have household data uploaded. To re-upload, delete the existing data first using the 'Delete All Data' button."
          type="warning"
          showIcon
          style={{ marginBottom: 20 }}
        />
      )}

      <Card title="Download Excel Template" style={{ maxWidth: 800 }}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <h4>{t('household.landUnit')}</h4>
            <p style={{ color: '#666', marginBottom: 10 }}>
              {t('household.landUnitHint')}
            </p>
            <Radio.Group
              value={landUnit}
              onChange={(e) => setLandUnit(e.target.value)}
              size="large"
            >
              <Radio.Button value="ropani">
                <strong>{t('household.ropani')}</strong>
              </Radio.Button>
              <Radio.Button value="kaththa">
                <strong>{t('household.kaththa')}</strong>
              </Radio.Button>
            </Radio.Group>
            <p style={{ color: '#999', marginTop: 10, fontSize: 12 }}>
              {t('household.ropaniNote')}
            </p>
          </div>

          <div>
            <h4>{t('household.optionalFields')}</h4>
            <Checkbox
              checked={includeCoordinates}
              onChange={(e) => setIncludeCoordinates(e.target.checked)}
            >
              <strong>{t('household.includeCoords')}</strong> (Latitude/Longitude)
            </Checkbox>
            <p style={{ color: '#999', marginTop: 5, fontSize: 12 }}>
              {t('household.includeCoordsHint')}
            </p>
          </div>

          <Alert
            message="Template Features"
            description={
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                <li>
                  <strong>{t('household.featureFormulas')}</strong> for automatic calculation of
                  firewood, grass, and bedding demands
                </li>
                <li>
                  <strong>{t('household.featureValidation')}</strong> dropdowns for Yes/No fields and
                  prosperity levels
                </li>
                <li>
                  <strong>{t('household.featureInstructions')}</strong> with detailed guidance in both
                  Nepali and English
                </li>
                <li>
                  <strong>{t('household.featureDefaults')}</strong>: Timber (5 cft), Poles (5),
                  {t('household.prosperityDefault')}
                </li>
              </ul>
            }
            type="info"
            showIcon
          />

          <div>
            <h4>{t('household.nextSteps')}</h4>
            <ol style={{ color: '#666', paddingLeft: 20 }}>
              <li>{t('household.step1')}</li>
              <li>{t('household.step2')}</li>
              <li>{t('household.step3')}</li>
              <li>
                {t('household.step4')}
              </li>
              <li>{t('household.step5')}</li>
            </ol>
          </div>

          <Button
            type="primary"
            size="large"
            icon={<DownloadOutlined />}
            onClick={handleDownload}
            loading={downloading}
            block
          >
            <FileExcelOutlined /> Download Excel Template
          </Button>
        </Space>
      </Card>
    </div>
  );
};

export default TemplateDownloadSection;
