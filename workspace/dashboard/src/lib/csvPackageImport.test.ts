import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { COOKBOOK_ROLES } from "./csvPackageImport";

/** Guard the hardcoded frontend role vocabulary against registry drift. */
describe("COOKBOOK_ROLES", () => {
  it("covers every required_roles entry in sql_rules/registry.yaml", () => {
    const registryPath = resolve(__dirname, "../../../../sql_rules/registry.yaml");
    const text = readFileSync(registryPath, "utf-8");
    const roles = new Set<string>();
    for (const m of text.matchAll(/required_roles:\s*\[([^\]]*)\]/g)) {
      for (const role of m[1].split(",")) {
        const r = role.trim();
        if (r) roles.add(r);
      }
    }
    expect(roles.size).toBeGreaterThan(10);
    const missing = [...roles].filter((r) => !COOKBOOK_ROLES.includes(r));
    expect(missing).toEqual([]);
  });

  it("starts with the empty (unassigned) option and has no duplicates", () => {
    expect(COOKBOOK_ROLES[0]).toBe("");
    expect(new Set(COOKBOOK_ROLES).size).toBe(COOKBOOK_ROLES.length);
  });
});
