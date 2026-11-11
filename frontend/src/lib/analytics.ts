/**
 * analytics.ts — Digitize analytics & telemetry event tracker (Task 4.1.5).
 *
 * Tracks key user actions and telemetry for UX friction, undo rates,
 * snap usage, and finalize success/failure rates.
 */
export enum DigitizeEvent {
  DRAFT_CREATED = 'draft_created',
  FEATURE_DRAWN = 'feature_drawn',
  BUFFER_FLUSHED = 'buffer_flushed',
  FINALIZE_INITIATED = 'finalize_initiated',
  FINALIZE_SUCCESS = 'finalize_success',
  FINALIZE_FAILED = 'finalize_failed',
  DRAFT_DISCARDED = 'draft_discarded',
  UNDO_USED = 'undo_used',
  SNAP_USED = 'snap_used',
  COPY_PASTE_USED = 'copy_paste_used',
}

export interface TelemetryPayload {
  event: DigitizeEvent;
  timestamp: number;
  calculationId?: string;
  layerId?: number;
  properties?: Record<string, unknown>;
}

export function track(event: DigitizeEvent, properties?: Record<string, unknown>, calculationId?: string, layerId?: number): void {
  const payload: TelemetryPayload = {
    event,
    timestamp: Date.now(),
    calculationId,
    layerId,
    properties,
  };

  // Log in development / structured output
  if (import.meta.env.DEV) {
    console.debug('[Telemetry]', payload);
  }

  // Push to analytics storage or beacon if enabled
  try {
    const queue = JSON.parse(localStorage.getItem('cf_telemetry_queue') || '[]');
    queue.push(payload);
    if (queue.length > 100) queue.shift();
    localStorage.setItem('cf_telemetry_queue', JSON.stringify(queue));
  } catch {
    /* ignore storage errors */
  }
}
