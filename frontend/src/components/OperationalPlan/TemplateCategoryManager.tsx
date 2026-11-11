/** CRUD manager for template categories — allows grouping and color-coding operational plan templates. */
import React, { useState, useEffect } from 'react';
import { Table, Button, Modal, Input, Form, message, Space, Tag, Popconfirm, Tooltip, ColorPicker } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, SortAscendingOutlined } from '@ant-design/icons';
import { operationalPlanApi } from '../../services/api';
import { useT } from '../../i18n/hooks';

const { TextArea } = Input;

interface Category {
  id: string;
  key: string;
  label_ne: string;
  label_en: string;
  description: string;
  color: string;
  sort_order: number;
}

const TemplateCategoryManager: React.FC = () => {

  const t = useT();  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCategories();
  }, []);

  const fetchCategories = async () => {
    setLoading(true);
    try {
      const data = await operationalPlanApi.listTemplateCategories();
      setCategories(data || []);
    } catch {
      message.error(t('operationalPlan.category.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (cat: Category) => {
    setEditing(cat);
    form.setFieldsValue(cat);
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await operationalPlanApi.updateTemplateCategory(editing.id, values);
        message.success(t('operationalPlan.category.msgUpdated'));
      } else {
        await operationalPlanApi.createTemplateCategory(values);
        message.success(t('operationalPlan.category.msgCreated'));
      }
      setModalOpen(false);
      fetchCategories();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('operationalPlan.category.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await operationalPlanApi.deleteTemplateCategory(id);
      message.success(t('operationalPlan.category.msgDeleted'));
      fetchCategories();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('operationalPlan.category.deleteFailed'));
    }
  };

  const columns = [
    {
      title: t('operationalPlan.category.sort'),
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 60,
    },
    {
      title: t('operationalPlan.category.key'),
      dataIndex: 'key',
      key: 'key',
      width: 120,
    },
    {
      title: t('operationalPlan.category.labelEn'),
      dataIndex: 'label_en',
      key: 'label_en',
    },
    {
      title: t('operationalPlan.category.labelNe'),
      dataIndex: 'label_ne',
      key: 'label_ne',
    },
    {
      title: t('operationalPlan.category.color'),
      dataIndex: 'color',
      key: 'color',
      width: 100,
      render: (color: string) => <Tag color={color || 'default'}>{color || 'default'}</Tag>,
    },
    {
      title: t('operationalPlan.category.description'),
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: t('operationalPlan.category.actions'),
      key: 'actions',
      width: 120,
      render: (_: any, record: Category) => (
        <Space>
          <Tooltip title={t('operationalPlan.category.edit')}>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Popconfirm title={t('operationalPlan.category.confirmDelete')} onConfirm={() => handleDelete(record.id)}>
            <Tooltip title={t('operationalPlan.category.delete')}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>
          <SortAscendingOutlined style={{ marginRight: 8 }} />
          <strong>{categories.length}</strong> categories defined
        </span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          {t('operationalPlan.category.add')}
        </Button>
      </div>

      <Table
        dataSource={categories}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
      />

      <Modal
        title={editing ? t('operationalPlan.category.edit') : t('operationalPlan.category.create')}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={editing ? t('operationalPlan.category.update') : t('operationalPlan.category.createAction')}
        width={520}
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <Form.Item name="key" label={t('operationalPlan.category.key')} rules={[{ required: true, message: t('operationalPlan.category.keyHint') }]}>
              <Input placeholder="community_forest" />
            </Form.Item>
          )}
          <Form.Item name="label_en" label={t('operationalPlan.category.labelEnFull')} rules={[{ required: true }]}>
            <Input placeholder="Community Forest" />
          </Form.Item>
          <Form.Item name="label_ne" label={t('operationalPlan.category.labelNeFull')} rules={[{ required: true }]}>
            <Input placeholder="सामुदायिक वन" />
          </Form.Item>
          <Form.Item name="description" label={t('operationalPlan.category.description')}>
            <TextArea rows={2} placeholder={t('operationalPlan.category.descHint')} />
          </Form.Item>
          <Space>
            <Form.Item name="color" label={t('operationalPlan.category.tagColor')}>
              <Input placeholder="green, blue, purple, orange, red" />
            </Form.Item>
            <Form.Item name="sort_order" label={t('operationalPlan.category.sortOrder')}>
              <Input type="text" inputMode="decimal" style={{ width: 80 }} placeholder="0" />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  );
};

export default TemplateCategoryManager;
