import { useMemo, useState } from "react";
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
import { HardDrive, Server, Activity } from "lucide-react";

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
  const containers = containersData?.containers ?? [];
  const disks = diskData?.disks ?? [];
  const disk = disks.length ? primaryDisk(disks) : null;

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
          <Card>
            <CardContent className="pt-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Container</TableHead>
                    <TableHead className="text-right">CPU %</TableHead>
                    <TableHead className="text-right">Mem (MB)</TableHead>
                    <TableHead className="text-right">Mem %</TableHead>
                    <TableHead className="text-right">PIDs</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {containers.map((c) => (
                    <TableRow key={c.container_name}>
                      <TableCell className="font-medium">{c.container_name}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.cpu_pct}</TableCell>
                      <TableCell className="text-right tabular-nums">{c.mem_mb}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {c.mem_pct != null ? `${c.mem_pct}%` : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{c.pids}</TableCell>
                    </TableRow>
                  ))}
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
        <Skeleton className="h-48 w-full rounded-xl" />
      )}
    </div>
  );
}
