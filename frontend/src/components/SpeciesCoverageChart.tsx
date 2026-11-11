/** SpeciesCoverageChart — bar chart displaying species coverage area distribution. */
import React from 'react';
import { Bar } from 'react-chartjs-2';
import '../utils/chartSetup';
import { useDimensionLabels } from '../hooks/useDimensionLabels';
import { useT } from '../i18n/hooks';

interface SpeciesData {
  scientific_name: string;
  local_name: string;
  present_in_blocks: number;
  total_blocks: number;
  coverage_percentage: number;
  confirmed: boolean;
  roles: string[];
}

interface SpeciesCoverageChartProps {
  speciesData: SpeciesData[];
  totalBlocks: number;
}

const SpeciesCoverageChart: React.FC<SpeciesCoverageChartProps> = ({ speciesData, totalBlocks }) => {
  const t = useT();
  const labels = useDimensionLabels({ hasCompartments: false });
  // Prepare data for the chart - show top 15 species by coverage
  const chartData = speciesData
    .slice(0, 15)
    .map(species => ({
      name: species.local_name || species.scientific_name,
      blocks: species.present_in_blocks,
      coverage: species.coverage_percentage,
      confirmed: species.confirmed
    }));

  // Color based on confirmation status
  const getBarColor = (confirmed: boolean) => {
    return confirmed ? '#10b981' : '#9ca3af'; // Green if confirmed, gray if not
  };

  return (
    <div className="w-full">
      <h3 className="text-lg font-semibold mb-4 text-gray-900">
        {t('species.chart.title')}
      </h3>
      <div style={{ width: '100%', height: 400 }}>
        <Bar
          height={400}
          data={{
            labels: chartData.map((d) => d.name),
            datasets: [{
              label: labels.unitLabelPlural,
              data: chartData.map((d) => d.blocks),
              backgroundColor: chartData.map((d) => getBarColor(d.confirmed)),
              borderRadius: 8,
            }],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: {
                ticks: { autoSkip: false, maxRotation: 45, minRotation: 45, font: { size: 11 } },
                grid: { display: true },
              },
              y: {
                beginAtZero: true,
                suggestedMax: totalBlocks,
                title: { display: true, text: t('species.chart.numberOfBlocks') },
              },
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: (ctx) => {
                    const d = chartData[ctx.dataIndex];
                    return [
                      `${d.name}`,
                      t('species.chart.presentIn', { blocks: d.blocks, total: totalBlocks }),
                      t('species.chart.coverageLine', { percent: d.coverage }),
                      t('species.chart.statusLine', {
                        status: d.confirmed
                          ? t('species.status.confirmed')
                          : t('species.status.unconfirmed'),
                      }),
                    ];
                  },
                },
              },
            },
          }}
        />
      </div>
      <div className="flex justify-center gap-4 text-sm mt-2">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-green-500 rounded"></div>
          <span>{t('species.status.confirmed')}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-gray-400 rounded"></div>
          <span>{t('species.status.unconfirmed')}</span>
        </div>
      </div>
      <p className="text-xs text-gray-500 mt-2 text-center">
        {t('species.chart.footnote')}
      </p>
    </div>
  );
};

export default SpeciesCoverageChart;
