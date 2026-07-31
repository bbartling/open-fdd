import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface ButtonProps extends Omit<WidgetBaseProps, "label"> {
  label: string;
  variant?: "primary" | "secondary" | "danger";
  type?: "button" | "submit" | "reset";
  onClick?: () => void;
}

export function Button({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  variant = "primary",
  type = "button",
  onClick,
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <div
      className={`widget widget--button widget--${density}`}
      data-testid={widgetTestId(`button-${id}`, testId)}
    >
      <button
        id={id}
        type={type}
        className={`widget-btn widget-btn--${variant}${density === "compact" ? " widget-btn--compact" : ""}`}
        disabled={isDisabled}
        aria-busy={loading || undefined}
        aria-describedby={description ? `${id}-desc` : undefined}
        aria-invalid={Boolean(error)}
        onClick={onClick}
      >
        {loading ? <span className="widget-btn__spinner" aria-hidden /> : null}
        {label}
      </button>
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
