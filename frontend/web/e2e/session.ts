import type { APIRequestContext, Page } from "@playwright/test";

const TOKEN_KEY = "openfdd.auth.token";

/**
 * When central auth is required, mint a session before gated routes (Overview, jobs, …).
 * No-op when auth is disabled or OPENFDD_ADMIN_PASSWORD is unset.
 */
export async function ensureProductSession(
  page: Page,
  request: APIRequestContext,
): Promise<void> {
  const password = process.env.OPENFDD_ADMIN_PASSWORD ?? "";
  const base = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

  let authRequired = false;
  try {
    const statusRes = await request.get(`${base}/api/auth/status`, { timeout: 8_000 });
    if (statusRes.ok()) {
      const status = (await statusRes.json()) as { auth_required?: boolean };
      authRequired = Boolean(status.auth_required);
    }
  } catch {
    return;
  }
  if (!authRequired) {
    return;
  }
  if (!password) {
    return;
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

  await page.goto("/auth");
  await page.evaluate(
    ([key, value]) => {
      sessionStorage.setItem(key, value);
    },
    [TOKEN_KEY, token] as const,
  );
}
