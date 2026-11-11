import { useState } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { CalculationCostSummary } from './CalculationCostSummary';
import { authHeaders } from '../lib/geometryUndo';

interface Props {
  open: boolean;
  onClose: () => void;
  calculationId: string;
}

export function DfoReviewPanel({ open, onClose, calculationId }: Props) {
  const t = useT();
  const setMapLifecycleStatus = useWorkspaceStore((s) => s.setMapLifecycleStatus);
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState<'approve' | 'reject' | null>(null);

  if (!open) return null;

  const handleApprove = async () => {
    setLoading('approve');
    try {
      const res = await fetch(`/api/calculations/${calculationId}/dfo-approve`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ notes }),
      });
      if (!res.ok) { const err = await res.json(); alert(err.detail?.message || t('dfo.approveFailed')); return; }
      setMapLifecycleStatus('locked');
      onClose();
    } catch { alert(t('generalErrors.network')); }
    finally { setLoading(null); }
  };

  const handleReject = async () => {
    if (!notes.trim()) { alert(t('dfo.reasonRequired')); return; }
    setLoading('reject');
    try {
      const res = await fetch(`/api/calculations/${calculationId}/dfo-reject`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ reason: notes }),
      });
      if (!res.ok) { const err = await res.json(); alert(err.detail?.message || t('dfo.rejectFailed')); return; }
      setMapLifecycleStatus('draft');
      onClose();
    } catch { alert(t('generalErrors.network')); }
    finally { setLoading(null); }
  };

  return (
    <div className="modal-overlay" style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.4)',
    }} onClick={onClose}>
      <div className="modal-content" style={{
        background: '#fff', borderRadius: 12, padding: 0, minWidth: 440, maxWidth: 540,
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '20px 24px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{ fontSize: 24 }}>🔍</span>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>{t('dfo.title')}</h2>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 14, color: '#6b7280' }}>
            {t('dfo.description')}
          </p>
        </div>

        <CalculationCostSummary calculationId={calculationId} />

        <div style={{ padding: '12px 24px' }}>
          <label style={{ fontSize: 13, fontWeight: 500, color: '#374151', display: 'block', marginBottom: 4 }}>
            {t('dfo.reviewNotes')}{' '}
            {loading === 'reject' && (
              <span style={{ color: '#ef4444' }}>{t('dfo.requiredForReject')}</span>
            )}
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={4}
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid #d1d5db',
              fontSize: 13, resize: 'vertical', fontFamily: 'inherit',
            }}
            placeholder={t('dfo.phNotes')}
          />
        </div>

        <div style={{ padding: '12px 24px', borderTop: '1px solid #e5e7eb', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} disabled={!!loading} style={{
            padding: '8px 16px', borderRadius: 6, border: '1px solid #d1d5db',
            background: '#fff', cursor: 'pointer', fontSize: 14,
          }}>
            {t('common.cancel')}
          </button>
          <button onClick={handleReject} disabled={loading === 'reject'} style={{
            padding: '8px 16px', borderRadius: 6, border: '1px solid #ef4444',
            background: '#fef2f2', color: '#ef4444', cursor: 'pointer', fontSize: 14, fontWeight: 500,
          }}>
            {loading === 'reject' ? t('dfo.rejecting') : t('dfo.reject')}
          </button>
          <button onClick={handleApprove} disabled={loading === 'approve'} style={{
            padding: '8px 16px', borderRadius: 6, border: 'none',
            background: '#2563eb', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 500,
          }}>
            {loading === 'approve' ? t('dfo.approving') : t('dfo.approveAndLock')}
          </button>
        </div>
      </div>
    </div>
  );
}
