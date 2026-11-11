/** ManagementPlanTab — tab for management plan data, charts, and reporting. */
import { useState, useEffect } from 'react';
import {
  Pie, Bar, Line,
} from 'react-chartjs-2';
import { fieldInventoryApi, forestApi } from '../services/api';
import { downloadBlob } from '../utils/download';
import '../utils/chartSetup';
import { useDbhClassConfig } from '../hooks/useDbhClasses';
import { useDimensionLabels } from '../hooks/useDimensionLabels';
import i18n from '../i18n';
import { useT } from '../i18n/hooks';
import { formatDecimal, parseLocaleNumber } from '../i18n/numberFormat';

interface ManagementPlanTabProps {
  calculationId: string;
  fieldInventoryId?: string;
  forestName?: string;
}

interface GroupConfig {
  id: string;
  /** i18n key — replaces the old label/en DualLang pair (rule 4). */
  labelKey: string;
  /** Dimension noun for keys that interpolate {{unit}} (Block vs Compartment). */
  labelUnit?: string;
  charts: string[];
}

/** Block/Compartment noun for the active language — the dimension SSOT holds both. */
function dimensionUnit(labels: ReturnType<typeof useDimensionLabels>): string {
  return i18n.language === 'ne' ? labels.unitLabelNp : labels.unitLabel;
}

function makeGroups(labels: ReturnType<typeof useDimensionLabels>): GroupConfig[] {
  return [
    { id: 'structure',      labelKey: 'managementPlan.group.structure',   charts: ['species', 'dbh', 'structure', 'growth'] },
    { id: 'block-analysis', labelKey: 'managementPlan.group.unitAnalysis', labelUnit: dimensionUnit(labels), charts: ['blocks', 'harvest', 'carbon'] },
    { id: 'condition',      labelKey: 'managementPlan.group.condition',    charts: ['condition', 'productivity'] },
    { id: 'landcover',      labelKey: 'managementPlan.group.landcover',    charts: ['landcover-pie', 'forest-type-pie', 'landcover-block'] },
    { id: 'health-loss',    labelKey: 'managementPlan.group.healthLoss',   charts: ['health-pie', 'canopy-pie', 'loss-gain'] },
    { id: 'terrain-soil',   labelKey: 'managementPlan.group.terrainSoil',  charts: ['slope-pie', 'soil'] },
  ];
}

const COLORS = ['#2e7d32', '#4caf50', '#a5d6a7', '#1565c0', '#42a5f5', '#795548', '#f9a825', '#c62828', '#78909c', '#8bc34a'];
const CONDITION_COLORS: Record<string, string> = { Good: '#2e7d32', Moderate: '#f9a825', Weak: '#c62828' };
const HEALTH_COLORS: Record<string, string> = { excellent: '#1b5e20', healthy: '#4caf50', moderate: '#f9a825', poor: '#ff9800', stressed: '#c62828' };
const CANOPY_COLORS: Record<string, string> = { high_forest: '#1b5e20', pole_trees: '#4caf50', bush_regenerated: '#a5d6a7', non_forest: '#d4d4d4' };
const SLOPE_COLORS: Record<string, string> = { flat: '#a5d6a7', gentle: '#4caf50', moderate: '#f9a825', steep: '#ff9800', very_steep: '#c62828' };

function getPercentColor(key: string, map: Record<string, string>): string {
  for (const [k, v] of Object.entries(map)) {
    if (key.toLowerCase().includes(k)) return v;
  }
  return '#78909c';
}

export function ManagementPlanTab({ calculationId, fieldInventoryId: propFiId, forestName = 'Forest' }: ManagementPlanTabProps) {

  const t = useT();  const [activeGroup, setActiveGroup] = useState('structure');
  const [mgmtData, setMgmtData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aahGood, setAahGood] = useState(75);
  const [aahModerate, setAahModerate] = useState(60);
  const [aahWeak, setAahWeak] = useState(40);
  const [fieldInventoryId, setFieldInventoryId] = useState<string | undefined>(propFiId);
  const [hasCompartments, setHasCompartments] = useState(false);
  const labels = useDimensionLabels({ hasCompartments });

  useEffect(() => {
    if (propFiId) { setFieldInventoryId(propFiId); return; }
    (async () => {
      try {
        const fi = await fieldInventoryApi.getByCalculation(calculationId);
        if (fi?.id) setFieldInventoryId(fi.id);
      } catch { /* no field inventory */ }
    })();
  }, [calculationId, propFiId]);

  useEffect(() => {
    if (!fieldInventoryId) return;
    fetchData();
  }, [fieldInventoryId, calculationId, aahGood, aahModerate, aahWeak]);

  useEffect(() => {
    (async () => {
      try {
        const calc = await forestApi.getCalculation(calculationId);
        const rd = calc?.result_data;
        if (rd && Array.isArray(rd.compartments) && rd.compartments.length > 0) {
          setHasCompartments(true);
        }
      } catch { /* ignore */ }
    })();
  }, [calculationId]);

  const fetchData = async () => {
    if (!fieldInventoryId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fieldInventoryApi.getManagementPlanData(fieldInventoryId, calculationId, aahGood, aahModerate, aahWeak);
      setMgmtData(data);
    } catch (err: any) {
      setError(err.message || t('managementPlan.msgLoadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const [showPlanDialog, setShowPlanDialog] = useState(false);
  const [includeMaps, setIncludeMaps] = useState(true);
  const [includeCharts, setIncludeCharts] = useState(true);
  const [generating, setGenerating] = useState(false);

  const handleExportDocx = async () => {
    if (!fieldInventoryId) return;
    try {
      const blob = await fieldInventoryApi.exportManagementPlanDocx(fieldInventoryId, calculationId, aahGood, aahModerate, aahWeak);
      const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      downloadBlob(blob, `${forestName.replace(/\s/g, '_')}_ManagementPlan_${dateStr}.docx`);
    } catch (err: any) {
      setError('DOCX export failed: ' + err.message);
    }
  };

  const handleExport10yrPlan = async () => {
    if (!fieldInventoryId) return;
    setGenerating(true);
    setError(null);
    try {
      const blob = await fieldInventoryApi.export10yrPlanDocx(
        fieldInventoryId, calculationId, aahGood, aahModerate, aahWeak, includeMaps, includeCharts
      );
      const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      downloadBlob(blob, `${forestName.replace(/\s/g, '_')}_10Yr_ManagementPlan_${dateStr}.docx`);
      setShowPlanDialog(false);
    } catch (err: any) {
      setError('10-Year Plan export failed: ' + err.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleExportDfo = async () => {
    if (!fieldInventoryId) return;
    try {
      const blob = await fieldInventoryApi.exportDfoSummary(fieldInventoryId, calculationId, aahGood, aahModerate, aahWeak);
      const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      downloadBlob(blob, `${forestName.replace(/\s/g, '_')}_FieldInventory_DFOSummary_${dateStr}.xlsx`);
    } catch (err: any) {
      setError('Excel export failed: ' + err.message);
    }
  };

  const renderChart = (chartId: string) => {
    if (!mgmtData) return null;
    switch (chartId) {
      case 'species':        return <SpeciesChart data={mgmtData.species_composition} />;
      case 'blocks':         return <BlockChart data={mgmtData.block_comparison} labels={labels} />;
      case 'harvest':        return <HarvestChart data={mgmtData.annual_harvest_plan} />;
      case 'condition':      return <ConditionChart data={mgmtData.forest_condition_summary} />;
      case 'dbh':            return <DbhClassChart data={mgmtData.dbh_class_volume} />;
      case 'carbon':         return <CarbonChart data={mgmtData.carbon_per_block} />;
      case 'growth':         return <GrowthChart data={mgmtData.growth_rate_classification} />;
      case 'structure':      return <StructureChart data={mgmtData.stand_structure} />;
      case 'productivity':   return <ProductivityChart data={mgmtData.productivity_classification} />;
      case 'landcover-pie':  return <PercentPieChart title={t('managementPlan.chart.landCover')} data={mgmtData.raster_analysis?.landcover_percentages} />;
      case 'forest-type-pie':return <PercentPieChart title={t('managementPlan.chart.forestType')} data={mgmtData.raster_analysis?.forest_type_percentages} />;
      case 'health-pie':     return <PercentPieChart title={t('managementPlan.chart.forestHealth')} data={mgmtData.raster_analysis?.forest_health_percentages} colorMap={HEALTH_COLORS} />;
      case 'canopy-pie':     return <PercentPieChart title={t('managementPlan.chart.canopy')} data={mgmtData.raster_analysis?.canopy_percentages} colorMap={CANOPY_COLORS} />;
      case 'slope-pie':      return <PercentPieChart title={t('managementPlan.chart.slope')} data={mgmtData.raster_analysis?.slope_percentages} colorMap={SLOPE_COLORS} />;
      case 'loss-gain':      return <LossGainChart data={mgmtData.raster_analysis} />;
      case 'landcover-block':return <BlockRasterChart title={t('managementPlan.chart.landCoverByUnit', { unit: dimensionUnit(labels) })} data={mgmtData.blocks_raster} dataKey="landcover_percentages" />;
      case 'soil':           return <SoilChart data={mgmtData.raster_analysis} />;
      default: return null;
    }
  };

  const renderGroup = () => {
    const group = makeGroups(labels).find(g => g.id === activeGroup);
    if (!group || !mgmtData) return null;
    const charts = group.charts.map(id => ({ id, el: renderChart(id) })).filter(c => c.el !== null);
    if (!charts.length) return <div className="text-center py-12 text-gray-400">{t('managementPlan.noDataGroup')}</div>;
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {charts.map(c => (
          <div key={c.id} className="bg-white rounded-lg border p-3">{c.el}</div>
        ))}
      </div>
    );
  };

  if (!fieldInventoryId) {
    return (
      <div className="p-6 text-center text-gray-500">
        {t('managementPlan.needFieldInventory')}
      </div>
    );
  }

  return (
    <>
    <div className="p-4 space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-bold text-green-800">{t('managementPlan.title')}</h2>
        <div className="flex gap-2 items-center">
          <div className="flex items-center gap-1 text-xs">
            <span className="text-gray-600">AAH:</span>
            <input type="text" inputMode="decimal" className="w-12 border rounded px-1 py-0.5 text-xs" value={aahGood}
              onChange={e => setAahGood(parseLocaleNumber(e.target.value))} title="Good %" />
            <input type="text" inputMode="decimal" className="w-12 border rounded px-1 py-0.5 text-xs" value={aahModerate}
              onChange={e => setAahModerate(parseLocaleNumber(e.target.value))} title="Moderate %" />
            <input type="text" inputMode="decimal" className="w-12 border rounded px-1 py-0.5 text-xs" value={aahWeak}
              onChange={e => setAahWeak(parseLocaleNumber(e.target.value))} title="Weak %" />
          </div>
          <button onClick={() => setShowPlanDialog(true)}
            className="px-3 py-1.5 bg-amber-700 text-white rounded text-xs hover:bg-amber-800 font-bold">{t('managementPlan.plan10yrDocx')}</button>
          <button onClick={handleExportDocx}
            className="px-3 py-1.5 bg-green-700 text-white rounded text-xs hover:bg-green-800">{t('managementPlan.downloadDocx')}</button>
          <button onClick={handleExportDfo}
            className="px-3 py-1.5 bg-blue-800 text-white rounded text-xs hover:bg-blue-900">{t('managementPlan.downloadExcel')}</button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b pb-2">
        {makeGroups(labels).map(group => (
          <button key={group.id} onClick={() => setActiveGroup(group.id)}
            className={`px-3 py-1.5 rounded-t text-xs font-medium transition-colors ${activeGroup === group.id ? 'bg-green-700 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}>
            {t(group.labelKey, { unit: group.labelUnit })}
          </button>
        ))}
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}
      {loading && <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-700" /></div>}
      {!loading && mgmtData && renderGroup()}
    </div>

      {/* 10-Year Plan Dialog */}
      {showPlanDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-green-800 mb-4">{t('managementPlan.generateTitle')}</h3>
            <p className="text-xs text-gray-500 mb-4">{t('managementPlan.generate10yr')}</p>

            <div className="space-y-3">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={includeMaps}
                  onChange={e => setIncludeMaps(e.target.checked)} />
                <span className="text-sm">{t('managementPlan.includeMaps')}</span>
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={includeCharts}
                  onChange={e => setIncludeCharts(e.target.checked)} />
                <span className="text-sm">{t('managementPlan.includeCharts')}</span>
              </label>
              <div className="text-xs text-gray-500 bg-gray-50 p-2 rounded">
                <p className="font-semibold mb-1">{t('managementPlan.includesTitle')}</p>
                <ul className="list-disc pl-4 space-y-0.5">
                  <li>{t('managementPlan.includes1')}</li>
                  <li>{t('managementPlan.includes2')}</li>
                  <li>{labels.unitWiseNp(t('managementPlan.tenYearSchedule'))}</li>
                  <li>{t('managementPlan.includes3')}</li>
                </ul>
              </div>
            </div>

            <div className="flex gap-2 mt-6 justify-end">
              <button onClick={() => setShowPlanDialog(false)} disabled={generating}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300">{t('managementPlan.cancel')}</button>
              <button onClick={handleExport10yrPlan} disabled={generating}
                className="px-4 py-2 bg-amber-700 text-white rounded text-sm hover:bg-amber-800 flex items-center gap-2">
                {generating && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />}
                {generating ? t('managementPlan.generating') : t('managementPlan.generateBtn')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── Helper: Generic Percentage Pie Chart ───

function PercentPieChart({ title, data, colorMap }: { title: string; data?: Record<string, number>; colorMap?: Record<string, string> }) {

  const t = useT();  if (!data || !Object.keys(data).length) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">{t('managementPlan.noRaster')}</div>;
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const labels = entries.map(([name]) => name.replace(/_/g, ' '));
  const values = entries.map(([, value]) => value);
  const colors = entries.map(([name], i) => colorMap ? getPercentColor(name, colorMap) : COLORS[i % COLORS.length]);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{title}</h3>
      <div className="h-56">
        <Pie
          height={224}
          data={{
            labels,
            datasets: [{ data: values, backgroundColor: colors, borderColor: '#fff', borderWidth: 1 }],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { position: 'bottom', labels: { font: { size: 11 } } },
              tooltip: {
                callbacks: {
                  label: (ctx) => `${ctx.label}: ${formatDecimal(Number(ctx.parsed), 1)}%`,
                },
              },
            },
          }}
        />
      </div>
    </div>
  );
}

// ─── Helper: Block-wise Raster Stacked Bar ───

function BlockRasterChart({ title, data, dataKey }: { title: string; data?: any[]; dataKey: string }) {

  const t = useT();  if (!data || !data.length) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">{t('managementPlan.noBlockRaster')}</div>;
  const allKeys = new Set<string>();
  data.forEach((b: any) => { const p = b[dataKey]; if (p) Object.keys(p).forEach(k => allKeys.add(k)); });
  const keys = Array.from(allKeys);
  if (!keys.length) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">{t('managementPlan.noBlockRasterShort')}</div>;
  const labels = data.map((b: any) => b.block_name);
  const datasets = keys.map((k, i) => ({
    label: k.replace(/_/g, ' '),
    data: data.map((b: any) => (b[dataKey] || {})[k] || 0),
    backgroundColor: COLORS[i % COLORS.length],
    stack: 'a',
  }));
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{title}</h3>
      <div className="h-56">
        <Bar
          height={224}
          data={{ labels, datasets }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { stacked: true, grid: { display: true } },
              y: { stacked: true, beginAtZero: true },
            },
          }}
        />
      </div>
    </div>
  );
}

// ─── Helper: Empty State ───

function EmptyState() {

  const t = useT();  return <div className="flex items-center justify-center h-48 text-gray-400">{t('managementPlan.noDataSection')}</div>;
}

// ══════════════════════════════════════════════════════════════
// GROUP 1: वन संरचना — Forest Structure Charts
// ══════════════════════════════════════════════════════════════

function SpeciesChart({ data }: { data: any }) {

  const t = useT();  const species = data?.forest_wide || [];
  if (!species.length) return <EmptyState />;
  const labels: string[] = species.map((s: any) => s.local_name || s.scientific_name);
  const values: number[] = species.map((s: any) => s.volume_pct || 0);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.species')}</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        <div className="h-60">
          <Pie
            height={240}
            data={{
              labels,
              datasets: [{ data: values, backgroundColor: labels.map((_, i) => COLORS[i % COLORS.length]), borderColor: '#fff', borderWidth: 1 }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed}%` } },
              },
            }}
          />
        </div>
        <div className="overflow-auto max-h-60">
          <table className="w-full text-xs border-collapse">
            <thead><tr className="bg-green-700 text-white">
              <th className="p-1 text-left">Species</th><th className="p-1 text-right">m³/ha</th><th className="p-1 text-right">%</th>
            </tr></thead>
            <tbody>
              {species.map((s: any, i: number) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-gray-50' : ''}>
                  <td className="p-1">{s.local_name || s.scientific_name}</td>
                  <td className="p-1 text-right">{s.total_volume_m3_per_ha}</td>
                  <td className="p-1 text-right">{s.volume_pct}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DbhClassChart({ data }: { data: any }) {

  const t = useT();  const blocks = data?.blocks || [];
  const dfoExportClasses = useDbhClassConfig('dfo_export');
  if (!blocks.length) return <EmptyState />;
    // P3: the class list is the database's now, via the API. Only the range
    // *text* is built here, because a range label is presentation.
    const dbhLabels = dfoExportClasses.map((c) => `${c.lower}-${c.upper ?? '+'}`);
  const labels = blocks.map((b: any) => b.block);
  const datasets = dbhLabels.map((l, i) => ({
    label: l,
    data: blocks.map((b: any) => b.classes?.find((c: any) => c.dbh_class === l)?.total_m3ha || 0),
    backgroundColor: COLORS[i % COLORS.length],
    stack: 'a',
  }));
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.dbh')}</h3>
      <div className="h-56">
        <Bar
          height={224}
          data={{ labels, datasets }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { stacked: true, grid: { display: true } },
              y: { stacked: true, beginAtZero: true, title: { display: true, text: 'm³/ha' } },
            },
          }}
        />
      </div>
    </div>
  );
}

function StructureChart({ data }: { data: any }) {

  const t = useT();  const blocks = data?.blocks || [];
  const dfoExportClasses = useDbhClassConfig('dfo_export');
  if (!blocks.length) return <EmptyState />;
    // P3: the class list is the database's now, via the API. Only the range
    // *text* is built here, because a range label is presentation.
    const dbhLabels = dfoExportClasses.map((c) => `${c.lower}-${c.upper ?? '+'}`);
  const labels = dbhLabels;
  const datasets = blocks.map((b: any, idx: number) => ({
    label: `${b.block} Actual`,
    data: dbhLabels.map((_, i) => b.classes?.[i]?.actual_nha || 0),
    borderColor: COLORS[idx % COLORS.length],
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    tension: 0.3,
    pointRadius: 2,
  }));
  datasets.push({
    label: 'Ideal',
    data: dbhLabels.map((_, i) => blocks[0]?.classes?.[i]?.ideal_nha || 0),
    borderColor: '#c62828',
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderDash: [5, 5],
    tension: 0.3,
    pointRadius: 3,
  } as any);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.structure')}</h3>
      <div className="h-56">
        <Line
          height={224}
          data={{ labels, datasets }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: 'DBH (cm)' } },
              y: { title: { display: true, text: 'N/ha' }, beginAtZero: true },
            },
          }}
        />
      </div>
      {data.assessment && <div className="mt-1 p-1.5 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-800">{data.assessment}</div>}
    </div>
  );
}

function GrowthChart({ data }: { data: any }) {

  const t = useT();  const classes = data?.classes || [];
  if (!classes.length) return <EmptyState />;
  const labels: string[] = classes.map((c: any) => String(c.rate));
  const values: number[] = classes.map((c: any) => c.volume_pct || 0);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.growth')}</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        <div className="h-48">
          <Pie
            height={192}
            data={{
              labels,
              datasets: [{ data: values, backgroundColor: labels.map((_, i) => COLORS[i % COLORS.length]), borderColor: '#fff', borderWidth: 1 }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed}%` } },
              },
            }}
          />
        </div>
        <div className="overflow-auto max-h-48">
          <table className="w-full text-xs border-collapse">
            <thead><tr className="bg-green-700 text-white">
              <th className="p-1 text-left">Rate</th><th className="p-1 text-right">Sp.</th><th className="p-1 text-right">m³/ha</th><th className="p-1 text-right">%</th>
            </tr></thead>
            <tbody>
              {classes.map((c: any, i: number) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-gray-50' : ''}>
                  <td className="p-1">{c.rate}</td><td className="p-1 text-right">{c.species_count}</td>
                  <td className="p-1 text-right">{c.volume_m3_per_ha}</td><td className="p-1 text-right">{c.volume_pct}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// GROUP 2: ब्लक विश्लेषण — Block Analysis Charts
// ══════════════════════════════════════════════════════════════

function BlockChart({ data, labels: dimLabels }: { data: any; labels?: ReturnType<typeof useDimensionLabels> }) {

  const t = useT();  const blocks = data?.ranked || [];
  if (!blocks.length) return <EmptyState />;
  const blockNames = blocks.map((b: any) => b.name);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.unitComparison', { unit: dimLabels ? dimensionUnit(dimLabels) : t('managementPlan.unitFallback') })}</h3>
      <div className="h-56">
        <Bar
          height={224}
          data={{
            labels: blockNames,
            datasets: [
              { label: 'Growing Stock', data: blocks.map((b: any) => b.growing_stock_m3ha), backgroundColor: COLORS[0] },
              { label: 'AAH Timber', data: blocks.map((b: any) => b.aah_timber_m3yr), backgroundColor: COLORS[3] },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            scales: {
              x: { beginAtZero: true, grid: { display: true } },
              y: { ticks: { font: { size: 11 } } },
            },
          }}
        />
      </div>
    </div>
  );
}

function HarvestChart({ data }: { data: any }) {

  const t = useT();  const blocks = data?.blocks || [];
  if (!blocks.length) return <EmptyState />;
  const labels = blocks.map((b: any) => b.name);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.harvest')}</h3>
      <div className="h-48">
        <Bar
          height={192}
          data={{
            labels,
            datasets: [
              { label: 'AAH Timber', data: blocks.map((b: any) => b.aah_timber_m3yr), backgroundColor: COLORS[0] },
              { label: 'AAH Fuelwood', data: blocks.map((b: any) => b.aah_fuelwood_m3yr), backgroundColor: COLORS[6] },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { grid: { display: true } },
              y: { beginAtZero: true, title: { display: true, text: 'm³/yr' } },
            },
          }}
        />
      </div>
    </div>
  );
}

function CarbonChart({ data }: { data: any }) {

  const t = useT();  const blocks = data?.blocks || [];
  if (!blocks.length) return <EmptyState />;
  const labels = blocks.map((b: any) => b.block);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.carbon')}</h3>
      <div className="h-48">
        <Bar
          height={192}
          data={{
            labels,
            datasets: [
              { label: 'AGB', data: blocks.map((b: any) => b.agb_tha), backgroundColor: COLORS[0] },
              { label: 'BGB', data: blocks.map((b: any) => b.bgb_tha), backgroundColor: COLORS[4] },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { grid: { display: true } },
              y: { beginAtZero: true, title: { display: true, text: 't/ha' } },
            },
          }}
        />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// GROUP 3: वन अवस्था — Forest Condition Charts
// ══════════════════════════════════════════════════════════════

function ConditionChart({ data }: { data: any }) {

  const t = useT();  const byCond = data?.by_condition || [];
  const regen = data?.regeneration || [];
  if (!byCond.length && !regen.length) return <EmptyState />;
  const condLabels = byCond.map((c: any) => c.condition);
  const condValues = byCond.map((c: any) => c.area_ha);
  const condColors = byCond.map((c: any) => CONDITION_COLORS[c.condition] || '#78909c');
  const regenLabels = regen.map((r: any) => r.block);
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.condition')}</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        <div className="h-48">
          <h4 className="text-xs font-semibold text-center">{t('managementPlan.conditionByArea')}</h4>
          <Pie
            height={180}
            data={{
              labels: condLabels,
              datasets: [{ data: condValues, backgroundColor: condColors, borderColor: '#fff', borderWidth: 1 }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${ctx.parsed} ha` } },
              },
            }}
          />
        </div>
        <div className="h-48">
          <h4 className="text-xs font-semibold text-center">{t('managementPlan.regenByBlock')}</h4>
          <Bar
            height={180}
            data={{
              labels: regenLabels,
              datasets: [
                { label: 'Seedling', data: regen.map((r: any) => r.seedling_nha), backgroundColor: COLORS[0] },
                { label: 'Sapling', data: regen.map((r: any) => r.sapling_nha), backgroundColor: COLORS[2] },
              ],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              scales: {
                x: { grid: { display: true } },
                y: { beginAtZero: true },
              },
            }}
          />
        </div>
      </div>
    </div>
  );
}

function ProductivityChart({ data }: { data: any }) {

  const t = useT();  const classes = data?.classes || [];
  if (!classes.length) return <EmptyState />;
  const labels = classes.map((c: any) => c.class);
  const values = classes.map((c: any) => c.area_ha);
  const colors = classes.map((c: any) =>
    c.class === 'High' ? COLORS[0] : c.class === 'Medium' ? COLORS[6] : COLORS[7]
  );
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.productivity')}</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        <div className="h-40">
          <Bar
            height={160}
            data={{
              labels,
              datasets: [{ label: 'Area', data: values, backgroundColor: colors }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              indexAxis: 'y',
              scales: {
                x: { beginAtZero: true, title: { display: true, text: 'Area (ha)' } },
                y: { ticks: { font: { size: 11 } } },
              },
            }}
          />
        </div>
        <div className="overflow-auto max-h-40">
          <table className="w-full text-xs border-collapse">
            <thead><tr className="bg-green-700 text-white">
              <th className="p-1 text-left">Class</th><th className="p-1 text-right">Area</th><th className="p-1 text-left">Recommendation</th>
            </tr></thead>
            <tbody>
              {classes.map((c: any, i: number) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-gray-50' : ''}>
                  <td className="p-1 font-medium">{c.class}</td><td className="p-1 text-right">{c.area_ha}</td>
                  <td className="p-1 text-xs">{c.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// GROUP 5: हानि/लाभ — Loss/Gain & Health Charts
// ══════════════════════════════════════════════════════════════

function LossGainChart({ data }: { data: any }) {

  const t = useT();  const lossHa = data?.forest_loss_hectares;
  const gainHa = data?.forest_gain_hectares;
  const fireHa = data?.fire_loss_hectares;
  const lossByYear = data?.forest_loss_by_year;
  if (lossHa === undefined && gainHa === undefined && !lossByYear) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">{t('managementPlan.noLossGain')}</div>;
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.lossGain')}</h3>
      {(lossHa !== undefined || gainHa !== undefined) && (
        <div className="h-32">
          <Bar
            height={128}
            data={{
              labels: ['Loss', 'Gain', ...(fireHa !== undefined ? ['Fire Loss'] : [])],
              datasets: [{
                label: 'ha',
                data: [lossHa || 0, gainHa || 0, ...(fireHa !== undefined ? [fireHa || 0] : [])],
                backgroundColor: [lossHa || 0, gainHa || 0, fireHa || 0].map((v, i) =>
                  i === 1 ? '#2e7d32' : '#c62828'
                ),
              }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { grid: { display: true } },
                y: { beginAtZero: true, title: { display: true, text: 'ha' } },
              },
            }}
          />
        </div>
      )}
      {lossByYear && Object.keys(lossByYear).length > 0 && (
        <div className="h-40 mt-2">
          <h4 className="text-xs font-semibold text-center mb-1">{t('managementPlan.lossByYear')}</h4>
          <Bar
            height={160}
            data={{
              labels: Object.keys(lossByYear),
              datasets: [{ label: 'ha', data: Object.values(lossByYear), backgroundColor: '#c62828' }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { grid: { display: true } },
                y: { beginAtZero: true },
              },
            }}
          />
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
// GROUP 6: भू-बनोट — Terrain & Soil Charts
// ══════════════════════════════════════════════════════════════

function SoilChart({ data }: { data: any }) {

  const t = useT();  if (!data || (!data.soil_texture && !data.fertility_class && !data.carbon_stock_t_ha)) return <div className="flex items-center justify-center h-48 text-gray-400 text-sm">{t('managementPlan.noSoil')}</div>;
  return (
    <div>
      <h3 className="text-sm font-semibold text-center mb-2">{t('managementPlan.chart.soil')}</h3>
      <div className="space-y-2">
        {data.soil_texture && (
          <div className="flex justify-between items-center p-2 bg-gray-50 rounded">
            <span className="text-xs font-medium">{t('managementPlan.soilTexture')}</span>
            <span className="text-xs">{data.soil_texture.replace(/_/g, ' ')}</span>
          </div>
        )}
        {data.fertility_class && (
          <div className="flex justify-between items-center p-2 bg-gray-50 rounded">
            <span className="text-xs font-medium">{t('managementPlan.soilFertility')}</span>
            <span className={`text-xs font-semibold ${data.fertility_class === 'Low' || data.fertility_class === 'Very Low' ? 'text-red-600' : 'text-green-700'}`}>
              {data.fertility_class} {data.fertility_score !== undefined ? `(${data.fertility_score}/100)` : ''}
            </span>
          </div>
        )}
        {data.carbon_stock_t_ha !== undefined && (
          <div className="flex justify-between items-center p-2 bg-gray-50 rounded">
            <span className="text-xs font-medium">{t('managementPlan.soilCarbon')}</span>
            <span className="text-xs">{data.carbon_stock_t_ha} t/ha</span>
          </div>
        )}
        {data.compaction_status && (
          <div className="flex justify-between items-center p-2 bg-gray-50 rounded">
            <span className="text-xs font-medium">{t('managementPlan.soilCompaction')}</span>
            <span className="text-xs">{data.compaction_status.replace(/_/g, ' ')}</span>
          </div>
        )}
        {data.soil_properties?.ph_h2o !== undefined && (
          <div className="flex justify-between items-center p-2 bg-gray-50 rounded">
            <span className="text-xs font-medium">pH:</span>
            <span className="text-xs">{data.soil_properties.ph_h2o}</span>
          </div>
        )}
      </div>
    </div>
  );
}
