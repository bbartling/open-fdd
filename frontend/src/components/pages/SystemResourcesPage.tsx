import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from "@/components/ui/chart";
import type { ChartConfig } from "@/components/ui/chart";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import {
  useSystemHost,
  useSystemHostSeries,
  useSystemContainers,
  useSystemContainersSeries,
  useSystemDisk,
} from "@/hooks/use-system";
import { TutorialPopover } from "@/components/ui/tutorial-popover";
import { HardDrive, Server, Activity, ScrollText } from "lucide-react";
import { apiStreamText } from "@/lib/api";

const LOG_BUFFER_CAP = 400_000;

function primaryDisk(
  disks: { hostname: string; mount_path: string; used_gb: number; free_gb: number; total_gb: number; used_pct: number }[],
) {
  const root = disks.find((d) => d.mount_path === "/");
  return root ?? disks[0];
}

const HOST_COLORS: Record<string, string> = {
  mem_used_gb: "hsl(215, 60%, 42%)",
  mem_available_gb: "hsl(142, 71%, 35%)",
  load_1: "hsl(262, 52%, 50%)",
  load_5: "hsl(38, 92%, 50%)",
  load_15: "hsl(190, 70%, 40%)",
  swap_used_gb: "hsl(330, 55%, 45%)",
};

function last6hIso(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - 6 * 60 * 60 * 1000);
  return { from: from.toISOString(), to: to.toISOString() };
}

function pivotHostSeries(
  series: { time: string; metric: string; value: number }[],
): { timestamp: number; [key: string]: number }[] {
  const byTs = new Map<number, Record<string, number>>();
  for (const r of series) {
    const t = new Date(r.time).getTime();
    if (!byTs.has(t)) byTs.set(t, {});
    byTs.get(t)![r.metric] = r.value;
  }
  return Array.from(byTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([timestamp, rest]) => ({ timestamp, ...rest }));
}

export function SystemResourcesPage() {
  const [range] = useState(last6hIso);
  const [logContainer, setLogContainer] = useState<string>("");
  const [logText, setLogText] = useState<string>("");
  const [logStreaming, setLogStreaming] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const logAbortRef = useRef<AbortController | null>(null);
  const logPreRef = useRef<HTMLPreElement | null>(null);
  const { data: hostData, isLoading: hostLoading } = useSystemHost();
  const { data: hostSeriesData, isLoading: hostSeriesLoading } = useSystemHostSeries(
    range.from,
    range.to,
  );
  const { data: containersData, isLoading: containersLoading } = useSystemContainers();
  const { data: containersSeriesData } =
    useSystemContainersSeries(range.from, range.to);
  const { data: diskData, isLoading: diskLoading } = useSystemDisk();

  const host = hostData?.hosts?.[0];
  const rawContainers = containersData?.containers;
  const containers = useMemo(() => rawContainers ?? [], [rawContainers]);
  const disks = diskData?.disks ?? [];
  const disk = disks.length ? primaryDisk(disks) : null;

  /** Container resource status: green / yellow / red from CPU and mem. */
  function containerStatus(c: { cpu_pct?: number; mem_pct?: number | null }): "green" | "yellow" | "red" {
    const cpu = c.cpu_pct ?? 0;
    const mem = c.mem_pct ?? 0;
    if (cpu >= 90 || mem >= 95) return "red";
    if (cpu >= 70 || mem >= 80) return "yellow";
    return "green";
  }

  const hostChartData = useMemo(() => {
    if (!hostSeriesData?.series?.length) return [];
    const filtered =
      host?.hostname ?
        hostSeriesData.series.filter((s) => (s as { hostname?: string }).hostname === host.hostname)
      : hostSeriesData.series;
    return pivotHostSeries(filtered);
  }, [hostSeriesData, host]);

  const hostChartConfig: ChartConfig = useMemo(
    () => ({
      mem_used_gb: { label: "Mem used (GB)", color: HOST_COLORS.mem_used_gb, unit: "GB" },
      mem_available_gb: {
        label: "Mem available (GB)",
        color: HOST_COLORS.mem_available_gb,
        unit: "GB",
      },
      load_1: { label: "Load 1m", color: HOST_COLORS.load_1 },
      load_5: { label: "Load 5m", color: HOST_COLORS.load_5 },
      load_15: { label: "Load 15m", color: HOST_COLORS.load_15 },
      swap_used_gb: { label: "Swap used (GB)", color: HOST_COLORS.swap_used_gb, unit: "GB" },
    }),
    [],
  );

  const containerMemSeries = useMemo(() => {
    if (!containersSeriesData?.series?.length) return [];
    const byType = containersSeriesData.series.filter((s) => s.type === "mem_mb");
    const byTs = new Map<number, Record<string, number>>();
    for (const r of byType) {
      const t = new Date(r.time).getTime();
      if (!byTs.has(t)) byTs.set(t, {});
      byTs.get(t)![r.metric] = r.value;
    }
    return Array.from(byTs.entries())
      .sort(([a], [b]) => a - b)
      .map(([timestamp, rest]) => ({ timestamp, ...rest }));
  }, [containersSeriesData]);

  const containerCpuSeries = useMemo(() => {
    if (!containersSeriesData?.series?.length) return [];
    const byType = containersSeriesData.series.filter((s) => s.type === "cpu_pct");
    const byTs = new Map<number, Record<string, number>>();
    for (const r of byType) {
      const t = new Date(r.time).getTime();
      if (!byTs.has(t)) byTs.set(t, {});
      byTs.get(t)![r.metric] = r.value;
    }
    return Array.from(byTs.entries())
      .sort(([a], [b]) => a - b)
      .map(([timestamp, rest]) => ({ timestamp, ...rest }));
  }, [containersSeriesData]);

  const containerNames = useMemo(() => {
    const set = new Set<string>();
    containersSeriesData?.series?.forEach((s) => set.add(s.metric));
    return Array.from(set);
  }, [containersSeriesData]);

  /** Names from latest metrics row per container plus any seen in chart series (same Docker name as `docker ps`). */
  const logContainerOptions = useMemo(() => {
    const set = new Set<string>();
    containers.forEach((c) => {
      if (c.container_name) set.add(c.container_name);
    });
    containerNames.forEach((n) => set.add(n));
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [containers, containerNames]);

  const stopLogStream = useCallback(() => {
    logAbortRef.current?.abort();
    logAbortRef.current = null;
    setLogStreaming(false);
  }, []);

  const startLogStream = useCallback(async () => {
    if (!logContainer) return;
    stopLogStream();
    setLogError(null);
    setLogText("");
    const ac = new AbortController();
    logAbortRef.current = ac;
    setLogStreaming(true);
    const path = `/analytics/system/containers/${encodeURIComponent(logContainer)}/logs?tail=500&follow=true`;
    try {
      await apiStreamText(
        path,
        (chunk) => {
          if (logAbortRef.current !== ac) return;
          setLogText((prev) => {
            const next = prev + chunk;
            return next.length > LOG_BUFFER_CAP ? next.slice(-LOG_BUFFER_CAP) : next;
          });
        },
        ac.signal,
      );
    } catch (e) {
      const err = e as Error;
      if (logAbortRef.current !== ac) return;
      if (err.name !== "AbortError") {
        setLogError(err.message || String(e));
      }
    } finally {
      if (logAbortRef.current === ac) {
        setLogStreaming(false);
        logAbortRef.current = null;
      }
    }
  }, [logContainer, stopLogStream]);

  useEffect(() => {
    return () => stopLogStream();
  }, [stopLogStream]);

  useEffect(() => {
    const el = logPreRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logText]);

  const containerChartConfig: ChartConfig = useMemo(() => {
    const colors = [
      "hsl(215, 60%, 42%)",
      "hsl(338, 65%, 48%)",
      "hsl(142, 71%, 35%)",
      "hsl(38, 92%, 50%)",
      "hsl(262, 52%, 50%)",
      "hsl(190, 70%, 40%)",
    ];
    const c: ChartConfig = {};
    containerNames.forEach((n, i) => {
      c[n] = { label: n, color: colors[i % colors.length], unit: "" };
    });
    return c;
  }, [containerNames]);

  const hasAnyData =
    (hostData?.hosts?.length ?? 0) > 0 ||
    (containersData?.containers?.length ?? 0) > 0 ||
    (diskData?.disks?.length ?? 0) > 0;

  if (!hasAnyData && !hostLoading && !containersLoading && !diskLoading) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">System resources</h1>
        <div className="flex flex-col items-center justify-center rounded-2xl border border-border/60 bg-card py-20">
          <Server className="mb-3 h-10 w-10 text-muted-foreground/60" />
          <p className="text-sm font-medium text-foreground">No system metrics yet</p>
          <p className="mt-1 max-w-md text-center text-sm text-muted-foreground">
            Start the <strong>host-stats</strong> service so host memory, load, container stats,
            and disk usage are written to the database. Then this page will show stats and charts.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">System resources</h1>

      {/* Containers table first */}
      {containers.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">Containers (latest)</h2>
          <p className="mb-2 text-xs text-muted-foreground">
            Status: <span className="inline-block h-2 w-2 rounded-full bg-emerald-500 align-middle" /> OK
            {" · "}
            <span className="inline-block h-2 w-2 rounded-full bg-amber-500 align-middle" /> Moderate (CPU ≥70% or Mem ≥80%)
            {" · "}
            <span className="inline-block h-2 w-2 rounded-full bg-red-500 align-middle" /> High (CPU ≥90% or Mem ≥95%)
          </p>
          <Card>
            <CardContent className="pt-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-20">Status</TableHead>
                    <TableHead>Container</TableHead>
                    <TableHead className="text-right">CPU %</TableHead>
                    <TableHead className="text-right">Mem (MB)</TableHead>
                    <TableHead className="text-right">Mem %</TableHead>
                    <TableHead className="text-right">PIDs</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {containers.map((c) => {
                    const status = containerStatus(c);
                    return (
                      <TableRow key={c.container_name}>
                        <TableCell className="w-20">
                          <span
                            className={`inline-block h-2.5 w-2.5 rounded-full ${
                              status === "green"
                                ? "bg-emerald-500"
                                : status === "yellow"
                                  ? "bg-amber-500"
                                  : "bg-red-500"
                            }`}
                            title={
                              status === "green"
                                ? "OK"
                                : status === "yellow"
                                  ? "Moderate load"
                                  : "High CPU or memory"
                            }
                            aria-label={status}
                          />
                        </TableCell>
                        <TableCell className="font-medium">{c.container_name}</TableCell>
                        <TableCell className="text-right tabular-nums">{c.cpu_pct}</TableCell>
                        <TableCell className="text-right tabular-nums">{c.mem_mb}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {c.mem_pct != null ? `${c.mem_pct}%` : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{c.pids}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Host memory & load charts */}
      {hostChartData.length > 0 && (
        <div className="mb-8 grid gap-6 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-6">
              <h3 className="mb-3 text-sm font-medium text-muted-foreground">Host memory (GB)</h3>
              <ChartContainer config={hostChartConfig} className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={hostChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
                    <XAxis
                      dataKey="timestamp"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      scale="time"
                      tickFormatter={(ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      tick={{ fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          config={hostChartConfig}
                          formatTime={(ts) => new Date(ts).toLocaleString()}
                        />
                      }
                    />
                    <ChartLegend content={<ChartLegendContent config={hostChartConfig} />} />
                    {["mem_used_gb", "mem_available_gb"].map((key) => (
                      <Line
                        key={key}
                        type="monotone"
                        dataKey={key}
                        stroke={hostChartConfig[key]?.color}
                        strokeWidth={1.5}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </ChartContainer>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <h3 className="mb-3 text-sm font-medium text-muted-foreground">Host load average</h3>
              <ChartContainer config={hostChartConfig} className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={hostChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
                    <XAxis
                      dataKey="timestamp"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      scale="time"
                      tickFormatter={(ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      tick={{ fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          config={hostChartConfig}
                          formatTime={(ts) => new Date(ts).toLocaleString()}
                        />
                      }
                    />
                    <ChartLegend content={<ChartLegendContent config={hostChartConfig} />} />
                    {["load_1", "load_5", "load_15"].map((key) => (
                      <Line
                        key={key}
                        type="monotone"
                        dataKey={key}
                        stroke={hostChartConfig[key]?.color}
                        strokeWidth={1.5}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </ChartContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {hostSeriesLoading && hostChartData.length === 0 && (
        <Skeleton className="mb-8 h-64 w-full rounded-xl" />
      )}

      {/* Container memory & CPU charts */}
      {(containerMemSeries.length > 0 || containerCpuSeries.length > 0) && (
        <div className="mb-8 grid gap-6 lg:grid-cols-2">
          <Card>
            <CardContent className="pt-6">
              <h3 className="mb-3 text-sm font-medium text-muted-foreground">Container memory (MB)</h3>
              <ChartContainer config={containerChartConfig} className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={containerMemSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
                    <XAxis
                      dataKey="timestamp"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      scale="time"
                      tickFormatter={(ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      tick={{ fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          config={containerChartConfig}
                          formatTime={(ts) => new Date(ts).toLocaleString()}
                        />
                      }
                    />
                    <ChartLegend content={<ChartLegendContent config={containerChartConfig} />} />
                    {containerNames.map((name) => (
                      <Line
                        key={name}
                        type="monotone"
                        dataKey={name}
                        stroke={containerChartConfig[name]?.color}
                        strokeWidth={1.5}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </ChartContainer>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <h3 className="mb-3 text-sm font-medium text-muted-foreground">Container CPU %</h3>
              <ChartContainer config={containerChartConfig} className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={containerCpuSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
                    <XAxis
                      dataKey="timestamp"
                      type="number"
                      domain={["dataMin", "dataMax"]}
                      scale="time"
                      tickFormatter={(ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      tick={{ fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} domain={[0, 100]} />
                    <ChartTooltip
                      content={
                        <ChartTooltipContent
                          config={containerChartConfig}
                          formatTime={(ts) => new Date(ts).toLocaleString()}
                        />
                      }
                    />
                    <ChartLegend content={<ChartLegendContent config={containerChartConfig} />} />
                    {containerNames.map((name) => (
                      <Line
                        key={name}
                        type="monotone"
                        dataKey={name}
                        stroke={containerChartConfig[name]?.color}
                        strokeWidth={1.5}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </ChartContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Host (hostname) + Memory/Load/Swap + Disk — same section at bottom */}
      {(host || disk != null) && (
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-muted-foreground">
            Host {host?.hostname ?? ""} · Memory, load, swap, disk
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
            {host && (
              <>
            <TutorialPopover
              title={`Memory Used: ${host.mem_used_gb} GB / Available: ${host.mem_available_gb} GB`}
              meaning="This refers to RAM (Random Access Memory). Your system is actively using RAM to run the operating system and applications."
              status={
                host.mem_available_gb >= 2
                  ? "Good. You have plenty of room before the system slows down."
                  : host.mem_available_gb >= 1
                    ? "Moderate. Consider closing unused apps."
                    : "Low. System may slow down or use swap."
              }
              side="top"
            >
              <Card className="cursor-help">
                <CardContent className="pt-6">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Server className="h-4 w-4" />
                    Memory used
                  </div>
                  <p
                    className={`mt-1 text-2xl font-semibold tabular-nums ${
                      host.mem_used_gb >= 7 ? "text-destructive" : host.mem_used_gb >= 6 ? "text-yellow-600 dark:text-yellow-500" : "text-foreground"
                    }`}
                  >
                    {host.mem_used_gb} GB
                  </p>
                </CardContent>
              </Card>
            </TutorialPopover>
            <TutorialPopover
              title={`Memory Available: ${host.mem_available_gb} GB`}
              meaning="Free RAM available for new applications and cache. Part of total system memory."
              status={
                host.mem_available_gb >= 2
                  ? "Good. Plenty of RAM available."
                  : host.mem_available_gb >= 1
                    ? "Moderate."
                    : "Low. System may use swap."
              }
              side="top"
            >
              <Card className="cursor-help">
                <CardContent className="pt-6">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Server className="h-4 w-4" />
                    Memory available
                  </div>
                  <p
                    className={`mt-1 text-2xl font-semibold tabular-nums ${
                      host.mem_available_gb < 1 ? "text-destructive" : host.mem_available_gb < 2 ? "text-yellow-600 dark:text-yellow-500" : "text-green-600 dark:text-green-500"
                    }`}
                  >
                    {host.mem_available_gb} GB
                  </p>
                </CardContent>
              </Card>
            </TutorialPopover>
            <TutorialPopover
              title={`Load (1m): ${host.load_1}`}
              meaning="The average number of tasks (processes) that are either running on the CPU or waiting to run over the last 1 minute. If the number is less than or equal to the number of CPU cores, the system is not struggling."
              status={
                host.load_1 <= 2
                  ? "Low. System has capacity."
                  : host.load_1 <= 4
                    ? "Moderate. If you have a 2-core processor, this is acceptable."
                    : "High. CPU may be busy."
              }
              side="top"
            >
              <Card className="cursor-help">
                <CardContent className="pt-6">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Activity className="h-4 w-4" />
                    Load (1m)
                  </div>
                  <p
                    className={`mt-1 text-2xl font-semibold tabular-nums ${
                      host.load_1 >= 8 ? "text-destructive" : host.load_1 >= 4 ? "text-yellow-600 dark:text-yellow-500" : "text-foreground"
                    }`}
                  >
                    {host.load_1}
                  </p>
                </CardContent>
              </Card>
            </TutorialPopover>
            <TutorialPopover
              title={`Swap Used: ${host.swap_used_gb} GB`}
              meaning="Swap is a safety net on your hard drive used when RAM is completely full. Data is moved to disk, which is slower than RAM."
              status={
                host.swap_used_gb === 0
                  ? "Excellent. Your computer has enough RAM and is not using slow disk space for memory."
                  : host.swap_used_gb < 0.5
                    ? "Low. System is fine."
                    : "System is using swap; RAM may be under pressure."
              }
              side="top"
            >
              <Card className="cursor-help">
                <CardContent className="pt-6">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Server className="h-4 w-4" />
                    Swap used
                  </div>
                  <p
                    className={`mt-1 text-2xl font-semibold tabular-nums ${
                      host.swap_used_gb >= 1 ? "text-destructive" : host.swap_used_gb >= 0.5 ? "text-yellow-600 dark:text-yellow-500" : "text-foreground"
                    }`}
                  >
                    {host.swap_used_gb} GB
                  </p>
                </CardContent>
              </Card>
            </TutorialPopover>
          </>
          )}
          {disk != null && (
            <TutorialPopover
              title={`Disk: ${disk.used_gb.toFixed(1)} / ${disk.total_gb.toFixed(1)} GB (${disk.used_pct}% used)`}
              meaning="Hard drive space for the root mount. When full, the system cannot write new data."
              status={
                disk.used_pct >= 90
                  ? "Critical. Free space is low."
                  : disk.used_pct >= 80
                    ? "Watch usage."
                    : `${disk.free_gb.toFixed(1)} GB free. Good.`
              }
              side="top"
            >
              <Card className="cursor-help">
                <CardContent className="pt-6">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <HardDrive className="h-4 w-4" />
                    / (root)
                  </div>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">
                    {disk.used_gb.toFixed(1)} / {disk.total_gb.toFixed(1)} GB
                  </p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {disk.used_pct}% used · {disk.free_gb.toFixed(1)} GB free
                  </p>
                  <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className={`h-full rounded-full ${
                        disk.used_pct >= 90 ? "bg-destructive" : disk.used_pct >= 80 ? "bg-yellow-500" : "bg-primary"
                      }`}
                      style={{ width: `${Math.min(100, disk.used_pct)}%` }}
                    />
                  </div>
                </CardContent>
              </Card>
            </TutorialPopover>
          )}
          </div>
        </div>
      )}

      {containersLoading && containers.length === 0 && !host && (
        <Skeleton className="mb-8 h-48 w-full rounded-xl" />
      )}

      {/* Docker container logs — API needs /var/run/docker.sock (see stack docker-compose api service) */}
      <div className="mt-10 border-t border-border/60 pt-8">
        <h2 className="mb-2 flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <ScrollText className="h-4 w-4" />
          Container logs
        </h2>
        <p className="mb-4 text-xs text-muted-foreground">
          Stream stdout/stderr from a container on the Docker host (same names as <code className="text-[11px]">docker ps</code> — from host-stats metrics: latest table and chart series). Containers must still exist when you stream.
        </p>
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[12rem] flex-1">
                <label
                  htmlFor="system-resources-container-logs-select"
                  className="mb-1 block text-xs font-medium text-muted-foreground"
                >
                  Container
                </label>
                <select
                  id="system-resources-container-logs-select"
                  value={logContainer}
                  onChange={(e) => {
                    setLogContainer(e.target.value);
                    setLogError(null);
                  }}
                  disabled={logContainerOptions.length === 0}
                  className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
                >
                  <option value="">
                    {logContainerOptions.length === 0 ? "No containers in metrics" : "Select container…"}
                  </option>
                  {logContainerOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                disabled={!logContainer || logStreaming}
                onClick={() => void startLogStream()}
                className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {logStreaming ? "Streaming…" : "Stream logs"}
              </button>
              <button
                type="button"
                disabled={!logStreaming}
                onClick={stopLogStream}
                className="h-9 rounded-lg border border-border/60 bg-background px-4 text-sm font-medium disabled:opacity-50"
              >
                Stop
              </button>
            </div>
            {logError && (
              <p className="text-sm text-destructive" role="alert">
                {logError}
              </p>
            )}
            <pre
              ref={logPreRef}
              className="max-h-96 min-h-[12rem] overflow-auto rounded-md border border-border/60 bg-muted/30 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all text-foreground"
            >
              {logText || (logStreaming ? "…" : "Output appears here while streaming.")}
            </pre>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
