import { useEffect, useState } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { CalculationCostSummary } from './CalculationCostSummary';
import { authHeaders } from '../lib/geometryUndo';

interface Props {
  open: boolean;
  onClose: () => void;
  status: string;
  calculationId: string;
}

export function CompletionModal({ open, onClose, status, calculationId }: Props) {
  const t = useT();
  const setMapLifecycleStatus = useWorkspaceStore((s) => s.setMapLifecycleStatus);

  if (!open) return null;

  const handleSubmit = async () => {
    try {
      const res = await fetch(`/api/calculations/${calculationId}/submit-for-calculation`, { method: 'POST', headers: authHeaders() });
      if (!res.ok) { const err = await res.json(); alert(err.detail?.message || t('dfo.submitFailed')); return; }
      const data = await res.json();
      setMapLifecycleStatus(data.map_lifecycle_status);
      onClose();
    } catch { alert(t('generalErrors.network')); }
  };

  return (
    <div className="modal-overlay" style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.4)',
    }} onClick={onClose}>
      <div className="modal-content" style={{
        background: '#fff', borderRadius: 12, padding: 0, minWidth: 420, maxWidth: 520,
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '20px 24px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{ fontSize: 24 }}>{status === 'locked' ? '🔒' : '✅'}</span>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
              {status === 'locked' ? t('dfo.mapLocked') : t('dfo.calcComplete')}
            </h2>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 14, color: '#6b7280' }}>
            {status === 'locked'
              ? t('dfo.lockedBody')
              : t('dfo.completeBody')}
          </p>
        </div>

        <CalculationCostSummary calculationId={calculationId} />

        <div style={{ padding: '16px 24px', borderTop: '1px solid #e5e7eb', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn btn-secondary" onClick={onClose} style={{
            padding: '8px 16px', borderRadius: 6, border: '1px solid #d1d5db',
            background: '#fff', cursor: 'pointer', fontSize: 14,
          }}>
            {status === 'locked' ? t('common.close') : t('dfo.review')}
          </button>
          {status !== 'locked' && (
            <button className="btn btn-primary" onClick={handleSubmit} style={{
              padding: '8px 16px', borderRadius: 6, border: 'none',
              background: '#2563eb', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 500,
            }}>
              {t('dfo.submitForReview')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
