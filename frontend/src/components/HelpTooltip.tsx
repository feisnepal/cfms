/** HelpTooltip — renders a question-mark icon with a tooltip explanation. */
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface HelpTooltipProps {
  /** i18n key for tooltip text (e.g., 'tooltips.gpsPoints') */
  tKey?: string;
  /** Fallback text if translation not found */
  fallbackText?: string;
  /** Custom title (not translated) */
  title?: string;
  /** Custom children (icon/label to show) */
  children?: React.ReactNode;
  /** Tooltip position */
  position?: 'top' | 'right' | 'bottom' | 'left';
  /** Legacy prop - use tKey instead */
  helpText?: string;
}

const HelpTooltip: React.FC<HelpTooltipProps> = ({
  tKey,
  fallbackText,
  title,
  children,
  position = 'right',
  helpText,
}) => {
  const { t } = useTranslation();
  const [isVisible, setIsVisible] = useState(false);

  const positionClasses = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
  };

  const arrowClasses = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-gray-700 border-l-transparent border-r-transparent border-b-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-gray-700 border-t-transparent border-b-transparent border-l-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-gray-700 border-l-transparent border-r-transparent border-t-transparent',
    left: 'left-full top-1/2 -translate-y-1/2 border-l-gray-700 border-t-transparent border-b-transparent border-r-transparent',
  };

  // Resolve tooltip text: i18n key > fallback > legacy helpText
  const tooltipText = tKey ? t(tKey) : (fallbackText || helpText || '');

  if (!tooltipText) return <>{children}</>;

  return (
    <div className="relative inline-block">
      {children}
      <button
        type="button"
        onClick={() => setIsVisible(!isVisible)}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        className="ml-1 inline-flex items-center justify-center w-5 h-5 text-gray-400 hover:text-gray-600 rounded-full border border-gray-300 hover:border-gray-400 transition-colors"
        aria-label={t('common.help')}
      >
        <span className="text-xs font-bold">?</span>
      </button>

      {isVisible && (
        <div
          className={`absolute z-50 w-72 p-3 text-sm bg-gray-800 text-white rounded-lg shadow-lg ${positionClasses[position]}`}
        >
          <p className="leading-relaxed">{tooltipText}</p>
          <div
            className={`absolute w-0 h-0 border-4 ${arrowClasses[position]}`}
          />
        </div>
      )}
    </div>
  );
};

export default HelpTooltip;
