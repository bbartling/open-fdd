import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useFaultsByEquipment } from "@/hooks/use-faults";

interface FaultsByDeviceChartProps {
  siteId: string | undefined;
  start: string;
  end: string;
}

/** Bar chart: active fault count per device (equipment name + BACnet instance ID when present). */
export function FaultsByDeviceChart({ siteId, start, end }: FaultsByDeviceChartProps) {
  const { data, isLoading, error } = useFaultsByEquipment(siteId ?? undefined, start, end);

  const chartData =
    data?.by_equipment?.map((row) => ({
      name:
        row.bacnet_device_id != null
          ? `${row.equipment_name} (BACnet ${row.bacnet_device_id})`
          : row.equipment_name,
      count: row.active_fault_count,
    })) ?? [];

  if (error) {
    return (
      <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
        <p className="text-sm text-destructive">Failed to load faults by device.</p>
      </div>
    );
  }

  if (isLoading) {
    return <Skeleton className="h-72 w-full rounded-2xl" />;
  }

  if (chartData.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
        <p className="text-sm text-muted-foreground">
          No faults by device in this period. FDD runs write to fault_results; select a range with data.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border/60 bg-card p-5">
      <ResponsiveContainer width="100%" height={340}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ left: 8, right: 24, top: 8, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
          <YAxis
            type="category"
            dataKey="name"
            width={180}
            tick={{ fontSize: 11 }}
            tickFormatter={(v: string) => (v.length > 32 ? v.slice(0, 29) + "…" : v)}
          />
          <Tooltip
            formatter={(value: number | undefined) => [value ?? 0, "Active faults"]}
            labelFormatter={(label) => label}
            contentStyle={{ fontSize: 12 }}
          />
          <Bar dataKey="count" fill="hsl(215, 60%, 42%)" radius={[0, 4, 4, 0]} name="Active faults" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
