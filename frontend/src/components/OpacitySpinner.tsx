/**
 * A compact percentage field with a stacked ▲▼ pair: `80% ▲▼`. About half the width of "− 80% +", and it types, steps with the
 * arrow keys, and steps with the buttons.
 *
 * - ▲ / ▼ (and the arrow keys) move to the NEXT multiple of 10, so 85 → 90 → 100 and 85 → 80 → 70: a value typed off the grid
 *   comes back onto it instead of staying 5 off forever;
 * - typing is committed on Enter or when the field loses focus, clamped to 0-100 and rounded to a whole number; Escape puts the
 *   old value back;
 * - arrows / Home / End are kept inside the field (`stopPropagation`), so a menu that cycles its rows with the arrow keys does not
 *   steal them.
 */
import { useEffect, useState } from 'react';
import { useT } from '../i18n/hooks';

export const clampPercent = (v: number, min = 0, max = 100): number => Math.max(min, Math.min(max, Math.round(v)));

/** The next multiple of `step` in a direction, within [min, max]. */
export function stepPercent(v: number, dir: 1 | -1, step = 10, min = 0, max = 100): number {
  const next = dir === 1 ? (Math.floor(v / step) + 1) * step : (Math.ceil(v / step) - 1) * step;
  return clampPercent(next, min, max);
}

interface Props {
  /** 0-100 */
  value: number;
  onChange: (percent: number) => void;
  ariaLabel: string;
  step?: number;
  min?: number;
  max?: number;
}

export function OpacitySpinner({ value, onChange, ariaLabel, step = 10, min = 0, max = 100 }: Props) {
  const t = useT();
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  const commit = (raw: string) => {
    const n = Number(raw.replace('%', '').trim());
    if (raw.trim() === '' || !Number.isFinite(n)) {
      setDraft(String(value)); // not a number: keep what it was
      return;
    }
    const next = clampPercent(n, min, max);
    setDraft(String(next));
    if (next !== value) onChange(next);
  };
  const go = (dir: 1 | -1) => {
    const next = stepPercent(value, dir, step, min, max);
    if (next !== value) onChange(next);
  };

  return (
    <span className="opacity-spinner">
      <input
        type="text"
        inputMode="numeric"
        className="opacity-spinner-input context-menu-item"
        value={draft}
        aria-label={ariaLabel}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, '').slice(0, 3))}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault();
            e.stopPropagation();
            go(e.key === 'ArrowUp' ? 1 : -1);
          } else if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            commit((e.target as HTMLInputElement).value);
          } else if (e.key === 'Escape') {
            if (draft !== String(value)) {
              e.stopPropagation(); // first Escape only undoes the typing; the next one closes the menu
              setDraft(String(value));
            }
          } else if (e.key === 'Home' || e.key === 'End') {
            e.stopPropagation(); // cursor movement inside the field
          }
        }}
        onClick={(e) => e.stopPropagation()}
      />
      <span className="opacity-spinner-unit" aria-hidden="true">%</span>
      <span className="opacity-spinner-arrows">
        <button type="button" tabIndex={-1} className="opacity-spinner-btn" aria-label={t('layerPanel.opacityUp', { defaultValue: 'More opaque' })} onClick={(e) => { e.stopPropagation(); go(1); }} disabled={value >= max}>▲</button>
        <button type="button" tabIndex={-1} className="opacity-spinner-btn" aria-label={t('layerPanel.opacityDown', { defaultValue: 'More transparent' })} onClick={(e) => { e.stopPropagation(); go(-1); }} disabled={value <= min}>▼</button>
      </span>
    </span>
  );
}
