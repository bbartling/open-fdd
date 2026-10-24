import type { APIRequestContext, Page } from "@playwright/test";

const TOKEN_KEY = "openfdd.auth.token";
const SESSION_GEN_KEY = "openfdd.auth.session_gen";

/**
 * When central auth is required, mint a session before gated routes (Overview, jobs, …).
 * No-op when auth is disabled.
 *
 * The sign-in page calls /api/auth/me as it loads. That request starts with no
 * token. If it returns 401 after the token is stored, the client clears the
 * session unless the session generation moved. setStoredToken does that bump;
 * writing the token alone does not, and the next navigation is logged out.
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

  await page.goto("/auth", { waitUntil: "domcontentloaded" });
  await page.evaluate(
    ([key, genKey, value]) => {
      sessionStorage.setItem(genKey, String(Date.now()));
      sessionStorage.setItem(key, value);
    },
    [TOKEN_KEY, SESSION_GEN_KEY, token] as const,
  );
}
