import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { useTheme } from "../../contexts/theme-context";

export type FaultTimelinePoint = {
  timestamp: string;
  raw?: number | boolean | null;
  confirmed?: number | boolean | null;
  operational?: number | boolean | null;
};

type Props = {
  title?: string;
  points: FaultTimelinePoint[];
  height?: number;
};

function to01(v: number | boolean | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v ? 1 : 0;
  return Number(v) > 0 ? 1 : 0;
}

/** Compact Plotly fault overlay — raw / confirmed / operational masks. */
export default function FaultTimeline({ title = "Fault timeline", points, height = 220 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const x = points.map((p) => p.timestamp);
    const traces = [
      {
        type: "scatter",
        mode: "lines",
        name: "raw_fault",
        x,
        y: points.map((p) => to01(p.raw)),
        line: { shape: "hv", width: 1.5 },
      },
      {
        type: "scatter",
        mode: "lines",
        name: "confirmed",
        x,
        y: points.map((p) => to01(p.confirmed)),
        line: { shape: "hv", width: 2 },
      },
    ] as Parameters<typeof Plotly.react>[1];
    if (points.some((p) => p.operational !== undefined && p.operational !== null)) {
      (traces as object[]).push({
        type: "scatter",
        mode: "lines",
        name: "operational",
        x,
        y: points.map((p) => to01(p.operational)),
        line: { shape: "hv", width: 1, dash: "dot" },
      });
    }
    const layout = {
      title: { text: title, font: { size: 14 } },
      paper_bgcolor: "transparent",
      plot_bgcolor: theme === "dark" ? "#111827" : "#ffffff",
      font: { color: theme === "dark" ? "#e5e7eb" : "#111827" },
      margin: { l: 48, r: 16, t: 40, b: 40 },
      height,
      yaxis: { range: [-0.05, 1.05], tickvals: [0, 1], title: "state" },
      xaxis: { title: "time" },
      legend: { orientation: "h" },
      dragmode: "zoom",
    };
    void Plotly.react(el, traces, layout, {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToAdd: ["toImage"],
    });
    return () => {
      Plotly.purge(el);
    };
  }, [points, theme, title, height]);

  return <div className="fault-timeline-chart" ref={ref} />;
}
