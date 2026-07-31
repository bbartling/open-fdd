import { useEffect, useRef } from "react";
import { widgetTestId } from "./types";

export interface ConfirmModalProps {
  id: string;
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  loading?: boolean;
  testId?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  id,
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  loading,
  testId,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) {
      cancelRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="widget-modal-backdrop"
      data-testid={widgetTestId(`modal-${id}`, testId)}
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-body`}
        className="widget-modal"
      >
        <h2 id={`${id}-title`} className="widget-modal__title">
          {title}
        </h2>
        <p id={`${id}-body`} className="widget-modal__body">
          {message}
        </p>
        <div className="widget-modal__actions">
          <button
            ref={cancelRef}
            type="button"
            className="widget-btn widget-btn--secondary"
            disabled={loading}
            onClick={onCancel}
            data-testid={`${id}-cancel`}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className="widget-btn widget-btn--danger"
            disabled={loading}
            aria-busy={loading || undefined}
            onClick={onConfirm}
            data-testid={`${id}-confirm`}
          >
            {loading ? <span className="widget-btn__spinner" aria-hidden /> : null}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
