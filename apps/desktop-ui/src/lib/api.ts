/** localStorage key for per-browser bridge base (remote UI + SSH tunnel / LAN). */
export const BRIDGE_BASE_STORAGE_KEY = "ofdd-bridge-base-override";

function trimSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

/** Effective bridge origin (override in localStorage, else Vite env, else localhost). */
export function getBridgeBase(): string {
  try {
    const raw = localStorage.getItem(BRIDGE_BASE_STORAGE_KEY);
    if (raw != null && raw.trim() !== "") {
      return trimSlash(raw.trim());
    }
  } catch {
    /* private mode */
  }
  const fromEnv = import.meta.env.VITE_DESKTOP_BRIDGE_BASE;
  const fallback = typeof fromEnv === "string" && fromEnv.trim() !== "" ? fromEnv.trim() : "http://127.0.0.1:8765";
  return trimSlash(fallback);
}

async function desktopFetchRaw(path: string, init?: RequestInit): Promise<Response> {
  const base = getBridgeBase();
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, init);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Request failed to ${base}${path}. (${detail}) `
        + `Bridge may be offline, blocked by CORS, or the process exited while handling the request. `
        + `If needed, restart bridge: open-fdd-desktop-bridge`,
    );
  }
  if (!res.ok) {
    throw new Error(`Bridge error ${res.status}: ${await res.text()}`);
  }
  return res;
}

/** Same connectivity error handling as desktop fetch, but returns the Response (caller checks res.ok). */
export async function bridgeFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = getBridgeBase();
  try {
    return await fetch(`${base}${path}`, init);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Request failed to ${base}${path}. (${detail}) `
        + `Bridge may be offline, blocked by CORS, or the process exited while handling the request. `
        + `If needed, restart bridge: open-fdd-desktop-bridge`,
    );
  }
}

export async function desktopFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await desktopFetchRaw(path, init);
  return (await res.json()) as T;
}

export async function desktopFetchText(path: string, init?: RequestInit): Promise<string> {
  const res = await desktopFetchRaw(path, init);
  return await res.text();
}
