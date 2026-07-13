import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { useTheme } from "../../contexts/theme-context";

export type HeatCell = {
  rule_id: string;
  equipment_id: string;
  fault_hours: number;
};

type Props = {
  cells: HeatCell[];
  height?: number;
};

/** Compact portfolio rule×equipment heatmap from batch rollup rows. */
export default function PortfolioRuleHeatmap({ cells, height = 320 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const rules = [...new Set(cells.map((c) => c.rule_id))].sort();
    const equips = [...new Set(cells.map((c) => c.equipment_id))].sort();
    const z = rules.map((rule) =>
      equips.map((eq) => {
        const hit = cells.find((c) => c.rule_id === rule && c.equipment_id === eq);
        return hit ? hit.fault_hours : 0;
      }),
    );
    void Plotly.react(
      el,
      [
        {
          type: "heatmap",
          z,
          x: equips,
          y: rules,
          colorscale: "YlOrRd",
          hoverongaps: false,
        },
      ],
      {
        title: { text: "Portfolio rule heatmap", font: { size: 14 } },
        paper_bgcolor: "transparent",
        plot_bgcolor: theme === "dark" ? "#111827" : "#ffffff",
        font: { color: theme === "dark" ? "#e5e7eb" : "#111827" },
        margin: { l: 100, r: 16, t: 40, b: 80 },
        height,
      },
      { responsive: true, displaylogo: false, modeBarButtonsToAdd: ["toImage"] },
    );
    return () => {
      Plotly.purge(el);
    };
  }, [cells, theme, height]);

  if (cells.length === 0) {
    return <p className="muted small">No heatmap cells.</p>;
  }
  return <div className="portfolio-rule-heatmap" ref={ref} />;
}
