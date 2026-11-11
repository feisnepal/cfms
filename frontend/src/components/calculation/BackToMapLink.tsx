/**
 * "← Map" link for the analysis tabs (Sustainable FM, later Hazard & Erosion): the way back to the map workspace after
 * "Open in … tab" from the Analysis maps group. `useNavigate` needs a Router; without one (tests, embeds) nothing is
 * rendered rather than a dead link.
 */
import { useInRouterContext, useNavigate } from 'react-router-dom';
import { Button } from 'antd';
import { useT } from '../../i18n/hooks';
import { toSurfaceId } from '../../lib/calcSurface';

function Inner({ calculationId }: { calculationId: string }) {
  const t = useT();
  const navigate = useNavigate();
  return (
    <Button
      size="small"
      onClick={() => navigate(`/calculations/${calculationId}?surface=${toSurfaceId('base', 'unified')}`)}
      data-testid="back-to-map"
    >
      {t('analysisMaps.backToMap', { defaultValue: '← Map' })}
    </Button>
  );
}

export default function BackToMapLink({ calculationId }: { calculationId: string }) {
  return useInRouterContext() ? <Inner calculationId={calculationId} /> : null;
}
