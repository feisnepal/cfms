/** AdminUsersPage — the super-admin panel for accounts and roles.
 *
 * Lists every account and lets a super admin give it a role (template designer, org admin, … — the list comes from the server, so a
 * role added later appears here with no change) and approve / suspend / reactivate it. New accounts are plain users; nobody picks
 * their own role. A super admin cannot change their own role (the server refuses it, and the dropdown is disabled for that row).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Table, Select, Input, Button, Tag, Typography, Space, Modal, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../i18n/hooks';
import { useAuth } from '../contexts/AuthContext';
import api from '../services/api';

const { Title, Text } = Typography;

interface UserRow {
  id: string;
  email: string | null;
  full_name: string;
  role: string;
  status: 'pending' | 'active' | 'suspended';
  created_at: string;
  last_login: string | null;
  phone?: string | null;
  designation?: string | null;
  sub_division?: string | null;
  instagram_handle?: string | null;
  phone_verified_at?: string | null;
  email_verified_at?: string | null;
  /** False = limited tier: signed in, but not approved yet. */
  is_approved?: boolean;
  user_type?: string | null;
  type_details?: Record<string, string> | null;
  access_level?: string;
  access_expires_at?: string | null;
  organization_id?: string | null;
  organization_name?: string | null;
  organization_verified?: boolean;
  org_member_role?: string | null;
  org_vouched_at?: string | null;
}

const DESIGNATION_TEXT: Record<string, string> = {
  forest_guard: 'Forest guard', forester: 'Forester', ranger: 'Ranger', office: 'Office',
};

const TYPE_TEXT: Record<string, string> = {
  official: 'Sub-division official', student: 'Student', researcher: 'Researcher', organization: 'Organization',
};

/** The declared facts a super admin judges on approval, one short line per type. */
const typeLines = (row: UserRow): string[] => {
  const d = row.type_details ?? {};
  switch (row.user_type) {
    case 'student':
      return [`${d.level ?? ''} · ${d.institution ?? ''}`, d.programme ?? '', `${d.supervisor_name ?? ''} <${d.supervisor_email ?? ''}>`];
    case 'researcher':
      return [d.affiliation ?? '', d.topic ?? '', d.orcid ? `ORCID ${d.orcid}` : ''];
    case 'organization':
      return [`${row.organization_name ?? d.organization_name ?? ''} (${d.org_kind ?? ''})`, d.position ?? ''];
    default:
      return [`${row.designation ? DESIGNATION_TEXT[row.designation] ?? row.designation : '—'}${row.sub_division ? `, ${row.sub_division}` : ''}`];
  }
};

interface RoleInfo {
  value: string;
  label: string;
  description: string;
}

const STATUS_COLOUR: Record<UserRow['status'], string> = { pending: 'gold', active: 'green', suspended: 'red' };
const STATUS_TEXT: Record<UserRow['status'], string> = { pending: 'Waiting for approval', active: 'Active', suspended: 'Suspended' };

export const AdminUsersPage: React.FC = () => {
  const t = useT();
  const { user: me } = useAuth();
  const [rows, setRows] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [roleFilter, setRoleFilter] = useState<string | undefined>();
  const [typeFilter, setTypeFilter] = useState<string | undefined>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [u, r] = await Promise.all([
        api.get<UserRow[]>('/api/admin/users', { params: { q: q || undefined, role: roleFilter, user_type: typeFilter } }),
        api.get<RoleInfo[]>('/api/admin/users/roles'),
      ]);
      setRows(u.data);
      setRoles(r.data);
    } catch {
      message.error(t('adminUsers.loadFailed', { defaultValue: 'The users could not be loaded.' }));
    } finally {
      setLoading(false);
    }
  }, [q, roleFilter, typeFilter, t]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (id: string, call: () => Promise<unknown>, ok: string) => {
    setBusy(id);
    try {
      await call();
      message.success(ok);
      await load();
    } catch {
      message.error(t('adminUsers.actionFailed', { defaultValue: 'That change was refused.' }));
    } finally {
      setBusy(null);
    }
  };

  /** For someone who lost both phone and email: a one-time link to hand over after confirming who they are. */
  const resetLink = async (row: UserRow) => {
    try {
      const { data } = await api.post<{ url: string; expires_in: number }>(`/api/auth/users/${row.id}/reset-link`);
      Modal.info({
        title: t('adminUsers.resetLinkTitle', { defaultValue: 'One-time password reset link' }),
        content: (
          <div>
            <p>{t('adminUsers.resetLinkHelp', { defaultValue: 'Give this to the person only after you have confirmed who they are, for example by calling the number on their office record. It works once and expires in {{minutes}} minutes.', minutes: Math.round(data.expires_in / 60) })}</p>
            <Input.TextArea readOnly autoSize value={data.url} onFocus={(e) => e.target.select()} />
          </div>
        ),
      });
    } catch {
      message.error(t('adminUsers.actionFailed', { defaultValue: 'That change was refused.' }));
    }
  };

  /** Set or clear when a student's / researcher's access ends. */
  const setExpiry = (row: UserRow) => {
    let picked = row.access_expires_at?.slice(0, 10) ?? '';
    Modal.confirm({
      title: t('adminUsers.expiryTitle'),
      content: (
        <div>
          <p>{t('adminUsers.expiryHelp')}</p>
          <Input type="date" defaultValue={picked} onChange={(e) => { picked = e.target.value; }} aria-label={t('adminUsers.accessEnds')} />
        </div>
      ),
      onOk: () =>
        act(
          row.id,
          () => api.patch(`/api/auth/users/${row.id}/access`, { access_expires_at: picked ? `${picked}T23:59:59Z` : null }),
          t('adminUsers.expirySaved'),
        ),
    });
  };

  const roleOptions = useMemo(
    () => roles.map((r) => ({ value: r.value, label: r.label, title: r.description })),
    [roles],
  );

  const columns: ColumnsType<UserRow> = [
    { title: t('adminUsers.email', { defaultValue: 'Email' }), dataIndex: 'email', key: 'email' },
    { title: t('adminUsers.name', { defaultValue: 'Name' }), dataIndex: 'full_name', key: 'name' },
    {
      title: t('adminUsers.status', { defaultValue: 'Status' }),
      dataIndex: 'status',
      key: 'status',
      render: (s: UserRow['status'], row) =>
        s === 'active' && row.is_approved === false ? (
          <Tag color="gold">{t('adminUsers.statusName.limited', { defaultValue: 'Limited — awaiting approval' })}</Tag>
        ) : (
          <Tag color={STATUS_COLOUR[s]}>{t(`adminUsers.statusName.${s}`, { defaultValue: STATUS_TEXT[s] })}</Tag>
        ),
    },
    {
      // What the person declared, so the approver can judge the claim; ✓ = proved by code or link.
      title: t('adminUsers.who', { defaultValue: 'Declared role & contact' }),
      key: 'who',
      render: (_: unknown, row) => (
        <div className="text-xs leading-5">
          <div className="font-semibold">
            {row.user_type ? t(`auth.type${row.user_type[0].toUpperCase()}${row.user_type.slice(1)}`) : '—'}
            {row.access_level === 'read_only' && ` · ${t('adminUsers.readOnly')}`}
          </div>
          {typeLines(row).filter(Boolean).map((line) => <div key={line}>{line}</div>)}
          {row.user_type === 'organization' && (
            <div>
              {row.organization_verified ? t('adminUsers.orgVerified') : t('adminUsers.orgUnverified')}
              {row.org_member_role === 'member' && (row.org_vouched_at ? ` · ${t('adminUsers.vouched')}` : ` · ${t('adminUsers.notVouched')}`)}
              {row.org_member_role === 'owner' && ` · ${t('adminUsers.orgOwner')}`}
            </div>
          )}
          {row.access_expires_at && <div>{t('adminUsers.accessEnds')} {row.access_expires_at.slice(0, 10)}</div>}
          <div>{row.phone ?? '—'} {row.phone_verified_at ? '✓' : ''}</div>
          {row.email_verified_at && <div>{t('adminUsers.emailVerified', { defaultValue: 'email ✓' })}</div>}
          {row.instagram_handle && <div>@{row.instagram_handle}</div>}
        </div>
      ),
    },
    {
      title: t('adminUsers.role', { defaultValue: 'Role' }),
      dataIndex: 'role',
      key: 'role',
      render: (role: string, row) => {
        const own = row.id === me?.id;
        return (
          <Select
            size="small"
            style={{ minWidth: 190 }}
            value={role}
            options={roleOptions}
            disabled={own || busy === row.id}
            aria-label={t('adminUsers.roleOf', { defaultValue: 'Role of {{email}}', email: row.email })}
            data-testid={`role-select-${row.email}`}
            title={own ? t('adminUsers.ownRole', { defaultValue: 'You cannot change your own role.' }) : undefined}
            onChange={(next: string) =>
              act(
                row.id,
                () => api.patch(`/api/admin/users/${row.id}/role`, { role: next }),
                t('adminUsers.roleChanged', { defaultValue: 'Role changed.' }),
              )
            }
          />
        );
      },
    },
    {
      title: '',
      key: 'actions',
      render: (_, row) => {
        if (row.id === me?.id) return null;
        const approve = row.status !== 'active' || row.is_approved === false;
        return (
          <Space size="small">
          <Button
            size="small"
            danger={!approve}
            loading={busy === row.id}
            data-testid={`${approve ? 'approve' : 'suspend'}-${row.email}`}
            onClick={() =>
              act(
                row.id,
                () => api.post(`/api/auth/users/${row.id}/${approve ? 'approve' : 'suspend'}`),
                approve
                  ? t('adminUsers.approved', { defaultValue: 'Account activated.' })
                  : t('adminUsers.suspended', { defaultValue: 'Account suspended.' }),
              )
            }
          >
            {approve ? t('adminUsers.approve', { defaultValue: 'Approve' }) : t('adminUsers.suspend', { defaultValue: 'Suspend' })}
          </Button>
          {row.user_type === 'organization' && row.organization_id && !row.organization_verified && row.org_member_role === 'owner' && (
            <Button size="small" disabled={busy === row.id} data-testid={`verify-org-${row.email}`}
              onClick={() => act(row.id, () => api.post(`/api/auth/organizations/${row.organization_id}/verify`), t('adminUsers.orgVerifiedDone'))}>
              {t('adminUsers.verifyOrg')}
            </Button>
          )}
          {(row.access_level === 'read_only' || row.access_expires_at) && (
            <Button size="small" disabled={busy === row.id} data-testid={`expiry-${row.email}`} onClick={() => setExpiry(row)}>
              {t('adminUsers.setExpiry')}
            </Button>
          )}
          <Button
            size="small"
            disabled={busy === row.id}
            data-testid={`reset-link-${row.email ?? row.id}`}
            onClick={() => resetLink(row)}
          >
            {t('adminUsers.resetLink', { defaultValue: 'Reset link' })}
          </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <div className="p-4 max-w-6xl mx-auto" data-testid="admin-users-page">
      <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>{t('adminUsers.title', { defaultValue: 'Users and roles' })}</Title>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('adminUsers.refresh', { defaultValue: 'Refresh' })}</Button>
      </Space>
      <Text type="secondary" style={{ display: 'block', margin: '4px 0 12px' }}>
        {t('adminUsers.hint', {
          defaultValue: 'New accounts start as plain users and wait for approval. Give a role here; it takes effect on the person\'s next request.',
        })}
      </Text>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          allowClear
          placeholder={t('adminUsers.search', { defaultValue: 'Search email or name' })}
          onSearch={setQ}
          style={{ width: 260 }}
        />
        <Select
          allowClear
          placeholder={t('adminUsers.filterRole', { defaultValue: 'Any role' })}
          style={{ width: 200 }}
          options={roleOptions}
          value={roleFilter}
          onChange={setRoleFilter}
        />
        <Select
          allowClear
          placeholder={t('adminUsers.filterType')}
          style={{ width: 220 }}
          options={Object.entries(TYPE_TEXT).map(([value, label]) => ({ value, label }))}
          value={typeFilter}
          onChange={setTypeFilter}
        />
      </Space>
      <Table<UserRow> rowKey="id" size="small" loading={loading} columns={columns} dataSource={rows} pagination={{ pageSize: 25, hideOnSinglePage: true }} />
    </div>
  );
};

export default AdminUsersPage;
