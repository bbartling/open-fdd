import { useState, useRef, useEffect } from "react";
import type { Point, Equipment } from "@/types/api";

const MAX_POINTS = 8;

interface PointPickerProps {
  points: Point[];
  equipment: Equipment[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

export function PointPicker({
  points,
  equipment,
  selectedIds,
  onChange,
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

  const grouped = new Map<string, Point[]>();
  for (const p of points) {
    const key = p.equipment_id ?? "__unassigned__";
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
        className="inline-flex h-10 items-center gap-2 rounded-xl border border-border/60 bg-card px-4 text-sm font-medium transition-all duration-200 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        onClick={() => setOpen(!open)}
      >
        {selectedIds.length === 0
          ? "Select points\u2026"
          : `${selectedIds.length} point${selectedIds.length > 1 ? "s" : ""} selected`}
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
        <div className="absolute left-0 z-50 mt-2 w-80 rounded-2xl border border-border/60 bg-card/95 shadow-xl shadow-black/[0.08] backdrop-blur-lg">
          <div className="border-b border-border/60 p-2.5">
            <input
              type="text"
              placeholder="Search points\u2026"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm transition-colors duration-200 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              autoFocus
            />
          </div>

          <div className="max-h-64 overflow-y-auto p-1.5">
            {Array.from(grouped.entries()).map(([eqId, eqPoints]) => {
              const filtered = eqPoints.filter(matchesSearch);
              if (filtered.length === 0) return null;

              const eqName =
                eqId === "__unassigned__"
                  ? "Unassigned"
                  : equipMap.get(eqId)?.name ?? eqId;

              return (
                <div key={eqId}>
                  <div className="px-2.5 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {eqName}
                  </div>
                  {filtered.map((p) => {
                    const checked = selectedIds.includes(p.id);
                    const disabled =
                      !checked && selectedIds.length >= MAX_POINTS;
                    return (
                      <label
                        key={p.id}
                        className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors duration-150 hover:bg-muted/50 ${disabled ? "pointer-events-none opacity-40" : ""}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          onChange={() => toggle(p.id)}
                          className="accent-primary"
                        />
                        <span className="truncate">
                          {p.object_name ?? p.external_id}
                        </span>
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
            <div className="border-t border-border/60 px-2.5 py-2">
              <button
                type="button"
                className="text-xs font-medium text-muted-foreground transition-colors duration-150 hover:text-foreground"
                onClick={() => onChange([])}
              >
                Clear selection
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
