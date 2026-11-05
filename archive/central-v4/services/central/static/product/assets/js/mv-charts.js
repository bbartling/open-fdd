/** M&V change-point panel (3-trace fit). */
export function mvChartOption(envelope) {
  const points = envelope?.points ?? [];
  if (!points.length) return null;
  const base = points.filter((p) => p.period_kind === "baseline");
  const rep = points.filter((p) => p.period_kind === "reporting");
  const pred = points.filter((p) => p.y_predicted != null);
  const series = [
    {
      type: "scatter",
      name: "Baseline",
      data: base.map((p) => [Number(p.x), Number(p.y)]),
    },
    {
      type: "scatter",
      name: "Reporting",
      data: rep.map((p) => [Number(p.x), Number(p.y)]),
    },
  ];
  if (pred.length) {
    series.push({
      type: "scatter",
      name: "Predicted",
      symbol: "diamond",
      data: pred.map((p) => [Number(p.x), Number(p.y_predicted)]),
    });
  }
  return {
    backgroundColor: "transparent",
    grid: { left: 48, right: 16, top: 36, bottom: 40 },
    legend: { top: 0 },
    xAxis: {
      type: "value",
      name: envelope?.coverage?.dd_kind ?? "degree-days",
    },
    yAxis: {
      type: "value",
      name: "energy",
    },
    series,
  };
}
