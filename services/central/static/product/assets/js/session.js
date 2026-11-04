const TOKEN_KEY = "openfdd.auth.token";

export function readToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function writeToken(token) {
  if (!token) {
    sessionStorage.removeItem(TOKEN_KEY);
    return;
  }
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
}
