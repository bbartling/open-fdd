const ACCESS_KEY = "ofdd_access_token";
let accessTokenMemory: string | null = null;

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
  if (accessTokenMemory) return accessTokenMemory;
  const persisted = sessionStorage.getItem(ACCESS_KEY);
  if (persisted) accessTokenMemory = persisted;
  return accessTokenMemory;
}

export function setAuthTokens(accessToken: string): void {
  accessTokenMemory = accessToken;
  sessionStorage.setItem(ACCESS_KEY, accessToken);
  notify();
}

export function setAccessToken(accessToken: string): void {
  accessTokenMemory = accessToken;
  sessionStorage.setItem(ACCESS_KEY, accessToken);
  notify();
}

export function clearAuthTokens(): void {
  accessTokenMemory = null;
  sessionStorage.removeItem(ACCESS_KEY);
  notify();
}

