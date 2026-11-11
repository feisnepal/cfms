/** Copy-to-clipboard tag component for copying label-value pairs. */
import React, { useState } from 'react';
import { useT } from '../../i18n/hooks';

interface CopyTagProps {
  label: string;
  value: string;
  variant?: 'section' | 'variable';
}

const CopyTag: React.FC<CopyTagProps> = ({ label, value, variant = 'variable' }) => {
  const t = useT();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = value;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const bgColor = variant === 'section' ? 'bg-purple-100 text-purple-800 border-purple-300' : 'bg-blue-50 text-blue-700 border-blue-200';

  return (
    <span
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono border cursor-pointer transition-colors hover:opacity-80 ${bgColor}`}
      title={t('operationalPlan.detail.clickToCopy', { value })}
    >
      <code>{label}</code>
      <span className="text-[10px] opacity-60">{copied ? '✓' : '📋'}</span>
    </span>
  );
};

export default CopyTag;
