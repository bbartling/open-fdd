import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface PlotlyHostProps extends Omit<WidgetBaseProps, "label"> {
  label?: string;
  /** Reserved for future Plotly figure JSON — not wired in M3-02. */
  figureId?: string;
}

export function PlotlyHost({
  id,
  label = "Chart",
  description,
  disabled,
  loading,
  error,
  testId,
  figureId,
}: PlotlyHostProps) {
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
        data-figure-id={figureId}
        aria-label={label}
      >
        {loading ? "Loading chart…" : "Plotly chart placeholder (M3-02)"}
      </div>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
