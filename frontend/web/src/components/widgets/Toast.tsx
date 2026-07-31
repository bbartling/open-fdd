import type { ReactNode } from "react";
import { widgetTestId } from "./types";

export type AlertVariant = "info" | "success" | "warning" | "danger";

export interface InlineAlertProps {
  id: string;
  variant?: AlertVariant;
  title?: string;
  children: ReactNode;
  testId?: string;
  onDismiss?: () => void;
}

export function InlineAlert({
  id,
  variant = "info",
  title,
  children,
  testId,
  onDismiss,
}: InlineAlertProps) {
  return (
    <div
      className={`widget-inline-alert widget-inline-alert--${variant}`}
      role="alert"
      data-testid={widgetTestId(`inline-alert-${id}`, testId)}
    >
      {title ? <strong>{title}</strong> : null}
      {title ? " " : null}
      {children}
      {onDismiss ? (
        <button
          type="button"
          className="widget-toast__dismiss"
          aria-label="Dismiss alert"
          onClick={onDismiss}
        >
          ×
        </button>
      ) : null}
    </div>
  );
}

export interface ToastItem {
  id: string;
  message: string;
  variant?: AlertVariant;
}

export interface ToastRegionProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
  testId?: string;
}

export function ToastRegion({
  toasts,
  onDismiss,
  testId,
}: ToastRegionProps) {
  if (toasts.length === 0) return null;

  return (
    <div
      className="widget-toast-region"
      aria-live="polite"
      aria-relevant="additions"
      data-testid={widgetTestId("toast-region", testId)}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`widget-toast widget-toast--${toast.variant ?? "info"}`}
          role="status"
          data-testid={`toast-${toast.id}`}
        >
          <span>{toast.message}</span>
          <button
            type="button"
            className="widget-toast__dismiss"
            aria-label={`Dismiss ${toast.message}`}
            onClick={() => onDismiss(toast.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
