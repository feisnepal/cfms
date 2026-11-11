import { readDetail } from '../hooks/useErrorHandler';

/**
 * Download a file from an API endpoint using fetch with auth token.
 * Extracts filename from Content-Disposition header (backup: fallback name).
 * Supports RFC 5987 UTF-8 encoding for Unicode filenames (Nepali).
 */
export async function downloadFromApi(
  url: string,
  fallbackFilename: string,
  extraParams?: Record<string, string>,
  options?: { method?: string; body?: unknown; timeoutMs?: number }
): Promise<void> {
  const token = localStorage.getItem('access_token');
  const separator = url.includes('?') ? '&' : '?';
  const fullUrl = extraParams && (!options || options.method !== 'POST')
    ? url + separator + new URLSearchParams(extraParams).toString()
    : url;

  // Default to a generous timeout so large report/OP exports don't fail silently
  // with a generic "Failed to fetch". 0/undefined = no timeout.
  const timeoutMs = options?.timeoutMs ?? 120000;
  const controller = new AbortController();
  const timer = timeoutMs > 0
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null;

  const fetchOptions: RequestInit = {
    method: options?.method || 'GET',
    headers: { Authorization: `Bearer ${token}` } as Record<string, string>,
    signal: controller.signal,
  };

  if (options?.method === 'POST' && options.body !== undefined) {
    (fetchOptions.headers as Record<string, string>)['Content-Type'] = 'application/json';
    (fetchOptions as any).body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(fullUrl, fetchOptions);
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(
        `Export timed out after ${Math.round(timeoutMs / 1000)}s. ` +
        `The server may be busy generating maps — please try again.`
      );
    }
    // Network-level failure (no response) — give a clearer message than the
    // browser's default "Failed to fetch".
    throw new Error(
      'Export failed to connect to the server (network error). ' +
      'Please check your connection and try again.'
    );
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (!response.ok) {
    const body = await response.text();
    let detail: unknown = body;
    let correlationId: unknown;
    try {
      const parsed: unknown = JSON.parse(body);
      if (parsed && typeof parsed === 'object') {
        const p = parsed as { detail?: unknown; message?: unknown; correlation_id?: unknown };
        detail = p.detail ?? p.message ?? body;
        correlationId = p.correlation_id;
      }
    } catch {}

    if (typeof detail === 'string' && detail) {
      throw new Error(detail);
    }
    const text = readDetail(detail, correlationId);
    throw new Error(text || `Export failed (${response.status})`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';

  const match =
    disposition.match(/filename\*?=UTF-8''([^;]+)/) ||
    disposition.match(/filename="([^"]+)"/);
  const filename = match ? decodeURIComponent(match[1]) : fallbackFilename;

  const urlObj = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = urlObj;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(urlObj);
}

/**
 * Download client-side generated content (blob) with a given filename.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}
