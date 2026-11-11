/** The assistant panel's body. Pure: the state and the actions come in as props, so every access state can be rendered and tested. */
import React, { useEffect, useRef, useState } from 'react';
import { useT } from '../../i18n/hooks';
import type { ChatAccessState } from './chatApi';

export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  sources?: string[];
  feedback?: -1 | 1 | null;
}

interface Props {
  access: ChatAccessState | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onRequest: (note: string) => void;
  onRetry: () => void;
  turns: ChatTurn[];
  sending: boolean;
  onSend: (message: string) => void;
  onFeedback: (id: string, value: -1 | 0 | 1) => void;
}

const STATE_MESSAGE: Record<string, string> = {
  requested: 'chat.stateRequested',
  revoked: 'chat.stateRevoked',
  expired: 'chat.stateExpired',
  switched_off: 'chat.stateSwitchedOff',
  not_eligible: 'chat.stateNotEligible',
};

const ChatPanelView: React.FC<Props> = ({ access, loading, error, busy, onRequest, onRetry, turns, sending, onSend, onFeedback }) => {
  const t = useT();
  const [note, setNote] = useState('');
  const [draft, setDraft] = useState('');
  const end = useRef<HTMLDivElement>(null);
  // keep the newest line (answer, thinking note or error) in view
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }); }, [turns, sending, error]);

  const submit = () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft('');
    onSend(text);
  };

  if (loading) return <p className="p-4 text-sm text-gray-500" role="status">{t('chat.loading')}</p>;
  if (!access) {
    return (
      <div className="p-4 text-sm" role="alert">
        <p className="text-red-700">{error || t('chat.loadFailed')}</p>
        <button type="button" className="mt-2 underline text-green-700" onClick={onRetry}>{t('chat.retry')}</button>
      </div>
    );
  }

  if (access.state === 'none' || access.state === 'revoked' || access.state === 'expired') {
    return (
      <div className="p-4 text-sm space-y-3">
        <p>{access.state === 'none' ? t('chat.intro') : t(STATE_MESSAGE[access.state])}</p>
        <label className="block">
          <span className="text-gray-600">{t('chat.noteLabel')}</span>
          <textarea className="mt-1 w-full border rounded p-2" rows={3} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && <p className="text-red-700" role="alert">{error}</p>}
        <button type="button" disabled={busy} onClick={() => onRequest(note)} className="px-3 py-1.5 rounded bg-green-600 text-white disabled:opacity-50">
          {t('chat.requestAccess')}
        </button>
      </div>
    );
  }

  if (!access.allowed) {
    return <p className="p-4 text-sm" role="status">{t(STATE_MESSAGE[access.state] ?? 'chat.stateNotEligible')}</p>;
  }

  const pct = access.daily_cap_tokens > 0 ? Math.min(100, Math.round((100 * access.tokens_left_today) / access.daily_cap_tokens)) : 0;
  return (
    <div className="flex flex-col h-full text-sm">
      <div className="p-3 border-b">
        <div className="flex justify-between text-gray-600">
          <span>{t('chat.tokensLeft')}</span>
          <span>{access.tokens_left_today.toLocaleString()} / {access.daily_cap_tokens.toLocaleString()}</span>
        </div>
        <div className="h-1.5 bg-gray-200 rounded mt-1" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-1.5 bg-green-600 rounded" style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-1 text-xs text-gray-500">{t('chat.questionsLeft', { count: access.approx_questions_left })}</p>
        {access.read_only && <p className="mt-1 text-xs text-amber-700">{t('chat.readOnly')}</p>}
      </div>
      <div className="flex-1 overflow-auto p-3 space-y-3" aria-live="polite">
        {turns.length === 0 && <p className="text-gray-500">{t('chat.emptyHint')}</p>}
        {turns.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'text-right' : ''}>
            <div className={`inline-block max-w-full rounded px-3 py-2 whitespace-pre-wrap text-left ${m.role === 'user' ? 'bg-green-100' : 'bg-gray-100'}`}>{m.text}</div>
            {m.role === 'assistant' && m.sources && m.sources.length > 0 && (
              <p className="mt-1 text-xs text-gray-500">{t('chat.sources')}: {m.sources.join('; ')}</p>
            )}
            {m.role === 'assistant' && (
              <div className="mt-1 flex gap-2 text-xs">
                <button type="button" aria-pressed={m.feedback === 1} aria-label={t('chat.thumbsUp')} className={m.feedback === 1 ? 'font-bold' : ''} onClick={() => onFeedback(m.id, m.feedback === 1 ? 0 : 1)}>👍</button>
                <button type="button" aria-pressed={m.feedback === -1} aria-label={t('chat.thumbsDown')} className={m.feedback === -1 ? 'font-bold' : ''} onClick={() => onFeedback(m.id, m.feedback === -1 ? 0 : -1)}>👎</button>
              </div>
            )}
          </div>
        ))}
        {sending && <p className="text-gray-500" role="status">{t('chat.thinking')}</p>}
        {error && <p className="text-red-700" role="alert">{error}</p>}
        <div ref={end} />
      </div>
      <div className="p-3 border-t">
        <textarea
          className="w-full border rounded p-2" rows={2} maxLength={2000} value={draft} disabled={sending}
          placeholder={t('chat.composerPlaceholder')} aria-label={t('chat.composerPlaceholder')}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
        />
        <div className="mt-1 flex justify-between items-center gap-2">
          <p className="text-xs text-gray-500">{t('chat.honesty')}</p>
          <button type="button" disabled={sending || !draft.trim()} onClick={submit} className="px-3 py-1 rounded bg-green-600 text-white disabled:opacity-50">{t('chat.send')}</button>
        </div>
      </div>
    </div>
  );
};

export default ChatPanelView;
