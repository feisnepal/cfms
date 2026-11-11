/** The assistant's launcher and panel, mounted once for the whole app. State is fetched when the panel is first opened, not on every page. */
import React, { useCallback, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useT } from '../../i18n/hooks';
import { chatApi, chatErrorMessage, type ChatAccessState } from './chatApi';
import ChatPanelView, { type ChatTurn } from './ChatPanelView';

const ChatDock: React.FC = () => {
  const t = useT();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [access, setAccess] = useState<ChatAccessState | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAccess(await chatApi.access());
    } catch (e) {
      setError(chatErrorMessage(e, t('chat.loadFailed')));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const request = async (note: string) => {
    setBusy(true);
    setError(null);
    try {
      setAccess(await chatApi.requestAccess(note));
    } catch (e) {
      setError(chatErrorMessage(e, t('chat.requestFailed')));
    } finally {
      setBusy(false);
    }
  };

  const send = async (message: string) => {
    setSending(true);
    setError(null);
    setTurns((cur) => [...cur, { id: `u${cur.length}-${Date.now()}`, role: 'user', text: message }]);
    try {
      const out = await chatApi.send(message, sessionId, null);
      setSessionId(out.session_id);
      setAccess(out.state);
      setTurns((cur) => [...cur, { id: out.message_id, role: 'assistant', text: out.reply, sources: out.sources, feedback: null }]);
    } catch (e) {
      setError(chatErrorMessage(e, t('chat.sendFailed')));
      // the allowance or the access may have changed; refresh quietly so the panel shows the truth
      try {
        setAccess(await chatApi.access());
      } catch {
        /* the error above already tells the user something went wrong */
      }
    } finally {
      setSending(false);
    }
  };

  const feedback = async (id: string, value: -1 | 0 | 1) => {
    setTurns((cur) => cur.map((m) => (m.id === id ? { ...m, feedback: value || null } : m)));
    try {
      await chatApi.feedback(id, value);
    } catch (e) {
      setError(chatErrorMessage(e, t('chat.sendFailed')));
    }
  };

  const toggle = () => {
    if (!open && !access && !loading) void load();
    setOpen((v) => !v);
  };

  // Guests are never eligible and the panel needs an account; hide the launcher rather than show a dead end.
  if (!user || user.role === 'guest') return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 print:hidden">
      {open && (
        <section aria-label={t('chat.title')} className="mb-2 w-80 max-w-[calc(100vw-2rem)] h-96 bg-white border rounded-lg shadow-xl flex flex-col overflow-hidden">
          <header className="px-3 py-2 bg-green-600 text-white flex justify-between items-center">
            <h2 className="text-sm font-semibold">{t('chat.title')}</h2>
            <button type="button" aria-label={t('chat.close')} onClick={() => setOpen(false)} className="text-white text-lg leading-none">×</button>
          </header>
          <div className="flex-1 overflow-hidden">
            <ChatPanelView
              access={access} loading={loading} error={error} busy={busy} onRequest={request} onRetry={load}
              turns={turns} sending={sending} onSend={send} onFeedback={feedback}
            />
          </div>
        </section>
      )}
      <button type="button" onClick={toggle} aria-expanded={open} className="px-4 py-2 rounded-full bg-green-600 text-white shadow-lg text-sm font-medium">
        {t('chat.launcher')}
      </button>
    </div>
  );
};

export default ChatDock;
