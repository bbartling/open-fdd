import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface MetricDelta {
  value: string;
  direction?: "up" | "down" | "neutral";
}

export interface MetricProps extends WidgetBaseProps {
  value: string | number;
  delta?: MetricDelta;
}

export function Metric({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  value,
  delta,
}: MetricProps) {
  return (
    <div
      className={`widget-metric widget-metric--${density}${error ? " widget--error" : ""}${disabled ? " widget--disabled" : ""}`}
      data-testid={widgetTestId(`metric-${id}`, testId)}
      aria-disabled={disabled || undefined}
      aria-busy={loading || undefined}
    >
      <p className="widget-metric__label">{label}</p>
      {description ? (
        <p className="widget__description">{description}</p>
      ) : null}
      <p className="widget-metric__value" aria-live="polite">
        {loading ? "…" : value}
      </p>
      {delta && !loading ? (
        <p
          className={`widget-metric__delta widget-metric__delta--${delta.direction ?? "neutral"}`}
        >
          {delta.value}
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
