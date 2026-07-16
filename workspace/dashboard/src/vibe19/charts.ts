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
      yaxis2: {
        overlaying: "y",
        side: "right",
        range: [0, 1.2],
        showgrid: false,
        title: { text: "fault" },
      },
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
    layout: {
      title: { text: opts.title },
      margin: { t: 48, r: 24, b: 40, l: 48 },
      legend: { orientation: "h" },
    },
  };
}

export function multiEquipmentBox(opts: {
  title: string;
  series: { name: string; values: number[] }[];
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: opts.series.map((s) => ({
      type: "box",
      name: s.name,
      y: downsample(s.values),
      boxpoints: false,
    })),
    layout: {
      title: { text: opts.title },
      margin: { t: 48, r: 24, b: 40, l: 48 },
      showlegend: false,
    },
  };
}

export function oatScatter(opts: {
  title: string;
  x: number[];
  y: number[];
  name?: string;
  xTitle?: string;
  yTitle?: string;
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
      xaxis: { title: { text: opts.xTitle ?? "OAT °F" } },
      yaxis: { title: { text: opts.yTitle ?? "Value" } },
      margin: { t: 48, r: 24, b: 48, l: 48 },
    },
  };
}

export function motorWeeklyRuntimeChart(opts: {
  title: string;
  weeks: string[];
  hours: number[];
  name?: string;
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: [
      {
        type: "bar",
        name: opts.name ?? "runtime_h",
        x: opts.weeks,
        y: opts.hours,
      },
    ],
    layout: {
      title: { text: opts.title },
      xaxis: { title: { text: "Week" } },
      yaxis: { title: { text: "Hours" } },
      margin: { t: 48, r: 24, b: 48, l: 48 },
    },
  };
}

function histogram(opts: {
  title: string;
  values: number[];
  name?: string;
  xTitle?: string;
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: [
      {
        type: "histogram",
        name: opts.name ?? "samples",
        x: downsample(opts.values),
        nbinsx: 40,
      },
    ],
    layout: {
      title: { text: opts.title },
      xaxis: { title: { text: opts.xTitle ?? "°F" } },
      yaxis: { title: { text: "Count" } },
      margin: { t: 48, r: 24, b: 48, l: 48 },
      bargap: 0.05,
    },
  };
}

export function mechCoolingOatHistogram(opts: {
  title: string;
  oatValues: number[];
}): { data: Data[]; layout: Partial<Layout> } {
  return histogram({
    title: opts.title,
    values: opts.oatValues,
    name: "mech_cooling_oat",
    xTitle: "OAT °F (mechanical cooling)",
  });
}

export function basVsWebOatHistogram(opts: {
  title: string;
  deltaValues: number[];
}): { data: Data[]; layout: Partial<Layout> } {
  return histogram({
    title: opts.title,
    values: opts.deltaValues,
    name: "bas_minus_web",
    xTitle: "BAS − web OAT °F",
  });
}

export function basVsWebOatOverlay(opts: {
  title: string;
  bas: SeriesPoint[];
  web: SeriesPoint[];
}): { data: Data[]; layout: Partial<Layout> } {
  const bas = downsample(opts.bas);
  const web = downsample(opts.web);
  return {
    data: [
      {
        type: "scatter",
        mode: "lines",
        name: "BAS OAT",
        x: bas.map((p) => p.t),
        y: bas.map((p) => p.y),
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Web OAT",
        x: web.map((p) => p.t),
        y: web.map((p) => p.y),
      },
    ],
    layout: {
      title: { text: opts.title },
      yaxis: { title: { text: "°F" } },
      margin: { t: 48, r: 24, b: 40, l: 48 },
      legend: { orientation: "h" },
    },
  };
}

/** Stacked/overlaid lines for equipment inspection. */
export function equipmentInspectionChart(opts: {
  title: string;
  series: { name: string; points: SeriesPoint[] }[];
}): { data: Data[]; layout: Partial<Layout> } {
  return multiEquipmentTimeseries(opts);
}

/** Sensor-health matrix — rows = sensors, columns = days, z = fault fraction. */
export function sensorFaultChart(opts: {
  title: string;
  sensors: string[];
  days: string[];
  z: number[][];
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: [
      {
        type: "heatmap",
        z: opts.z,
        x: opts.days,
        y: opts.sensors,
        colorscale: "YlOrRd",
        zmin: 0,
        zmax: 1,
      },
    ],
    layout: {
      title: { text: opts.title },
      margin: { t: 48, r: 24, b: 48, l: 96 },
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

/** Metering: monthly bars + degree-day scatter companion. */
export function meteringBarScatter(opts: {
  title: string;
  months: string[];
  usage: number[];
  degreeDays: number[];
  usageName?: string;
  ddName?: string;
}): { data: Data[]; layout: Partial<Layout> } {
  return {
    data: [
      {
        type: "bar",
        name: opts.usageName ?? "usage",
        x: opts.months,
        y: opts.usage,
        yaxis: "y",
      },
      {
        type: "scatter",
        mode: "markers+lines",
        name: opts.ddName ?? "degree_days",
        x: opts.months,
        y: opts.degreeDays,
        yaxis: "y2",
      },
    ],
    layout: {
      title: { text: opts.title },
      margin: { t: 48, r: 48, b: 48, l: 48 },
      legend: { orientation: "h" },
      yaxis2: { overlaying: "y", side: "right", title: { text: "DD" } },
    },
  };
}
