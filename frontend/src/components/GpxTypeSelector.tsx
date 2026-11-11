import { useState } from 'react';

interface GpxTypeSelectorProps {
  value?: string[];
  onChange: (types: string[]) => void;
  disabled?: boolean;
}

const GPX_TYPES = [
  { id: 'waypoints', label: 'Waypoints', labelNp: 'मार्गबिन्दु', icon: '📍' },
  { id: 'tracks', label: 'Tracks', labelNp: 'ट्र्याक', icon: '〰️' },
  { id: 'routes', label: 'Routes', labelNp: 'मार्ग', icon: '➡️' },
] as const;

export default function GpxTypeSelector({ value = ['waypoints', 'tracks', 'routes'], onChange, disabled }: GpxTypeSelectorProps) {
  const [selected, setSelected] = useState<string[]>(value);

  const toggle = (id: string) => {
    const next = selected.includes(id)
      ? selected.filter((t) => t !== id)
      : [...selected, id];
    if (next.length === 0) return;
    setSelected(next);
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-700">
        GPX Sub-Layers to Import
      </label>
      <div className="flex gap-2">
        {GPX_TYPES.map((t) => (
          <button
            key={t.id}
            type="button"
            disabled={disabled}
            onClick={() => toggle(t.id)}
            className={`px-3 py-2 text-sm rounded-md border transition-colors
              ${selected.includes(t.id)
                ? 'border-green-500 bg-green-50 text-green-800'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}
              ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            <span className="mr-1">{t.icon}</span>
            <span>{t.label}</span>
            <span className="block text-xs text-gray-500">{t.labelNp}</span>
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-500">At least one type must be selected.</p>
    </div>
  );
}
