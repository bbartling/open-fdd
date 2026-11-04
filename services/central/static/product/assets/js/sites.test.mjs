import test from "node:test";
import assert from "node:assert/strict";
import { isAuthorizedSite } from "./sites.js";

test("isAuthorizedSite rejects foreign and unknown ids", () => {
  const authorized = ["OWN_A", "SHARED"];
  assert.equal(isAuthorizedSite("OWN_A", authorized), true);
  assert.equal(isAuthorizedSite("FOREIGN_B", authorized), false);
  assert.equal(isAuthorizedSite("", authorized), false);
  assert.equal(isAuthorizedSite("  ", authorized), false);
});
