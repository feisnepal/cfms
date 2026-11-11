/** Committee management UI — create, edit, and delete forest user-group committee members. */
import React, { useState, useEffect } from 'react';
import { Table, Button, Select, Input, message, Alert, Space, Popconfirm, Card, Progress, Tag, Collapse, Divider } from 'antd';
import { PlusOutlined, DeleteOutlined, SaveOutlined, WarningOutlined, CheckCircleOutlined, CodeOutlined } from '@ant-design/icons';
import { userGroupApi } from '../../services/api';
import HouseholdVariablePanel from './HouseholdVariablePanel';
import { useT } from '../../i18n/hooks';

const { Option } = Select;
const { Panel } = Collapse;

interface CommitteeMember {
  id?: string;
  serial_no: number;
  name: string;
  address: string;
  mobile?: string;
}

interface MainCommitteeMember extends CommitteeMember {
  gender: string;
  position: string;
  caste_category: string;
}

interface CommitteeData {
  main_committee: MainCommitteeMember[];
  advisory_committee: CommitteeMember[];
  financial_committee: CommitteeMember[];
  summary?: {
    main_committee_size: number;
    main_committee_women: number;
    main_committee_men: number;
    women_percentage: number;
    meets_50_percent_rule: boolean;
    positions_filled: { [key: string]: string };
    positions_unfilled: string[];
    key_position_warnings: string[];
    validation_warnings: string[];
    advisory_committee_size: number;
    financial_committee_size: number;
  };
}

interface CommitteeManagementProps {
  calculationId: string;
}

const GENDERS = ['महिला', 'पुरूष'];
const POSITIONS = ['अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव', 'सदस्य'];
const CASTE_CATEGORIES = ['जनजाती', 'आदिवासी', 'दलित', 'सिमान्तकृत', 'अन्य'];

/** Display keys for the persisted committee option values above. */
const OPTION_LABEL_KEY: Record<string, string> = {
  'महिला': 'committee.gender.female',
  'पुरूष': 'committee.gender.male',
  'अध्यक्ष': 'committee.position.chairperson',
  'उपाध्यक्ष': 'committee.position.viceChairperson',
  'कोषाध्यक्ष': 'committee.position.treasurer',
  'सह कोषाध्यक्ष': 'committee.position.jointTreasurer',
  'सचिव': 'committee.position.secretary',
  'सह सचिव': 'committee.position.jointSecretary',
  'सदस्य': 'committee.position.member',
  'जनजाती': 'committee.caste.janajati',
  'आदिवासी': 'committee.caste.adivasi',
  'दलित': 'committee.caste.dalit',
  'सिमान्तकृत': 'committee.caste.marginalised',
  'अन्य': 'committee.caste.other',
};

const CommitteeManagement = React.memo(({ calculationId }: CommitteeManagementProps) => {
  const t = useT();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<CommitteeData>({
    main_committee: [],
    advisory_committee: [],
    financial_committee: [],
  });

  const [editingKey, setEditingKey] = useState<string>('');

  useEffect(() => {
    loadCommittees();
  }, [calculationId]);

  const loadCommittees = async () => {
    setLoading(true);
    try {
      const response = await userGroupApi.getAllCommittees(calculationId);
      setData(response);
    } catch (error: any) {
      if (error.response?.status !== 404) {
        console.error('Error loading committees:', error);
        message.error(t('committee.msgLoadFailed'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        main_committee: data.main_committee.map(({ id, ...rest }) => rest),
        advisory_committee: data.advisory_committee.map(({ id, ...rest }) => rest),
        financial_committee: data.financial_committee.map(({ id, ...rest }) => rest),
      };

      await userGroupApi.createCommitteesBulk(calculationId, payload);
      message.success(t('committee.msgSaved'));
      loadCommittees();
    } catch (error: any) {
      console.error('Error saving committees:', error);
      const errorDetail = error.response?.data?.detail;
      const errorMsg = typeof errorDetail === 'string'
        ? errorDetail
        : Array.isArray(errorDetail)
        ? errorDetail.map((e: any) => e.msg || JSON.stringify(e)).join(', ')
        : 'Failed to save committee data';
      message.error(errorMsg);
    } finally {
      setSaving(false);
    }
  };

  const addMainMember = () => {
    if (data.main_committee.length >= 15) {
      message.warning(t('committee.msgMaxMain'));
      return;
    }

    const newMember: MainCommitteeMember = {
      serial_no: data.main_committee.length + 1,
      gender: 'महिला',
      position: 'सदस्य',
      caste_category: 'अन्य',
      name: '',
      address: '',
      mobile: '',
    };

    setData({
      ...data,
      main_committee: [...data.main_committee, newMember],
    });
  };

  const addAdvisoryMember = () => {
    if (data.advisory_committee.length >= 10) {
      message.warning(t('committee.msgMaxAdvisory'));
      return;
    }

    const newMember: CommitteeMember = {
      serial_no: data.advisory_committee.length + 1,
      name: '',
      address: '',
      mobile: '',
    };

    setData({
      ...data,
      advisory_committee: [...data.advisory_committee, newMember],
    });
  };

  const addFinancialMember = () => {
    if (data.financial_committee.length >= 10) {
      message.warning(t('committee.msgMaxFinancial'));
      return;
    }

    const newMember: CommitteeMember = {
      serial_no: data.financial_committee.length + 1,
      name: '',
      address: '',
      mobile: '',
    };

    setData({
      ...data,
      financial_committee: [...data.financial_committee, newMember],
    });
  };

  const deleteMainMember = (index: number) => {
    const newMembers = data.main_committee.filter((_, i) => i !== index);
    // Renumber serial_no
    newMembers.forEach((member, i) => {
      member.serial_no = i + 1;
    });
    setData({ ...data, main_committee: newMembers });
  };

  const deleteAdvisoryMember = (index: number) => {
    const newMembers = data.advisory_committee.filter((_, i) => i !== index);
    newMembers.forEach((member, i) => {
      member.serial_no = i + 1;
    });
    setData({ ...data, advisory_committee: newMembers });
  };

  const deleteFinancialMember = (index: number) => {
    const newMembers = data.financial_committee.filter((_, i) => i !== index);
    newMembers.forEach((member, i) => {
      member.serial_no = i + 1;
    });
    setData({ ...data, financial_committee: newMembers });
  };

  const updateMainMember = (index: number, field: keyof MainCommitteeMember, value: any) => {
    const newMembers = [...data.main_committee];
    newMembers[index] = { ...newMembers[index], [field]: value };
    setData({ ...data, main_committee: newMembers });
  };

  const updateAdvisoryMember = (index: number, field: string, value: any) => {
    const newMembers = [...data.advisory_committee];
    newMembers[index] = { ...newMembers[index], [field]: value };
    setData({ ...data, advisory_committee: newMembers });
  };

  const updateFinancialMember = (index: number, field: string, value: any) => {
    const newMembers = [...data.financial_committee];
    newMembers[index] = { ...newMembers[index], [field]: value };
    setData({ ...data, financial_committee: newMembers });
  };

  // Main Committee Columns
  const mainColumns = [
    {
      title: t('committee.col.sn'),
      dataIndex: 'serial_no',
      key: 'serial_no',
      width: 70,
      align: 'center' as const,
    },
    {
      title: t('committee.col.gender'),
      dataIndex: 'gender',
      key: 'gender',
      width: 120,
      render: (text: string, record: MainCommitteeMember, index: number) => (
        <Select
          value={text}
          onChange={(value) => updateMainMember(index, 'gender', value)}
          style={{ width: '100%' }}
        >
          {GENDERS.map((g) => (
            <Option key={g} value={g}>
              {OPTION_LABEL_KEY[g] ? t(OPTION_LABEL_KEY[g]) : g}
            </Option>
          ))}
        </Select>
      ),
    },
    {
      title: t('committee.col.position'),
      dataIndex: 'position',
      key: 'position',
      width: 150,
      render: (text: string, record: MainCommitteeMember, index: number) => (
        <Select
          value={text}
          onChange={(value) => updateMainMember(index, 'position', value)}
          style={{ width: '100%' }}
        >
          {POSITIONS.map((p) => (
            <Option key={p} value={p}>
              {OPTION_LABEL_KEY[p] ? t(OPTION_LABEL_KEY[p]) : p}
            </Option>
          ))}
        </Select>
      ),
    },
    {
      title: t('committee.col.caste'),
      dataIndex: 'caste_category',
      key: 'caste_category',
      width: 150,
      render: (text: string, record: MainCommitteeMember, index: number) => (
        <Select
          value={text}
          onChange={(value) => updateMainMember(index, 'caste_category', value)}
          style={{ width: '100%' }}
        >
          {CASTE_CATEGORIES.map((c) => (
            <Option key={c} value={c}>
              {OPTION_LABEL_KEY[c] ? t(OPTION_LABEL_KEY[c]) : c}
            </Option>
          ))}
        </Select>
      ),
    },
    {
      title: t('committee.col.name'),
      dataIndex: 'name',
      key: 'name',
      width: 200,
      render: (text: string, record: MainCommitteeMember, index: number) => (
        <Input
          value={text}
          onChange={(e) => updateMainMember(index, 'name', e.target.value)}
          placeholder={t('committee.col.name')}
        />
      ),
    },
    {
      title: t('committee.col.address'),
      dataIndex: 'address',
      key: 'address',
      width: 200,
      render: (text: string, record: MainCommitteeMember, index: number) => (
        <Input
          value={text}
          onChange={(e) => updateMainMember(index, 'address', e.target.value)}
          placeholder={t('committee.col.address')}
        />
      ),
    },
    {
      title: t('committee.col.mobile'),
      dataIndex: 'mobile',
      key: 'mobile',
      width: 150,
      render: (text: string, record: MainCommitteeMember, index: number) => (
        <Input
          value={text}
          onChange={(e) => updateMainMember(index, 'mobile', e.target.value)}
          placeholder="9841234567"
          maxLength={10}
        />
      ),
    },
    {
      title: t('committee.col.actions'),
      key: 'actions',
      width: 80,
      fixed: 'right' as const,
      render: (_: any, record: MainCommitteeMember, index: number) => (
        <Popconfirm
          title={t('committee.confirmDeleteMember')}
          onConfirm={() => deleteMainMember(index)}
          okText="Yes"
          cancelText="No"
        >
          <Button type="link" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  // Advisory/Financial Committee Columns
  const simpleColumns = (
    updateFn: (index: number, field: string, value: any) => void,
    deleteFn: (index: number) => void
  ) => [
    {
      title: t('committee.col.sn'),
      dataIndex: 'serial_no',
      key: 'serial_no',
      width: 70,
      align: 'center' as const,
    },
    {
      title: t('committee.col.name'),
      dataIndex: 'name',
      key: 'name',
      width: 250,
      render: (text: string, record: CommitteeMember, index: number) => (
        <Input
          value={text}
          onChange={(e) => updateFn(index, 'name', e.target.value)}
          placeholder={t('committee.col.name')}
        />
      ),
    },
    {
      title: t('committee.col.address'),
      dataIndex: 'address',
      key: 'address',
      width: 250,
      render: (text: string, record: CommitteeMember, index: number) => (
        <Input
          value={text}
          onChange={(e) => updateFn(index, 'address', e.target.value)}
          placeholder={t('committee.col.address')}
        />
      ),
    },
    {
      title: t('committee.col.mobile'),
      dataIndex: 'mobile',
      key: 'mobile',
      width: 150,
      render: (text: string, record: CommitteeMember, index: number) => (
        <Input
          value={text}
          onChange={(e) => updateFn(index, 'mobile', e.target.value)}
          placeholder="9841234567"
          maxLength={10}
        />
      ),
    },
    {
      title: t('committee.col.actions'),
      key: 'actions',
      width: 80,
      fixed: 'right' as const,
      render: (_: any, record: CommitteeMember, index: number) => (
        <Popconfirm
          title={t('committee.confirmDeleteMember')}
          onConfirm={() => deleteFn(index)}
          okText="Yes"
          cancelText="No"
        >
          <Button type="link" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ];

  const hasData = data.main_committee.length > 0 || data.advisory_committee.length > 0 || data.financial_committee.length > 0;

  return (
    <div style={{ padding: '20px' }}>
      <div style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>{t('committee.title')}</h2>
        <Space>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
            disabled={!hasData}
          >
            {t('committee.saveAll')}
          </Button>
        </Space>
      </div>

      {/* Validation Summary */}
      {data.summary && data.summary.validation_warnings.length > 0 && (
        <Alert
          message={t('committee.validationWarnings')}
          description={
            <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
              {data.summary.validation_warnings.map((warning, idx) => (
                <li key={idx}>{typeof warning === 'string' ? warning : JSON.stringify(warning)}</li>
              ))}
            </ul>
          }
          type="warning"
          icon={<WarningOutlined />}
          showIcon
          style={{ marginBottom: 20 }}
        />
      )}

      {/* Gender Ratio Indicator */}
      {data.main_committee.length > 0 && (
        <Card size="small" style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <div style={{ flex: 1 }}>
              <div style={{ marginBottom: 5 }}>
                <strong>{t('committee.womenRepresentation')}</strong> {data.main_committee.filter(m => m.gender === 'महिला').length} / {data.main_committee.length} members
              </div>
              <Progress
                percent={Math.round((data.main_committee.filter(m => m.gender === 'महिला').length / data.main_committee.length) * 100)}
                status={(data.main_committee.filter(m => m.gender === 'महिला').length / data.main_committee.length) >= 0.5 ? 'success' : 'exception'}
                format={(percent) => `${percent}%`}
              />
              <div style={{ fontSize: 12, color: '#888', marginTop: 5 }}>
                {t('committee.womenRequirement')}
              </div>
            </div>
            {(data.main_committee.filter(m => m.gender === 'महिला').length / data.main_committee.length) >= 0.5 ? (
              <Tag color="success" icon={<CheckCircleOutlined />}>
                {t('committee.meetsRequirement')}
              </Tag>
            ) : (
              <Tag color="warning" icon={<WarningOutlined />}>
                {t('committee.below50')}
              </Tag>
            )}
          </div>
        </Card>
      )}

      <Collapse defaultActiveKey={['1', '2', '3']} style={{ marginBottom: 20 }}>
        {/* Main Committee */}
        <Panel
          header={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 'bold' }}>
                {t('committee.mainCommittee')} - {data.main_committee.length}
              </span>
            </div>
          }
          key="1"
        >
          <div className="flex gap-2 mb-2">
            <span className="text-xs text-gray-400 font-mono">{'{{uc_members}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{uc_total_members}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{uc_caste_distribution}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{uc_position_distribution}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{uc_gender_distribution}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{section:committee_narration}}'}</span>
          </div>
          <div style={{ marginBottom: 10 }}>
            <Button type="dashed" onClick={addMainMember} icon={<PlusOutlined />} disabled={data.main_committee.length >= 15}>
              {t('committee.addMember')}
            </Button>
          </div>
          <Table
            columns={mainColumns}
            dataSource={data.main_committee}
            rowKey={(_, index) => `main-${index}`}
            pagination={false}
            loading={loading}
            scroll={{ x: 1200 }}
            size="small"
            bordered
          />
        </Panel>

        {/* Advisory Committee */}
        <Panel
          header={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 'bold' }}>
                {t('committee.advisoryCommittee')} - {data.advisory_committee.length}
              </span>
            </div>
          }
          key="2"
        >
          <div className="flex gap-2 mb-2">
            <span className="text-xs text-gray-400 font-mono">{'{{ac_members}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{ac_total_members}}'}</span>
          </div>
          <div style={{ marginBottom: 10 }}>
            <Button type="dashed" onClick={addAdvisoryMember} icon={<PlusOutlined />} disabled={data.advisory_committee.length >= 10}>
              {t('committee.addMember')}
            </Button>
          </div>
          <Table
            columns={simpleColumns(updateAdvisoryMember, deleteAdvisoryMember)}
            dataSource={data.advisory_committee}
            rowKey={(_, index) => `advisory-${index}`}
            pagination={false}
            loading={loading}
            scroll={{ x: 800 }}
            size="small"
            bordered
          />
        </Panel>

        {/* Financial Committee */}
        <Panel
          header={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 'bold' }}>
                {t('committee.financialCommittee')} - {data.financial_committee.length}
              </span>
            </div>
          }
          key="3"
        >
          <div className="flex gap-2 mb-2">
            <span className="text-xs text-gray-400 font-mono">{'{{fc_members}}'}</span>
            <span className="text-xs text-gray-400 font-mono">{'{{fc_total_members}}'}</span>
          </div>
          <div style={{ marginBottom: 10 }}>
            <Button type="dashed" onClick={addFinancialMember} icon={<PlusOutlined />} disabled={data.financial_committee.length >= 10}>
              {t('committee.addMember')}
            </Button>
          </div>
          <Table
            columns={simpleColumns(updateFinancialMember, deleteFinancialMember)}
            dataSource={data.financial_committee}
            rowKey={(_, index) => `financial-${index}`}
            pagination={false}
            loading={loading}
            scroll={{ x: 800 }}
            size="small"
            bordered
          />
        </Panel>
      </Collapse>

      {!hasData && !loading && (
        <Alert
          message={t('committee.noData')}
          description="{t('committee.noDataHint')} 'Add Member' buttons above, or upload data via the Excel template in the Upload tab."
          type="info"
          showIcon
        />
      )}

      {calculationId && (
        <div style={{ marginTop: 24 }}>
          <Divider>{t('committee.variables')}</Divider>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 60%', minWidth: 300 }}>
              <div style={{
                border: '1px solid #d9d9d9',
                borderRadius: 6,
                padding: 12,
                background: '#fafafa',
              }}>
                <h4 style={{ margin: '0 0 8px 0', fontSize: 13 }}>
                  <CodeOutlined /> {t('committee.additionalNotes')}
                </h4>
                <textarea
                  id="committee-notes"
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
                  placeholder={t('committee.insertHint')}
                />
              </div>
            </div>
            <div style={{ flex: '0 0 340px' }}>
              <HouseholdVariablePanel
                calculationId={calculationId}
                tabKey="committee"
                onInsert={(varStr) => {
                  const ta = document.getElementById('committee-notes') as HTMLTextAreaElement;
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
        </div>
      )}
    </div>
  );
});

export default CommitteeManagement;
