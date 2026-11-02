import { clearSession, readToken } from "./session.js";

function showLoginGateAfterUnauthorized() {
  clearSession();
  const gate = document.getElementById("loginGate");
  if (gate) gate.hidden = false;
  const logout = document.getElementById("logoutBtn");
  if (logout) logout.hidden = true;
}

export async function apiFetch(path, init = {}) {
  const headers = new Headers(init.headers || {});
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = readToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, { ...init, headers });
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : await response.text();
  if (!response.ok) {
    if (response.status === 401 && readToken()) {
      showLoginGateAfterUnauthorized();
    }
    const message =
      (payload && typeof payload === "object" && (payload.error || payload.message)) ||
      response.statusText;
    throw new Error(String(message));
  }
  return payload;
}

export async function login(username, password) {
  return apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchHealth() {
  return apiFetch("/api/health");
}

export async function fetchCapabilities() {
  return apiFetch("/api/capabilities");
}
