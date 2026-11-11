import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useT } from '../i18n/hooks';

interface AddLayerMenuProps {
  position: { x: number; y: number };
  disabled?: boolean;
  onImportFile: () => void;
  onImportWithPurpose?: (purpose: string) => void;
  onDrawOnMap: () => void;
  onClose: () => void;
}

const PURPOSE_IMPORTS: { purpose: string; labelKey: string; descKey: string; icon: string }[] = [
  { purpose: 'blocks', labelKey: 'addLayerMenu.importAsBlocks', descKey: 'addLayerMenu.importAsBlocksDesc', icon: '📦' },
  { purpose: 'sub_blocks', labelKey: 'addLayerMenu.importAsSubBlocks', descKey: 'addLayerMenu.importAsSubBlocksDesc', icon: '⬛' },
  { purpose: 'compartments', labelKey: 'addLayerMenu.importAsCompartments', descKey: 'addLayerMenu.importAsCompartmentsDesc', icon: '📐' },
  { purpose: 'sub_compartments', labelKey: 'addLayerMenu.importAsSubCompartments', descKey: 'addLayerMenu.importAsSubCompartmentsDesc', icon: '🔲' },
  { purpose: 'sub_areas', labelKey: 'addLayerMenu.importAsSubAreas', descKey: 'addLayerMenu.importAsSubAreasDesc', icon: '📍' },
  { purpose: 'activity_features', labelKey: 'addLayerMenu.importAsActivityFeatures', descKey: 'addLayerMenu.importAsActivityFeaturesDesc', icon: '🏃' },
];

export default function AddLayerMenu({ position, disabled = false, onImportFile, onImportWithPurpose, onDrawOnMap, onClose }: AddLayerMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const t = useT();

  useEffect(() => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      ref.current.style.left = `${Math.max(8, position.x - rect.width)}px`;
    }
    if (rect.bottom > window.innerHeight) {
      ref.current.style.top = `${Math.max(8, position.y - rect.height)}px`;
    }
  }, [position]);

  useEffect(() => {
    const onDocMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  return createPortal(
    <div
      ref={ref}
      className="add-layer-menu"
      role="menu"
      aria-label={t('addLayerMenu.aria')}
      style={{ left: position.x, top: position.y }}
    >
      <button
        type="button"
        role="menuitem"
        className="add-layer-menu-item"
        disabled={disabled}
        onClick={() => {
          onClose();
          onImportFile();
        }}
      >
        <span className="aml-icon" aria-hidden="true">⬈</span>
        <span className="aml-text">
          <span className="aml-label">{t('addLayerMenu.importFile')}</span>
          <span className="aml-desc">{t('addLayerMenu.importFileDesc')}</span>
        </span>
      </button>
      {onImportWithPurpose && PURPOSE_IMPORTS.map((p) => (
        <button
          key={p.purpose}
          type="button"
          role="menuitem"
          className="add-layer-menu-item"
          disabled={disabled}
          onClick={() => {
            onClose();
            onImportWithPurpose(p.purpose);
          }}
        >
          <span className="aml-icon" aria-hidden="true">{p.icon}</span>
          <span className="aml-text">
            <span className="aml-label">{t(p.labelKey)}</span>
            <span className="aml-desc">{t(p.descKey)}</span>
          </span>
        </button>
      ))}
      <button
        type="button"
        role="menuitem"
        className="add-layer-menu-item"
        disabled={disabled}
        onClick={() => {
          onClose();
          onDrawOnMap();
        }}
      >
        <span className="aml-icon" aria-hidden="true">✎</span>
        <span className="aml-text">
          <span className="aml-label">{t('addLayerMenu.drawOnMap')}</span>
          <span className="aml-desc">{t('addLayerMenu.drawOnMapDesc')}</span>
        </span>
      </button>
    </div>,
    document.body,
  );
}