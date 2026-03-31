const ACCESS_KEY = "ofdd_access_token";
const REFRESH_KEY = "ofdd_refresh_token";

type AuthListener = () => void;
const listeners = new Set<AuthListener>();

function notify() {
  for (const l of listeners) l();
}

export function subscribeAuth(listener: AuthListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setAuthTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_KEY, accessToken);
  localStorage.setItem(REFRESH_KEY, refreshToken);
  notify();
}

export function setAccessToken(accessToken: string): void {
  localStorage.setItem(ACCESS_KEY, accessToken);
  notify();
}

export function clearAuthTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  notify();
}

