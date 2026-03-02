import * as React from "react";
import { cn } from "@/lib/utils";
import { Tooltip, Legend } from "recharts";

export interface ChartConfigEntry {
  label: string;
  color: string;
  unit?: string;
}

export type ChartConfig = Record<string, ChartConfigEntry>;

interface ChartContextValue {
  config: ChartConfig;
}

const ChartContext = React.createContext<ChartContextValue>({ config: {} });

export function useChartContext() {
  return React.useContext(ChartContext);
}

interface ChartContainerProps extends React.HTMLAttributes<HTMLDivElement> {
  config: ChartConfig;
  children: React.ReactNode;
}

export function ChartContainer({
  config,
  children,
  className,
  ...props
}: ChartContainerProps) {
  const cssVars = Object.entries(config).reduce(
    (acc, [key, entry]) => {
      acc[`--color-${key}`] = entry.color;
      return acc;
    },
    {} as Record<string, string>,
  );

  return (
    <ChartContext.Provider value={{ config }}>
      <div
        className={cn(
          "w-full [&_.recharts-cartesian-grid_line]:stroke-border/50 [&_.recharts-curve]:stroke-[1.5]",
          className,
        )}
        style={cssVars}
        {...props}
      >
        {children}
      </div>
    </ChartContext.Provider>
  );
}

export function ChartTooltip(
  props: React.ComponentProps<typeof Tooltip>,
) {
  return <Tooltip {...props} />;
}

interface TooltipContentProps {
  active?: boolean;
  payload?: Array<{
    dataKey: string;
    value: number;
    color: string;
  }>;
  label?: number;
  config: ChartConfig;
  formatTime: (ts: number) => string;
}

export function ChartTooltipContent({
  active,
  payload,
  label,
  config,
  formatTime,
}: TooltipContentProps) {
  if (!active || !payload?.length || label == null) return null;

  return (
    <div className="rounded-xl border border-border/60 bg-card/95 px-3.5 py-2.5 shadow-lg shadow-black/[0.08] backdrop-blur-md">
      <p className="mb-2 text-xs font-medium text-muted-foreground">
        {formatTime(label)}
      </p>
      <div className="space-y-1">
        {payload.map((p) => {
          const entry = config[p.dataKey];
          return (
            <div key={p.dataKey} className="flex items-center gap-2 text-sm">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: p.color }}
                aria-hidden="true"
              />
              <span className="text-muted-foreground">
                {entry?.label ?? p.dataKey}
              </span>
              <span className="ml-auto font-medium tabular-nums text-foreground">
                {typeof p.value === "number" ? p.value.toFixed(1) : p.value}
                {entry?.unit ? ` ${entry.unit}` : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ChartLegend(
  props: React.ComponentProps<typeof Legend>,
) {
  return <Legend {...props} />;
}

interface LegendContentProps {
  payload?: Array<{
    dataKey?: string;
    value: string;
    color: string;
  }>;
  config: ChartConfig;
}

export function ChartLegendContent({ payload, config }: LegendContentProps) {
  if (!payload?.length) return null;

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1.5 pt-3">
      {payload.map((p) => {
        const key = p.dataKey ?? p.value;
        const entry = config[key];
        return (
          <div key={key} className="flex items-center gap-1.5 text-xs">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: p.color }}
              aria-hidden="true"
            />
            <span className="text-muted-foreground">
              {entry?.label ?? key}
            </span>
          </div>
        );
      })}
    </div>
  );
}
