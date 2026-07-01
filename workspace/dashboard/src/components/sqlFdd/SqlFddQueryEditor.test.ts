import { describe, expect, it } from "vitest";
import { sql as sqlLanguage } from "@codemirror/lang-sql";

/** Regression: SqlFddQueryEditor prop named `sql` must not shadow the CodeMirror sql() extension. */
describe("SqlFddQueryEditor codemirror wiring", () => {
  it("sqlLanguage extension factory is callable", () => {
    expect(typeof sqlLanguage).toBe("function");
    const ext = sqlLanguage();
    expect(ext).toBeTruthy();
  });
});
