import { useState } from 'react';

export const CRS_OPTIONS = [
  { epsg: 4326, label: 'WGS 84 (Geographic)', labelNp: 'डब्लुजिएस ८४', zone: 'global' },
  { epsg: 32644, label: 'UTM Zone 44N', labelNp: 'युटिएम जोन ४४उ', zone: '44N' },
  { epsg: 32645, label: 'UTM Zone 45N', labelNp: 'युटिएम जोन ४५उ', zone: '45N' },
] as const;

export type CrsEpsg = (typeof CRS_OPTIONS)[number]['epsg'];

interface CrsSelectorProps {
  value?: number;
  onChange: (epsg: number) => void;
  disabled?: boolean;
}

export default function CrsSelector({ value, onChange, disabled }: CrsSelectorProps) {
  const [customEpsg, setCustomEpsg] = useState('');
  const preselected = CRS_OPTIONS.find((o) => o.epsg === value);

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-700">
        Coordinate Reference System
      </label>
      <div className="grid grid-cols-3 gap-2">
        {CRS_OPTIONS.map((opt) => (
          <button
            key={opt.epsg}
            type="button"
            disabled={disabled}
            onClick={() => { setCustomEpsg(''); onChange(opt.epsg); }}
            className={`px-3 py-2 text-sm rounded-md border text-left transition-colors
              ${(value === opt.epsg || (!preselected && opt.epsg === 4326 && !customEpsg))
                ? 'border-green-500 bg-green-50 text-green-800'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}
              ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            <span className="block font-medium">{opt.label}</span>
            <span className="block text-xs text-gray-500">{opt.labelNp}</span>
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500">or custom EPSG:</span>
        <input
          type="text" inputMode="decimal"
          value={customEpsg}
          disabled={disabled}
          onChange={(e) => {
            const v = e.target.value;
            setCustomEpsg(v);
            if (v) onChange(Number(v));
          }}
          placeholder="e.g. 32744"
          className="w-28 px-2 py-1 text-sm border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
        />
      </div>
    </div>
  );
}
