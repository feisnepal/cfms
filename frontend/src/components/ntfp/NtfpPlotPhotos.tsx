/**
 * NtfpPlotPhotos — the photos taken at a plot, in the entry sheet (owner, 2026-10-22).
 *
 * "Take a photo" opens the phone's camera (a file picker elsewhere). The photo is made smaller on the phone before it is sent, then kept with the plot. Photos are fetched with the
 * sign-in (an <img src> cannot send it), shown as thumbnails, and can be deleted.
 */
import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Popconfirm } from 'antd';
import { CameraOutlined, DeleteOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpPhoto } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { errorKey, type Position } from '../../lib/ntfp';
import { shrinkImage } from '../../lib/imageShrink';
import { discard, enqueue, isNetworkFailure, type OutboxItem } from '../../services/ntfpOutbox';

export const MAX_PHOTOS = 10;

interface Props {
  calculationId: string;
  plotNumber: number;
  photos: NtfpPhoto[];
  /** the position of the last "I am here" check, kept with a photo taken after it */
  position?: Position | null;
  onChanged: () => void;
  /** photos of this plot kept on the phone, waiting for a signal */
  pending?: OutboxItem[];
  onQueued?: () => void;
}

function PendingThumb({ item, onDelete }: { item: OutboxItem; onDelete: () => void }) {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!item.blob) return undefined;
    const made = URL.createObjectURL(item.blob);
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [item.blob]);
  return (
    <div style={{ position: 'relative', width: 104, height: 104, background: '#eee', borderRadius: 6, overflow: 'hidden', outline: '2px dashed #fb8c00' }} data-testid="pending-photo">
      {url && <img src={url} alt={item.fileName ?? 'photo'} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
      <span style={{ position: 'absolute', left: 0, right: 0, bottom: 0, background: 'rgba(251,140,0,0.9)', color: '#fff', fontSize: 11, textAlign: 'center' }}>{t('ntfp.offline.waiting')}</span>
      <Button size="small" icon={<DeleteOutlined />} aria-label={t('ntfp.photo.delete')} onClick={onDelete} style={{ position: 'absolute', top: 4, right: 4 }} />
    </div>
  );
}

function Thumb({ calculationId, photo, onDelete }: { calculationId: string; photo: NtfpPhoto; onDelete: () => void }) {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    ntfpApi.photoBlob(calculationId, photo.id).then((b) => { if (alive) { made = URL.createObjectURL(b); setUrl(made); } }).catch(() => { /* a thumbnail that cannot load stays a grey box */ });
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [calculationId, photo.id]);
  return (
    <div style={{ position: 'relative', width: 104, height: 104, background: '#eee', borderRadius: 6, overflow: 'hidden' }}>
      {url && <img src={url} alt={photo.file_name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
      <Popconfirm title={t('ntfp.photo.deleteConfirm')} okText={t('common.delete')} cancelText={t('common.cancel')} onConfirm={onDelete}>
        <Button size="small" icon={<DeleteOutlined />} aria-label={t('ntfp.photo.delete')} style={{ position: 'absolute', top: 4, right: 4 }} />
      </Popconfirm>
    </div>
  );
}

export default function NtfpPlotPhotos({ calculationId, plotNumber, photos, position, onChanged, pending = [], onQueued }: Props) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await shrinkImage(file);
      const keep = async () => { await enqueue({ calcId: calculationId, kind: 'photo', plotNumber, blob, fileName: file.name, position: position ?? undefined }); onQueued?.(); };
      if (typeof navigator !== 'undefined' && navigator.onLine === false) { await keep(); return; }
      try {
        await ntfpApi.uploadPhoto(calculationId, plotNumber, blob, file.name, position ?? null);
        onChanged();
      } catch (err: any) {
        if (!isNetworkFailure(err)) throw err;
        await keep();   // no signal: the (already shrunk) photo waits on the phone
      }
    } catch (err: any) {
      const key = errorKey(err?.response?.data?.detail?.code);
      setError(key ? t(key) : apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';   // the same photo can be chosen again
    }
  };

  const remove = async (id: string) => {
    try {
      await ntfpApi.deletePhoto(calculationId, id);
      onChanged();
    } catch (err) {
      setError(apiErrorText(err, t('ntfp.error.generic')));
    }
  };

  return (
    <section aria-label={t('ntfp.photo.label')} style={{ border: '1px solid #d9d9d9', borderRadius: 8, padding: 12, marginBottom: 12 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('ntfp.photo.title', { n: photos.length, max: MAX_PHOTOS })}</h4>
      <input ref={input} type="file" accept="image/*" capture="environment" hidden data-testid="photo-input" onChange={(e) => void pick(e.target.files?.[0])} />
      <Button size="large" icon={<CameraOutlined />} loading={busy} disabled={photos.length + pending.length >= MAX_PHOTOS} onClick={() => input.current?.click()}>{t('ntfp.photo.take')}</Button>
      {photos.length + pending.length >= MAX_PHOTOS && <span style={{ marginLeft: 8 }}>{t('ntfp.photo.full')}</span>}
      {error && <Alert type="error" showIcon style={{ marginTop: 8 }} title={error} />}
      {photos.length + pending.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
          {pending.map((p) => <PendingThumb key={p.id} item={p} onDelete={() => void discard(p.id)} />)}
          {photos.map((p) => <Thumb key={p.id} calculationId={calculationId} photo={p} onDelete={() => void remove(p.id)} />)}
        </div>
      )}
    </section>
  );
}
