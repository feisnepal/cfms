/** Super admin screen for the assistant: the kill switch and shared ceiling, then requests, approvals, caps and today's use per person. Pure. */
import React, { useState } from 'react';
import { useT } from '../../i18n/hooks';
import type { ChatAdminRow, ChatAdminSettings } from './chatApi';

interface Props {
  settings: ChatAdminSettings | null;
  rows: ChatAdminRow[];
  busy: boolean;
  error: string | null;
  onSaveSettings: (enabled: boolean, pool: number | null) => void;
  onApprove: (userId: string, cap?: number) => void;
  onRevoke: (userId: string) => void;
  onSetCap: (userId: string, cap: number) => void;
}

const ORDER: Record<string, number> = { requested: 0, approved: 1, revoked: 2 };

const AdminChatView: React.FC<Props> = ({ settings, rows, busy, error, onSaveSettings, onApprove, onRevoke, onSetCap }) => {
  const t = useT();
  const [pool, setPool] = useState<string>(settings?.pool_daily_tokens == null ? '' : String(settings.pool_daily_tokens));
  const [caps, setCaps] = useState<Record<string, string>>({});
  const sorted = [...rows].sort((a, b) => ORDER[a.status] - ORDER[b.status] || b.requested_at.localeCompare(a.requested_at));
  const capOf = (r: ChatAdminRow) => caps[r.user_id] ?? String(r.daily_cap_tokens);
  const capValue = (r: ChatAdminRow): number | null => {
    const n = Number(capOf(r));
    return Number.isInteger(n) && n >= 0 ? n : null;
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-4 space-y-6">
      <h1 className="text-xl font-semibold">{t('chatAdmin.title')}</h1>
      {error && <p className="text-red-700" role="alert">{error}</p>}

      {settings && (
        <section className="border rounded p-4 bg-white space-y-3" aria-label={t('chatAdmin.settings')}>
          <h2 className="font-medium">{t('chatAdmin.settings')}</h2>
          <p className={settings.enabled ? 'text-green-700' : 'text-red-700 font-semibold'} role="status">
            {settings.enabled ? t('chatAdmin.on') : t('chatAdmin.off')}
          </p>
          <label className="block text-sm">
            <span className="text-gray-600">{t('chatAdmin.poolLabel')}</span>
            <input className="ml-2 border rounded px-2 py-1 w-40" inputMode="numeric" value={pool} placeholder={t('chatAdmin.noPool')} onChange={(e) => setPool(e.target.value)} />
          </label>
          <p className="text-sm text-gray-600">{t('chatAdmin.poolUsed', { used: settings.pool_used_today.toLocaleString() })}</p>
          <div className="flex gap-2">
            <button type="button" disabled={busy} className="px-3 py-1.5 rounded bg-green-600 text-white disabled:opacity-50"
              onClick={() => onSaveSettings(settings.enabled, pool.trim() === '' ? null : Number(pool))}>{t('chatAdmin.savePool')}</button>
            <button type="button" disabled={busy} className={`px-3 py-1.5 rounded text-white disabled:opacity-50 ${settings.enabled ? 'bg-red-600' : 'bg-green-700'}`}
              onClick={() => onSaveSettings(!settings.enabled, settings.pool_daily_tokens)}>{settings.enabled ? t('chatAdmin.switchOff') : t('chatAdmin.switchOn')}</button>
          </div>
        </section>
      )}

      <section aria-label={t('chatAdmin.people')}>
        <h2 className="font-medium mb-2">{t('chatAdmin.people')}</h2>
        {sorted.length === 0 ? (
          <p className="text-gray-500">{t('chatAdmin.none')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm bg-white border">
              <thead>
                <tr className="text-left bg-gray-50">
                  <th className="p-2">{t('chatAdmin.person')}</th>
                  <th className="p-2">{t('chatAdmin.status')}</th>
                  <th className="p-2">{t('chatAdmin.cap')}</th>
                  <th className="p-2">{t('chatAdmin.usedToday')}</th>
                  <th className="p-2">{t('chatAdmin.thumbsDown')}</th>
                  <th className="p-2" />
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => (
                  <tr key={r.user_id} className="border-t align-top">
                    <td className="p-2">
                      <div>{r.full_name || r.email}</div>
                      <div className="text-xs text-gray-500">{r.email} · {r.role}</div>
                      {r.request_note && <div className="text-xs text-gray-600 mt-1">“{r.request_note}”</div>}
                    </td>
                    <td className="p-2">{t(`chatAdmin.status_${r.status}`)}</td>
                    <td className="p-2">
                      <input aria-label={t('chatAdmin.cap')} className="border rounded px-2 py-1 w-28" inputMode="numeric" value={capOf(r)}
                        onChange={(e) => setCaps((c) => ({ ...c, [r.user_id]: e.target.value }))} />
                    </td>
                    <td className="p-2">{r.tokens_used_today.toLocaleString()} ({r.messages_today})</td>
                    <td className="p-2">{r.thumbs_down_30d}</td>
                    <td className="p-2 space-x-2 whitespace-nowrap">
                      {r.status !== 'approved' && (
                        <button type="button" disabled={busy || capValue(r) === null} className="px-2 py-1 rounded bg-green-600 text-white disabled:opacity-50"
                          onClick={() => onApprove(r.user_id, capValue(r) ?? undefined)}>{t('chatAdmin.approve')}</button>
                      )}
                      {r.status === 'approved' && (
                        <button type="button" disabled={busy || capValue(r) === null} className="px-2 py-1 rounded border disabled:opacity-50"
                          onClick={() => onSetCap(r.user_id, capValue(r) as number)}>{t('chatAdmin.saveCap')}</button>
                      )}
                      {r.status !== 'revoked' && (
                        <button type="button" disabled={busy} className="px-2 py-1 rounded border border-red-600 text-red-700 disabled:opacity-50"
                          onClick={() => onRevoke(r.user_id)}>{t('chatAdmin.revoke')}</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};

export default AdminChatView;
