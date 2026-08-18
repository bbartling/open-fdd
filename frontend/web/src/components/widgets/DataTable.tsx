import type { ReactNode } from "react";
import { isValidElement } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface DataTableColumn<T extends Record<string, unknown>> {
  key: keyof T & string;
  header: string;
}

export interface DataTableProps<T extends Record<string, unknown>>
  extends WidgetBaseProps {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowClassName?: (row: T) => string | undefined;
}

function renderCell(value: unknown): ReactNode {
  if (value == null) return "";
  if (isValidElement(value)) return value;
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  return String(value);
}

export function DataTable<T extends Record<string, unknown>>({
  id,
  label,
  description,
  disabled,
  loading,
  error,
  testId,
  density = "comfortable",
  columns,
  rows,
  rowClassName,
}: DataTableProps<T>) {
  return (
    <div
      className={`widget widget--table widget--${density}${error ? " widget--error" : ""}`}
      data-testid={widgetTestId(`table-${id}`, testId)}
      aria-disabled={disabled || undefined}
      aria-busy={loading || undefined}
    >
      <span className="widget__label" id={`${id}-label`}>
        {label}
      </span>
      {description ? (
        <p className="widget__description" id={`${id}-desc`}>
          {description}
        </p>
      ) : null}
      <div className="widget-table-wrap">
        <table
          className={`widget-table${density === "compact" ? " widget-table--compact" : ""}`}
          aria-labelledby={`${id}-label`}
          aria-describedby={description ? `${id}-desc` : undefined}
        >
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} scope="col">
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length}>Loading…</td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length}>No data</td>
              </tr>
            ) : (
              rows.map((row, rowIdx) => {
                const extra = rowClassName?.(row);
                const broken = extra?.match(/broken-(\d)/)?.[1];
                return (
                  <tr
                    key={rowIdx}
                    className={extra || undefined}
                    data-broken={broken ?? undefined}
                  >
                    {columns.map((col) => (
                      <td key={col.key}>{renderCell(row[col.key])}</td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {error ? (
        <p className="widget__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
