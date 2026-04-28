export const bridgeBase = import.meta.env.VITE_DESKTOP_BRIDGE_BASE ?? "http://127.0.0.1:8765";

export async function desktopFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${bridgeBase}${path}`, init);
  } catch (_err) {
    throw new Error(
      `Request failed to ${bridgeBase}${path}. `
        + `Bridge may be offline, blocked by CORS, or endpoint crashed. `
        + `If needed, restart bridge: open-fdd-desktop-bridge`,
    );
  }
  if (!res.ok) {
    throw new Error(`Bridge error ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export async function desktopFetchText(path: string, init?: RequestInit): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${bridgeBase}${path}`, init);
  } catch (_err) {
    throw new Error(
      `Request failed to ${bridgeBase}${path}. `
        + `Bridge may be offline, blocked by CORS, or endpoint crashed. `
        + `If needed, restart bridge: open-fdd-desktop-bridge`,
    );
  }
  if (!res.ok) {
    throw new Error(`Bridge error ${res.status}: ${await res.text()}`);
  }
  return await res.text();
}
