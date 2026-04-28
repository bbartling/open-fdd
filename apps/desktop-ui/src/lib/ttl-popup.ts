export interface PopupLike {
  closed?: boolean;
  document: {
    hidden?: boolean;
    closed?: boolean;
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
  const doc = popup?.document;
  if (!doc || typeof doc.write !== "function" || typeof doc.close !== "function") {
    return;
  }
  if (popup.closed || doc.hidden || doc.closed) {
    return;
  }
  const escaped = escapeHtml(ttl);
  try {
    doc.write(
      `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Data model TTL</title></head><body style="margin:0;background:#ffffff;color:#111111;"><pre style="margin:0;padding:1rem;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.4;white-space:pre-wrap;word-break:break-word;">${escaped}</pre></body></html>`,
    );
    doc.close();
  } catch {
    return;
  }
}
