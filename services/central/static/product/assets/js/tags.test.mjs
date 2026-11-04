import test from "node:test";
import assert from "node:assert/strict";
import { isBoolRole, normalizeTags } from "./tags.js";

test("fan command percent is Number not Bool", () => {
  assert.equal(isBoolRole({ role: "fan_cmd", kind: "Number", tags: ["cmd", "point"] }), false);
});

test("enable command with Bool kind stays Bool", () => {
  assert.equal(isBoolRole({ role: "enable", kind: "Bool", tags: ["cmd", "point"] }), true);
});

test("normalizeTags does not invent sensor on cmd roles", () => {
  const tags = normalizeTags(["cmd", "point"], "fan_cmd");
  assert.equal(tags.includes("sensor"), false);
});
