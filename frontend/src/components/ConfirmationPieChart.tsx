/** ConfirmationPieChart — pie chart displaying confirmation status proportions. */
import React from 'react';
import { Pie } from 'react-chartjs-2';
import '../utils/chartSetup';

interface ConfirmationPieChartProps {
  confirmedCount: number;
  unconfirmedCount: number;
}

const ConfirmationPieChart: React.FC<ConfirmationPieChartProps> = ({ confirmedCount, unconfirmedCount }) => {
  const data = [
    { name: 'Confirmed', value: confirmedCount, color: '#10b981' },
    { name: 'Unconfirmed', value: unconfirmedCount, color: '#9ca3af' }
  ];

  const totalSpecies = confirmedCount + unconfirmedCount;
  const confirmedPercentage = totalSpecies > 0 ? ((confirmedCount / totalSpecies) * 100).toFixed(1) : '0.0';

  return (
    <div className="w-full">
      <h3 className="text-lg font-semibold mb-4 text-gray-900">
        Species Confirmation Status
      </h3>
      <div className="flex flex-col items-center">
        <div style={{ width: '100%', height: 300 }}>
          <Pie
            height={300}
            data={{
              labels: data.map((d) => d.name),
              datasets: [{
                data: data.map((d) => d.value),
                backgroundColor: data.map((d) => d.color),
                borderColor: '#fff',
                borderWidth: 1,
              }],
            }}
            options={{
              plugins: {
                legend: { display: false },
                tooltip: {
                  callbacks: {
                    label: (ctx) => {
                      const value = ctx.parsed as number;
                      const percent = totalSpecies > 0 ? ((value / totalSpecies) * 100).toFixed(1) : '0.0';
                      return `${ctx.label}: ${value} species (${percent}%)`;
                    },
                  },
                },
              },
            }}
          />
        </div>
        <div className="flex justify-center gap-4 text-sm mt-4">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-green-500 rounded"></div>
            <span>Confirmed ({confirmedCount})</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-gray-400 rounded"></div>
            <span>Unconfirmed ({unconfirmedCount})</span>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-4 w-full max-w-md">
          <div className="bg-gray-50 p-3 rounded-lg text-center">
            <p className="text-2xl font-bold text-gray-900">{totalSpecies}</p>
            <p className="text-xs text-gray-600 mt-1">Total Species</p>
          </div>
          <div className="bg-green-50 p-3 rounded-lg text-center">
            <p className="text-2xl font-bold text-green-600">{confirmedCount}</p>
            <p className="text-xs text-gray-600 mt-1">Confirmed</p>
          </div>
          <div className="bg-gray-100 p-3 rounded-lg text-center">
            <p className="text-2xl font-bold text-gray-600">{unconfirmedCount}</p>
            <p className="text-xs text-gray-600 mt-1">Unconfirmed</p>
          </div>
        </div>

        <div className="mt-4 text-center">
          <p className="text-sm text-gray-600">
            Confirmation Progress: <span className="font-semibold text-green-600">{confirmedPercentage}%</span> complete
          </p>
        </div>
      </div>
    </div>
  );
};

export default ConfirmationPieChart;
