import { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { useSiteContext } from "@/contexts/site-context";
import { SiteCard } from "@/components/dashboard/SiteCard";
import { FddStatusBanner } from "@/components/dashboard/FddStatusBanner";
import { FaultList } from "@/components/dashboard/FaultList";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import type { ChartConfig } from "@/components/ui/chart";
import { useSites, useAllEquipment, useAllPoints, useEquipment, usePoints } from "@/hooks/use-sites";
import { useActiveFaults, useFaultDefinitions, useSiteFaults } from "@/hooks/use-faults";
import { useCapabilities } from "@/hooks/use-fdd-status";
import { callAiAgent } from "@/lib/crud-api";
import type {
  AiAgentResponse,
  FaultResultsSampleResponse,
  FaultTimeseriesResponse,
  FaultsByEquipmentResponse,
  PointTimeseriesResponse,
} from "@/types/api";
// Overview AI (Open‑Claw-only): no client-side model selection.

const CHART_COLORS = [
  "hsl(215, 60%, 42%)",
  "hsl(338, 65%, 48%)",
  "hsl(142, 71%, 35%)",
  "hsl(38, 92%, 50%)",
  "hsl(262, 52%, 50%)",
  "hsl(190, 70%, 40%)",
];

/** Escape a CSV cell (quote if contains comma, newline, or quote). */
function escapeCsvCell(value: string | number): string {
  const s = String(value);
  if (/[,"\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function downloadCsv(filename: string, csvContent: string) {
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 100);
}

function faultTimeseriesToCsv(data: FaultTimeseriesResponse): string {
  const series = data?.series ?? [];
  const pivoted = pivotFaultSeries(series);
  const metrics = Array.from(new Set(series.map((r) => r.metric))).sort();
  const headers = ["timestamp", "datetime", ...metrics];
  const rows = pivoted.map((row) => {
    const ts = row.timestamp as number;
    const datetime = Number.isFinite(ts) ? new Date(ts).toISOString() : "";
    const rest = metrics.map((m) => (row[m] ?? "") as number);
    return [ts, datetime, ...rest];
  });
  return [headers.map(escapeCsvCell).join(","), ...rows.map((r) => r.map(escapeCsvCell).join(","))].join("\n");
}

function pointTimeseriesToCsv(data: PointTimeseriesResponse): string {
  const series = data?.series ?? [];
  const pivoted = pivotFaultSeries(series);
  const metrics = Array.from(new Set(series.map((r) => r.metric))).sort();
  const headers = ["timestamp", "datetime", ...metrics];
  const rows = pivoted.map((row) => {
    const ts = row.timestamp as number;
    const datetime = Number.isFinite(ts) ? new Date(ts).toISOString() : "";
    const rest = metrics.map((m) => (row[m] ?? "") as number);
    return [ts, datetime, ...rest];
  });
  return [headers.map(escapeCsvCell).join(","), ...rows.map((r) => r.map(escapeCsvCell).join(","))].join("\n");
}

function faultsByEquipmentToCsv(data: FaultsByEquipmentResponse): string {
  const rows = data?.by_equipment ?? [];
  const headers = ["equipment_name", "site_id", "equipment_id", "bacnet_device_id", "active_fault_count"];
  return [
    headers.join(","),
    ...rows.map((r) =>
      [
        r.equipment_name,
        r.site_id,
        r.equipment_id,
        r.bacnet_device_id ?? "",
        r.active_fault_count,
      ].map(escapeCsvCell).join(",")
    ),
  ].join("\n");
}

function faultResultsToCsv(data: FaultResultsSampleResponse): string {
  const rows = data?.rows ?? [];
  const headers = ["ts", "site_id", "equipment_id", "fault_id", "flag_value", "evidence"];
  return [
    headers.join(","),
    ...rows.map((r) =>
      [
        r.ts,
        r.site_id,
        r.equipment_id,
        r.fault_id,
        r.flag_value,
        r.evidence != null ? JSON.stringify(r.evidence) : "",
      ].map(escapeCsvCell).join(",")
    ),
  ].join("\n");
}

/** Pivoted row: timestamp plus one numeric column per metric (indexable by string). */
type PivotedSeriesRow = { timestamp: number; [k: string]: number | undefined };

function pivotFaultSeries(series: { time: string; metric: string; value: number }[]): PivotedSeriesRow[] {
  const byTs = new Map<number, Record<string, number>>();
  for (const r of series) {
    const t = new Date(r.time).getTime();
    if (!Number.isFinite(t)) continue;
    if (!byTs.has(t)) byTs.set(t, {});
    byTs.get(t)![r.metric] = r.value;
  }
  return Array.from(byTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([timestamp, rest]) => ({ timestamp, ...rest } as PivotedSeriesRow));
}

/** Spreadsheet-style table for pivoted timeseries (chart data). */
function ChartDataTable({
  data,
  metrics,
}: {
  data: PivotedSeriesRow[];
  metrics: string[];
}) {
  if (data.length === 0) return null;
  const cols = ["datetime", ...metrics];
  return (
    <div className="mt-4 overflow-auto rounded-lg border border-border/60" style={{ maxHeight: "40vh" }}>
      <Table>
        <TableHeader>
          <TableRow>
            {cols.map((c) => (
              <TableHead key={c} className="whitespace-nowrap text-xs">
                {c}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((row, i) => (
            <TableRow key={i}>
              <TableCell className="text-xs text-muted-foreground">
                {Number.isFinite(row.timestamp) ? new Date(row.timestamp).toISOString() : "—"}
              </TableCell>
              {metrics.map((m) => (
                <TableCell key={m} className="text-right text-xs tabular-nums">
                  {row[m] ?? "—"}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function OverviewChatFaultChart({
  data,
  height = 180,
  onPopOut,
}: {
  data: FaultTimeseriesResponse;
  height?: number;
  onPopOut?: () => void;
}) {
  const chartData = useMemo(() => {
    const raw = data?.series ? pivotFaultSeries(data.series) : [];
    return raw.filter((row) => Number.isFinite(row.timestamp));
  }, [data]);
  const metrics = useMemo(() => {
    const set = new Set<string>();
    for (const r of data?.series ?? []) {
      set.add(r.metric);
    }
    return Array.from(set);
  }, [data]);
  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    metrics.forEach((faultId, i) => {
      c[faultId] = { label: faultId, color: CHART_COLORS[i % CHART_COLORS.length] };
    });
    return c;
  }, [metrics]);
  const timeFormat = (ts: number) =>
    new Date(ts).toLocaleDateString([], { month: "short", day: "numeric" });
  const tooltipFormat = (ts: number) =>
    new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit" });
  if (chartData.length === 0) return null;
  return (
    <div className="relative mt-2">
      {onPopOut && (
        <button
          type="button"
          onClick={onPopOut}
          className="absolute right-2 top-2 z-10 rounded bg-muted/90 px-2 py-1 text-xs hover:bg-muted"
        >
          Pop out
        </button>
      )}
      <ChartContainer
        config={config}
        className="w-full rounded-lg border border-border/60 bg-card p-3"
        style={height ? { minHeight: height } : undefined}
      >
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            scale="time"
            tickFormatter={timeFormat}
            tick={{ fontSize: 10, fill: "hsl(220 8% 46%)" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "hsl(220 8% 46%)" }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <ChartTooltip content={<ChartTooltipContent config={config} formatTime={tooltipFormat} />} />
          {metrics.map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={config[key]?.color}
              strokeWidth={1.5}
              dot={false}
              connectNulls
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
    </div>
  );
}

function OverviewChatFaultTable({
  data,
  onPopOut,
  scrollMaxHeight = "12rem",
}: {
  data: FaultsByEquipmentResponse;
  onPopOut?: () => void;
  scrollMaxHeight?: string;
}) {
  const rows = data?.by_equipment ?? [];
  if (rows.length === 0) return null;
  return (
    <div className="relative mt-2">
      {onPopOut && (
        <button
          type="button"
          onClick={onPopOut}
          className="absolute right-2 top-2 z-10 rounded bg-muted/90 px-2 py-1 text-xs hover:bg-muted"
        >
          Pop out
        </button>
      )}
      <div
        className="overflow-auto rounded-lg border border-border/60"
        style={{ maxHeight: scrollMaxHeight }}
      >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Equipment</TableHead>
            <TableHead className="text-xs">BACnet device</TableHead>
            <TableHead className="text-xs text-right">Active faults</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={i}>
              <TableCell className="text-xs">{r.equipment_name}</TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {r.bacnet_device_id ?? "—"}
              </TableCell>
              <TableCell className="text-right text-xs tabular-nums">{r.active_fault_count}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
    </div>
  );
}

/** Point-timeseries chart (same shape as fault chart). */
function OverviewChatPointChart({
  data,
  height = 180,
  onPopOut,
}: {
  data: PointTimeseriesResponse;
  height?: number;
  onPopOut?: () => void;
}) {
  const chartData = useMemo(() => {
    const raw = data?.series ? pivotFaultSeries(data.series) : [];
    return raw.filter((row) => Number.isFinite(row.timestamp));
  }, [data]);
  const metrics = useMemo(() => {
    const set = new Set<string>();
    for (const r of data?.series ?? []) {
      set.add(r.metric);
    }
    return Array.from(set);
  }, [data]);
  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    metrics.forEach((metric, i) => {
      c[metric] = { label: metric, color: CHART_COLORS[i % CHART_COLORS.length] };
    });
    return c;
  }, [metrics]);
  const timeFormat = (ts: number) =>
    new Date(ts).toLocaleDateString([], { month: "short", day: "numeric" });
  const tooltipFormat = (ts: number) =>
    new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit" });
  if (chartData.length === 0) return null;
  return (
    <div className="relative mt-2">
      {onPopOut && (
        <button
          type="button"
          onClick={onPopOut}
          className="absolute right-2 top-2 z-10 rounded bg-muted/90 px-2 py-1 text-xs hover:bg-muted"
        >
          Pop out
        </button>
      )}
      <ChartContainer
        config={config}
        className="w-full rounded-lg border border-border/60 bg-card p-3"
        style={height ? { minHeight: height } : undefined}
      >
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
          <XAxis
            dataKey="timestamp"
            type="number"
            domain={["dataMin", "dataMax"]}
            scale="time"
            tickFormatter={timeFormat}
            tick={{ fontSize: 10, fill: "hsl(220 8% 46%)" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "hsl(220 8% 46%)" }}
            tickLine={false}
            axisLine={false}
            allowDecimals={true}
          />
          <ChartTooltip content={<ChartTooltipContent config={config} formatTime={tooltipFormat} />} />
          {metrics.map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={config[key]?.color}
              strokeWidth={1.5}
              dot={false}
              connectNulls
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
    </div>
  );
}

function OverviewChatFaultResultsTable({
  data,
  onPopOut,
  scrollMaxHeight = "12rem",
}: {
  data: FaultResultsSampleResponse;
  onPopOut?: () => void;
  scrollMaxHeight?: string;
}) {
  const rows = data?.rows ?? [];
  if (rows.length === 0) return null;
  return (
    <div className="relative mt-2">
      {onPopOut && (
        <button
          type="button"
          onClick={onPopOut}
          className="absolute right-2 top-2 z-10 rounded bg-muted/90 px-2 py-1 text-xs hover:bg-muted"
        >
          Pop out
        </button>
      )}
      <div
        className="overflow-auto rounded-lg border border-border/60"
        style={{ maxHeight: scrollMaxHeight }}
      >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Time</TableHead>
            <TableHead className="text-xs">Site</TableHead>
            <TableHead className="text-xs">Equipment</TableHead>
            <TableHead className="text-xs">Fault</TableHead>
            <TableHead className="text-xs text-right">Flag</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={i}>
              <TableCell className="text-xs text-muted-foreground">{r.ts}</TableCell>
              <TableCell className="text-xs">{r.site_id}</TableCell>
              <TableCell className="text-xs">{r.equipment_id}</TableCell>
              <TableCell className="text-xs">{r.fault_id}</TableCell>
              <TableCell className="text-right text-xs tabular-nums">{r.flag_value}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
    </div>
  );
}

type PopoutState =
  | { kind: "fault-chart"; data: FaultTimeseriesResponse }
  | { kind: "point-chart"; data: PointTimeseriesResponse }
  | { kind: "equipment-table"; data: FaultsByEquipmentResponse }
  | { kind: "fault-results-table"; data: FaultResultsSampleResponse };

function OverviewAiChat() {
  const { selectedSiteId } = useSiteContext();
  const { data: capabilities } = useCapabilities();
  const aiAvailable = capabilities?.ai_available === true;

  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<
    {
      role: "user" | "assistant";
      content: string;
      plot_data?: FaultTimeseriesResponse;
      table_data?: FaultsByEquipmentResponse;
      point_plot_data?: PointTimeseriesResponse;
      table_fault_results_data?: FaultResultsSampleResponse;
    }[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFddError, setLastFddError] = useState<string | null>(null);
  const [popout, setPopout] = useState<PopoutState | null>(null);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    if (!aiAvailable) {
      setError("AI disabled: bootstrap with --with-open-claw and set OFDD_OPEN_CLAW_BASE_URL + OFDD_OPEN_CLAW_API_KEY.");
      return;
    }
    const question = input.trim();
    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);
    try {
      const body = {
        mode: "overview_chat" as const,
        message: question,
        include_context: false,
        site_id: selectedSiteId ?? undefined,
      };
      const resp: AiAgentResponse = await callAiAgent(body);
      setLastFddError(resp.last_fdd_error ?? null);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: resp.answer,
          plot_data: resp.plots ?? undefined,
          table_data: resp.tables ?? undefined,
          point_plot_data: resp.point_plots ?? undefined,
          table_fault_results_data: resp.table_fault_results ?? undefined,
        },
      ]);
    } catch (err: unknown) {
      let msg = "Failed to call Overview AI assistant.";
      if (err instanceof Error) msg = err.message;
      else if (err && typeof err === "object" && "error" in err) {
        const e = (err as { error?: { message?: string } }).error;
        if (e && typeof e.message === "string") msg = e.message;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!popout) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPopout(null);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [popout]);

  return (
    <Card className="mt-6">
      <CardContent className="pt-6 space-y-4">
        {lastFddError && (
          <div
            className="rounded-lg border border-amber-500/60 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200"
            role="alert"
          >
            <span className="font-medium">Last FDD run error: </span>
            {lastFddError}
          </div>
        )}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-medium text-muted-foreground">
              Overview AI assistant (read-only)
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Answers “what&apos;s going on?” using data model, faults, and BACnet summaries. Does not write to the system.
            </p>
          </div>
        </div>

        {aiAvailable ? (
          <p className="rounded-md border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            Using server-configured Open‑Claw. No API key needed.
          </p>
        ) : (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            AI disabled. Run bootstrap with <code className="rounded bg-muted px-1">--with-open-claw</code> and set <code className="rounded bg-muted px-1">OFDD_OPEN_CLAW_BASE_URL</code> + <code className="rounded bg-muted px-1">OFDD_OPEN_CLAW_API_KEY</code>.
          </p>
        )}

        {aiAvailable && (
          <>
            <div className="h-px w-full bg-border" />

            <p className="text-xs text-muted-foreground">
              Ask a question and click Send. The assistant automatically attaches fault and sensor data (last 24h) and offers advice based on what it sees.
            </p>
          </>
        )}
        {aiAvailable && (
          <div className="h-56 overflow-y-auto rounded-md border bg-muted/40 p-3 text-xs space-y-2">
            {messages.length === 0 ? (
              <p className="text-muted-foreground italic">
                e.g. “How is the HVAC running overall?” or “Which sites have the most active faults right now?”
              </p>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={idx}
                  className={`max-w-[90%] rounded-md px-2 py-1 ${
                    m.role === "user"
                      ? "ml-auto bg-primary text-primary-foreground"
                      : "mr-auto w-full max-w-md bg-background border text-foreground"
                  }`}
                >
                  <div className="whitespace-pre-wrap text-xs">{m.content}</div>
                  {m.role === "assistant" && m.plot_data && (
                    <div className="mt-2">
                      <p className="text-xs font-medium text-muted-foreground">Fault overlay (24h)</p>
                      <OverviewChatFaultChart
                        data={m.plot_data}
                        onPopOut={() => setPopout({ kind: "fault-chart", data: m.plot_data! })}
                      />
                    </div>
                  )}
                  {m.role === "assistant" && m.point_plot_data && (
                    <div className="mt-2">
                      <p className="text-xs font-medium text-muted-foreground">Sensor data (24h)</p>
                      <OverviewChatPointChart
                        data={m.point_plot_data}
                        onPopOut={() => setPopout({ kind: "point-chart", data: m.point_plot_data! })}
                      />
                    </div>
                  )}
                  {m.role === "assistant" && m.table_data && (
                    <OverviewChatFaultTable
                      data={m.table_data}
                      onPopOut={() => setPopout({ kind: "equipment-table", data: m.table_data! })}
                    />
                  )}
                  {m.role === "assistant" && m.table_fault_results_data && (
                    <OverviewChatFaultResultsTable
                      data={m.table_fault_results_data}
                      onPopOut={() =>
                        setPopout({ kind: "fault-results-table", data: m.table_fault_results_data! })
                      }
                    />
                  )}
                </div>
              ))
            )}
          </div>
          )}

        {aiAvailable && (
          <>
            <form onSubmit={handleSend} className="flex gap-2">
              <label className="sr-only" htmlFor="overview-ai-input">
                Your question
              </label>
              <input
                id="overview-ai-input"
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                className="flex-1 rounded-md border-2 border-input bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="Ask the Overview assistant a question..."
                aria-label="Your question"
              />
              <button
                type="submit"
                disabled={loading}
                className="inline-flex items-center rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
              >
                {loading ? "Thinking..." : "Send"}
              </button>
            </form>
            {error && (
              <p className="text-xs text-destructive">
                {error}
              </p>
            )}
          </>
        )}
        {popout && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Pop-out chart or table"
            onClick={() => setPopout(null)}
          >
            <div
              className="relative flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl border bg-card shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex shrink-0 items-center justify-end gap-2 border-b px-4 py-2">
                <button
                  type="button"
                  onClick={() => {
                    const filename =
                      popout.kind === "fault-chart"
                        ? "fault-timeseries.csv"
                        : popout.kind === "point-chart"
                          ? "point-timeseries.csv"
                          : popout.kind === "equipment-table"
                            ? "faults-by-equipment.csv"
                            : "fault-results.csv";
                    const csv =
                      popout.kind === "fault-chart"
                        ? faultTimeseriesToCsv(popout.data)
                        : popout.kind === "point-chart"
                          ? pointTimeseriesToCsv(popout.data)
                          : popout.kind === "equipment-table"
                            ? faultsByEquipmentToCsv(popout.data)
                            : faultResultsToCsv(popout.data);
                    downloadCsv(filename, csv);
                  }}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
                >
                  Download CSV
                </button>
                <button
                  type="button"
                  onClick={() => setPopout(null)}
                  className="rounded-md bg-muted px-3 py-1.5 text-sm font-medium hover:bg-muted/80"
                >
                  Close
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-auto p-4">
                {popout.kind === "fault-chart" && (
                  <>
                    <OverviewChatFaultChart data={popout.data} height={400} />
                    <h3 className="mt-4 text-sm font-medium text-muted-foreground">Data (spreadsheet)</h3>
                    <ChartDataTable
                      data={pivotFaultSeries(popout.data.series ?? []).filter((row) =>
                        Number.isFinite(row.timestamp)
                      )}
                      metrics={Array.from(new Set((popout.data.series ?? []).map((r) => r.metric))).sort()}
                    />
                  </>
                )}
                {popout.kind === "point-chart" && (
                  <>
                    <OverviewChatPointChart data={popout.data} height={400} />
                    <h3 className="mt-4 text-sm font-medium text-muted-foreground">Data (spreadsheet)</h3>
                    <ChartDataTable
                      data={pivotFaultSeries(popout.data.series ?? []).filter((row) =>
                        Number.isFinite(row.timestamp)
                      )}
                      metrics={Array.from(new Set((popout.data.series ?? []).map((r) => r.metric))).sort()}
                    />
                  </>
                )}
                {popout.kind === "equipment-table" && (
                  <OverviewChatFaultTable data={popout.data} scrollMaxHeight="70vh" />
                )}
                {popout.kind === "fault-results-table" && (
                  <OverviewChatFaultResultsTable data={popout.data} scrollMaxHeight="70vh" />
                )}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AllSitesView() {
  const { setSelectedSiteId } = useSiteContext();
  const { data: sites, isLoading: sitesLoading } = useSites();
  const { data: equipment = [] } = useAllEquipment();
  const { data: points = [] } = useAllPoints();
  const { data: faults = [] } = useActiveFaults();
  const { data: definitions = [] } = useFaultDefinitions();

  return (
    <>
      <FddStatusBanner />
      <div className="mt-6">
        {sitesLoading ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-52 rounded-2xl" />
            ))}
          </div>
        ) : !sites || sites.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center">
            <p className="text-lg font-medium text-foreground">
              No sites configured
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Add sites via the API or config UI to get started.
            </p>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {sites.map((site) => (
              <SiteCard
                key={site.id}
                site={site}
                equipment={equipment.filter((e) => e.site_id === site.id)}
                points={points.filter((p) => p.site_id === site.id)}
                faults={faults.filter((f) => f.site_id === site.id)}
                definitions={definitions}
                onSelect={setSelectedSiteId}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function SiteSummaryView({ siteId }: { siteId: string }) {
  const { selectedSite } = useSiteContext();
  const { data: equipment = [] } = useEquipment(siteId);
  const { data: points = [] } = usePoints(siteId);
  const { data: faults = [] } = useSiteFaults(siteId);
  const { data: definitions = [] } = useFaultDefinitions();

  if (!selectedSite) {
    return (
      <div className="grid gap-5 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  const faultCount = faults.length;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          {selectedSite.name}
        </h1>
        {selectedSite.description && (
          <p className="mt-1 text-sm text-muted-foreground">
            {selectedSite.description}
          </p>
        )}
        <div className="mt-3">
          {faultCount > 0 ? (
            <Badge variant="destructive">
              {faultCount} active fault{faultCount !== 1 ? "s" : ""}
            </Badge>
          ) : (
            <Badge variant="success">No faults</Badge>
          )}
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Equipment</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {equipment.length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Points</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {points.length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">Active Faults</p>
            <p className={`mt-1 text-3xl font-semibold tabular-nums ${faultCount > 0 ? "text-destructive" : "text-success"}`}>
              {faultCount}
            </p>
          </CardContent>
        </Card>
      </div>

      {faults.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">
            Active Faults
          </h2>
          <Card>
            <CardContent className="pt-4">
              <FaultList
                faults={faults}
                definitions={definitions}
                equipment={equipment}
              />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

export function OverviewPage() {
  const { selectedSiteId } = useSiteContext();

  if (selectedSiteId) {
    return (
      <>
        <SiteSummaryView siteId={selectedSiteId} />
        <OverviewAiChat />
      </>
    );
  }

  return (
    <>
      <AllSitesView />
      <OverviewAiChat />
    </>
  );
}
