/** Thin wrapper around react-nepali-datepicker-bs providing a controlled Nepali (Bikram Sambat) date input. */
import React from 'react';
import { NepaliDatePicker as BsDatePicker } from 'react-nepali-datepicker-bs';
import 'react-nepali-datepicker-bs/dist/index.css';
import { useT } from '../../i18n/hooks';

interface NepaliDatePickerProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
}

export const NepaliDatePicker: React.FC<NepaliDatePickerProps> = ({ value, onChange, placeholder }) => {

  const t = useT();  return (
    <BsDatePicker
      value={value ?? ''}
      onChange={(date: string) => onChange?.(date)}
      formatOptions={{
        separator: '/',
        format: 'YYYY/MM/DD',
      }}
      options={{
        calenderLocale: 'ne',
        valueLocale: 'en',
        closeOnSelect: true,
      }}
      placeholder={placeholder || t('operationalPlan.datePicker.placeholder')}
      theme="forest"
      style={{ width: '100%' }}
      todayIfEmpty={false}
    />
  );
};
