type Props = {
  title: string;
  columns: string[];
  rows: Record<string, unknown>[] | string[][];
  rowCount?: number;
  meta?: string;
  loading?: boolean;
  error?: string;
  onClose?: () => void;
};

function normalizeRows(columns: string[], rows: Record<string, unknown>[] | string[][]): string[][] {
  if (!rows.length) return [];
  if (Array.isArray(rows[0])) return rows as string[][];
  return (rows as Record<string, unknown>[]).map((row) =>
    columns.map((col) => {
      const v = row[col];
      if (v == null) return "";
      return String(v);
    }),
  );
}

export default function CsvDataPreview({ title, columns, rows, rowCount, meta, loading, error, onClose }: Props) {
  const tableRows = normalizeRows(columns, rows);
  const displayCols = columns.length ? columns : tableRows[0]?.map((_, i) => `col${i + 1}`) ?? [];

  return (
    <div className="csv-preview-panel">
      <div className="csv-preview-header">
        <h4 className="csv-preview-title">{title}</h4>
        {onClose ? (
          <button type="button" className="linkish-btn" onClick={onClose} aria-label="Close preview">
            ×
          </button>
        ) : null}
      </div>
      {loading ? <p className="muted csv-preview-status">Loading preview…</p> : null}
      {error ? <p className="error csv-preview-status">{error}</p> : null}
      {meta ? <p className="muted csv-preview-meta">{meta}</p> : null}
      {!loading && !error && tableRows.length > 0 ? (
        <div className="csv-preview-scroll">
          <table className="csv-preview-table">
            <thead>
              <tr>
                {displayCols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td key={ci}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rowCount != null && rowCount > tableRows.length ? (
            <p className="muted csv-preview-more">Showing {tableRows.length} of {rowCount.toLocaleString()} rows</p>
          ) : null}
        </div>
      ) : null}
      {!loading && !error && tableRows.length === 0 ? (
        <p className="muted csv-preview-status">No rows to preview.</p>
      ) : null}
    </div>
  );
}
