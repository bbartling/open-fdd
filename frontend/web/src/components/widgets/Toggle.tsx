import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface ToggleProps extends WidgetBaseProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function Toggle({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  checked,
  onChange,
}: ToggleProps) {
  const isDisabled = disabled || loading;

  return (
    <div
      className={`widget widget--toggle widget--${density}${error ? " widget--error" : ""}${isDisabled ? " widget--disabled" : ""}`}
      data-testid={widgetTestId(`toggle-${id}`, testId)}
    >
      <div className="widget__toggle-row">
        <input
          id={id}
          type="checkbox"
          role="switch"
          className="widget__toggle"
          checked={checked}
          disabled={isDisabled}
          aria-checked={checked}
          aria-invalid={Boolean(error)}
          aria-describedby={
            description ? `${id}-desc` : error ? `${id}-error` : undefined
          }
          onChange={(e) => onChange(e.target.checked)}
        />
        <div>
          <label className="widget__check-label" htmlFor={id}>
            {label}
          </label>
          {description ? (
            <p className="widget__description" id={`${id}-desc`}>
              {description}
            </p>
          ) : null}
        </div>
      </div>
      {error ? (
        <p className="widget__error" id={`${id}-error`} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
