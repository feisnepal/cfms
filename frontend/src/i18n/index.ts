import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import ne from './locales/ne.json';
import en from './locales/en.json';

const resources = {
  ne: { translation: ne },
  en: { translation: en },
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'ne',
    supportedLngs: ['ne', 'en'],
    defaultNS: 'translation',
    interpolation: {
      escapeValue: false,
    },
    detection: {
      order: ['localStorage'],
      caches: ['localStorage'],
    },
    react: {
      useSuspense: false,
    },
  });

const OVERLAY_URL = '/api/translations/overlay';
const OVERLAY_RETRIES = 2;
const OVERLAY_TIMEOUT_MS = 5000;

interface TranslationOverlay {
  ne?: Record<string, unknown>;
  en?: Record<string, unknown>;
}

async function fetchOverlayWithRetry(
  url: string,
  retries: number,
  timeoutMs: number,
): Promise<TranslationOverlay | null> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      const response = await fetch(url, {
        signal: controller.signal,
        headers: { 'Accept': 'application/json' },
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        console.warn(
          `[i18n] Overlay fetch attempt ${attempt + 1}/${retries + 1} failed: HTTP ${response.status}`,
        );
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        }
        continue;
      }

      return await response.json() as TranslationOverlay;
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      console.warn(
        `[i18n] Overlay fetch attempt ${attempt + 1}/${retries + 1} failed: ${isAbort ? 'timeout' : 'network error'}`,
      );
      if (attempt >= retries) return null;
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
    }
  }
  return null;
}

function mergeOverlay(overlay: TranslationOverlay): void {
  if (!overlay) return;

  if (overlay.ne && typeof overlay.ne === 'object' && Object.keys(overlay.ne).length > 0) {
    i18n.addResourceBundle('ne', 'translation', overlay.ne, true, true);
    console.debug(`[i18n] Merged Nepali overlay (${Object.keys(overlay.ne).length} top-level keys)`);
  }

  if (overlay.en && typeof overlay.en === 'object' && Object.keys(overlay.en).length > 0) {
    i18n.addResourceBundle('en', 'translation', overlay.en, true, true);
    console.debug(`[i18n] Merged English overlay (${Object.keys(overlay.en).length} top-level keys)`);
  }
}

/**
 * Fetch the translations overlay and merge it on top of the bundled defaults.
 *
 * Invoked at app boot (below) and after any super-admin editor save (Phase 3)
 * so corrected Nepali surfaces without a redeploy; every other user picks the
 * changes up on their next page load (boot fetch).
 */
export async function refreshTranslations(): Promise<boolean> {
  const overlay = await fetchOverlayWithRetry(OVERLAY_URL, OVERLAY_RETRIES, OVERLAY_TIMEOUT_MS);
  if (overlay) {
    mergeOverlay(overlay);
    return true;
  }
  console.info('[i18n] No overlay available — using base translations only');
  return false;
}

if (typeof window !== 'undefined') {
  refreshTranslations().catch((err) => {
    console.error('[i18n] Unexpected overlay error:', err);
  });
}

export default i18n;