/** Super admin page for the assistant (CHATBOT_PLAN C1.6): loads the data and runs the actions; the screen itself is AdminChatView. */
import React, { useCallback, useEffect, useState } from 'react';
import { useT } from '../i18n/hooks';
import AdminChatView from '../features/chat/AdminChatView';
import { chatApi, chatErrorMessage, type ChatAdminRow, type ChatAdminSettings } from '../features/chat/chatApi';

const AdminChatPage: React.FC = () => {
  const t = useT();
  const [settings, setSettings] = useState<ChatAdminSettings | null>(null);
  const [rows, setRows] = useState<ChatAdminRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([chatApi.adminSettings(), chatApi.adminList()]);
      setSettings(s);
      setRows(r);
      setError(null);
    } catch (e) {
      setError(chatErrorMessage(e, t('chatAdmin.loadFailed')));
    } finally {
      setLoaded(true);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (e) {
      setError(chatErrorMessage(e, t('chatAdmin.actionFailed')));
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) return <p className="p-4 text-gray-500" role="status">{t('chat.loading')}</p>;
  return (
    <AdminChatView
      // a new key rebuilds the pool field when the saved value changes
      key={String(settings?.pool_daily_tokens)}
      settings={settings} rows={rows} busy={busy} error={error}
      onSaveSettings={(enabled, pool) => run(async () => setSettings(await chatApi.adminSaveSettings(enabled, pool)))}
      onApprove={(id, cap) => run(() => chatApi.adminApprove(id, cap))}
      onRevoke={(id) => run(() => chatApi.adminRevoke(id))}
      onSetCap={(id, cap) => run(() => chatApi.adminSetCap(id, cap))}
    />
  );
};

export default AdminChatPage;
