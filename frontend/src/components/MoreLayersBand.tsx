/**
 * MoreLayersBand — the layer panel's "Advanced" band (owner, 2026-10-27): analysis maps, reference data and an NTFP survey the forest does not have
 * sit behind ONE collapsed header instead of being permanently attached above the forest's own layers.
 *
 * The children stay mounted when it is closed (hidden, not removed): the groups draw on the map and take their layers off when they unmount, so closing the band must never
 * switch a layer off. It opens by itself when something inside is on (an analysis map, a reference layer, the NTFP layer), so what is drawn is never out of sight;
 * the user's own open/closed choice is remembered for this browser.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';
import { readSaved } from '../lib/referenceLayers';
import { readNtfpLayerOn } from '../lib/ntfp';

const STORAGE_KEY = 'cf.layerPanel.moreLayersOpen';

const readChoice = (): boolean => {
  try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch { return false; }   // storage blocked: starts closed
};
const writeChoice = (open: boolean): void => {
  try { localStorage.setItem(STORAGE_KEY, open ? '1' : '0'); } catch { /* nothing remembered, nothing breaks */ }
};

interface Props {
  calculationId?: string;
  /** The NTFP layer is inside the band (the forest has no NTFP survey), so its switch counts too. */
  ntfpInside: boolean;
  children: ReactNode;
}

export function MoreLayersBand({ calculationId, ntfpInside, children }: Props) {
  const t = useT();
  const activeMap = useWorkspaceStore((s) => s.activeAnalysisMap);
  const referenceOn = readSaved(calculationId).visible.length;
  const ntfpOn = ntfpInside && readNtfpLayerOn(calculationId);
  const onCount = (activeMap ? 1 : 0) + referenceOn + (ntfpOn ? 1 : 0);

  const [open, setOpen] = useState<boolean>(() => readChoice() || onCount > 0);
  // a different forest, or an analysis map switched on from somewhere else (the Sustainable FM tab, Forest summary): show what is drawn
  useEffect(() => { if (onCount > 0) setOpen(true); }, [calculationId, activeMap]);   // eslint-disable-line react-hooks/exhaustive-deps -- reference/NTFP switches only change while the band is open

  if (!calculationId) return null;
  const toggle = () => { const next = !open; setOpen(next); writeChoice(next); };
  return (
    <div className="more-layers-band" data-testid="more-layers-band">
      <button type="button" className="analysis-maps-header more-layers-header" aria-expanded={open} title={t('layerPanel.moreLayersTitle')} onClick={toggle}>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span> <span aria-hidden="true">⚙️</span> {t('layerPanel.moreLayers')}
        {!open && onCount > 0 && <span className="analysis-maps-active"> · {t('referenceLayers.onCount', { count: onCount })}</span>}
      </button>
      <div hidden={!open} data-testid="more-layers-body">{children}</div>
    </div>
  );
}
