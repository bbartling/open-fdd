import { useMemo, useState } from "react";
import type { PlotlyFigure } from "../api/plotDataset";
import { DataTable, Select } from "./widgets";
import {
  DEFAULT_SERIES_PREVIEW_ROWS,
  SERIES_PREVIEW_ROW_OPTIONS,
  coerceSeriesPreviewLimit,
  recentSeriesPreview,
  type SeriesPreviewLimit,
} from "./seriesPreview";

/**
 * Per-plot preview of the most recent samples in the figure already on screen.
 * Each instance keeps its own row count (default 10).
 */
export function SeriesPreview({
  id,
  figure,
  testId,
}: {
  id: string;
  figure: PlotlyFigure | null;
  testId?: string;
}) {
  const [limit, setLimit] = useState<SeriesPreviewLimit>(
    DEFAULT_SERIES_PREVIEW_ROWS,
  );
  const preview = useMemo(
    () => recentSeriesPreview(figure, limit),
    [figure, limit],
  );
  if (!preview) return null;

  const columns = preview.columns.map((key) => ({ key, header: key }));
  return (
    <div data-testid={testId ? `${testId}-preview` : `${id}-preview`}>
      <Select
        id={`${id}-rows`}
        label="Most recent rows"
        value={String(limit)}
        options={SERIES_PREVIEW_ROW_OPTIONS.map((n) => ({
          value: String(n),
          label: String(n),
        }))}
        onChange={(value) => {
          const next = Number(value);
          if (Number.isFinite(next)) setLimit(coerceSeriesPreviewLimit(next));
        }}
        testId={testId ? `${testId}-rows` : `${id}-rows`}
      />
      <DataTable
        id={id}
        label={`Series preview (most recent ${limit})`}
        columns={columns}
        rows={preview.rows}
        testId={testId ? `${testId}-table` : `${id}-table`}
      />
    </div>
  );
}
