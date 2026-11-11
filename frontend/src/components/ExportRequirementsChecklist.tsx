import React from 'react';
import { CheckCircleFilled, CloseCircleFilled, RightOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { ExportRequirements } from '../services/api';
import { requirementUrl } from '../lib/exportRequirementLinks';

/**
 * The mandatory steps before the Operational Plan can be exported, each marked done or not.
 * Labels and hints come from the backend (`export_requirements.py`) already in both languages.
 *
 * With a `calculationId` every step is a shortcut to the page where it is done. `onNavigate` lets a caller that has a
 * router (and, for a dialog, a way to close itself) do the navigation; without it the link is an ordinary address, which
 * also works from places that sit outside the router (an antd `Modal.warning` renders in its own tree).
 */
export function ExportRequirementsChecklist({
  data,
  calculationId,
  onNavigate,
}: {
  data: ExportRequirements;
  calculationId?: string;
  onNavigate?: (url: string) => void;
}) {
  const { i18n } = useTranslation();
  const ne = i18n.language?.startsWith('ne');
  const done = data.items.filter((i) => i.done).length;
  return (
    <div data-testid="export-requirements">
      <p style={{ marginBottom: 8 }}>
        {ne
          ? `${done} / ${data.items.length} अनिवार्य चरण पूरा भएका छन्।`
          : `${done} of ${data.items.length} required steps are complete.`}
      </p>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {data.items.map((i) => {
          const url = calculationId ? requirementUrl(calculationId, i.key) : null;
          const body = (
            <>
              {i.done
                ? <CheckCircleFilled style={{ color: '#52c41a', marginTop: 4 }} />
                : <CloseCircleFilled style={{ color: '#ff4d4f', marginTop: 4 }} />}
              <span style={{ flex: 1 }}>
                <strong>{ne ? i.label_ne : i.label_en}</strong>
                {!i.done && <div style={{ opacity: 0.75 }}>{ne ? i.hint_ne : i.hint_en}</div>}
              </span>
              {url && <RightOutlined aria-hidden="true" style={{ marginTop: 4, opacity: 0.5 }} />}
            </>
          );
          return (
            <li key={i.key} style={{ padding: 0 }}>
              {url ? (
                <a
                  href={url}
                  data-testid={`export-requirement-link-${i.key}`}
                  onClick={(e) => {
                    if (onNavigate) {
                      e.preventDefault();
                      onNavigate(url);
                    }
                  }}
                  style={{ display: 'flex', gap: 8, padding: '6px 4px', color: 'inherit', textDecoration: 'none', borderRadius: 4 }}
                  title={ne ? 'यो चरण गर्ने पेजमा जानुहोस्' : 'Go to the page where this step is done'}
                >
                  {body}
                </a>
              ) : (
                <div style={{ display: 'flex', gap: 8, padding: '4px 0' }}>{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
