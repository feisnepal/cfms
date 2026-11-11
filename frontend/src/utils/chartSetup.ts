/**
 * Chart.js global registration and default configuration.
 *
 * Registers all required Chart.js component types (arc, bar, line,
 * point, scales, title, tooltip, legend) so they are available across
 * the app without per-component registration.
 */
import {
  Chart as ChartJS,
  ArcElement,
  BarElement,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';

ChartJS.register(
  ArcElement,
  BarElement,
  LineElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Title,
  Tooltip,
  Legend,
  Filler
);

ChartJS.defaults.font.family =
  "'Helvetica Neue', 'Helvetica', 'Arial', 'Noto Sans', sans-serif";

export {};
