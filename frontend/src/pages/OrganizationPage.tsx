/** OrganizationPage — the owner of an organization sees who joined it and vouches for the real members.
 *
 * Vouching is a statement to the super admin who approves the account; it does not approve anyone itself,
 * and it is only open once a super admin has verified the organization.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';
import { authApi, type OrgMember } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';

const OrganizationPage: React.FC = () => {
  const t = useT();
  const { user } = useAuth();
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMembers(await authApi.organizationMembers());
    } catch (err) {
      setError(apiErrorText(err, t('organization.loadFailed')));
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const vouch = async (id: string) => {
    setBusy(id);
    setError('');
    try {
      await authApi.vouchForMember(id);
      await load();
    } catch (err) {
      setError(apiErrorText(err, t('organization.vouchFailed')));
    } finally {
      setBusy(null);
    }
  };

  const verified = !!user?.organization_verified;

  return (
    <div className="mx-auto max-w-3xl p-4 space-y-4" data-testid="organization-page">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{user?.organization_name}</h1>
        <p className={`mt-1 text-sm ${verified ? 'text-emerald-700' : 'text-amber-700'}`}>
          {verified ? `✓ ${t('organization.verified')}` : t('organization.notVerified')}
        </p>
      </div>
      {error && <div className="rounded-xl bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</div>}
      <ul className="divide-y divide-gray-100 rounded-2xl border border-gray-200 bg-white shadow-sm">
        {members.map((m) => (
          <li key={m.id} className="flex items-center justify-between gap-3 p-4">
            <div className="min-w-0">
              <p className="truncate font-medium text-gray-900">
                {m.full_name}
                {m.org_member_role === 'owner' && (
                  <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">{t('organization.owner')}</span>
                )}
              </p>
              <p className="truncate text-xs text-gray-500">
                {[m.type_details?.position, m.email, m.phone].filter(Boolean).join(' · ')}
              </p>
            </div>
            {m.org_member_role === 'owner' ? null : m.org_vouched_at ? (
              <span className="shrink-0 text-sm font-medium text-emerald-700">✓ {t('organization.vouched')}</span>
            ) : (
              <button type="button" disabled={!verified || busy === m.id} onClick={() => vouch(m.id)}
                title={verified ? undefined : t('organization.notVerified')}
                className="shrink-0 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:bg-gray-300">
                {t('organization.vouch')}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default OrganizationPage;
