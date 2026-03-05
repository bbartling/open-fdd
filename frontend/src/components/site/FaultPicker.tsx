import { useState, useRef, useEffect } from "react";
import type { FaultDefinition } from "@/types/api";

const MAX_FAULTS = 12;

interface FaultPickerProps {
  definitions: FaultDefinition[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  label?: string;
}

export function FaultPicker({
  definitions,
  selectedIds,
  onChange,
  label = "Add faults",
}: FaultPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const lowerSearch = search.toLowerCase();
  const filtered = definitions.filter(
    (d) =>
      !search ||
      d.name.toLowerCase().includes(lowerSearch) ||
      d.fault_id.toLowerCase().includes(lowerSearch) ||
      (d.category?.toLowerCase().includes(lowerSearch) ?? false),
  );

  function toggle(id: string) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((s) => s !== id));
    } else if (selectedIds.length < MAX_FAULTS) {
      onChange([...selectedIds, id]);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        className="inline-flex h-9 min-w-[10rem] items-center justify-between gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-left text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen(!open)}
      >
        <span className="truncate">
          {selectedIds.length === 0 ? `${label}\u2026` : `${selectedIds.length} fault(s)`}
        </span>
        <svg
          className="h-4 w-4 shrink-0 text-muted-foreground"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 z-50 mt-1.5 w-80 rounded-xl border border-border bg-card shadow-xl">
          <div className="border-b border-border p-2">
            <input
              type="text"
              placeholder="Search by name or id…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              autoFocus
            />
          </div>
          <div className="max-h-64 overflow-y-auto p-1.5">
            {filtered.length === 0 ? (
              <p className="px-2 py-4 text-sm text-muted-foreground">No fault definitions.</p>
            ) : (
              filtered.map((d) => {
                const checked = selectedIds.includes(d.fault_id);
                const disabled = !checked && selectedIds.length >= MAX_FAULTS;
                return (
                  <label
                    key={d.fault_id}
                    className={`flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors hover:bg-muted/60 ${disabled ? "pointer-events-none opacity-50" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => toggle(d.fault_id)}
                      className="h-4 w-4 shrink-0 rounded border-border accent-primary"
                    />
                    <span className="min-w-0 truncate font-medium">{d.name}</span>
                    <span className="shrink-0 truncate text-xs text-muted-foreground">
                      {d.fault_id}
                    </span>
                  </label>
                );
              })
            )}
          </div>
          {selectedIds.length > 0 && (
            <div className="border-t border-border px-2.5 py-2">
              <button
                type="button"
                className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => onChange([])}
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
