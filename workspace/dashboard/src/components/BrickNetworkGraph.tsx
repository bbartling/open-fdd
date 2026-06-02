import { useCallback, useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { useTheme } from "../contexts/theme-context";
import { buildBrickNetworkPlot, type BrickNetworkInput } from "../lib/brickNetworkGraph";

type Props = {
  graph: BrickNetworkInput | null;
  className?: string;
  height?: number;
};

export default function BrickNetworkGraph({ graph, className = "", height = 420 }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();

  const render = useCallback(async () => {
    const el = chartRef.current;
    if (!el || !graph?.equipment?.length) {
      if (el) await Plotly.purge(el);
      return;
    }
    const { data, layout } = buildBrickNetworkPlot(graph, theme);
    await Plotly.react(el, data, { ...layout, height }, { displayModeBar: false, responsive: true });
  }, [graph, theme, height]);

  useEffect(() => {
    render().catch(() => undefined);
  }, [render]);

  useEffect(() => {
    return () => {
      if (chartRef.current) Plotly.purge(chartRef.current);
    };
  }, []);

  if (!graph?.equipment?.length) {
    return <p className="muted dm-network-empty">No equipment in model. Import the bench model or sync BACnet polling.</p>;
  }

  return <div ref={chartRef} className={`dm-network-chart ${className}`.trim()} style={{ minHeight: height }} />;
}

export async function downloadBrickNetworkPng(
  el: HTMLDivElement | null,
  filename = "brick-network-graph.png",
): Promise<void> {
  if (!el) return;
  const url = await Plotly.toImage(el, { format: "png", width: 1400, height: 900, scale: 2 });
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}
