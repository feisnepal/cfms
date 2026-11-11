import React, { useState } from 'react';

/**
 * One year of one plan line as a spreadsheet cell (owner, 2026-10-15): click and type, Enter saves and goes down, Tab goes right,
 * Up / Down move between rows, Esc puts the old number back, and a block copied from Excel fills the cells from here on.
 * The cell shows ONE number - the quantity or the budget, whichever the table is switched to.
 */
export const YearInputCell: React.FC<{
  testId: string;
  row: number;
  col: number;
  /** the number as text, or '' for a year that is not planned */
  shown: string;
  filled?: boolean;
  /** save the typed text; resolves false when it was refused (the cell keeps what was typed and turns red) */
  onCommit: (text: string) => Promise<boolean>;
  /** a copied block (tab / new-line separated) was pasted with this cell as its top-left corner */
  onPasteBlock: (text: string, row: number, col: number) => void;
  /** move the focus to another cell of the grid */
  onMove: (row: number, col: number) => void;
}> = ({ testId, row, col, shown, filled, onCommit, onPasteBlock, onMove }) => {
  const [text, setText] = useState<string | null>(null); // null = not being edited
  const [invalid, setInvalid] = useState(false);

  const commit = async (): Promise<boolean> => {
    if (text === null || text === shown) {
      setText(null);
      setInvalid(false);
      return true;
    }
    const ok = await onCommit(text);
    if (ok) {
      setText(null);
      setInvalid(false);
    } else {
      setInvalid(true);
    }
    return ok;
  };

  return (
    <input
      data-testid={testId}
      data-grid-row={row}
      data-grid-col={col}
      inputMode="decimal"
      value={text ?? shown}
      placeholder="—"
      aria-invalid={invalid || undefined}
      onFocus={(e) => {
        setText(shown);
        e.currentTarget.select();
      }}
      onChange={(e) => {
        setText(e.target.value);
        setInvalid(false);
      }}
      onBlur={() => void commit()}
      onPaste={(e) => {
        const pasted = e.clipboardData.getData('text');
        if (!/[\t\n\r]/.test(pasted.trim())) return; // one value: the normal paste
        e.preventDefault();
        setText(null);
        onPasteBlock(pasted, row, col);
      }}
      onKeyDown={async (e) => {
        if (e.key === 'Enter' || e.key === 'ArrowDown') {
          e.preventDefault();
          if (await commit()) onMove(row + 1, col);
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (await commit()) onMove(row - 1, col);
        } else if (e.key === 'Escape') {
          setText(null);
          setInvalid(false);
          (e.currentTarget as HTMLInputElement).blur();
        }
      }}
      style={{
        width: 70,
        textAlign: 'right',
        border: `1px solid ${invalid ? '#dc2626' : 'transparent'}`,
        borderBottom: invalid ? '1px solid #dc2626' : '1px dotted #d1d5db',
        background: filled ? '#fffbe6' : 'transparent',
        font: 'inherit',
        padding: '2px 4px',
      }}
    />
  );
};
