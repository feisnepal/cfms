import React from 'react'
import { useT } from '../i18n/hooks'

const LEGEND_ITEMS = [
  { dash: '─ ─', color: '#FFD700', statusKey: 'boundary.status_draft' },
  { dash: '───', color: '#228B22', statusKey: 'boundary.status_validated' },
  { dash: '───', color: '#1E90FF', statusKey: 'boundary.status_approved' },
  { dash: '···', color: '#FF4444', statusKey: 'boundary.status_disputed' },
]

export default function BoundaryLegend() {
  const t = useT()
  return (
    <div
      style={{
        background: 'white',
        borderRadius: 4,
        padding: '8px 12px',
        boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
        fontSize: 12,
        lineHeight: '20px',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{t('boundary.statusTitle')}</div>
      {LEGEND_ITEMS.map(item => (
        <div key={item.statusKey} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: item.color, fontWeight: 'bold', fontFamily: 'monospace' }}>
            {item.dash}
          </span>
          <span>{t(item.statusKey)}</span>
        </div>
      ))}
    </div>
  )
}