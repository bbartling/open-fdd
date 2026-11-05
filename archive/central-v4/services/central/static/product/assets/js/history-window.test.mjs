import test from "node:test";
import assert from "node:assert/strict";
import {
  filterSeriesByRangeHours,
  chartDataState,
  dataEndMsFromHistory,
} from "./history-window.js";

test("filterSeriesByRangeHours anchors on data end not wall clock", () => {
  const end = 1_730_000_720_000;
  const series = [
    [end - 48 * 3_600_000, 1],
    [end - 2 * 3_600_000, 2],
    [end, 3],
  ];
  const out = filterSeriesByRangeHours(series, 6, end);
  assert.equal(out.length, 2);
  assert.equal(out[0][1], 2);
  assert.equal(out[1][1], 3);
});

test("chartDataState distinguishes empty vs loading", () => {
  assert.equal(chartDataState({ loading: true }).kind, "loading");
  assert.equal(
    chartDataState({ loading: false, history: new Map(), cardPoints: [{ id: "p" }] }).kind,
    "empty",
  );
  const history = new Map([["sat", [[1_730_000_000_000, 1]]]]);
  assert.equal(
    chartDataState({ loading: false, history, cardPoints: [{ id: "p" }] }).kind,
    "ready",
  );
  assert.equal(dataEndMsFromHistory(history), 1_730_000_000_000);
});
