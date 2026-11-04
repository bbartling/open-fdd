import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface DownloadButtonProps extends Omit<WidgetBaseProps, "label"> {
  label: string;
  href: string;
  filename?: string;
  variant?: "primary" | "secondary";
}

export function DownloadButton({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  href,
  filename,
  variant = "secondary",
}: DownloadButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <div
      className={`widget widget--download widget--${density}`}
      data-testid={widgetTestId(`download-${id}`, testId)}
    >
      {/* Download affordance keeps native <a download> (not SPA navigation). */}
      {/* eslint-disable-next-line jsx-a11y/anchor-is-valid */}
      <a
        id={id}
        href={isDisabled ? undefined : href}
        download={filename}
        className={`widget-btn widget-btn--${variant}${density === "compact" ? " widget-btn--compact" : ""}`}
        aria-disabled={isDisabled || undefined}
        aria-busy={loading || undefined}
        aria-describedby={description ? `${id}-desc` : undefined}
        tabIndex={isDisabled ? -1 : 0}
        onClick={(e) => {
          if (isDisabled) e.preventDefault();
        }}
      >
        {loading ? <span className="widget-btn__spinner" aria-hidden /> : null}
        {label}
      </a>
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
