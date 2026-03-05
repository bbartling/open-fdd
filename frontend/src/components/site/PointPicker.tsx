import { useState, useRef, useEffect } from "react";
import type { Point, Equipment } from "@/types/api";
import { pointGroupKey, uniquePointsForDropdown } from "./point-picker-utils";

const MAX_POINTS = 20;

interface PointPickerProps {
  points: Point[];
  equipment: Equipment[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  label?: string;
}

export function PointPicker({
  points,
  equipment,
  selectedIds,
  onChange,
  label = "Select points",
}: PointPickerProps) {
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

  const equipMap = new Map(equipment.map((e) => [e.id, e]));

  const uniquePoints = uniquePointsForDropdown(points);
  const grouped = new Map<string, Point[]>();
  for (const p of uniquePoints) {
    const key = pointGroupKey(p);
    const arr = grouped.get(key) ?? [];
    arr.push(p);
    grouped.set(key, arr);
  }

  const lowerSearch = search.toLowerCase();
  function matchesSearch(p: Point) {
    if (!search) return true;
    return (
      p.external_id.toLowerCase().includes(lowerSearch) ||
      (p.object_name?.toLowerCase().includes(lowerSearch) ?? false) ||
      (p.brick_type?.toLowerCase().includes(lowerSearch) ?? false) ||
      (p.fdd_input?.toLowerCase().includes(lowerSearch) ?? false)
    );
  }

  function toggle(id: string) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((s) => s !== id));
    } else if (selectedIds.length < MAX_POINTS) {
      onChange([...selectedIds, id]);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="listbox"
        className="inline-flex h-9 min-w-[10rem] items-center justify-between gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-left text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen(!open)}
      >
        <span className="truncate">
          {selectedIds.length === 0
            ? `${label}\u2026`
            : `${selectedIds.length} series`}
        </span>
        <svg
          className="h-4 w-4 text-muted-foreground"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 z-50 mt-1.5 w-96 rounded-xl border border-border bg-card shadow-xl">
          <div className="border-b border-border p-2">
            <input
              type="text"
              placeholder="Search by name or external_id\u2026"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              autoFocus
            />
          </div>

          <div className="max-h-80 overflow-y-auto p-1.5">
            {Array.from(grouped.entries()).map(([eqId, eqPoints]) => {
              const filtered = eqPoints.filter(matchesSearch);
              if (filtered.length === 0) return null;

              const eqName =
                eqId === "__unassigned__"
                  ? "Unassigned"
                  : equipMap.get(eqId)?.name ?? eqId;

              return (
                <div key={eqId}>
                  <div className="sticky top-0 z-10 bg-muted/80 px-2.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground backdrop-blur-sm">
                    {eqName}
                  </div>
                  {filtered.map((p) => {
                    const checked = selectedIds.includes(p.id);
                    const disabled =
                      !checked && selectedIds.length >= MAX_POINTS;
                    return (
                      <label
                        key={p.id}
                        className={`flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors hover:bg-muted/60 ${disabled ? "pointer-events-none opacity-50" : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          onChange={() => toggle(p.id)}
                          className="h-4 w-4 shrink-0 rounded border-border accent-primary"
                        />
                        <span className="min-w-0 truncate font-medium">
                          {p.object_name ?? p.external_id}
                        </span>
                        {p.external_id && p.object_name !== p.external_id && (
                          <span className="truncate text-xs text-muted-foreground">
                            {p.external_id}
                          </span>
                        )}
                        {p.unit && (
                          <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">
                            {p.unit}
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
              );
            })}
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
