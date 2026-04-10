import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function parseUtcTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /z$/i.test(value) || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function timeAgo(value: string | null | undefined): string {
  const date = parseUtcTimestamp(value);
  if (!date) return "unknown";

  const diffMs = Date.now() - date.getTime();
  if (diffMs < 0) {
    // Future timestamps are rare in this UI; show a simple relative hint.
    const seconds = Math.round(Math.abs(diffMs) / 1000);
    if (seconds < 60) return "in a few seconds";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `in ${minutes}m`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `in ${hours}h`;
    const days = Math.round(hours / 24);
    return `in ${days}d`;
  }

  const seconds = Math.round(diffMs / 1000);
  if (seconds < 45) return "just now";

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;

  // Older than a week: fall back to locale date (used in tests).
  return date.toLocaleDateString();
}

export function severityVariant(severity: string | null | undefined):
  | "default"
  | "secondary"
  | "destructive"
  | "success"
  | "warning"
  | "outline" {
  switch ((severity ?? "").toLowerCase()) {
    case "critical":
    case "high":
    case "error":
      return "destructive";
    case "warning":
      // Tests (and UI) treat warning as a neutral/outlined badge.
      return "outline";
    default:
      // Info and any other severities use a secondary badge style.
      return "secondary";
  }
}