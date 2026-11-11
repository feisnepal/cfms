import { useState, useRef, useEffect } from 'react';
import { useT } from '../i18n/hooks';
import { SYMBOL_GROUPS, getSymbolEmoji, getSymbolDef } from '../lib/pointSymbols';

interface SymbolPickerProps {
  value: string | undefined | null;
  onChange: (symbolId: string) => void;
}

export default function SymbolPicker({ value, onChange }: SymbolPickerProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          background: 'none', border: '1px solid #ccc', borderRadius: 4,
          cursor: 'pointer', fontSize: 20, padding: '1px 6px', lineHeight: 1.4,
        }}
        title={getSymbolDef(value)?.labelEn || t('layerPanel.selectSymbol')}
      >
        {getSymbolEmoji(value)}
      </button>
      {open && (
        <div
          style={{
            position: 'fixed', zIndex: 9999, background: '#fff', border: '1px solid #ddd',
            borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.18)',
            padding: 12, maxHeight: 360, overflowY: 'auto', minWidth: 280,
            top: ref.current ? ref.current.getBoundingClientRect().bottom + 4 : 0,
            left: ref.current ? Math.min(
              ref.current.getBoundingClientRect().left,
              window.innerWidth - 300,
            ) : 0,
          }}
        >
          {SYMBOL_GROUPS.map(({ group, symbols }) => (
            <div key={group} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#888', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                {group}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                {symbols.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => { onChange(s.id); setOpen(false); }}
                    style={{
                      background: s.id === value ? '#e3f2fd' : 'transparent',
                      border: s.id === value ? '2px solid #1976d2' : '1px solid transparent',
                      borderRadius: 4, cursor: 'pointer', fontSize: 20, padding: 2, width: 34, height: 34,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                    title={`${s.labelEn} (${s.labelNp})`}
                  >
                    {s.emoji}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
