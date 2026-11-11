/**
 * PanelSkeleton — the loading fallback for a context panel.
 *
 * WORKSPACE_FLOW_NAV_PLAN P2a. The four lazy containers each carried their own
 * copy of this markup, identical except for the `aria-label`, which named the
 * group being loaded. Dissolving the containers means one component, so the
 * label is passed in — the announcement a screen reader makes while a panel
 * loads is unchanged.
 *
 * The `map-skeleton*` / `skeleton-*` class names are referenced by
 * `index.css` and are deliberately unchanged.
 */
import React from 'react';
import { useT } from '../../i18n/hooks';

const PanelSkeleton: React.FC<{ label: string }> = ({ label }) => {
  const t = useT();
  return (
    <div className="map-skeleton" role="status" aria-label={label}>
      <div className="map-skeleton__toolbar">
        <div className="skeleton-pill" />
        <div className="skeleton-pill" />
        <div className="skeleton-pill" />
      </div>
      <div className="map-skeleton__canvas">
        <div className="skeleton-grid">
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="skeleton-tile" style={{ animationDelay: `${i * 50}ms` }} />
          ))}
        </div>
      </div>
    </div>
  );
};

/**
 * Per-group loading label, transcribed from the four lazy containers so the
 * announcement is byte-identical to before.
 */
export const GROUP_SKELETON_LABEL: Record<string, string> = {
  'forest-data': 'calc.loadingForestData',
  'sampling-model': 'calc.loadingSamplingModel',
  'data-maps': 'calc.loadingDataMaps',
  'reports-outputs': 'calc.loadingReportsOutputs',
};

export default PanelSkeleton;
