import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";
import type { PlotlyFigure } from "../../api/plotDataset";

export interface PlotlyHostProps extends Omit<WidgetBaseProps, "label"> {
  label?: string;
  /** Figure JSON from plotDataset / future Plotly.react */
  figure?: PlotlyFigure | null;
  figureId?: string;
  height?: number;
}

function buildSvgPath(
  xs: number[],
  ys: Array<number | null>,
  width: number,
  height: number,
  pad: number,
): string {
  const finite = ys
    .map((y, i) => (y == null || !Number.isFinite(y) ? null : { i, y }))
    .filter((p): p is { i: number; y: number } => p != null);
  if (!finite.length || xs.length < 2) return "";
  const yMin = Math.min(...finite.map((p) => p.y));
  const yMax = Math.max(...finite.map((p) => p.y));
  const ySpan = yMax - yMin || 1;
  const xSpan = xs.length - 1 || 1;
  let d = "";
  let penUp = true;
  for (let i = 0; i < ys.length; i++) {
    const y = ys[i];
    if (y == null || !Number.isFinite(y)) {
      penUp = true;
      continue;
    }
    const px = pad + (i / xSpan) * (width - 2 * pad);
    const py = height - pad - ((y - yMin) / ySpan) * (height - 2 * pad);
    d += penUp ? `M ${px} ${py}` : ` L ${px} ${py}`;
    penUp = false;
  }
  return d;
}

const TRACE_COLORS = ["#0f766e", "#b45309", "#1d4ed8", "#be123c", "#7c3aed"];

export function PlotlyHost({
  id,
  label = "Chart",
  description,
  disabled,
  loading,
  error,
  testId,
  figure,
  figureId,
  height = 220,
}: PlotlyHostProps) {
  const width = 640;
  const pad = 24;
  const traces = figure?.data ?? [];
  const xs = traces[0]?.x?.map((_, i) => i) ?? [];

  return (
    <div
      className={`widget widget--plotly${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`plotly-host-${id}`, testId)}
      aria-disabled={disabled || undefined}
      aria-busy={loading || undefined}
    >
      <span className="widget__label">{label}</span>
      {description ? (
        <p className="widget__description">{description}</p>
      ) : null}
      <div
        className="widget-plotly-host"
        data-figure-id={figureId ?? figure?.meta?.rule_id}
        aria-label={label}
      >
        {loading ? (
          "Loading chart…"
        ) : !figure || !traces.length ? (
          "No series loaded"
        ) : (
          <svg
            viewBox={`0 0 ${width} ${height}`}
            width="100%"
            height={height}
            role="img"
            data-testid={`plotly-svg-${id}`}
          >
            <title>{figure.layout?.title ?? label}</title>
            {traces.map((t, idx) => {
              const d = buildSvgPath(
                xs.length ? xs : t.x.map((_, i) => i),
                t.y,
                width,
                height,
                pad,
              );
              if (!d) return null;
              return (
                <path
                  key={t.name}
                  d={d}
                  fill="none"
                  stroke={TRACE_COLORS[idx % TRACE_COLORS.length]}
                  strokeWidth={2}
                  data-trace={t.name}
                />
              );
            })}
          </svg>
        )}
      </div>
      {figure?.meta ? (
        <p className="widget__description" data-testid={`plotly-meta-${id}`}>
          {figure.meta.point_count ?? 0} pts
          {figure.meta.downsampled ? " · downsampled" : ""}
          {figure.meta.provenance ? ` · ${figure.meta.provenance}` : ""}
        </p>
      ) : null}
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
