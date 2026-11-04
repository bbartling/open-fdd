import test from "node:test";
import assert from "node:assert/strict";
import {
  recentSeriesPreviewFromLines,
  coerceSeriesPreviewLimit,
} from "./series-preview.js";
import { parseTimestampMillis } from "./timestamp-adapter.js";

test("parseTimestampMillis accepts ISO and epoch ms", () => {
  assert.equal(parseTimestampMillis(1_730_000_000_000), 1_730_000_000_000);
  assert.equal(parseTimestampMillis("1730000000000"), 1_730_000_000_000);
  assert.ok(parseTimestampMillis("2024-10-09T12:00:00Z") > 0);
  assert.equal(parseTimestampMillis("not-a-date"), null);
});

test("preview uses loaded epoch-ms series without refetch and keeps nulls", () => {
  const lines = [
    {
      name: "sat",
      data: [
        [1_730_000_000_000, 12.1],
        [1_730_000_360_000, null],
        [1_730_000_720_000, 12.4],
      ],
    },
  ];
  const ten = recentSeriesPreviewFromLines(lines, 10);
  assert.equal(ten.rows.length, 3);
  assert.equal(ten.rows[0].sat, "12.4");
  assert.equal(ten.rows[1].sat, "");
  const twenty = recentSeriesPreviewFromLines(lines, 20);
  assert.equal(twenty.rows.length, 3);
  assert.equal(coerceSeriesPreviewLimit(20), 20);
});
