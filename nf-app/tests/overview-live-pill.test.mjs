import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const sharedDir = fileURLToPath(new URL("../../shared/static", import.meta.url));
const appDir = fileURLToPath(new URL("../static", import.meta.url));

test("setLive is a no-op when the live pill is not in the DOM", () => {
  const elements = new Map();
  const mk = (id) => {
    if (!elements.has(id)) elements.set(id, { textContent: "", classList: { toggle() {} } });
    return elements.get(id);
  };
  const ctx = vm.createContext({
    console,
    document: { getElementById: (id) => (id === "liveDot" ? null : mk(id)) },
  });
  vm.runInContext(fs.readFileSync(path.join(sharedDir, "app-core.js"), "utf8"), ctx, { filename: "app-core.js" });
  assert.doesNotThrow(() => ctx.setLive(false, "Cannot set properties of undefined (setting 'disabled')"));
});

test("Overview / RCx rendering guards missing range mounts and FDD run-now controls", () => {
  const core = fs.readFileSync(path.join(sharedDir, "app-core.js"), "utf8");
  const app = fs.readFileSync(path.join(appDir, "app.js"), "utf8");
  const occ = fs.readFileSync(path.join(appDir, "occupancy-editor.js"), "utf8");
  assert.match(core, /if \(!dot \|\| !live\) return/);
  assert.match(app, /const rangeEl = \$\(T\.range\)/);
  assert.match(app, /if \(!rangeEl\)/);
  assert.match(app, /const btn = \$\("fddRunNow"\)/);
  assert.match(app, /if \(!btn\) return/);
  assert.match(occ, /if \(!save\.isConnected\) return/);
});

test("renderRangeControl tolerates a missing container", () => {
  const ctx = vm.createContext({ console, Date, Math, JSON, Intl, esc: (x) => String(x ?? "") });
  vm.runInContext(fs.readFileSync(path.join(sharedDir, "charts.js"), "utf8"), ctx, { filename: "charts.js" });
  assert.doesNotThrow(() => ctx.renderRangeControl(null, { key: "overview", state: { preset: "24h" } }));
});