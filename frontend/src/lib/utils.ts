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
  const future = diffMs < 0;
  const absMs = Math.abs(diffMs);
  const absSec = Math.round(absMs / 1000);

  if (absSec < 45) return future ? "in a few seconds" : "just now";

  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["year", 60 * 60 * 24 * 365],
    ["month", 60 * 60 * 24 * 30],
    ["day", 60 * 60 * 24],
    ["hour", 60 * 60],
    ["minute", 60],
  ];

  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, seconds] of units) {
    if (absSec >= seconds) {
      const amount = Math.round(absSec / seconds);
      return rtf.format(future ? amount : -amount, unit);
    }
  }

  return future ? `in ${absSec} seconds` : `${absSec} seconds ago`;
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
    case "medium":
      return "warning";
    case "ok":
    case "healthy":
    case "success":
    case "low":
      return "success";
    case "info":
      return "secondary";
    default:
      return "outline";
  }
}