import { useCallback, type KeyboardEvent } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface SliderProps extends WidgetBaseProps {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function stepValue(
  current: number,
  delta: number,
  min: number,
  max: number,
  step: number,
): number {
  const next = current + delta * step;
  const rounded = Math.round(next / step) * step;
  return clamp(Number(rounded.toFixed(10)), min, max);
}

export function Slider({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  value,
  min,
  max,
  step = 1,
  onChange,
}: SliderProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (disabled || loading) return;

      let next: number | null = null;
      switch (e.key) {
        case "ArrowRight":
        case "ArrowUp":
          next = stepValue(value, 1, min, max, step);
          break;
        case "ArrowLeft":
        case "ArrowDown":
          next = stepValue(value, -1, min, max, step);
          break;
        case "PageUp":
          next = stepValue(value, 10, min, max, step);
          break;
        case "PageDown":
          next = stepValue(value, -10, min, max, step);
          break;
        case "Home":
          next = min;
          break;
        case "End":
          next = max;
          break;
        default:
          return;
      }
      e.preventDefault();
      onChange(next);
    },
    [disabled, loading, value, min, max, step, onChange],
  );

  return (
    <div
      className={`widget widget--slider widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`slider-${id}`, testId)}
    >
      <label className="widget__label" htmlFor={id}>
        {label}
      </label>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <div className="widget__slider-row">
        <input
          id={id}
          type="range"
          className="widget__slider widget__control"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled || loading}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-valuenow={value}
          aria-invalid={Boolean(error)}
          aria-describedby={description ? `${id}-desc` : undefined}
          onChange={(e) => onChange(Number(e.target.value))}
          onKeyDown={handleKeyDown}
        />
        <span className="widget__slider-value" aria-hidden>
          {value}
        </span>
      </div>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
