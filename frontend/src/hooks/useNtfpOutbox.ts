/**
 * useNtfpOutbox — the offline outbox of one forest as React state: what is waiting, whether the phone is online, and a way to send now.
 *
 * It tries to send when the page opens, when the phone comes back online, and every 20 seconds while something is waiting (a phone can say "online" with no usable signal, so the
 * `online` event alone is not enough). `onSynced` is called after something was sent so the page can reload the records.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { discard as discardItem, flushOutbox, listOutbox, retry as retryItem, subscribe, type FlushResult, type OutboxItem } from '../services/ntfpOutbox';

const RETRY_MS = 20_000;

export function useNtfpOutbox(calcId: string, onSynced?: () => void) {
  const [items, setItems] = useState<OutboxItem[]>([]);
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine);
  const [sending, setSending] = useState(false);
  const synced = useRef(onSynced);
  synced.current = onSynced;

  const reload = useCallback(() => { void listOutbox(calcId).then(setItems); }, [calcId]);

  const flush = useCallback(async (): Promise<FlushResult> => {
    setSending(true);
    try {
      const r = await flushOutbox(calcId);
      if (r.sent > 0) synced.current?.();
      return r;
    } finally {
      setSending(false);
      reload();
    }
  }, [calcId, reload]);

  useEffect(() => {
    reload();
    const off = subscribe(reload);
    const goOnline = () => { setOnline(true); void flush(); };
    const goOffline = () => setOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    void flush();   // what was left from an earlier visit
    return () => { off(); window.removeEventListener('online', goOnline); window.removeEventListener('offline', goOffline); };
  }, [reload, flush]);

  const waiting = items.filter((i) => i.state === 'waiting');
  const rejected = items.filter((i) => i.state === 'rejected');

  useEffect(() => {
    if (waiting.length === 0) return undefined;
    const id = window.setInterval(() => { void flush(); }, RETRY_MS);
    return () => window.clearInterval(id);
  }, [waiting.length, flush]);

  return {
    items, waiting, rejected, online, sending, flush,
    discard: async (id: string) => { await discardItem(id); },
    retry: async (item: OutboxItem) => { await retryItem(item); void flush(); },
  };
}
