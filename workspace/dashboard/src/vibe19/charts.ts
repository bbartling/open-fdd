import { MAX_PLOT_POINTS } from "./contract";

// plotly.js-dist-min does not export TS Data/Layout types reliably — keep loose.
type Data = Record<string, unknown>;
type Layout = Record<string, unknown>;
type Config = Record<string, unknown>;

export function plotlyConfig(): Partial<Config> {
  return {
    displaylogo: false,
    responsive: true,
    toImageButtonOptions: { format: "png", filename: "openfdd-chart" },
  };
}

/** Display-only downsample — never use for rule math. */
export function downsample<T>(xs: T[], max = MAX_PLOT_POINTS): T[] {
  if (xs.length <= max) return xs;
  const step = Math.ceil(xs.length / max);
  return xs.filter((_, i) => i % step === 0);
}

export type SeriesPoint = { t: string | number; y: number | null };

/** Multi-y traces + confirmed-fault swim lane (vibe19 rule_result_chart). */
export function ruleResultChart(opts: {
  title: string;
  series: { name: string; points: SeriesPoint[]; yaxis?: string }[];
  confirmed: { t: string | number; fault: boolean }[];
}): { data: Data[]; layout: Partial<Layout> } {
  const data: Data[] = opts.series.map((s, i) => {
    const pts = downsample(s.points);
    return {
      type: "scatter",
      mode: "lines",
      name: s.name,
      x: pts.map((p) => p.t),
      y: pts.map((p) => p.y),
      yaxis: s.yaxis ?? (i === 0 ? "y" : `y${i + 1}`),
    };
  });
  const conf = downsample(opts.confirmed);
  data.push({
    type: "scatter",
    mode: "lines",
    name: "confirmed_fault",
    x: conf.map((p) => p.t),
    y: conf.map((p) => (p.fault ? 1 : 0)),
    yaxis: "y2",
    line: { shape: "hv", width: 1 },
    fill: "tozeroy",
  });
  return {
    data,
    layout: {
      title: { text: opts.title },
      margin: { t: 48, r: 48, b: 40, l: 48 },
      legend: { orientation: "h" },
      yaxis2: { overlaying: "y", side: "right", range: [0, 1.2], showgrid: false, title: { text: "fault" } },
    },
  };
}

export function multiEquipmentTimeseries(opts: {
  title: string;
  series: { name: string; points: SeriesPoint[] }[];
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: opts.series.map((s) => {
      const pts = downsample(s.points);
      return {
        type: "scatter",
        mode: "lines",
        name: s.name,
        x: pts.map((p) => p.t),
        y: pts.map((p) => p.y),
      };
    }),
    layout: { title: { text: opts.title }, margin: { t: 48, r: 24, b: 40, l: 48 }, legend: { orientation: "h" } },
  };
}

export function oatScatter(opts: {
  title: string;
  x: number[];
  y: number[];
  name?: string;
}): { data: Data[]; layout: Partial<Layout> } {
  const n = Math.min(opts.x.length, opts.y.length);
  const idx = downsample([...Array(n).keys()]);
  return {
    data: [
      {
        type: "scatter",
        mode: "markers",
        name: opts.name ?? "samples",
        x: idx.map((i) => opts.x[i]),
        y: idx.map((i) => opts.y[i]),
        marker: { size: 5, opacity: 0.6 },
      },
    ],
    layout: {
      title: { text: opts.title },
      xaxis: { title: { text: "OAT °F" } },
      yaxis: { title: { text: "Value" } },
      margin: { t: 48, r: 24, b: 48, l: 48 },
    },
  };
}

export function vavComfortDonut(opts: {
  title: string;
  inComfort: number;
  outComfort: number;
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: [
      {
        type: "pie",
        hole: 0.55,
        labels: ["In comfort", "Out of comfort"],
        values: [opts.inComfort, opts.outComfort],
      },
    ],
    layout: { title: { text: opts.title }, margin: { t: 48, r: 24, b: 24, l: 24 } },
  };
}

export function barChart(opts: {
  title: string;
  labels: string[];
  values: number[];
  name?: string;
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: [{ type: "bar", name: opts.name ?? "value", x: opts.labels, y: opts.values }],
    layout: { title: { text: opts.title }, margin: { t: 48, r: 24, b: 48, l: 48 } },
  };
}
