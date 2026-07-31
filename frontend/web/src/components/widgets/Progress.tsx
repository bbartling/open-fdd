import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface ProgressProps extends WidgetBaseProps {
  value: number;
  max?: number;
  showLabel?: boolean;
}

export function Progress({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  value,
  max = 100,
  showLabel = true,
}: ProgressProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div
      className={`widget widget--progress widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`progress-${id}`, testId)}
      aria-disabled={disabled || undefined}
    >
      <span className="widget__label" id={`${id}-label`}>
        {label}
      </span>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <div
        className="widget-progress"
        role="progressbar"
        aria-labelledby={`${id}-label`}
        aria-describedby={description ? `${id}-desc` : undefined}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={loading ? undefined : value}
        aria-busy={loading || undefined}
      >
        <div className="widget-progress__track">
          <div
            className="widget-progress__bar"
            style={{ width: loading ? "30%" : `${pct}%` }}
          />
        </div>
        {showLabel ? (
          <span className="widget-progress__label">
            {loading ? "Loading…" : `${Math.round(pct)}%`}
          </span>
        ) : null}
      </div>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export type StatusBadgeVariant =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral";

export interface StatusBadgeProps extends Omit<WidgetBaseProps, "label"> {
  label: string;
  variant?: StatusBadgeVariant;
}

export function StatusBadge({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  variant = "neutral",
}: StatusBadgeProps) {
  return (
    <div
      className={`widget widget--badge widget--${density}`}
      data-testid={widgetTestId(`badge-${id}`, testId)}
    >
      <span
        id={id}
        className={`widget-badge widget-badge--${variant}`}
        aria-disabled={disabled || undefined}
        aria-busy={loading || undefined}
        aria-describedby={description ? `${id}-desc` : undefined}
      >
        {loading ? "…" : label}
      </span>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
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
