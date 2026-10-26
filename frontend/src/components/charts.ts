import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Filler, Tooltip, Legend);

ChartJS.defaults.font.family = '"IBM Plex Sans", system-ui, sans-serif';
ChartJS.defaults.font.size = 12;
ChartJS.defaults.plugins.legend.labels.boxWidth = 12;
ChartJS.defaults.plugins.legend.labels.boxHeight = 12;
ChartJS.defaults.plugins.tooltip.padding = 10;
ChartJS.defaults.maintainAspectRatio = false;
// Colours depend on the theme: see useChartColors() in theme.tsx.

export const pctTick = (d = 0) => (v: string | number) => `${(Number(v) * 100).toFixed(d)}%`;
