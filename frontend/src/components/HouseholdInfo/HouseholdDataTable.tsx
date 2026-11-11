/**
 * Household Data Table
 * Displays household records with inline editing
 */
import React, { useState } from 'react';
import { Table, Button, Tag, Popconfirm, message, Space, Tooltip, Form, Input, Select, Modal } from 'antd';
import { DeleteOutlined, EditOutlined, ReloadOutlined, SaveOutlined, CloseOutlined, PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import * as api from '../../services/api';
import type { HouseholdInfo } from '../../types/household';
import HouseholdVariablePanel from './HouseholdVariablePanel';
import { LocaleInputNumber } from '../LocaleInputNumber';
import { useT } from '../../i18n/hooks';
import { apiErrorText } from '../../lib/apiErrorText';

interface HouseholdDataTableProps {
  households: HouseholdInfo[];
  onRefresh: () => void;
  calculationId: string;
}

interface EditableCellProps {
  editing: boolean;
  dataIndex: string;
  title: string;
  inputType: 'number' | 'text' | 'select';
  record: HouseholdInfo;
  index: number;
  children: React.ReactNode;
  selectOptions?: { label: string; value: any }[];
}


/** Display keys for the persisted caste / prosperity values. The values
 *  themselves are stored and compared, so only the label is translated. */
const OPTION_LABEL_KEY: Record<string, string> = {
  'जनजाती': 'household.caste.janajati',
  'दलित': 'household.caste.dalit',
  'सीमान्तकृत': 'household.caste.marginalised',
  'अति सीमान्तकृत': 'household.caste.highlyMarginalised',
  'लोपोन्मुख र सीमान्तकृत': 'household.caste.endangered',
  'अन्य': 'household.caste.other',
  'अति विपन्न': 'household.prosperity.veryPoor',
  'विपन्न': 'household.prosperity.poor',
  'मध्यम': 'household.prosperity.medium',
  'सम्पन्न': 'household.prosperity.wellOff',
};

const EditableCell: React.FC<EditableCellProps> = ({
  editing,
  dataIndex,
  title,
  inputType,
  record,
  index,
  children,
  selectOptions,
  ...restProps
}) => {

  const t = useT();  let inputNode: React.ReactNode;

  if (inputType === 'number') {
    inputNode = <LocaleInputNumber style={{ width: '100%' }} min={0} />;
  } else if (inputType === 'select' && selectOptions) {
    inputNode = <Select options={selectOptions} style={{ width: '100%' }} />;
  } else {
    inputNode = <Input />;
  }

  return (
    <td {...restProps}>
      {editing ? (
        <Form.Item
          name={dataIndex}
          style={{ margin: 0 }}
          rules={[
            {
              required: ['surname', 'female_count', 'male_count'].includes(dataIndex),
              message: `Please input ${title}!`,
            },
          ]}
        >
          {inputNode}
        </Form.Item>
      ) : (
        children
      )}
    </td>
  );
};

const HouseholdDataTable = React.memo(({
  households,
  onRefresh,
  calculationId,
}: HouseholdDataTableProps) => {
  const t = useT();
  const [form] = Form.useForm();
  const [addForm] = Form.useForm();
  const [editingKey, setEditingKey] = useState<string>('');
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set());
  const [autoSaving, setAutoSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [originalData, setOriginalData] = useState<Record<string, HouseholdInfo>>({});
  const autoSaveTimerRef = React.useRef<NodeJS.Timeout | null>(null);

  // Add household modal state
  const [isAddModalVisible, setIsAddModalVisible] = useState(false);
  const [isAdding, setIsAdding] = useState(false);

  const isEditing = (record: HouseholdInfo) => record.id === editingKey;

  // Auto-save effect
  React.useEffect(() => {
    if (editingKey) {
      // Clear existing timer
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }

      // Set new timer for 2 minutes (120000ms)
      autoSaveTimerRef.current = setTimeout(() => {
        handleAutoSave();
      }, 120000); // 2 minutes

      return () => {
        if (autoSaveTimerRef.current) {
          clearTimeout(autoSaveTimerRef.current);
        }
      };
    }
  }, [editingKey, form]);

  const handleAutoSave = async () => {
    if (!editingKey) return;

    try {
      const row = await form.validateFields();
      setAutoSaving(true);

      // Perform save
      const updateData = { ...row };
      const originalRecord = households.find(h => h.id === editingKey);

      if (originalRecord) {
        if (row.firewood_demand_bhari !== undefined &&
            Number(row.firewood_demand_bhari) !== Number(originalRecord.firewood_demand_bhari)) {
          updateData.firewood_auto_calculated = false;
        }
        if (row.grass_demand_bhari !== undefined &&
            Number(row.grass_demand_bhari) !== Number(originalRecord.grass_demand_bhari)) {
          updateData.grass_auto_calculated = false;
        }
        if (row.bedding_demand_bhari !== undefined &&
            Number(row.bedding_demand_bhari) !== Number(originalRecord.bedding_demand_bhari)) {
          updateData.bedding_auto_calculated = false;
        }
      }

      await api.userGroupApi.updateHousehold(editingKey, updateData);

      setLastSaved(new Date());
      message.success(t('household.msgAutoSaved'), 2);
      setOriginalData(prev => {
        const newData = { ...prev };
        delete newData[editingKey];
        return newData;
      });
      onRefresh();
    } catch (error: any) {
      console.error('Auto-save error:', error);
      message.warning(t('household.msgAutoSaveFailed'), 3);
    } finally {
      setAutoSaving(false);
    }
  };

  const edit = (record: HouseholdInfo) => {
    form.setFieldsValue({
      house_no: record.house_no,
      surname: record.surname,
      household_head_male: record.household_head_male,
      household_head_female: record.household_head_female,
      address_tole: record.address_tole,
      female_count: record.female_count,
      male_count: record.male_count,
      land_area: record.land_area ? Number(record.land_area) : undefined,
      land_unit: record.land_unit,
      cow_ox_count: record.cow_ox_count,
      buffalo_count: record.buffalo_count,
      goat_sheep_count: record.goat_sheep_count,
      timber_demand_cft: Number(record.timber_demand_cft),
      pole_demand: record.pole_demand,
      firewood_demand_bhari: record.firewood_demand_bhari ? Number(record.firewood_demand_bhari) : undefined,
      grass_demand_bhari: record.grass_demand_bhari ? Number(record.grass_demand_bhari) : undefined,
      bedding_demand_bhari: record.bedding_demand_bhari ? Number(record.bedding_demand_bhari) : undefined,
      caste_classification_ne: record.caste_classification_ne,
      prosperity_level: record.prosperity_level,
      forest_based_occupation: record.forest_based_occupation,
      remarks: record.remarks,
    });
    setOriginalData(prev => ({ ...prev, [record.id]: record }));
    setEditingKey(record.id);
  };

  const revertChanges = (record: HouseholdInfo) => {
    const original = originalData[record.id];
    if (original) {
      form.setFieldsValue({
        house_no: original.house_no,
        surname: original.surname,
        household_head_male: original.household_head_male,
        household_head_female: original.household_head_female,
        address_tole: original.address_tole,
        female_count: original.female_count,
        male_count: original.male_count,
        land_area: original.land_area ? Number(original.land_area) : undefined,
        land_unit: original.land_unit,
        cow_ox_count: original.cow_ox_count,
        buffalo_count: original.buffalo_count,
        goat_sheep_count: original.goat_sheep_count,
        timber_demand_cft: Number(original.timber_demand_cft),
        pole_demand: original.pole_demand,
        firewood_demand_bhari: original.firewood_demand_bhari ? Number(original.firewood_demand_bhari) : undefined,
        grass_demand_bhari: original.grass_demand_bhari ? Number(original.grass_demand_bhari) : undefined,
        bedding_demand_bhari: original.bedding_demand_bhari ? Number(original.bedding_demand_bhari) : undefined,
        caste_classification_ne: original.caste_classification_ne,
        prosperity_level: original.prosperity_level,
        forest_based_occupation: original.forest_based_occupation,
        remarks: original.remarks,
      });
      message.info(t('household.msgReverted'));
    }
  };

  const cancel = () => {
    setEditingKey('');
    setLastSaved(null);
    setOriginalData(prev => {
      const newData = { ...prev };
      delete newData[editingKey];
      return newData;
    });
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }
  };

  const save = async (id: string) => {
    try {
      const row = await form.validateFields();
      setSavingIds((prev) => new Set(prev).add(id));

      const updateData: any = { ...row };

      // Handle auto-calculated field flags
      const originalRecord = households.find(h => h.id === id);
      if (originalRecord) {
        if (row.firewood_demand_bhari !== undefined &&
            Number(row.firewood_demand_bhari) !== Number(originalRecord.firewood_demand_bhari)) {
          updateData.firewood_auto_calculated = false;
        }
        if (row.grass_demand_bhari !== undefined &&
            Number(row.grass_demand_bhari) !== Number(originalRecord.grass_demand_bhari)) {
          updateData.grass_auto_calculated = false;
        }
        if (row.bedding_demand_bhari !== undefined &&
            Number(row.bedding_demand_bhari) !== Number(originalRecord.bedding_demand_bhari)) {
          updateData.bedding_auto_calculated = false;
        }
        if (row.prosperity_level !== undefined &&
            row.prosperity_level !== originalRecord.prosperity_level) {
          updateData.prosperity_auto_suggested = false;
        }
        if (row.caste_classification_ne !== undefined &&
            row.caste_classification_ne !== originalRecord.caste_classification_ne) {
          updateData.caste_classification_manual = true;
        }
        if (row.forest_based_occupation !== undefined &&
            row.forest_based_occupation !== originalRecord.forest_based_occupation) {
          // No flag needed, just save the value
        }
      }

      console.log('Saving household:', id, updateData);
      try {
        const response = await api.userGroupApi.updateHousehold(id, updateData);
        console.log('Save response:', response);
      } catch (saveError: any) {
        console.error('Save error details:', saveError);
        throw saveError;
      }

      message.success(t('household.msgUpdated'));
      setEditingKey('');
      setLastSaved(null);
      setOriginalData(prev => {
        const newData = { ...prev };
        delete newData[id];
        return newData;
      });
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }
      onRefresh();
    } catch (error: any) {
      if (error?.errorFields) {
        message.error(t('household.msgFillRequired'));
      } else {
        console.error('Error updating household:', error);
        message.error(apiErrorText(error, t('household.msgUpdateFailed')));
      }
    } finally {
      setSavingIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(id);
        return newSet;
      });
    }
  };

  const handleDelete = async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try {
      await api.userGroupApi.deleteHousehold(id);
      message.success(t('household.msgDeleted'));
      onRefresh();
    } catch (error) {
      console.error('Error deleting household:', error);
      message.error(t('household.msgDeleteOneFailed'));
    } finally {
      setDeletingIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(id);
        return newSet;
      });
    }
  };

  const handleShowAddModal = () => {
    addForm.resetFields();
    // Set default values
    addForm.setFieldsValue({
      land_unit: 'ropani',
      cow_ox_count: 0,
      buffalo_count: 0,
      goat_sheep_count: 0,
      timber_demand_cft: 0,
      pole_demand: 0,
      forest_based_occupation: false,
    });
    setIsAddModalVisible(true);
  };

  const handleAddCancel = () => {
    setIsAddModalVisible(false);
    addForm.resetFields();
  };

  const handleAdd = async (values: any) => {
    setIsAdding(true);
    try {
      // Prepare the data
      const addData = {
        ...values,
        // Convert numeric values
        house_no: Number(values.house_no),
        female_count: Number(values.female_count),
        male_count: Number(values.male_count),
        land_area: values.land_area ? Number(values.land_area) : 0,
        cow_ox_count: values.cow_ox_count || 0,
        buffalo_count: values.buffalo_count || 0,
        goat_sheep_count: values.goat_sheep_count || 0,
        timber_demand_cft: values.timber_demand_cft || 0,
        pole_demand: values.pole_demand || 0,
        firewood_demand_bhari: values.firewood_demand_bhari || undefined,
        grass_demand_bhari: values.grass_demand_bhari || undefined,
        bedding_demand_bhari: values.bedding_demand_bhari || undefined,
      };

      await api.userGroupApi.createHousehold(calculationId, addData);
      message.success(t('household.add.msgAdded'));
      setIsAddModalVisible(false);
      addForm.resetFields();
      onRefresh();
    } catch (error: any) {
      console.error('Error adding household:', error);
      message.error(apiErrorText(error, t('household.msgAddFailed')));
    } finally {
      setIsAdding(false);
    }
  };

  const columns: (ColumnsType<HouseholdInfo>[number] & { selectOptions?: { label: string; value: any }[] })[] = [
    {
      title: t('household.col.houseNo'),
      dataIndex: 'house_no',
      key: 'house_no',
      width: 90,
      fixed: 'left',
      sorter: (a, b) => a.house_no - b.house_no,
      render: (value: number, record: HouseholdInfo) => (
        <Tag color="blue">{value}</Tag>
      ),
    },
    {
      title: t('household.field.surname'),
      dataIndex: 'surname',
      key: 'surname',
      width: 150,
      fixed: 'left',
    },
    {
      title: t('household.col.maleHead'),
      dataIndex: 'household_head_male',
      key: 'household_head_male',
      width: 150,
      ellipsis: true,
    },
    {
      title: t('household.col.femaleHead'),
      dataIndex: 'household_head_female',
      key: 'household_head_female',
      width: 150,
      ellipsis: true,
    },
    {
      title: t('household.col.address'),
      dataIndex: 'address_tole',
      key: 'address_tole',
      width: 150,
      ellipsis: true,
    },
    {
      title: t('household.col.female'),
      dataIndex: 'female_count',
      key: 'female_count',
      width: 90,
    },
    {
      title: t('household.col.male'),
      dataIndex: 'male_count',
      key: 'male_count',
      width: 90,
    },
    {
      title: t('household.col.landArea'),
      dataIndex: 'land_area',
      key: 'land_area',
      width: 120,
      render: (value: any, record: HouseholdInfo) =>
        value ? `${Number(value).toFixed(2)} ${record.land_unit || ''}` : '-',
    },
    {
      title: t('household.col.landUnit'),
      dataIndex: 'land_unit',
      key: 'land_unit',
      width: 110,
      selectOptions: [
        { label: t('household.ropani'), value: 'ropani' },
        { label: t('household.kaththa'), value: 'kaththa' },
      ],
    },
    {
      title: t('household.col.cowOx'),
      dataIndex: 'cow_ox_count',
      key: 'cow_ox_count',
      width: 90,
    },
    {
      title: t('household.col.buffalo'),
      dataIndex: 'buffalo_count',
      key: 'buffalo_count',
      width: 90,
    },
    {
      title: t('household.col.goatSheep'),
      dataIndex: 'goat_sheep_count',
      key: 'goat_sheep_count',
      width: 110,
    },
    {
      title: t('household.col.firewood'),
      dataIndex: 'firewood_demand_bhari',
      key: 'firewood_demand_bhari',
      width: 140,
      render: (value: any, record: HouseholdInfo) => (
        <Space>
          <span>{value ? Number(value).toFixed(1) : '0.0'}</span>
          {record.firewood_auto_calculated !== false ? (
            <Tag icon={<ReloadOutlined />} color="green">Auto</Tag>
          ) : (
            <Tag icon={<EditOutlined />} color="orange">{t('household.tagManual')}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: t('household.col.grass'),
      dataIndex: 'grass_demand_bhari',
      key: 'grass_demand_bhari',
      width: 140,
      render: (value: any, record: HouseholdInfo) => (
        <Space>
          <span>{value ? Number(value).toFixed(1) : '0.0'}</span>
          {record.grass_auto_calculated !== false ? (
            <Tag icon={<ReloadOutlined />} color="green">Auto</Tag>
          ) : (
            <Tag icon={<EditOutlined />} color="orange">{t('household.tagManual')}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: t('household.col.bedding'),
      dataIndex: 'bedding_demand_bhari',
      key: 'bedding_demand_bhari',
      width: 140,
      render: (value: any, record: HouseholdInfo) => (
        <Space>
          <span>{value ? Number(value).toFixed(1) : '0.0'}</span>
          {record.bedding_auto_calculated !== false ? (
            <Tag icon={<ReloadOutlined />} color="green">Auto</Tag>
          ) : (
            <Tag icon={<EditOutlined />} color="orange">{t('household.tagManual')}</Tag>
          )}
        </Space>
      ),
    },
    {
      title: t('household.col.timber'),
      dataIndex: 'timber_demand_cft',
      key: 'timber_demand_cft',
      width: 110,
      render: (value: any) => Number(value).toFixed(1),
    },
    {
      title: t('household.col.poles'),
      dataIndex: 'pole_demand',
      key: 'pole_demand',
      width: 90,
    },
    {
      title: t('household.col.caste'),
      dataIndex: 'caste_classification_ne',
      key: 'caste_classification_ne',
      width: 180,
      selectOptions: [
        { label: t('household.caste.janajati'), value: 'जनजाती' },
        { label: t('household.caste.dalit'), value: 'दलित' },
        { label: t('household.caste.marginalised'), value: 'सीमान्तकृत' },
        { label: t('household.caste.highlyMarginalised'), value: 'अति सीमान्तकृत' },
        { label: t('household.caste.endangered'), value: 'लोपोन्मुख र सीमान्तकृत' },
        { label: t('household.caste.other'), value: 'अन्य' },
      ],
      render: (value: string, record: HouseholdInfo) => (
        <Space direction="vertical" size={0}>
          <Tag color={record.caste_classification_manual === true ? 'orange' : 'green'}>
            {value || 'N/A'}
          </Tag>
          {record.caste_classification_manual === true && (
            <Tag icon={<EditOutlined />} color="orange" style={{ fontSize: 10 }}>
              {t('household.manual')}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: t('household.col.prosperity'),
      dataIndex: 'prosperity_level',
      key: 'prosperity_level',
      width: 130,
      selectOptions: [
        { label: t('household.prosperity.veryPoor'), value: 'अति विपन्न' },
        { label: t('household.prosperity.poor'), value: 'विपन्न' },
        { label: t('household.prosperity.medium'), value: 'मध्यम' },
        { label: t('household.prosperity.wellOff'), value: 'सम्पन्न' },
      ],
      render: (value: string, record: HouseholdInfo) => {
        const colorMap: Record<string, string> = {
          'सम्पन्न': 'green',
          'मध्यम': 'blue',
          'विपन्न': 'orange',
          'अति विपन्न': 'red',
        };
        return (
          <Space direction="vertical" size={0}>
            <Tag color={colorMap[value] || 'default'}>{value}</Tag>
            {record.prosperity_auto_suggested !== false && (
              <Tag color="green" style={{ fontSize: 10 }}>{t('household.tagAuto')}</Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: t('household.col.forestOccupation'),
      dataIndex: 'forest_based_occupation',
      key: 'forest_occupation',
      width: 120,
      selectOptions: [
        { label: t('household.yes'), value: true },
        { label: t('household.no'), value: false },
      ],
      render: (value: boolean, record: HouseholdInfo) =>
        record.forest_based_occupation ? (
          <Tag color="green">{t('common.yes')}</Tag>
        ) : (
          <Tag>No</Tag>
        ),
    },
    {
      title: t('household.col.remarks'),
      dataIndex: 'remarks',
      key: 'remarks',
      width: 150,
      ellipsis: true,
    },
    {
      title: t('household.col.actions'),
      key: 'actions',
      width: 280,
      fixed: 'right',
      render: (_: any, record: HouseholdInfo) => {
        const editable = isEditing(record);
        return editable ? (
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <Space>
              <Button
                type="primary"
                size="small"
                icon={<SaveOutlined />}
                onClick={() => save(record.id)}
                loading={savingIds.has(record.id)}
              >
                {t('household.save')}
              </Button>
              <Tooltip title={t('household.revertTooltip')}>
                <Button 
                  size="small" 
                  icon={<ReloadOutlined />} 
                  onClick={() => revertChanges(record)}
                  disabled={!originalData[record.id]}
                >
                  {t('household.revert')}
                </Button>
              </Tooltip>
              <Button size="small" icon={<CloseOutlined />} onClick={cancel}>
                {t('household.cancel')}
              </Button>
            </Space>
            {autoSaving && (
              <Tag color="processing" icon={<ReloadOutlined spin />} style={{ margin: 0 }}>
                {t('household.autoSaving')}
              </Tag>
            )}
          </Space>
        ) : (
          <Space>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => edit(record)}
              disabled={editingKey !== ''}
            >
              {t('household.edit')}
            </Button>
            <Popconfirm
              title={t('household.confirmDelete')}
              description={t('household.confirmDeleteHint')}
              onConfirm={() => handleDelete(record.id)}
              okText={t('household.yes')}
              cancelText={t('household.no')}
            >
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                loading={deletingIds.has(record.id)}
                disabled={editingKey !== ''}
              >
                {t('household.delete')}
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  const mergedColumns = columns.map((col: any) => {
    if (!col.editable) {
      return col;
    }
    const selectFields = ['land_unit', 'prosperity_level', 'caste_classification_ne', 'forest_occupation'];
    const numberFields = ['female_count', 'male_count', 'cow_ox_count', 'buffalo_count', 'goat_sheep_count',
                    'timber_demand_cft', 'pole_demand', 'land_area', 'firewood_demand_bhari',
                    'grass_demand_bhari', 'bedding_demand_bhari', 'house_no'];
    return {
      ...col,
      onCell: (record: HouseholdInfo) => ({
        record,
        inputType: selectFields.includes(col.dataIndex) ? 'select' :
                   numberFields.includes(col.dataIndex) ? 'number' : 'text',
        dataIndex: col.dataIndex,
        title: col.title,
        editing: isEditing(record),
        selectOptions: col.selectOptions,
      }),
    };
  });

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <Space wrap>
          <Tag color="blue">💡 Click "Edit" to modify any row (Excel-like editing)</Tag>
          <Tag color="green" icon={<ReloadOutlined />}>{t('household.tagAutoCalculated')}</Tag>
          <Tag color="orange" icon={<EditOutlined />}>{t('household.tagManuallyEntered')}</Tag>
        </Space>
        <Space>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleShowAddModal}
            disabled={editingKey !== ''}
          >
            {t('household.add.submit')}
          </Button>
          {editingKey && (
            <Tag color="purple" icon={autoSaving ? <ReloadOutlined spin /> : <ReloadOutlined />}>
              {autoSaving ? t('household.autoSaving') : t('household.autoSaveEvery')}
            </Tag>
          )}
          {lastSaved && (
            <Tag color="green">
              Last saved: {lastSaved.toLocaleTimeString()}
            </Tag>
          )}
        </Space>
      </div>

      <p className="text-xs text-gray-400 font-mono mb-1">{'{{hh_records}}'}</p>

      <Form form={form} component={false}>
        <Table
          components={{
            body: {
              cell: EditableCell,
            },
          }}
          dataSource={households}
          columns={mergedColumns}
          rowKey="id"
          scroll={{ x: 2800, y: 600 }}
          pagination={{
            pageSize: 20,
            showSizeChanger: true,
            showTotal: (total) => `Total ${total} households`,
            onChange: cancel,
          }}
          size="small"
          bordered
        />
      </Form>

      {/* Variable Panel + Notes Section */}
      <div style={{ marginTop: 24, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 60%', minWidth: 300 }}>
          <div style={{
            border: '1px solid #d9d9d9',
            borderRadius: 6,
            padding: 12,
            background: '#fafafa',
          }}>
            <h4 style={{ margin: '0 0 8px 0', fontSize: 13 }}>
              {t('household.summary.additionalNotes')}
            </h4>
            <textarea
              id="household-notes"
              rows={4}
              style={{
                width: '100%',
                border: '1px solid #d9d9d9',
                borderRadius: 4,
                padding: '8px 12px',
                fontSize: 13,
                lineHeight: 1.6,
                fontFamily: 'inherit',
                resize: 'vertical',
              }}
              placeholder={t('household.insertHint')}
            />
          </div>
        </div>
        <div style={{ flex: '0 0 340px' }}>
          <HouseholdVariablePanel
            calculationId={calculationId}
            tabKey="households"
            onInsert={(varStr) => {
              const ta = document.getElementById('household-notes') as HTMLTextAreaElement;
              if (ta) {
                const start = ta.selectionStart;
                const end = ta.selectionEnd;
                ta.value = ta.value.substring(0, start) + varStr + ta.value.substring(end);
                ta.focus();
                ta.selectionStart = ta.selectionEnd = start + varStr.length;
              }
            }}
          />
        </div>
      </div>

      {/* Add Household Modal */}
      <Modal
        title={t('household.add.title')}
        open={isAddModalVisible}
        onCancel={handleAddCancel}
        footer={null}
        width={800}
        destroyOnHidden
      >
        <Form
          form={addForm}
          layout="vertical"
          onFinish={handleAdd}
        >
          <div style={{ maxHeight: '60vh', overflowY: 'auto', padding: '0 8px' }}>
            {/* Basic Information */}
            <h3 style={{ borderBottom: '1px solid #d9d9d9', paddingBottom: 8 }}>{t('household.group.basic')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <Form.Item
                label={t('household.field.houseNo')}
                name="house_no"
                rules={[{ required: true, message: t('household.add.houseNoRequired') }]}
              >
                <LocaleInputNumber style={{ width: '100%' }} min={1} />
              </Form.Item>

              <Form.Item
                label={t('household.field.surname')}
                name="surname"
                rules={[{ required: true, message: t('household.add.surnameRequired') }]}
              >
                <Input />
              </Form.Item>

              <Form.Item
                label={t('household.field.maleHead')}
                name="household_head_male"
              >
                <Input />
              </Form.Item>

              <Form.Item
                label={t('household.field.femaleHead')}
                name="household_head_female"
              >
                <Input />
              </Form.Item>

              <Form.Item
                label={t('household.field.address')}
                name="address_tole"
              >
                <Input />
              </Form.Item>
            </div>

            {/* Family Members */}
            <h3 style={{ borderBottom: '1px solid #d9d9d9', paddingBottom: 8, marginTop: 16 }}>{t('household.group.family')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <Form.Item
                label={t('household.field.femaleCount')}
                name="female_count"
                rules={[{ required: true, message: t('household.add.femaleCountRequired') }]}
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>

              <Form.Item
                label={t('household.field.maleCount')}
                name="male_count"
                rules={[{ required: true, message: t('household.add.maleCountRequired') }]}
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </div>

            {/* Land & Livestock */}
            <h3 style={{ borderBottom: '1px solid #d9d9d9', paddingBottom: 8, marginTop: 16 }}>{t('household.group.land')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <Form.Item
                label={t('household.field.landArea')}
                name="land_area"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} step={0.01} />
              </Form.Item>

              <Form.Item
                label={t('household.field.landUnit')}
                name="land_unit"
              >
                <Select>
                  <Select.Option value="ropani">{t('units.ropani')}</Select.Option>
                  <Select.Option value="kaththa">{t('units.kaththa')}</Select.Option>
                </Select>
              </Form.Item>

              <Form.Item
                label={t('household.field.cowOx')}
                name="cow_ox_count"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>

              <Form.Item
                label={t('household.field.buffalo')}
                name="buffalo_count"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>

              <Form.Item
                label={t('household.field.goatSheep')}
                name="goat_sheep_count"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>
            </div>

            {/* Forest Product Demand */}
            <h3 style={{ borderBottom: '1px solid #d9d9d9', paddingBottom: 8, marginTop: 16 }}>{t('household.group.demand')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <Form.Item
                label={t('household.field.timberDemand')}
                name="timber_demand_cft"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} step={0.1} />
              </Form.Item>

              <Form.Item
                label={t('household.field.poleDemand')}
                name="pole_demand"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} />
              </Form.Item>

              <Form.Item
                label={t('household.field.firewoodDemand')}
                name="firewood_demand_bhari"
                extra="Leave blank for auto-calculation"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} step={0.1} />
              </Form.Item>

              <Form.Item
                label={t('household.field.grassDemand')}
                name="grass_demand_bhari"
                extra="Leave blank for auto-calculation"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} step={0.1} />
              </Form.Item>

              <Form.Item
                label={t('household.field.beddingDemand')}
                name="bedding_demand_bhari"
                extra="Leave blank for auto-calculation"
              >
                <LocaleInputNumber style={{ width: '100%' }} min={0} step={0.1} />
              </Form.Item>
            </div>

            {/* Classification */}
            <h3 style={{ borderBottom: '1px solid #d9d9d9', paddingBottom: 8, marginTop: 16 }}>{t('household.group.classification')}</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <Form.Item
                label={t('household.field.casteClassification')}
                name="caste_classification_ne"
              >
                <Select>
                  <Select.Option value="जनजाती">{t('household.caste.janajati')}</Select.Option>
                  <Select.Option value="दलित">{t('household.caste.dalit')}</Select.Option>
                  <Select.Option value="सीमान्तकृत">{t('household.caste.marginalised')}</Select.Option>
                  <Select.Option value="अति सीमान्तकृत">{t('household.caste.highlyMarginalised')}</Select.Option>
                  <Select.Option value="लोपोन्मुख र सीमान्तकृत">{t('household.caste.endangered')}</Select.Option>
                  <Select.Option value="अन्य">{t('household.caste.other')}</Select.Option>
                </Select>
              </Form.Item>

              <Form.Item
                label={t('household.field.prosperityLevel')}
                name="prosperity_level"
              >
                <Select>
                  <Select.Option value="अति विपन्न">{t('household.prosperity.veryPoor')}</Select.Option>
                  <Select.Option value="विपन्न">{t('household.prosperity.poor')}</Select.Option>
                  <Select.Option value="मध्यम">{t('household.prosperity.medium')}</Select.Option>
                  <Select.Option value="सम्पन्न">{t('household.prosperity.wellOff')}</Select.Option>
                </Select>
              </Form.Item>

              <Form.Item
                label={t('household.field.forestOccupation')}
                name="forest_based_occupation"
              >
                <Select>
                  <Select.Option value={true}>Yes</Select.Option>
                  <Select.Option value={false}>No</Select.Option>
                </Select>
              </Form.Item>
            </div>

            {/* Remarks */}
            <h3 style={{ borderBottom: '1px solid #d9d9d9', paddingBottom: 8, marginTop: 16 }}>{t('household.group.additional')}</h3>
            <Form.Item
              label={t('household.field.remarks')}
              name="remarks"
            >
              <Input.TextArea rows={3} />
            </Form.Item>
          </div>

          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end', gap: '8px', borderTop: '1px solid #d9d9d9', paddingTop: 16 }}>
            <Button onClick={handleAddCancel}>
              {t('household.cancel')}
            </Button>
            <Button type="primary" htmlType="submit" loading={isAdding}>
              {t('household.add.submit')}
            </Button>
          </div>
        </Form>
      </Modal>
    </div>
  );
});

export default HouseholdDataTable;
