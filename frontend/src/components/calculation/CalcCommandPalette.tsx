/**
 * CalcCommandPalette — Ctrl/Cmd+K quick-switch across every group → context in
 * the tabbed calculation shell. Single Workspace task A6.
 *
 * Mounted once by `CalculationDetailTabbed`; `onNavigate` is the shell's
 * guarded tab+context setter. Keyboard handling lives here (one listener)
 * alongside the single `ActivityRail`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from 'antd';
import { Search } from 'lucide-react';
import { useT } from '../../i18n/hooks';
import { TABS, TAB_CONFIG, type TabId } from '../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from './calcContexts';

interface Entry {
  group: TabId;
  groupLabel: string;
  context: string;
  label: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
}

interface CalcCommandPaletteProps {
  onNavigate: (group: TabId, context: string) => void;
}

export function CalcCommandPalette({ onNavigate }: CalcCommandPaletteProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const entries = useMemo<Entry[]>(
    () =>
      TABS.flatMap((group) =>
        GROUP_CONTEXTS[group].map((c) => ({
          group,
          groupLabel: t(TAB_CONFIG[group].labelKey),
          context: c.id,
          label: t(c.labelKey),
          Icon: c.icon,
        })),
      ),
    [t],
  );

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) => e.label.toLowerCase().includes(q) || e.groupLabel.toLowerCase().includes(q),
    );
  }, [entries, query]);

  useEffect(() => setHighlight(0), [query]);

  // Global shortcut: Ctrl/Cmd+K opens the palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setHighlight(0);
      // antd renders the modal body on the next frame
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  const choose = useCallback(
    (e: Entry | undefined) => {
      if (!e) return;
      setOpen(false);
      onNavigate(e.group, e.context);
    },
    [onNavigate],
  );

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(results[highlight]);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={() => setOpen(false)}
      footer={null}
      closable={false}
      destroyOnHidden
      width={520}
      styles={{ body: { padding: 0 } }}
    >
      <div className="p-3 border-b border-gray-200 flex items-center gap-2">
        <Search size={16} className="text-gray-400 flex-shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onInputKeyDown}
          placeholder={t('calc.palette.placeholder')}
          aria-label={t('calc.palette.placeholder')}
          className="flex-1 text-sm outline-none bg-transparent"
        />
      </div>
      <ul role="listbox" className="max-h-80 overflow-y-auto py-1 m-0 list-none">
        {results.length === 0 && (
          <li className="px-4 py-3 text-sm text-gray-400">{t('calc.palette.empty')}</li>
        )}
        {results.map((e, i) => {
          const Icon = e.Icon;
          return (
            <li key={`${e.group}:${e.context}`} role="option" aria-selected={i === highlight}>
              <button
                type="button"
                onMouseEnter={() => setHighlight(i)}
                onClick={() => choose(e)}
                className={`w-full flex items-center gap-3 px-4 py-2 text-left text-sm ${
                  i === highlight ? 'bg-green-50 text-green-900' : 'text-gray-700 hover:bg-gray-50'
                }`}
              >
                <Icon size={16} className="flex-shrink-0 text-gray-400" />
                <span className="flex-1 truncate">{e.label}</span>
                <span className="text-xs text-gray-400 flex-shrink-0">{e.groupLabel}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}

export default CalcCommandPalette;
