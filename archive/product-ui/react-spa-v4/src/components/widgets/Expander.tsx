import type { ReactNode } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface ExpanderProps extends WidgetBaseProps {
  expanded: boolean;
  onChange: (expanded: boolean) => void;
  children: ReactNode;
}

export function Expander({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  expanded,
  onChange,
  children,
}: ExpanderProps) {
  const isDisabled = disabled || loading;

  return (
    <div
      className={`widget widget--expander widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`expander-${id}`, testId)}
    >
      <div className={`widget-expander${expanded ? " widget-expander--open" : ""}`}>
        <button
          type="button"
          id={`${id}-trigger`}
          className="widget-expander__trigger"
          aria-expanded={expanded}
          aria-controls={`${id}-content`}
          aria-describedby={description ? `${id}-desc` : undefined}
          disabled={isDisabled}
          onClick={() => onChange(!expanded)}
        >
          <span>{label}</span>
          <span className="widget-expander__icon" aria-hidden>
            ▼
          </span>
        </button>
        {description ? (
          <p className="widget__description" id={`${id}-desc`} style={{ padding: "0 var(--space-md)" }}>
            {description}
          </p>
        ) : null}
        {expanded ? (
          <div
            id={`${id}-content`}
            role="region"
            aria-labelledby={`${id}-trigger`}
            className="widget-expander__content"
          >
            {children}
          </div>
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
