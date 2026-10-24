import type { APIRequestContext, Page } from "@playwright/test";

const TOKEN_KEY = "openfdd.auth.token";
const SESSION_GEN_KEY = "openfdd.auth.session_gen";

/**
 * When central auth is required, mint a session before gated routes (Overview, jobs, …).
 * No-op when auth is disabled.
 *
 * The token is installed with an init script so the first document already has
 * it. Opening /auth first lets that page call /api/auth/me with no token. Chrome
 * logs the 401, and a test that listens for console errors fails on it. The
 * generation bump matches setStoredToken: a late 401 from an older request must
 * not clear the session.
 */
export async function ensureProductSession(
  page: Page,
  request: APIRequestContext,
): Promise<void> {
  const password = process.env.OPENFDD_ADMIN_PASSWORD ?? "";
  const base = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

  let statusRes;
  try {
    statusRes = await request.get(`${base}/api/auth/status`, { timeout: 8_000 });
  } catch (err) {
    throw new Error(
      `auth status unreachable at ${base}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
  if (!statusRes.ok()) {
    throw new Error(`auth status failed (HTTP ${statusRes.status()})`);
  }
  const status = (await statusRes.json()) as { auth_required?: boolean };
  if (!status.auth_required) {
    return;
  }
  if (!password) {
    throw new Error("OPENFDD_ADMIN_PASSWORD required for auth stack gate");
  }

  const loginRes = await request.post(`${base}/api/auth/login`, {
    timeout: 15_000,
    data: { username: "admin", password },
  });
  if (!loginRes.ok()) {
    throw new Error(`auth login failed (HTTP ${loginRes.status()})`);
  }
  const body = (await loginRes.json()) as { token?: string; access_token?: string };
  const token = body.token ?? body.access_token;
  if (!token) {
    throw new Error("auth login returned no token");
  }

  await page.addInitScript(
    ([key, genKey, value, gen]) => {
      sessionStorage.setItem(genKey, gen);
      sessionStorage.setItem(key, value);
    },
    [TOKEN_KEY, SESSION_GEN_KEY, token, String(Date.now())] as const,
  );
}

/** Drop the injected token on later document loads. A reload re-runs init scripts. */
export async function clearProductSession(page: Page): Promise<void> {
  await page.addInitScript((key: string) => {
    sessionStorage.removeItem(key);
  }, TOKEN_KEY);
  await page
    .evaluate((key: string) => sessionStorage.removeItem(key), TOKEN_KEY)
    .catch(() => undefined);
}
