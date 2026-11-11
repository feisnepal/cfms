/**
 * LanguageSelector — Nepali/English segmented control (Phase 1.2).
 *
 * Bound to `i18n.language`; on change switches the active language and persists
 * it to the detector cache (`localStorage['i18nextLng']`) so the choice survives
 * reloads. Reused on Login/Register cards and (compact) in the Layout header.
 */
import React from 'react';
import { Segmented } from 'antd';
import { GlobalOutlined } from '@ant-design/icons';
import i18n from '../i18n';
import '../styles/LanguageSelector.css';

interface LanguageSelectorProps {
  compact?: boolean;
}

const LanguageSelector: React.FC<LanguageSelectorProps> = ({ compact = false }) => {
  const [lng, setLng] = React.useState<string>(i18n.language);

  React.useEffect(() => {
    const onChange = (next: string) => setLng(next);
    i18n.on('languageChanged', onChange);
    return () => {
      i18n.off('languageChanged', onChange);
    };
  }, []);

  const handleChange = (value: string | number) => {
    const next = value === 'en' ? 'en' : 'ne';
    i18n.changeLanguage(next);
    localStorage.setItem('i18nextLng', next);
  };

  return (
    <div className={compact ? 'language-selector language-selector--compact' : 'language-selector'}>
      <GlobalOutlined />
      <Segmented
        size={compact ? 'small' : 'middle'}
        value={lng === 'en' ? 'en' : 'ne'}
        onChange={handleChange}
        options={[
          { label: 'नेपाली', value: 'ne' },
          { label: 'English', value: 'en' },
        ]}
      />
    </div>
  );
};

export default LanguageSelector;