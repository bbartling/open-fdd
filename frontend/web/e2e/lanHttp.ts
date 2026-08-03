import type { Page } from "@playwright/test";

/**
 * Simulate LAN HTTP secure-context rules inside Playwright.
 * `http://127.0.0.1` keeps `crypto.randomUUID`; `http://192.168.x.x` does not.
 * Gate/CI on loopback would miss that bug without this stub.
 */
export async function simulateLanHttpCrypto(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const real = globalThis.crypto;
    if (!real) return;
    const getRandomValues = real.getRandomValues.bind(real);
    const subtle = real.subtle;
    // Replace the whole crypto object — randomUUID is non-configurable on Chromium.
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      enumerable: true,
      value: {
        getRandomValues,
        subtle,
        // intentionally no randomUUID
      } as Crypto,
    });
  });
}

export function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}
