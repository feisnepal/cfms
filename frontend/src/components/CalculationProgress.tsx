import { useEffect, useState, useRef } from 'react';
import { CalculationCostSummary } from './CalculationCostSummary';
import { useT } from '../i18n/hooks';

interface ProgressData {
  progress: {
    current_step: string;
    step_label: string | null;
    step_index: number;
    total_steps: number;
    percent: number;
    message: string | null;
    error_message: string | null;
    started_at: string | null;
    completed_at: string | null;
    failed_at: string | null;
  } | null;
  cost_estimate: any;
  map_lifecycle_status: string;
}

interface Props {
  calculationId: string;
  pollIntervalMs?: number;
  onComplete?: (cost: any) => void;
  onError?: (msg: string) => void;
}

export function CalculationProgress({ calculationId, pollIntervalMs = 2000, onComplete, onError }: Props) {
  const t = useT();
  const [data, setData] = useState<ProgressData | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!calculationId) return;
    let cancelled = false;
    let useSse = true;

    const handleData = (d: ProgressData) => {
      if (cancelled) return;
      setData(d);
      if (d.map_lifecycle_status === 'completed' || d.map_lifecycle_status === 'locked') {
        cleanup();
        onComplete?.(d.cost_estimate);
      }
      if (d.progress?.error_message) {
        cleanup();
        onError?.(d.progress.error_message);
      }
    };

    const cleanup = () => {
      if (eventSourceRef.current) { eventSourceRef.current.close(); eventSourceRef.current = null; }
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    };

    // Try SSE first
    try {
      const es = new EventSource(`/api/calculations/${calculationId}/progress/stream`);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        try {
          handleData(JSON.parse(event.data));
        } catch { /* ignore parse errors */ }
      };

      es.onerror = () => {
        // SSE failed — fall back to polling
        es.close();
        eventSourceRef.current = null;
        if (!cancelled && !useSse) return;
        useSse = false;

        const poll = async () => {
          try {
            const res = await fetch(`/api/calculations/${calculationId}/progress`);
            if (!res.ok) return;
            handleData(await res.json());
          } catch { /* silent */ }
        };

        poll();
        intervalRef.current = setInterval(poll, pollIntervalMs);
      };
    } catch {
      // EventSource not supported — use polling
      useSse = false;
      const poll = async () => {
        try {
          const res = await fetch(`/api/calculations/${calculationId}/progress`);
          if (!res.ok) return;
          handleData(await res.json());
        } catch { /* silent */ }
      };
      poll();
      intervalRef.current = setInterval(poll, pollIntervalMs);
    }

    return cleanup;
  }, [calculationId, pollIntervalMs, onComplete, onError]);

  if (!data?.progress) {
    return (
      <div className="calc-progress" style={{ padding: '12px 16px', fontSize: 13, color: '#6b7280' }}>
        {t('calc.waitingForStart')}
      </div>
    );
  }

  const p = data.progress;
  const isFailed = data.map_lifecycle_status === 'failed' || !!p.error_message;
  const isDone = data.map_lifecycle_status === 'completed' || data.map_lifecycle_status === 'locked';

  return (
    <div className="calc-progress" style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
        <span style={{ color: '#374151' }}>{p.step_label || p.current_step}</span>
        <span style={{ color: '#6b7280', fontVariantNumeric: 'tabular-nums' }}>
          {p.step_index + 1} / {p.total_steps} ({Math.round(p.percent)}%)
        </span>
      </div>

      <div style={{
        height: 6, borderRadius: 3, background: '#e5e7eb', overflow: 'hidden',
        marginBottom: 6,
      }}>
        <div style={{
          width: `${Math.round(p.percent)}%`,
          height: '100%',
          borderRadius: 3,
          background: isFailed ? '#ef4444' : isDone ? '#22c55e' : '#3b82f6',
          transition: 'width 0.3s ease, background 0.3s ease',
        }} />
      </div>

      {p.message && <p style={{ margin: 0, fontSize: 12, color: '#6b7280' }}>{p.message}</p>}
      {isFailed && <p style={{ margin: '4px 0 0', fontSize: 12, color: '#ef4444' }}>{p.error_message || t('calc.calculationFailed')}</p>}

      {isDone && <CalculationCostSummary calculationId={calculationId} />}
    </div>
  );
}
