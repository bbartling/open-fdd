import test from "node:test";
import assert from "node:assert/strict";
import { confirmMinForRule, numericParamsFromSession } from "./rule-params.js";

test("numericParamsFromSession converts confirm_seconds to confirm_min", () => {
  const bag = numericParamsFromSession({
    FC1: { confirm_seconds: 120 },
  });
  assert.equal(bag.FC1.confirm_min, 2);
  assert.equal(bag.FC1.confirm_seconds, undefined);
});

test("numericParamsFromSession accepts string confirm_min", () => {
  const bag = numericParamsFromSession({
    FC1: { confirm_min: "15" },
  });
  assert.equal(bag.FC1.confirm_min, 15);
});

test("confirmMinForRule prefers session bag over rule meta", () => {
  const session = { config: { params: { FC1: { confirm_min: 10 } } } };
  assert.equal(confirmMinForRule(session, "FC1", { confirm_min: 5 }), 10);
});

test("confirmMinForRule converts session confirm_seconds", () => {
  const session = { config: { params: { FC1: { confirm_seconds: 300 } } } };
  assert.equal(confirmMinForRule(session, "FC1", {}), 5);
});
