// The vendored role file and binding are the generator output. A drift fails this test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

test("vendored role file and binding match gen_roles_223p.py", () => {
  const py = ["python3", "python"].find((cmd) => spawnSync(cmd, ["-c", "print(1)"]).status === 0);
  assert.ok(py, "python3 or python is required to check the vendored role files");
  const run = spawnSync(py, ["scripts/nf/gen_roles_223p.py", "--check"], { cwd: root, encoding: "utf8" });
  assert.equal(run.status, 0, (run.stdout || "") + (run.stderr || ""));
});
