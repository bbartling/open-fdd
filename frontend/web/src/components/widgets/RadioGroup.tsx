import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface RadioOption {
  value: string;
  label: string;
  description?: string;
}

export interface RadioGroupProps extends WidgetBaseProps {
  value: string;
  options: RadioOption[];
  onChange: (value: string) => void;
}

export function RadioGroup({
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
}: RadioGroupProps) {
  const isDisabled = disabled || loading;

  return (
    <fieldset
      className={`widget widget--radio widget--${density}${error ? " widget--error" : ""}${isDisabled ? " widget--disabled" : ""}`}
      data-testid={widgetTestId(`radio-${id}`, testId)}
      disabled={isDisabled}
      aria-invalid={Boolean(error)}
    >
      <legend className="widget__label">{label}</legend>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <div
        className="widget__radio-group"
        role="radiogroup"
        aria-labelledby={`${id}-legend`}
        aria-describedby={description ? `${id}-desc` : undefined}
      >
        {options.map((opt) => {
          const optionId = `${id}-${opt.value}`;
          return (
            <div key={opt.value} className="widget__radio-row">
              <input
                id={optionId}
                type="radio"
                name={id}
                className="widget__radio"
                value={opt.value}
                checked={value === opt.value}
                disabled={isDisabled}
                onChange={() => onChange(opt.value)}
              />
              <div>
                <label className="widget__check-label" htmlFor={optionId}>
                  {opt.label}
                </label>
                {opt.description ? (
                  <p className="widget__description">{opt.description}</p>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
