/**
 * LocaleSync — re-renders the app (and thus antd's ConfigProvider) whenever the
 * active i18n language changes (Phase 1.3).
 *
 * Returns the antd Locale matching the current language, subscribing to
 * i18next `languageChanged` events so the ConfigProvider swaps instantly when a
 * user flips the LanguageSelector (Table "No data", pagination, Modal default
 * buttons, Select search, Upload.Dragger copy, …).
 */
import React from 'react';
import i18n from './index';
import neLocale from 'antd/locale/ne_NP';
import enLocale from 'antd/locale/en_US';

export const useAntdLocale = () => {
  const [language, setLanguage] = React.useState<string>(i18n.language);

  React.useEffect(() => {
    const onChange = (next: string) => setLanguage(next);
    i18n.on('languageChanged', onChange);
    return () => {
      i18n.off('languageChanged', onChange);
    };
  }, []);

  return language === 'en' ? enLocale : neLocale;
};

export default useAntdLocale;