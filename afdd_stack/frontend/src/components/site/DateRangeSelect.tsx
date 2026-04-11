import { cn } from "@/lib/utils";

export type DatePreset = "24h" | "7d" | "30d" | "custom";

interface DateRangeSelectProps {
  preset: DatePreset;
  onPresetChange: (p: DatePreset) => void;
  customStart: string;
  customEnd: string;
  onCustomStartChange: (v: string) => void;
  onCustomEndChange: (v: string) => void;
}

const presets: { value: DatePreset; label: string }[] = [
  { value: "24h", label: "24 h" },
  { value: "7d", label: "7 d" },
  { value: "30d", label: "30 d" },
  { value: "custom", label: "Custom" },
];

export function DateRangeSelect({
  preset,
  onPresetChange,
  customStart,
  customEnd,
  onCustomStartChange,
  onCustomEndChange,
}: DateRangeSelectProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="inline-flex h-10 items-center gap-1 rounded-xl bg-muted/70 p-1">
        {presets.map((p) => (
          <button
            key={p.value}
            type="button"
            aria-pressed={preset === p.value}
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-3.5 py-1.5 text-sm font-medium transition-all duration-200",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              preset === p.value
                ? "bg-card text-foreground shadow-sm shadow-black/[0.04]"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => onPresetChange(p.value)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {preset === "custom" && (
        <div className="flex items-center gap-2">
          <input
            type="datetime-local"
            aria-label="Start date"
            value={customStart}
            onChange={(e) => onCustomStartChange(e.target.value)}
            className="h-10 rounded-xl border border-border/60 bg-card px-3 text-sm transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <span className="text-sm text-muted-foreground">to</span>
          <input
            type="datetime-local"
            aria-label="End date"
            value={customEnd}
            onChange={(e) => onCustomEndChange(e.target.value)}
            className="h-10 rounded-xl border border-border/60 bg-card px-3 text-sm transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
        </div>
      )}
    </div>
  );
}
