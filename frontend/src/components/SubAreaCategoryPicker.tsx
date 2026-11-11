import { SUB_AREA_CATEGORIES, subAreaCategoryColor } from '../lib/subAreaCategories';

interface SubAreaCategoryPickerProps {
  value?: string;
  onChange: (category: string) => void;
  language?: 'en' | 'np';
}

export function SubAreaCategoryPicker({ value, onChange, language = 'en' }: SubAreaCategoryPickerProps) {
  return (
    <div style={styles.grid}>
      {SUB_AREA_CATEGORIES.map(cat => {
        const fillColor = subAreaCategoryColor(cat.key);
        const isSelected = value === cat.key;
        return (
          <button
            key={cat.key}
            onClick={() => onChange(cat.key)}
            style={{
              ...styles.cell,
              background: fillColor,
              border: isSelected ? `3px solid ${subAreaCategoryColor(cat.key)}` : '1px solid #ccc',
              color: '#FFFFFF',
              fontWeight: isSelected ? 700 : 400,
            }}
            title={language === 'np' ? cat.labelNp : cat.label}
            aria-pressed={isSelected}
          >
            {language === 'np' ? cat.labelNp : cat.label}
          </button>
        );
      })}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    gap: 6,
    padding: 8,
    maxHeight: 320,
    overflowY: 'auto',
  },
  cell: {
    padding: '8px 6px',
    border: '1px solid #ccc',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 12,
    lineHeight: 1.3,
    textAlign: 'center',
    transition: 'border-color 0.15s, transform 0.1s',
  },
};

export default SubAreaCategoryPicker;
