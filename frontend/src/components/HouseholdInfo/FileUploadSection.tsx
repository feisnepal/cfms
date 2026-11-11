/**
 * File Upload Section
 * Handles Excel (.xlsx, .xls) and CSV file upload with validation preview
 */
import React, { useState } from 'react';
import { Upload, Button, Card, Alert, Table, Tag, Space, message, Modal, Form, Input, Select, Checkbox } from 'antd';
import { UploadOutlined, CheckCircleOutlined, CloseCircleOutlined, WarningOutlined, PlusOutlined } from '@ant-design/icons';
import type { UploadProps } from 'antd';
import * as api from '../../services/api';
import type { HouseholdUploadResponse, HouseholdUploadValidation } from '../../types/household';
import { LocaleInputNumber } from '../LocaleInputNumber';
import { UploadReport } from '../UploadReport';
import { findingsFromBody, findingsFromError, type UploadFinding } from '../../lib/uploadFindings';
import { UploadStateLine } from '../UploadStateLine';
import { useT } from '../../i18n/hooks';
import { apiErrorText } from '../../lib/apiErrorText';

interface FileUploadSectionProps {
  calculationId: string;
  hasExistingData: boolean;
  onUploadSuccess: () => void;
  /** Some rows were saved but others need attention: refresh the data and stay on this screen. */
  onUploadPartial?: () => void;
  /** how many households are in the system now, for the replace-the-whole-list confirmation */
  existingCount?: number;
}

const FileUploadSection: React.FC<FileUploadSectionProps> = ({
  calculationId,
  hasExistingData,
  onUploadSuccess,
  onUploadPartial,
  existingCount = 0,
}) => {

  const t = useT();  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<HouseholdUploadResponse | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [replaceAll, setReplaceAll] = useState(false); // D5: the explicit "replace the whole list" choice (default: update by house number)
  const [errorFindings, setErrorFindings] = useState<UploadFinding[] | null>(null); // a refused file: what is wrong and how to fix it
  const [addModalVisible, setAddModalVisible] = useState(false);
  const [addForm] = Form.useForm();
  const [adding, setAdding] = useState(false);

  // Choosing the file IS the upload (owner, 2026-10-12): no second button, no OK / Continue. Valid rows are imported straight away (decision D1);
  // rows with problems are listed below with what to fix.
  const handleUpload = async (file: File, replaceAllList = false) => {
    setUploading(true);
    setErrorFindings(null);
    try {
      const result = await api.userGroupApi.uploadHouseholdData(calculationId, file, replaceAllList ? { replaceAll: true } : {});
      setUploadResult(result);
      const saved = (result.records_imported ?? 0) + (result.records_updated ?? 0);
      if (saved > 0 && result.invalid_rows === 0) {
        onUploadSuccess(); // everything went in: show the households
      } else if (saved > 0) {
        onUploadPartial?.(); // refresh the data but stay here: the user needs to see which rows to fix
      }
    } catch (error: any) {
      console.error('Error uploading file:', error);
      const findings = findingsFromError(error);
      if (findings) setErrorFindings(findings);
      else message.error(apiErrorText(error, t('household.upload.msgUploadFailed')));
    } finally {
      setUploading(false);
    }
  };

  const uploadProps: UploadProps = {
    accept: '.xlsx,.xls,.csv',
    multiple: false,
    maxCount: 1,
    beforeUpload: (file) => {
      setSelectedFile(file);
      setUploadResult(null);
      if (replaceAll) {
        // D5: replacing the whole list removes households, so say how many are in the system and ask first
        Modal.confirm({
          title: t('household.upload.replaceConfirmTitle'),
          content: t('household.upload.replaceConfirmBody', { count: existingCount }),
          okText: t('household.upload.replaceConfirmOk'),
          okType: 'danger',
          cancelText: t('household.cancel'),
          onOk: () => handleUpload(file, true),
          onCancel: () => setSelectedFile(null),
        });
      } else {
        void handleUpload(file);
      }
      return false; // antd must not upload it itself: handleUpload does
    },
    onRemove: () => {
      setSelectedFile(null);
      setUploadResult(null);
    },
  };

  const validationColumns = [
    {
      title: t('household.col.row'),
      dataIndex: 'row_number',
      key: 'row_number',
      width: 80,
    },
    {
      title: t('household.col.status'),
      key: 'status',
      width: 100,
      render: (_: any, record: HouseholdUploadValidation) => (
        record.is_valid ? (
          <Tag icon={<CheckCircleOutlined />} color="success">{t('household.valid')}</Tag>
        ) : (
          <Tag icon={<CloseCircleOutlined />} color="error">{t('household.invalid')}</Tag>
        )
      ),
    },
    {
      title: t('household.col.houseNo'),
      key: 'house_no',
      width: 100,
      render: (_: any, record: HouseholdUploadValidation) => record.data?.house_no || '-',
    },
    {
      title: t('household.col.surname'),
      key: 'surname',
      width: 120,
      render: (_: any, record: HouseholdUploadValidation) => record.data?.surname || '-',
    },
    {
      title: t('household.col.errors'),
      dataIndex: 'errors',
      key: 'errors',
      render: (errors: string[]) => (
        errors.length > 0 ? (
          <Space direction="vertical" size={0}>
            {errors.map((error, idx) => (
              <Tag key={idx} color="red" icon={<CloseCircleOutlined />}>
                {error}
              </Tag>
            ))}
          </Space>
        ) : (
          <Tag color="success">{t('household.noErrors')}</Tag>
        )
      ),
    },
    {
      title: t('household.col.warnings'),
      dataIndex: 'warnings',
      key: 'warnings',
      render: (warnings: string[]) => (
        warnings.length > 0 ? (
          <Space direction="vertical" size={0}>
            {warnings.map((warning, idx) => (
              <Tag key={idx} color="orange" icon={<WarningOutlined />}>
                {warning}
              </Tag>
            ))}
          </Space>
        ) : null
      ),
    },
  ];

  const handleAddHousehold = async (values: any) => {
    setAdding(true);
    try {
      await api.userGroupApi.createHousehold(calculationId, values);
      message.success(t('household.add.msgAdded'));
      setAddModalVisible(false);
      addForm.resetFields();
      onUploadSuccess();
    } catch (error: any) {
      message.error(apiErrorText(error, t('household.add.msgAddFailed')));
    } finally {
      setAdding(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setAddModalVisible(true)}
        >
          {t('household.upload.addManually')}
        </Button>
        <span style={{ marginLeft: 12, color: '#666' }}>
          {t('household.upload.orUpload')}
        </span>
      </div>

      <UploadStateLine present={hasExistingData} className="mb-3" />

      {hasExistingData && (
        <Alert
          message={t('household.upload.appendMode')}
          description={t('household.upload.updateMode')}
          type="info"
          showIcon
          style={{ marginBottom: 20 }}
        />
      )}

      <Card title={t('household.upload.title')}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Alert
            message={t('household.upload.beforeUploading')}
            description={
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                <li>{t('household.upload.hint1')}</li>
                <li>{t('household.upload.hint2')}</li>
                <li>{t('household.upload.hint3')}</li>
                <li>{t('household.upload.hint4')}</li>
              </ul>
            }
            type="info"
            showIcon
          />

          {hasExistingData && (
            <Checkbox checked={replaceAll} onChange={(e) => setReplaceAll(e.target.checked)} data-testid="household-replace-all">
              <strong>{t('household.upload.replaceAll')}</strong>
              <div style={{ fontSize: 12, color: '#666' }}>{t('household.upload.replaceAllHint')}</div>
            </Checkbox>
          )}

          <Upload.Dragger {...uploadProps} disabled={uploading}>
            <p className="ant-upload-drag-icon">
              <UploadOutlined style={{ fontSize: 48, color: uploading ? '#ccc' : '#1890ff' }} />
            </p>
            <p className="ant-upload-text">
              {t('household.upload.dragHint')}
            </p>
            <p className="ant-upload-hint">
              {t('household.upload.supportHint')}{' '}
              {hasExistingData ? t('household.upload.appendNote') : t('household.upload.validateNote')}
            </p>
          </Upload.Dragger>

          {uploading && (
            <Alert type="info" showIcon message={t('household.upload.reading')} data-testid="household-upload-reading" />
          )}

          {errorFindings && <UploadReport findings={errorFindings} />}

          {uploadResult && (
            <>
              <Alert
                data-testid="household-upload-summary"
                message={
                  uploadResult.total_rows === 0
                    ? t('household.upload.noRows')
                    : uploadResult.records_imported + uploadResult.records_updated === 0
                      ? t('household.upload.nothingImported', { bad: uploadResult.invalid_rows })
                      : uploadResult.invalid_rows === 0
                        ? t('household.upload.doneAll', { imported: uploadResult.records_imported, updated: uploadResult.records_updated })
                        : t('household.upload.donePartial', {
                            ok: uploadResult.records_imported + uploadResult.records_updated,
                            imported: uploadResult.records_imported,
                            updated: uploadResult.records_updated,
                            bad: uploadResult.invalid_rows,
                          })
                }
                description={
                  <div>
                    {uploadResult.invalid_rows > 0 && <p><strong>{t('household.upload.fixHint')}</strong></p>}
                    {(uploadResult.records_removed ?? 0) > 0 && <p data-testid="household-removed">{t('household.upload.removed', { count: uploadResult.records_removed })}</p>}
                    <p><strong>{t('household.upload.totalRows')}</strong> {uploadResult.total_rows}</p>
                    <p><strong>{t('household.upload.validRows')}</strong> {uploadResult.valid_rows}</p>
                    <p><strong>{t('household.upload.invalidRows')}</strong> {uploadResult.invalid_rows}</p>
                    <p><strong>{t('household.upload.imported')}</strong> {uploadResult.records_imported}</p>
                    <p><strong>{t('household.upload.updated')}</strong> {uploadResult.records_updated}</p>
                  </div>
                }
                type={uploadResult.success && uploadResult.invalid_rows === 0 ? 'success' : 'warning'}
                showIcon
              />

              <UploadReport
                findings={findingsFromBody(uploadResult)}
                fileName="household_rows_to_correct"
                problemRows={(uploadResult.validations ?? [])
                  .filter((v: any) => !v.is_valid)
                  .map((v: any) => ({ row: v.row_number, problem: (v.errors ?? []).join('; ') }))}
              />

              <Card title={t('household.upload.validationDetails')} size="small">
                <Table
                  dataSource={uploadResult.validations}
                  columns={validationColumns}
                  rowKey="row_number"
                  size="small"
                  pagination={{ pageSize: 10 }}
                  scroll={{ x: 1000 }}
                />
              </Card>

            </>
          )}
        </Space>
      </Card>

      <Modal
        title={t('household.add.title')}
        open={addModalVisible}
        onCancel={() => { setAddModalVisible(false); addForm.resetFields(); }}
        footer={null}
        width={600}
        destroyOnHidden
      >
        <Form
          form={addForm}
          layout="vertical"
          onFinish={handleAddHousehold}
        >
          <Form.Item
            name="house_no"
            label={t('household.col.houseNo')}
            rules={[{ required: true, message: t('household.add.houseNoRequired') }]}
          >
            <Input placeholder={t('household.add.houseNoExample')} />
          </Form.Item>

          <Form.Item
            name="surname"
            label={t('household.add.surnameLabel')}
            rules={[{ required: true, message: t('household.add.surnameRequired') }]}
          >
            <Input placeholder={t('household.add.surnameExample')} />
          </Form.Item>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
            <Form.Item
              name="male_population"
              label={t('household.add.malePopulation')}
            >
              <LocaleInputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>

            <Form.Item
              name="female_population"
              label={t('household.add.femalePopulation')}
            >
              <LocaleInputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>

            <Form.Item
              name="total_population"
              label={t('household.add.totalPopulation')}
            >
              <LocaleInputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Form.Item
              name="forest_dependent"
              label={t('household.add.forestDependent')}
            >
              <Select placeholder={t('household.add.select')}>
                <Select.Option value="Yes">Yes</Select.Option>
                <Select.Option value="No">No</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item
              name="caste"
              label={t('household.add.caste')}
            >
              <Input placeholder={t('household.add.casteExample')} />
            </Form.Item>
          </div>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={adding}>
                {t('household.add.submit')}
              </Button>
              <Button onClick={() => { setAddModalVisible(false); addForm.resetFields(); }}>
                {t('household.cancel')}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default FileUploadSection;
