import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface CheckboxProps extends WidgetBaseProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function Checkbox({
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
}: CheckboxProps) {
  const isDisabled = disabled || loading;

  return (
    <div
      className={`widget widget--checkbox widget--${density}${error ? " widget--error" : ""}${isDisabled ? " widget--disabled" : ""}`}
      data-testid={widgetTestId(`checkbox-${id}`, testId)}
    >
      <div className="widget__check-row">
        <input
          id={id}
          type="checkbox"
          className="widget__checkbox"
          checked={checked}
          disabled={isDisabled}
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
