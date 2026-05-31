export interface PopupLike {
  document: {
    write: (html: string) => void;
    close: () => void;
  };
  close?: () => void;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Render raw TTL in a plain white popup tab (legacy Open-FDD UX). */
export function writeTtlToPopup(popup: PopupLike, ttl: string): void {
  const escaped = escapeHtml(ttl);
  popup.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head>` +
      `<body style="margin:0;background:#fff;color:#111;">` +
      `<pre style="margin:0;padding:1rem;font-family:ui-monospace,monospace;font-size:12px;` +
      `white-space:pre-wrap;word-break:break-word;">${escaped}</pre></body></html>`,
  );
  popup.document.close();
}

export async function openTtlPopup(
  fetchTtl: () => Promise<string>,
  ttlPath = "/api/model/ttl?save=false",
): Promise<string | null> {
  const popup = window.open("", "_blank");
  if (!popup) {
    return "Popup blocked. Allow popups for this site and try again.";
  }
  popup.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head>` +
      `<body style="font-family:system-ui,sans-serif;padding:1rem;background:#fff;color:#333;">` +
      `<p>Loading BRICK TTL graph…</p>` +
      `<p style="color:#666;font-size:14px;">If this hangs, ` +
      `<a href="${ttlPath}">open raw TTL</a>.</p></body></html>`,
  );
  popup.document.close();
  try {
    const ttl = await fetchTtl();
    writeTtlToPopup(popup, ttl);
    return null;
  } catch (err) {
    try {
      popup.location.href = ttlPath;
    } catch {
      popup.close?.();
    }
    return err instanceof Error ? err.message : "Failed to load TTL";
  }
}
