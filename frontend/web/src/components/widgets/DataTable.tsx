import type { ReactNode } from "react";
import { isValidElement } from "react";
import type { WidgetBaseProps } from "./types";
import { widgetTestId } from "./types";

export interface DataTableColumn<T extends Record<string, unknown>> {
  key: keyof T & string;
  header: string;
  /** Full header text for hover tooltips (compact tables). */
  headerTitle?: string;
}

export interface DataTableProps<T extends Record<string, unknown>>
  extends WidgetBaseProps {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowClassName?: (row: T) => string | undefined;
}

function textField(row: Record<string, unknown>, key: string): string {
  const value = row[key];
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

/** Stable row identity. Displayed cells are not the key. */
export function dataTableRowKey<T extends Record<string, unknown>>(
  row: T,
  index: number,
): string {
  const explicit = row.row_key;
  if (typeof explicit === "string" && explicit.length > 0) return explicit;
  const site = textField(row, "site_id") || textField(row, "building_id");
  const equipment = textField(row, "equipment_id");
  const role = textField(row, "role");
  if (site || equipment || role) {
    return [site, equipment, role].join("\u001f");
  }
  const fingerprint = Object.keys(row)
    .sort()
    .map((key) => `${key}=${textField(row, key)}`)
    .join("\u001f");
  return `${fingerprint}\u001f${index}`;
}

/** One unique key per row so a repeated identity cannot reuse another row's DOM. */
export function assignDataTableRowKeys<T extends Record<string, unknown>>(
  rows: readonly T[],
): string[] {
  const seen = new Map<string, number>();
  return rows.map((row, index) => {
    const base = dataTableRowKey(row, index);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    if (count === 0) return base;
    return `${base}\u001f#${count}`;
  });
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
  const rowKeys = assignDataTableRowKeys(rows);
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
                <th key={col.key} scope="col" title={col.headerTitle ?? col.header}>
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
              rows.map((row, index) => {
                const extra = rowClassName?.(row);
                const broken = extra?.match(/broken-(\d)/)?.[1];
                const rowKey = rowKeys[index] ?? dataTableRowKey(row, index);
                return (
                  <tr
                    key={rowKey}
                    data-row-key={rowKey}
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
