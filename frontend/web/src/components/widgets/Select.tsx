import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps extends WidgetBaseProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  multiple?: false;
}

export interface MultiSelectProps extends WidgetBaseProps {
  value: string[];
  options: SelectOption[];
  onChange: (value: string[]) => void;
}

export function Select({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  value,
  options,
  onChange,
}: SelectProps) {
  return (
    <div
      className={`widget widget--select widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`select-${id}`, testId)}
    >
      <label className="widget__label" htmlFor={id}>
        {label}
      </label>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <select
        id={id}
        className="widget__control"
        value={value}
        disabled={disabled || loading}
        aria-invalid={Boolean(error)}
        aria-describedby={description ? `${id}-desc` : undefined}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function MultiSelect({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  value,
  options,
  onChange,
}: MultiSelectProps) {
  return (
    <div
      className={`widget widget--multiselect widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`multiselect-${id}`, testId)}
    >
      <span className="widget__label" id={`${id}-label`}>
        {label}
      </span>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <select
        id={id}
        className="widget__control"
        multiple
        value={value}
        disabled={disabled || loading}
        aria-labelledby={`${id}-label`}
        aria-invalid={Boolean(error)}
        aria-describedby={description ? `${id}-desc` : undefined}
        onChange={(e) =>
          onChange(
            Array.from(e.target.selectedOptions).map((o) => o.value),
          )
        }
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
