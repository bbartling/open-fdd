// NF installs only the files app.json maps, so every module a listed hook requires (relative paths, followed
// recursively) and every SQL analytics template the hooks read (rules/analytics/*.sql, #1649) must be in that map.
// A miss deploys a hook that fails on its first require.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = fileURLToPath(new URL("..", import.meta.url));
const listed = new Set(Object.values(JSON.parse(readFileSync(path.join(appDir, "app.json"), "utf8")).files));

function relativeRequires(file) {
  const src = readFileSync(path.join(appDir, file), "utf8");
  const out = [];
  for (const m of src.matchAll(/require\(\s*['"](\.{1,2}\/[^'"]+)['"]\s*\)/g)) {
    let rel = path.posix.normalize(path.posix.join(path.posix.dirname(file), m[1]));
    if (!rel.endsWith(".js") && !rel.endsWith(".json")) rel += ".js";
    out.push(rel);
  }
  return out;
}

test("every module a listed hook requires is listed in app.json", () => {
  const seen = new Set(), missing = [];
  const todo = [...listed].filter((f) => f.startsWith("hooks/") && f.endsWith(".js") && !f.startsWith("hooks/vendor/"));
  while (todo.length) {
    const f = todo.pop();
    if (seen.has(f)) continue;
    seen.add(f);
    if (!existsSync(path.join(appDir, f))) continue;
    for (const dep of relativeRequires(f)) {
      if (!existsSync(path.join(appDir, dep))) continue;          // optional requires guarded at runtime
      if (!listed.has(dep)) missing.push(`${f} -> ${dep}`);
      if (dep.startsWith("hooks/") && !dep.startsWith("hooks/vendor/")) todo.push(dep);
    }
  }
  assert.ok(seen.has("hooks/analytics.js") && seen.has("hooks/lib/sql-analytics.js"));
  assert.deepEqual(missing, []);
});

test("every SQL analytics template is listed in app.json", () => {
  const sql = readdirSync(path.join(appDir, "rules", "analytics")).filter((f) => f.endsWith(".sql"));
  assert.ok(sql.length >= 6);
  assert.deepEqual(sql.map((f) => `rules/analytics/${f}`).filter((f) => !listed.has(f)), []);
});
