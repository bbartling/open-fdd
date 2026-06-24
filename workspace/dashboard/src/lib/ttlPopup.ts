export interface PopupLike {
  document: {
    write: (html: string) => void;
    close: () => void;
  };
  close?: () => void;
  location?: { href: string };
}

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function escapeAttr(text: string): string {
  return escapeHtml(text).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** Render plain text in a new browser tab (TTL, JSON, etc.). */
export function writeTextToPopup(popup: PopupLike, title: string, text: string): void {
  const escaped = escapeHtml(text);
  const safeTitle = escapeHtml(title);
  popup.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${safeTitle}</title></head>` +
      `<body style="margin:0;background:#fff;color:#111;">` +
      `<pre style="margin:0;padding:1rem;font-family:ui-monospace,monospace;font-size:12px;` +
      `white-space:pre-wrap;word-break:break-word;">${escaped}</pre></body></html>`,
  );
  popup.document.close();
}

/** Render raw TTL in a plain white popup tab (legacy Open-FDD UX). */
export function writeTtlToPopup(popup: PopupLike, ttl: string): void {
  writeTextToPopup(popup, "Data model TTL", ttl);
}

export async function openTtlPopup(
  fetchTtl: () => Promise<string>,
  ttlPath = "/api/model/ttl?save=false",
): Promise<string | null> {
  const popup = window.open("", "_blank");
  if (!popup) {
    return "Popup blocked. Allow popups for this site and try again.";
  }
  const href = escapeAttr(ttlPath);
  popup.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head>` +
      `<body style="font-family:system-ui,sans-serif;padding:1rem;background:#fff;color:#333;">` +
      `<p>Loading Haystack TTL graph…</p>` +
      `<p style="color:#666;font-size:14px;">If this hangs, ` +
      `<a href="${href}">open raw TTL</a>.</p></body></html>`,
  );
  popup.document.close();
  try {
    const ttl = await fetchTtl();
    writeTtlToPopup(popup, ttl);
    return null;
  } catch (err) {
    try {
      if (popup.location) popup.location.href = ttlPath;
    } catch {
      popup.close?.();
    }
    return err instanceof Error ? err.message : "Failed to load TTL";
  }
}

export function openTextPopup(title: string, text: string): boolean {
  const popup = window.open("", "_blank");
  if (!popup) return false;
  writeTextToPopup(popup, title, text);
  return true;
}
