import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';

/**
 * Single-namespace translation hooks.
 *
 * All strings live under the single `translation` namespace committed in
 * `locales/{en,ne}.json`, so every `t()` call must use fully-qualified keys
 * (e.g. `t('common.save')`, `t('activityValidation.geometryRequired')`).
 *
 * Phase 0.1 removed the old per-namespace hooks (`useTCommon`, `useTValidation`,
 * etc.) — the i18n bundles are key-symmetric across languages (see `keySync` test).
 */
export const useT = (): TFunction => {
  const { t } = useTranslation();
  return t;
};

export const useChangeLanguage = () => {
  const { i18n } = useTranslation();
  return (lng: string) => i18n.changeLanguage(lng);
};