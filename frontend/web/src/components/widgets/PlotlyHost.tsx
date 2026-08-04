import { useEffect, useMemo, useRef, useState } from "react";
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
  Plots?: { resize: (el: HTMLElement) => void };
};

declare global {
  interface Window {
    Plotly?: PlotlyStatic;
  }
}

/** Drop Plotly.py template blobs — they bloat JSON and can break newPlot. */
export function sanitizePlotlyFigure(
  figure: PlotlyFigure | null | undefined,
): PlotlyFigure | null {
  if (!figure || !Array.isArray(figure.data) || figure.data.length === 0) {
    return null;
  }
  const layout = { ...(figure.layout ?? {}) } as Record<string, unknown>;
  delete layout.template;
  return { ...figure, data: figure.data, layout };
}

function waitForPlotly(timeoutMs = 8000): Promise<PlotlyStatic | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.Plotly) return Promise.resolve(window.Plotly);
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      if (window.Plotly) {
        resolve(window.Plotly);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        resolve(null);
        return;
      }
      window.setTimeout(tick, 50);
    };
    tick();
  });
}

/** Real Plotly.js host (vendored `/plotly.min.js`). */
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
  const [renderErr, setRenderErr] = useState<string | null>(null);
  const [plotlyReady, setPlotlyReady] = useState(() => Boolean(window.Plotly));
  const [drawn, setDrawn] = useState(false);
  const clean = useMemo(() => sanitizePlotlyFigure(figure), [figure]);

  useEffect(() => {
    let cancelled = false;
    void waitForPlotly().then((P) => {
      if (!cancelled) setPlotlyReady(Boolean(P));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    let cancelled = false;

    const draw = async () => {
      setRenderErr(null);
      setDrawn(false);
      if (!clean?.data?.length) {
        try {
          window.Plotly?.purge(el);
        } catch {
          /* ignore */
        }
        el.replaceChildren();
        return;
      }
      const Plotly = (await waitForPlotly()) ?? window.Plotly;
      if (cancelled || !Plotly) {
        if (!cancelled && !Plotly) {
          setRenderErr("Plotly.js failed to load — check /plotly.min.js");
        }
        return;
      }
      const layout: Record<string, unknown> = {
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: "Source Sans 3, Source Sans, sans-serif", size: 12 },
        ...(clean.layout as object),
        height: (clean.layout as { height?: number } | undefined)?.height ?? height,
        autosize: true,
      };
      delete layout.template;
      const config = {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
      };
      try {
        await (Plotly.react ?? Plotly.newPlot)(el, clean.data, layout, config);
        if (cancelled) {
          Plotly.purge(el);
          return;
        }
        setDrawn(true);
        try {
          Plotly.Plots?.resize(el);
        } catch {
          /* ignore */
        }
      } catch (err) {
        if (!cancelled) {
          setRenderErr(err instanceof Error ? err.message : String(err));
          setDrawn(false);
        }
      }
    };

    void draw();
    return () => {
      cancelled = true;
      try {
        window.Plotly?.purge(el);
      } catch {
        /* ignore */
      }
    };
  }, [clean, height]);

  const statusMsg = loading
    ? "Loading chart…"
    : renderErr
      ? null
      : !clean
        ? "No series loaded"
        : !plotlyReady
          ? "Waiting for Plotly.js…"
          : drawn
            ? null
            : "Rendering chart…";

  return (
    <div
      className={`widget widget--plotly${error || renderErr ? " widget--error" : ""}`}
      data-testid={widgetTestId(`plotly-host-${id}`, testId)}
      aria-disabled={disabled || undefined}
      aria-busy={loading || (!drawn && Boolean(clean)) || undefined}
    >
      <span className="widget__label">{label}</span>
      {description ? (
        <p className="widget__description">{description}</p>
      ) : null}
      <div
        className="widget-plotly-host"
        data-figure-id={figureId ?? figure?.meta?.rule_id}
        aria-label={label}
        style={{
          position: "relative",
          minHeight: height,
          width: "100%",
        }}
      >
        {/* Always mounted so Plotly can draw; overlays communicate status */}
        <div
          ref={hostRef}
          data-testid={`plotly-div-${id}`}
          style={{ width: "100%", minHeight: height }}
        />
        {statusMsg ? (
          <p
            className="widget-plotly-host__status"
            data-testid={`plotly-status-${id}`}
            role="status"
          >
            {statusMsg}
          </p>
        ) : null}
      </div>
      {drawn && clean ? (
        <p className="widget__description" data-testid={`plotly-meta-${id}`}>
          {clean.data.length} trace{clean.data.length === 1 ? "" : "s"}
          {clean.meta?.point_count != null
            ? ` · ${clean.meta.point_count} pts`
            : ""}
          {clean.meta?.downsampled ? " · downsampled" : ""}
          {clean.meta?.provenance ? ` · ${clean.meta.provenance}` : ""}
          {" · rendered"}
        </p>
      ) : null}
      {renderErr || error ? (
        <p className="widget__error" role="alert">
          {renderErr || error}
        </p>
      ) : null}
    </div>
  );
}
