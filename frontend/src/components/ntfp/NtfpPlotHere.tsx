/**
 * NtfpPlotHere — the "I am here" check at the top of a plot's entry sheet (owner, 2026-10-22).
 *
 * Reads the phone's position, sends it with its accuracy, and shows what the server made of it: at the plot, far from it, or too uncertain to say. It never stops the survey:
 * under a closed canopy the position can be tens of metres out, so a "far" answer is a warning to check the plot number, not a lock.
 */
import { useState } from 'react';
import { Alert, Button } from 'antd';
import { AimOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpPresence } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { positionFailureKey, readPosition, verdictKey, type Position, type PositionFailure } from '../../lib/ntfp';
import { enqueue, isNetworkFailure } from '../../services/ntfpOutbox';

interface Props {
  calculationId: string;
  plotNumber: number;
  presence: NtfpPresence | null;
  /** called with the new check and the position it was made from */
  onChecked: (p: NtfpPresence, pos: Position) => void;
  /** a position check of this plot is waiting on the phone for a signal */
  queued?: boolean;
  /** the check was kept on the phone (no signal): the position is still used for photos taken after it */
  onQueued?: (pos: Position) => void;
}

const metres = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`);

export default function NtfpPlotHere({ calculationId, plotNumber, presence, onChecked, queued, onQueued }: Props) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = async () => {
    setBusy(true);
    setError(null);
    try {
      const pos = await readPosition();
      const keep = async () => { await enqueue({ calcId: calculationId, kind: 'presence', plotNumber, position: pos }); onQueued?.(pos); };
      if (typeof navigator !== 'undefined' && navigator.onLine === false) { await keep(); return; }
      try {
        const res = await ntfpApi.checkPresence(calculationId, plotNumber, pos);
        onChecked(res, pos);
      } catch (err: any) {
        if (!isNetworkFailure(err)) throw err;
        await keep();   // no signal: the position is read now, while the person is at the plot, and compared when it can be sent
      }
    } catch (err: any) {
      if (typeof err === 'string') setError(t(positionFailureKey(err as PositionFailure)));
      else setError(apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setBusy(false);
    }
  };

  const level = presence ? (presence.verdict === 'at' ? 'success' : presence.verdict === 'far' ? 'warning' : 'info') : null;
  return (
    <div style={{ marginBottom: 12 }}>
      <Button size="large" icon={<AimOutlined />} loading={busy} onClick={() => void check()} block>{t('ntfp.here.button')}</Button>
      {error && <Alert type="error" showIcon style={{ marginTop: 8 }} title={error} />}
      {queued && <Alert type="info" showIcon style={{ marginTop: 8 }} title={t('ntfp.offline.positionKept')} />}
      {presence && level && (
        <Alert type={level} showIcon style={{ marginTop: 8 }}
          title={t(verdictKey(presence.verdict))}
          description={t('ntfp.here.detail', { distance: metres(presence.distance_m), accuracy: presence.accuracy_m == null ? '—' : metres(presence.accuracy_m) })} />
      )}
    </div>
  );
}
