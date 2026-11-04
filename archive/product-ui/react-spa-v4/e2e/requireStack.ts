import { test } from "@playwright/test";

/** Required CI sets this so an unreachable SPA or a missing login is a failure. */
export const stackRequired = process.env.OPENFDD_PLAYWRIGHT_REQUIRE_STACK === "1";

export function failIfRequired(reason: string): void {
  if (stackRequired) {
    throw new Error(reason);
  }
  test.skip(true, reason);
}
