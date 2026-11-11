import { useEffect, useState } from 'react';
import { useT } from '../i18n/hooks';
import { authHeaders } from '../lib/geometryUndo';

interface CostEstimate {
  cpu_seconds: number;
  peak_memory_mb: number;
  cpu_cost: number;
  memory_cost: number;
  total_cost: number;
  currency: string;
  rates_applied?: { cpu_cost_per_hour: number; memory_cost_per_gb_hour: number };
  computed_at?: string;
}

interface Props {
  calculationId: string;
}

export function CalculationCostSummary({ calculationId }: Props) {
  const t = useT();
  const [cost, setCost] = useState<CostEstimate | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!calculationId) return;
    let cancelled = false;

    const fetchCost = async () => {
      try {
        const res = await fetch(`/api/calculations/${calculationId}/progress`, { headers: authHeaders() });
        if (!res.ok) { setLoading(false); return; }
        const data = await res.json();
        if (!cancelled) {
          setCost(data.cost_estimate);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };

    fetchCost();
    return () => { cancelled = true; };
  }, [calculationId]);

  if (loading) return <div className="cost-summary-loading" style={{ padding: '8px 12px', fontSize: 13, color: '#6b7280' }}>{t('calc.loadingCostEstimate')}</div>;
  if (!cost) return null;

  const formatCurrency = (val: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: cost.currency, minimumSignificantDigits: 3 }).format(val);

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m ${s.toFixed(0)}s`;
  };

  return (
    <div className="cost-summary" style={{
      borderTop: '1px solid #e5e7eb',
      padding: '10px 14px',
      fontSize: 13,
      color: '#374151',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ fontWeight: 600, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.5px', color: '#6b7280' }}>
          {t('calc.calculationCost')}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 16px' }}>
        <span style={{ color: '#6b7280' }}>{t('calc.cpuTime')}</span>
        <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{formatDuration(cost.cpu_seconds)}</span>
        <span style={{ color: '#6b7280' }}>{t('calc.peakMemory')}</span>
        <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{cost.peak_memory_mb.toFixed(0)} MB</span>
        <span style={{ color: '#6b7280' }}>{t('calc.cpuCost')}</span>
        <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{formatCurrency(cost.cpu_cost)}</span>
        <span style={{ color: '#6b7280' }}>{t('calc.memoryCost')}</span>
        <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{formatCurrency(cost.memory_cost)}</span>
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginTop: 6, paddingTop: 6, borderTop: '1px solid #e5e7eb',
        fontWeight: 600, fontSize: 14,
      }}>
        <span>{t('calc.total')}</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatCurrency(cost.total_cost)}</span>
      </div>
    </div>
  );
}
