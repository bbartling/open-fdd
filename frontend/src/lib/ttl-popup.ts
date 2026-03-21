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

export function writeTtlToPopup(popup: PopupLike, ttl: string): void {
  const escaped = escapeHtml(ttl);
  popup.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head><body><pre style="margin:0;padding:1rem;font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap;word-break:break-all;">${escaped}</pre></body></html>`,
  );
  popup.document.close();
}

