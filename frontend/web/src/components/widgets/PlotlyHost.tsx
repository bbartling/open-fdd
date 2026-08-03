import { useEffect, useRef } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";
import type { PlotlyFigure } from "../../api/plotDataset";

export interface PlotlyHostProps extends Omit<WidgetBaseProps, "label"> {
  label?: string;
  /** Figure JSON compatible with Plotly.newPlot */
  figure?: PlotlyFigure | null;
  figureId?: string;
  height?: number;
}

type PlotlyStatic = {
  newPlot: (
    el: HTMLElement,
    data: unknown,
    layout?: unknown,
    config?: unknown,
  ) => Promise<unknown>;
  purge: (el: HTMLElement) => void;
  react?: (
    el: HTMLElement,
    data: unknown,
    layout?: unknown,
    config?: unknown,
  ) => Promise<unknown>;
};

declare global {
  interface Window {
    Plotly?: PlotlyStatic;
  }
}

/** Real Plotly.js host (vendored `/plotly.min.js`). Falls back to a caption if Plotly missing. */
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
  height = 320,
}: PlotlyHostProps) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = hostRef.current;
    const Plotly = window.Plotly;
    if (!el || !Plotly || !figure?.data?.length) return;
    let cancelled = false;
    const layout = {
      margin: { t: 40, r: 20, b: 40, l: 50 },
      height,
      showlegend: figure.layout?.showlegend ?? true,
      title: figure.layout?.title,
      xaxis: figure.layout?.xaxis ?? {},
      yaxis: figure.layout?.yaxis ?? {},
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Source Sans 3, Source Sans, sans-serif", size: 12 },
      ...(figure.layout as object),
    };
    const config = { responsive: true, displayModeBar: true, displaylogo: false };
    void (Plotly.react ?? Plotly.newPlot)(el, figure.data, layout, config).then(
      () => {
        if (cancelled) Plotly.purge(el);
      },
    );
    return () => {
      cancelled = true;
      try {
        Plotly.purge(el);
      } catch {
        /* ignore */
      }
    };
  }, [figure, height]);

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
        style={{ minHeight: height }}
      >
        {loading ? (
          "Loading chart…"
        ) : !figure || !figure.data.length ? (
          "No series loaded"
        ) : !window.Plotly ? (
          <p className="widget__error" role="alert">
            Plotly.js failed to load — check /plotly.min.js
          </p>
        ) : (
          <div ref={hostRef} data-testid={`plotly-div-${id}`} />
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
