/** EditableCell — inline-editable table cell with click-to-edit behaviour. */
import { useState, useRef, useEffect } from 'react';
import { useT } from '../i18n/hooks';

interface EditableCellProps {
  value: string | number | undefined;
  displayValue?: string;
  onSave: (newValue: string) => void;
  className?: string;
}

export function EditableCell({ value, displayValue, onSave, className = '' }: EditableCellProps) {
  const t = useT();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value != null ? String(value) : '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSave = async () => {
    if (editValue === (value != null ? String(value) : '')) {
      setIsEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(editValue);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setEditValue(value != null ? String(value) : '');
    } finally {
      setSaving(false);
      setIsEditing(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    } else if (e.key === 'Escape') {
      setEditValue(value != null ? String(value) : '');
      setIsEditing(false);
    }
  };

  if (isEditing) {
    return (
      <input
        ref={inputRef}
        type="text"
        value={editValue}
        onChange={(e) => setEditValue(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        className="w-full px-1 py-0.5 text-sm font-mono border border-blue-400 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
    );
  }

  return (
    <span
      onClick={() => { setEditValue(value != null ? String(value) : ''); setIsEditing(true); }}
      className={`cursor-pointer hover:bg-yellow-50 hover:border border hover:border-yellow-300 rounded px-1 py-0.5 inline-block ${saved ? 'text-green-600' : ''} ${className}`}
      title={t('editing.cell.clickToEdit')}
    >
      {saved && <span className="text-green-500 mr-1 text-xs">✓</span>}
      {displayValue ?? (value != null ? String(value) : '-')}
      {saving && <span className="ml-1 text-gray-400 text-xs">...</span>}
    </span>
  );
}
