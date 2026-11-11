/**
 * NtfpOutboxBar — what is kept on the phone for want of a signal, above the plot map (owner, 2026-10-22).
 *
 * Says plainly when the phone is offline, how many plots, photos and position checks are waiting and lets the person send them now. An item the server refused is listed with the reason
 * and can be tried again or discarded: nothing the person typed disappears without their say.
 */
import { Alert, Button, Space } from 'antd';
import { useT } from '../../i18n/hooks';
import { persistent, type OutboxItem } from '../../services/ntfpOutbox';
import type { useNtfpOutbox } from '../../hooks/useNtfpOutbox';

interface Props {
  outbox: ReturnType<typeof useNtfpOutbox>;
  names: Record<string, string>;
}

const count = (items: OutboxItem[], kind: OutboxItem['kind']) => items.filter((i) => i.kind === kind).length;

export default function NtfpOutboxBar({ outbox, names }: Props) {
  const t = useT();
  const { waiting, rejected, online, sending } = outbox;
  if (online && waiting.length === 0 && rejected.length === 0) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      {!online && <Alert type="warning" showIcon style={{ marginBottom: 8 }} title={t('ntfp.offline.offline')} />}
      {waiting.length > 0 && (
        <Alert type="info" showIcon style={{ marginBottom: 8 }}
          title={t('ntfp.offline.waitingSummary', { plots: count(waiting, 'plot'), photos: count(waiting, 'photo'), checks: count(waiting, 'presence') })}
          description={persistent() ? t('ntfp.offline.kept') : t('ntfp.offline.keptMemory')}
          action={<Button size="small" type="primary" loading={sending} disabled={!online} onClick={() => void outbox.flush()}>{t('ntfp.offline.sendNow')}</Button>} />
      )}
      {rejected.map((i) => (
        <Alert key={i.id} type="error" showIcon style={{ marginBottom: 8 }}
          title={t('ntfp.offline.refused', { what: t(`ntfp.offline.kind.${i.kind}`), n: i.plotNumber })}
          description={(
            <div>
              <div>{i.error}</div>
              {i.findings && i.findings.length > 0 && (
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {i.findings.filter((f) => f.severity === 'error').map((f, k) => <li key={k}>{f.species_key ? `${names[f.species_key] ?? f.species_key}: ` : ''}{f.message}</li>)}
                </ul>
              )}
            </div>
          )}
          action={(
            <Space>
              <Button size="small" onClick={() => void outbox.retry(i)}>{t('ntfp.offline.retry')}</Button>
              <Button size="small" danger onClick={() => void outbox.discard(i.id)}>{t('ntfp.offline.discard')}</Button>
            </Space>
          )} />
      ))}
    </div>
  );
}
