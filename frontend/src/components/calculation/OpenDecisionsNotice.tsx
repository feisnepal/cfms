/**
 * Step 11 (Sustainable FM): says how many plan decisions are still open, and takes the reader to where they are answered
 * (the Forest summary panel on the map). It is a notice, never a gate: step 11 can be completed with decisions open, and a
 * failed or refused load simply shows nothing.
 */
import { useInRouterContext, useNavigate } from 'react-router-dom';
import { Alert, Button } from 'antd';
import { useTranslation } from 'react-i18next';
import { useT } from '../../i18n/hooks';
import { localDigits } from '../../lib/forestSummary';
import { useDecisions } from '../../hooks/useForestSummary';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { toSurfaceId } from '../../lib/calcSurface';

function Inner({ calculationId }: { calculationId: string }) {
  const t = useT();
  const { i18n } = useTranslation();
  const lang = i18n.language?.toLowerCase().startsWith('ne') ? 'ne' : 'en';
  const navigate = useNavigate();
  const { data } = useDecisions(calculationId, true);
  const setOpen = useWorkspaceStore((s) => s.setForestSummaryOpen);
  if (!data || data.open_count <= 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="open-decisions-notice"
      message={t('forestSummary.decisions.stepWarning', { count: data.open_count, n: localDigits(data.open_count, lang) })}
      action={
        <Button
          size="small"
          onClick={() => {
            setOpen(true);
            navigate(`/calculations/${calculationId}?surface=${toSurfaceId('base', 'unified')}`);
          }}
        >
          {t('forestSummary.decisions.openSummary')}
        </Button>
      }
    />
  );
}

export default function OpenDecisionsNotice({ calculationId }: { calculationId: string }) {
  return useInRouterContext() ? <Inner calculationId={calculationId} /> : null;
}
