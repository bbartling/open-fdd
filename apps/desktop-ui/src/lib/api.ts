export const bridgeBase = import.meta.env.VITE_DESKTOP_BRIDGE_BASE ?? "http://127.0.0.1:8765";

async function desktopFetchRaw(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${bridgeBase}${path}`, init);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Request failed to ${bridgeBase}${path}. (${detail}) `
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
  try {
    return await fetch(`${bridgeBase}${path}`, init);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Request failed to ${bridgeBase}${path}. (${detail}) `
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
