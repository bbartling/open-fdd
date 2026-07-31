import { useCallback, useRef, useState } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface FileUploadProps extends WidgetBaseProps {
  accept?: string;
  multiple?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
}

export function FileUpload({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  accept,
  multiple = false,
  files,
  onChange,
}: FileUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const isDisabled = disabled || loading;

  const handleFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming || isDisabled) return;
      const list = Array.from(incoming);
      onChange(multiple ? [...files, ...list] : list.slice(0, 1));
    },
    [files, isDisabled, multiple, onChange],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  return (
    <div
      className={`widget widget--file widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`file-upload-${id}`, testId)}
    >
      <span className="widget__label" id={`${id}-label`}>
        {label}
      </span>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <div
        className={`widget__dropzone${dragOver ? " widget__dropzone--dragover" : ""}${isDisabled ? " widget__dropzone--disabled" : ""}`}
        role="button"
        tabIndex={isDisabled ? -1 : 0}
        aria-labelledby={`${id}-label`}
        aria-describedby={description ? `${id}-desc` : undefined}
        aria-disabled={isDisabled}
        onClick={() => !isDisabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !isDisabled) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!isDisabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          id={id}
          type="file"
          className="widget__dropzone-input"
          accept={accept}
          multiple={multiple}
          disabled={isDisabled}
          aria-invalid={Boolean(error)}
          onChange={(e) => handleFiles(e.target.files)}
        />
        <p>Drop files here or click to browse</p>
      </div>
      {files.length > 0 ? (
        <ul className="widget__file-list" aria-live="polite">
          {files.map((f) => (
            <li key={`${f.name}-${f.size}`}>{f.name}</li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
