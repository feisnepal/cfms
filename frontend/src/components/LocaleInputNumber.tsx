/** antd InputNumber that accepts Devanagari digits (D6, revised 2026-08-18). */
import { InputNumber } from 'antd';
import type { InputNumberProps } from 'antd';
import { parseLocaleNumber } from '../i18n/numberFormat';

/**
 * antd's default parser only understands ASCII digits, so a Nepali keyboard's
 * ०-९ is discarded before `onChange` fires and the field reads back empty.
 * Routing the parser through `parseLocaleNumber` accepts either script, and
 * mixed input, while leaving ASCII behaviour unchanged.
 *
 * Wrapped rather than applied per call site so the parser lives in one place.
 * A caller that needs its own parser can still pass one; it wins.
 */
export function LocaleInputNumber<T extends string | number = number>(
  props: InputNumberProps<T>,
) {
  return (
    <InputNumber<T>
      parser={((value?: string) => parseLocaleNumber(String(value ?? ''))) as never}
      {...props}
    />
  );
}

export default LocaleInputNumber;
