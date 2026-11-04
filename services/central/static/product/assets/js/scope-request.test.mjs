import test from "node:test";
import assert from "node:assert/strict";
import {
  beginScopedRequest,
  createScopeHolder,
  freezeScope,
  isAbortError,
} from "./scope-request.js";

test("delayed site A response cannot commit after site B begins", async () => {
  const holder = createScopeHolder();
  const ticketA = beginScopedRequest(holder);
  const ticketB = beginScopedRequest(holder);
  assert.equal(ticketA.isCurrent(), false);
  assert.equal(ticketB.isCurrent(), true);
  let committed = "";
  await new Promise((resolve) => {
    setTimeout(() => {
      if (ticketA.isCurrent()) committed = "A";
      resolve();
    }, 5);
  });
  assert.equal(committed, "");
  if (ticketB.isCurrent()) committed = "B";
  assert.equal(committed, "B");
});

test("freezeScope is immutable", () => {
  const s = freezeScope({ site: "S1", equip: "E1", generation: 2 });
  assert.throws(() => {
    s.site = "X";
  });
});

test("isAbortError recognizes AbortError", () => {
  assert.equal(isAbortError({ name: "AbortError" }), true);
  assert.equal(isAbortError(new Error("nope")), false);
});
