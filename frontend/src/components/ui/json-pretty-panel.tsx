import { useCallback, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

const MAX_ARRAY_PREVIEW = 80;
const MAX_DEPTH = 24;

function escapeKey(k: string): string {
  return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(k) ? k : JSON.stringify(k);
}

type JsonTreeProps = {
  value: unknown;
  depth: number;
  defaultExpandDepth: number;
  seen: WeakSet<object>;
  pathKey: string;
};

function JsonTree({ value, depth, defaultExpandDepth, seen, pathKey }: JsonTreeProps) {
  const autoOpen = depth < defaultExpandDepth;
  const [open, setOpen] = useState(autoOpen);

  if (value === null) {
    return <span className="text-muted-foreground">null</span>;
  }
  if (value === undefined) {
    return <span className="text-muted-foreground">undefined</span>;
  }
  if (typeof value === "boolean") {
    return <span className="text-violet-600 dark:text-violet-400">{String(value)}</span>;
  }
  if (typeof value === "number") {
    return <span className="text-sky-600 dark:text-sky-400 tabular-nums">{String(value)}</span>;
  }
  if (typeof value === "string") {
    const q = JSON.stringify(value);
    return <span className="text-emerald-700 dark:text-emerald-400/90 break-all">{q}</span>;
  }

  if (depth >= MAX_DEPTH) {
    return <span className="text-muted-foreground">…</span>;
  }

  if (Array.isArray(value)) {
    if (seen.has(value)) {
      return <span className="text-amber-700 dark:text-amber-400">[Circular]</span>;
    }
    seen.add(value);
    if (value.length === 0) {
      return <span className="text-muted-foreground">[]</span>;
    }
    const preview = value.length > MAX_ARRAY_PREVIEW ? value.slice(0, MAX_ARRAY_PREVIEW) : value;
    const more = value.length - preview.length;
    return (
      <span className="inline-flex flex-col gap-0.5 align-top">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="group inline-flex items-center gap-1 rounded px-0.5 text-left hover:bg-muted/60"
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="text-muted-foreground">
            [{value.length}]{more > 0 && !open ? ` (+${more} more)` : ""}
          </span>
        </button>
        {open && (
          <ul className="ml-4 list-none border-l border-border/50 pl-2">
            {preview.map((item, i) => (
              <li key={`${pathKey}.${i}`} className="py-0.5">
                <JsonTree
                  value={item}
                  depth={depth + 1}
                  defaultExpandDepth={defaultExpandDepth}
                  seen={seen}
                  pathKey={`${pathKey}.${i}`}
                />
              </li>
            ))}
            {more > 0 && (
              <li className="py-0.5 text-xs text-muted-foreground">… {more} more items</li>
            )}
          </ul>
        )}
      </span>
    );
  }

  if (typeof value === "object") {
    if (seen.has(value)) {
      return <span className="text-amber-700 dark:text-amber-400">[Circular]</span>;
    }
    seen.add(value);
    const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== undefined);
    if (entries.length === 0) {
      return <span className="text-muted-foreground">{"{}"}</span>;
    }
    entries.sort(([a], [b]) => a.localeCompare(b));
    return (
      <span className="inline-flex flex-col gap-0.5 align-top">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="group inline-flex items-center gap-1 rounded px-0.5 text-left hover:bg-muted/60"
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="text-muted-foreground">
            {"{"}
            {entries.length} {entries.length === 1 ? "key" : "keys"}
            {"}"}
          </span>
        </button>
        {open && (
          <ul className="ml-4 list-none border-l border-border/50 pl-2">
            {entries.map(([k, v]) => (
              <li key={`${pathKey}.${k}`} className="py-0.5">
                <span className="text-muted-foreground">{escapeKey(k)}</span>
                <span className="text-muted-foreground">: </span>
                <JsonTree
                  value={v}
                  depth={depth + 1}
                  defaultExpandDepth={defaultExpandDepth}
                  seen={seen}
                  pathKey={`${pathKey}.${k}`}
                />
              </li>
            ))}
          </ul>
        )}
      </span>
    );
  }

  return <span className="break-all">{String(value)}</span>;
}

export type JsonPrettyPanelProps = {
  value: unknown;
  className?: string;
  /** Tailwind max-height class, e.g. max-h-64 */
  maxHeightClass?: string;
  /** Nesting levels expanded by default (0 = all collapsed except leaves) */
  defaultExpandDepth?: number;
  showCopy?: boolean;
  compact?: boolean;
};

/**
 * Collapsible tree + optional copy for arbitrary JSON-shaped values (config dumps, integrity checks, raw API bodies).
 */
export function JsonPrettyPanel({
  value,
  className,
  maxHeightClass = "max-h-64",
  defaultExpandDepth = 2,
  showCopy = true,
  compact = false,
}: JsonPrettyPanelProps) {
  const [copied, setCopied] = useState(false);
  const text = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }, [text]);

  const seen = new WeakSet<object>();

  return (
    <div
      className={cn(
        "relative rounded-lg border border-border/60 bg-muted/25",
        compact ? "p-2" : "p-3",
        className,
      )}
    >
      {showCopy && (
        <button
          type="button"
          onClick={() => void copy()}
          className="absolute right-2 top-2 z-[1] inline-flex h-7 items-center gap-1 rounded-md border border-border/60 bg-background/80 px-2 text-[10px] font-medium text-muted-foreground shadow-sm hover:text-foreground"
          title="Copy JSON"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      )}
      <div
        className={cn(
          "overflow-auto font-mono text-xs leading-relaxed text-foreground",
          showCopy && "pr-16",
          maxHeightClass,
        )}
      >
        <JsonTree value={value} depth={0} defaultExpandDepth={defaultExpandDepth} seen={seen} pathKey="root" />
      </div>
    </div>
  );
}
