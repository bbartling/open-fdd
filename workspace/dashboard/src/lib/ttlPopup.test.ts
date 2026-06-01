import { describe, expect, it } from "vitest";
import { writeTtlToPopup } from "./ttlPopup";

describe("writeTtlToPopup", () => {
  it("writes escaped turtle into popup document", () => {
    const writes: string[] = [];
    const popup = {
      document: {
        write: (html: string) => writes.push(html),
        close: () => undefined,
      },
    };
    writeTtlToPopup(popup, '@prefix brick: <https://brickschema.org/schema/Brick#> .\nbrick:Site a brick:Site .');
    expect(writes).toHaveLength(1);
    expect(writes[0]).toContain("brick:Site");
    expect(writes[0]).not.toContain("<script");
  });
});
