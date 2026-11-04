import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, it } from "node:test";

const here = path.dirname(fileURLToPath(import.meta.url));
const productRoot = path.resolve(here, "../..");
const parity = JSON.parse(
  fs.readFileSync(path.join(productRoot, "chart-parity.json"), "utf8"),
);
const contract = JSON.parse(
  fs.readFileSync(
    path.resolve(productRoot, "../../../../archive/product-ui/react-spa-v4/src/api/charts.contract.json"),
    "utf8",
  ),
);

async function loadExport(spec) {
  if (!spec) return null;
  const [modPath, exportName] = String(spec).split("#");
  const url = pathToFileURL(path.join(productRoot, modPath));
  const mod = await import(url.href);
  return mod[exportName];
}

describe("chart-parity.json", () => {
  it("covers every required archive builder", () => {
    const covered = new Set(
      parity.charts.map((row) => {
        const part = String(row.old_builder).split("#")[1] || row.old_builder;
        if (part.includes("MvChangePointPanel")) return "MvChangePointPanel";
        if (part.includes("equipmentInspectionChart")) return "equipmentInspectionChart";
        if (part.includes("HealthMatrixSection")) return part;
        return part.split(".")[0]?.replace(/.*\//, "") || part;
      }),
    );
    for (const name of parity.required_archive_builders) {
      const hit = parity.charts.some((row) => row.old_builder.includes(name));
      assert.ok(hit, `missing matrix row for archive builder ${name}`);
    }
  });

  it("every ported new_renderer export exists", async () => {
    for (const row of parity.charts) {
      if (!String(row.status).startsWith("ported")) continue;
      if (!row.new_renderer) {
        assert.fail(`ported row missing new_renderer: ${row.old_builder}`);
      }
      const fn = await loadExport(row.new_renderer);
      assert.equal(typeof fn, "function", row.new_renderer);
    }
  });

  it("charts.contract overview and fuel stems have matrix rows", () => {
    const stems = new Set([
      ...contract.overview_png_stems,
      ...contract.png_stem_vocabulary.fuel,
    ]);
    for (const stem of stems) {
      const hit = parity.charts.some((row) => row.png_stem === stem);
      assert.ok(hit, `contract stem ${stem} missing from chart-parity.json`);
    }
  });

  it("RCx ported renderers do not expose fault lane helpers in name", async () => {
    const { rcxOptionHasFaultLane } = await import("./rcx-vibe-charts.js");
    const rcxRows = parity.charts.filter((r) =>
      String(r.new_renderer || "").includes("rcx-vibe-charts"),
    );
    for (const row of rcxRows) {
      if (row.new_renderer.includes("outlierEquipmentIds")) continue;
      const fn = await loadExport(row.new_renderer);
      const sample =
        row.new_renderer.includes("Donut") || row.new_renderer.includes("comfort")
          ? fn([{ value_f: 1, label: "a" }], { title: "t" })
          : row.new_renderer.includes("metering")
            ? fn([{ month: "2026-01", energy: 1, dd: 2 }], { title: "t" })
            : fn(
                [{ equipment_id: "E1", timestamp_utc: "2026-01-01T00:00:00Z", value_f: 1 }],
                { title: "t" },
              );
      if (sample) {
        assert.equal(
          rcxOptionHasFaultLane(sample),
          false,
          `${row.new_renderer} must not include fault lane`,
        );
      }
    }
  });

  it("ported rows map to workflows without void-only renderers", async () => {
    const { workflowForParityRow } = await import("./chart-workflows.js");
    for (const row of parity.charts) {
      if (!String(row.status).startsWith("ported")) continue;
      const workflow = workflowForParityRow(row);
      assert.ok(workflow, `workflow missing for ${row.old_builder}`);
      if (workflow.internal) continue;
      if (String(row.status).includes("deferred:")) continue;
      assert.ok(
        workflow.renderer || workflow.adapt,
        `${row.old_builder} has no renderer or adapt`,
      );
      assert.notEqual(
        workflow.renderer,
        null,
        `${row.old_builder} void-only renderer`,
      );
    }
  });
});
