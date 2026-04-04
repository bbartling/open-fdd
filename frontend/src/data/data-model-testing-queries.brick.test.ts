import { describe, expect, it } from "vitest";
import { PREDEFINED_QUERIES, DEFAULT_SPARQL } from "./data-model-testing-queries";
import { BRICK_14_QUERY_CLASS_ALLOWLIST, BRICK_PREDICATE_LOCAL_NAMES } from "./brick-1.4-query-class-allowlist";

/**
 * Extract `brick:LocalName` tokens from SPARQL; drop known Brick **predicates** (not classes).
 */
function brickClassesReferencedInSparql(sparql: string): Set<string> {
  const found = new Set<string>();
  const re = /\bbrick:([A-Za-z][A-Za-z0-9_]*)\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(sparql)) !== null) {
    const local = m[1];
    if (!BRICK_PREDICATE_LOCAL_NAMES.has(local)) {
      found.add(local);
    }
  }
  return found;
}

describe("Data Model Testing SPARQL vs Brick 1.4 class allowlist", () => {
  it("every brick: class token in presets is in BRICK_14_QUERY_CLASS_ALLOWLIST", () => {
    const all = new Set<string>();
    for (const q of PREDEFINED_QUERIES) {
      for (const sparql of [q.query, q.queryWithBacnet].filter(Boolean) as string[]) {
        for (const c of brickClassesReferencedInSparql(sparql)) {
          all.add(c);
        }
      }
    }
    for (const c of brickClassesReferencedInSparql(DEFAULT_SPARQL)) {
      all.add(c);
    }

    const unknown: string[] = [];
    for (const c of all) {
      if (!BRICK_14_QUERY_CLASS_ALLOWLIST.has(c)) {
        unknown.push(c);
      }
    }
    expect(
      unknown,
      `Add to brick-1.4-query-class-allowlist.ts (or fix typo): ${unknown.join(", ")}`,
    ).toEqual([]);
  });
});
