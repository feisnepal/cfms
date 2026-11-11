/**
 * The unit card: click a block / compartment / sub-unit and every fact the workspace knows about it appears in one place — its
 * Sustainable FM class, its hazard numbers and its field-inventory numbers — whatever analysis map is on. One glance replaces
 * switching between maps and reading the legend for each.
 *
 * It is drawn into the map container (a portal), top right, so it sits over the map and never over the layer panel. Facts come from
 * the same stores that feed the colours, the labels and the table (`unitFacts`), so nothing here can disagree with them.
 */
import { useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import L from 'leaflet';
import { useMap } from 'react-leaflet';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { useT } from '../../i18n/hooks';
import i18n from '../../i18n';
import { getFeatureLayerRegistry } from '../../lib/featureLayerRegistry';
import { sfmPropsFor } from '../../lib/sfmFeatureProps';
import { hazardPropsFor } from '../../lib/hazardFeatureProps';
import { unitFacts } from '../../lib/unitFacts';
import { isUnitLayerId } from '../../lib/analysisMaps';

type UnitLayer = L.Layer & { feature?: { properties?: Record<string, unknown> } };

export function UnitFactsCard() {
  const map = useMap();
  const t = useT();
  const selection = useWorkspaceStore((s) => s.selection);
  const sfm = useWorkspaceStore((s) => s.sfmBlockTypes);
  const hazard = useWorkspaceStore((s) => s.hazardUnits);
  const fi = useWorkspaceStore((s) => s.fieldInventoryUnits);
  const inspected = useWorkspaceStore((s) => s.inspectedUnit);
  const clear = useWorkspaceStore((s) => s.clearSelection);

  const node = useMemo(() => {
    const d = document.createElement('div');
    d.className = 'unit-facts-card';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.disableScrollPropagation(d);
    return d;
  }, []);
  useEffect(() => {
    map.getContainer().appendChild(node);
    return () => {
      node.remove();
    };
  }, [map, node]);

  const selected = selection.layerId && isUnitLayerId(selection.layerId) && selection.featureIds.length === 1 ? selection.featureIds[0] : null;
  const single = inspected && isUnitLayerId(inspected.layerId) ? inspected.id : selected;
  const base = single ? (getFeatureLayerRegistry().get(single) as UnitLayer | undefined)?.feature?.properties : undefined;
  const name = base ? String(base.name ?? '') : '';
  const sections = useMemo(() => {
    if (!base) return [];
    const props: Record<string, unknown> = { ...base };
    if (sfm?.[name]) Object.assign(props, sfmPropsFor(sfm[name]));
    if (hazard?.[name]) Object.assign(props, hazardPropsFor(hazard[name]));
    if (fi?.[name]) Object.assign(props, fi[name]);
    return unitFacts(props, i18n.language, (k, o) => String(i18n.t(k, o as never)));
  }, [base, name, sfm, hazard, fi]);

  // the node is always in the DOM (cheap); it is only visible when a unit is selected
  node.style.display = base ? 'block' : 'none';
  if (!base) return null;
  return createPortal(
    <div data-testid="unit-facts-card" role="region" aria-label={t('unitFacts.title', { defaultValue: 'Unit facts', name })}>
      <div className="unit-facts-head">
        <b>{name}</b>
        <button type="button" className="unit-facts-close" onClick={clear} aria-label={t('unitFacts.close', { defaultValue: 'Close' })}>×</button>
      </div>
      {sections.length === 0 && <div className="unit-facts-empty">{t('unitFacts.none', { defaultValue: 'Nothing is known about this unit yet.' })}</div>}
      {sections.map((s) => (
        <div key={s.id} className="unit-facts-section" data-testid={`unit-facts-${s.id}`}>
          <div className="unit-facts-title">{s.title}</div>
          {s.rows.map((r) => (
            <div key={r.label} className="unit-facts-row">
              <span>{r.label}</span>
              <b>{r.value}</b>
            </div>
          ))}
        </div>
      ))}
    </div>,
    node,
  );
}
