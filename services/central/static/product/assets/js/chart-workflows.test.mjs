import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import {
  CHART_WORKFLOWS,
  assertNoVoidRenderersInAppSource,
  optionHasSeries,
  parityBuilderSuffix,
  workflowForParityRow,
} from "./chart-workflows.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const productRoot = path.resolve(here, "../..");
const parity = JSON.parse(
  fs.readFileSync(path.join(productRoot, "chart-parity.json"), "utf8"),
);
const indexHtml = fs.readFileSync(path.join(productRoot, "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(here, "app.js"), "utf8");

describe("chart-workflows", () => {
  it("app.js does not void reachable chart renderers", () => {
    assert.doesNotThrow(() => assertNoVoidRenderersInAppSource(appJs));
  });

  it("every ported parity row has a workflow or honest deferral", () => {
    for (const row of parity.charts) {
      const status = String(row.status || "");
      if (!status.startsWith("ported")) continue;
      const workflow = workflowForParityRow(row);
      assert.ok(workflow, `missing workflow for ${row.old_builder} (${row.png_stem})`);
      if (workflow.internal) continue;
      assert.ok(workflow.controlId, `${row.old_builder} missing controlId`);
      assert.ok(
        indexHtml.includes(`id="${workflow.controlId}"`),
        `${workflow.controlId} not in index.html`,
      );
      assert.ok(Number.isFinite(workflow.maxPoints), `${row.old_builder} missing maxPoints`);
      if (workflow.renderer) {
        assert.equal(typeof workflow.renderer, "function", row.new_renderer);
      }
    }
  });

  it("sample adapters produce nonempty chart options for user-facing workflows", () => {
    for (const workflow of CHART_WORKFLOWS) {
      if (workflow.internal || !workflow.sampleOption) continue;
      if (workflow.tab === "ops") continue;
      const option = workflow.sampleOption({
        equipmentId: "EQ1",
        ruleId: "FC1",
        roleUnitIndex: new Map(),
      });
      if (workflow.builder === "equipmentInspectionChart") {
        assert.ok(option);
        continue;
      }
      if (workflow.builder === "expandFddPlotRoles" || workflow.builder === "deriveSensorFaultMasks") {
        continue;
      }
      assert.ok(
        optionHasSeries(option) || (option && Object.keys(option).length),
        workflow.builder,
      );
    }
  });

  it("PNG toolbox stems are present on sample options when pngStem is set", () => {
    for (const workflow of CHART_WORKFLOWS) {
      if (workflow.internal || !workflow.pngStem || !workflow.sampleOption) continue;
      const option = workflow.sampleOption({ equipmentId: "EQ1", ruleId: "FC1" });
      if (!option?.series?.length) continue;
      const toolbox = option.toolbox?.feature?.saveAsImage;
      assert.ok(toolbox, `${workflow.builder} missing saveAsImage`);
    }
  });

  it("parity builder suffix is stable", () => {
    assert.equal(
      parityBuilderSuffix("archive/foo.ts#sensorHealthHeatmap"),
      "sensorHealthHeatmap",
    );
  });
});
