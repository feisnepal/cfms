/** Chart renderer (pie/bar) using Chart.js with Nepali-locale digit formatting. */
import React, { useMemo } from 'react';
import { Pie, Bar } from 'react-chartjs-2';
import { GraphicData } from '../../services/sectionGenerators';
import { toNepaliDigit } from '../../constants/nepaliLabels';
import '../../utils/chartSetup';

interface NepaliChartProps {
  graphic: GraphicData;
  height?: number;
}

const FALLBACK_PALETTE = [
  '#059669', '#dc2626', '#2563eb', '#d97706',
  '#7c3aed', '#db2777', '#0891b2', '#65a30d',
  '#ea580c', '#4f46e5', '#0d9488', '#9333ea',
  '#ca8a04', '#16a34a', '#e11d48', '#0284c7',
  '#a21caf', '#c2410c', '#64748b', '#84cc16',
];

function dedupeColors(data: { label: string; value: number; color: string }[]):
  { label: string; value: number; color: string }[] {
  const used = new Set<string>();
  let paletteIdx = 0;
  return data.map((d) => {
    let color = d.color || FALLBACK_PALETTE[paletteIdx % FALLBACK_PALETTE.length];
    while (used.has(color)) {
      paletteIdx++;
      color = FALLBACK_PALETTE[paletteIdx % FALLBACK_PALETTE.length];
    }
    used.add(color);
    paletteIdx++;
    return { ...d, color };
  });
}

const np = (n: number, d = 1) => toNepaliDigit(n, d);

const PieLegend = ({ data }: { data: { label: string; value: number; color: string }[] }) => {
  return (
    <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 mt-2 text-xs">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: d.color }} />
          <span className="text-gray-700">{d.label}</span>
          <span className="text-gray-500 font-medium">{np(d.value, 0)}</span>
        </div>
      ))}
    </div>
  );
};

const NepaliChart: React.FC<NepaliChartProps> = ({ graphic, height = 250 }) => {
  const deduped = useMemo(() => dedupeColors(graphic.data), [graphic.data]);

  if (graphic.type === 'none' || deduped.length === 0) return null;

  const labels = deduped.map((d) => d.label);
  const values = deduped.map((d) => d.value);
  const colors = deduped.map((d) => d.color);
  const total = deduped.reduce((s, d) => s + d.value, 0);

  const tooltipLabel = (ctx: any) => {
    const d = deduped[ctx.dataIndex];
    return [`${d.label}`, `${np(d.value)}%`];
  };

  if (graphic.type === 'pie') {
    return (
      <div>
        <div style={{ width: '100%', height }}>
          <Pie
            height={height}
            data={{
              labels,
              datasets: [{ data: values, backgroundColor: colors, borderColor: '#fff', borderWidth: 1 }],
            }}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: tooltipLabel } },
              },
            }}
          />
        </div>
        <PieLegend data={deduped} />
      </div>
    );
  }

  if (graphic.type === 'bar') {
    return (
      <div style={{ width: '100%', height }}>
        <Bar
          height={height}
          data={{
            labels,
            datasets: [{ label: '', data: values, backgroundColor: colors, borderRadius: 4 }],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: tooltipLabel } },
            },
            scales: {
              x: { ticks: { font: { size: 11 }, autoSkip: false, maxRotation: 35, minRotation: 35 }, grid: { display: true } },
              y: { beginAtZero: true, ticks: { callback: (v) => np(Number(v), 0) } },
            },
          }}
        />
      </div>
    );
  }

  if (graphic.type === 'horizontal_bar') {
    return (
      <div style={{ width: '100%', height: Math.max(height, deduped.length * 35) }}>
        <Bar
          height={Math.max(height, deduped.length * 35)}
          data={{
            labels,
            datasets: [{ label: '', data: values, backgroundColor: colors, borderRadius: 4 }],
          }}
          options={{
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: tooltipLabel } },
            },
            scales: {
              x: { beginAtZero: true, ticks: { callback: (v) => np(Number(v), 0) } },
              y: { ticks: { font: { size: 11 } } },
            },
          }}
        />
      </div>
    );
  }

  if (graphic.type === 'stacked_bar') {
    const innerLabels = deduped.map((d) => d.label);
    const dsColors = deduped.map((d) => d.color);
    return (
      <div style={{ width: '100%', height }}>
        <Bar
          height={height}
          data={{
            labels: ['क्षेत्रफल'],
            datasets: innerLabels.map((l, i) => ({
              label: l,
              data: [values[i]],
              backgroundColor: dsColors[i],
              stack: 'a',
            })),
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: true, labels: { font: { size: 11 } } },
              tooltip: { callbacks: { label: (ctx: any) => `${ctx.dataset.label}: ${np(ctx.parsed.y)}` } },
            },
            scales: {
              x: { stacked: true, grid: { display: true } },
              y: { stacked: true, beginAtZero: true, ticks: { callback: (v) => np(Number(v), 0) } },
            },
          }}
        />
      </div>
    );
  }

  return null;
};

export default NepaliChart;
