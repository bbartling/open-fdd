import test from "node:test";
import assert from "node:assert/strict";
import { buildTreeModel, renderModelChecks } from "./tree-view.js";

test("buildTreeModel tolerates null model", () => {
  const root = buildTreeModel(null, "SITE_A", "");
  assert.equal(root.kind, "site");
  assert.ok(Array.isArray(root.children));
});

test("renderModelChecks tolerates null model", () => {
  const el = { innerHTML: "" };
  renderModelChecks(null, "SITE_A", el);
  assert.match(el.innerHTML, /No model loaded/);
});
