import { useHealth } from "@/hooks/use-fdd-status";
import { useBacnetStatus } from "@/hooks/use-bacnet-status";
import { cn } from "@/lib/utils";

type Status = "green" | "yellow" | "red" | "gray";

function StatusDot({ status, label, title }: { status: Status; label: string; title?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        status === "green" && "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
        status === "yellow" && "bg-amber-500/15 text-amber-700 dark:text-amber-400",
        status === "red" && "bg-red-500/15 text-red-700 dark:text-red-400",
        status === "gray" && "bg-muted text-muted-foreground",
      )}
      title={title ?? label}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          status === "green" && "bg-emerald-500",
          status === "yellow" && "bg-amber-500",
          status === "red" && "bg-red-500",
          status === "gray" && "bg-muted-foreground",
        )}
        aria-hidden
      />
      {label}
    </span>
  );
}

export function StackStatusStrip() {
  const { data: health, isError: healthError, isLoading: healthLoading } = useHealth();
  const { data: bacnet, isError: bacnetError, isLoading: bacnetLoading } = useBacnetStatus();

  const apiStatus: Status = healthLoading ? "gray" : healthError || health?.status !== "ok" ? "red" : "green";
  const result = bacnet?.body?.result;
  const mqtt = result?.mqtt_bridge;
  const bacnetStatus: Status = bacnetLoading
    ? "gray"
    : bacnetError || !bacnet?.ok
      ? "red"
      : "green";
  const mqttStatus: Status =
    !mqtt ? "gray" : mqtt.enabled && mqtt.connected ? "green" : mqtt.enabled ? "yellow" : "gray";

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border/40 bg-muted/20 px-6 py-2 text-sm">
      <span className="mr-1 text-muted-foreground">Stack:</span>
      <StatusDot
        status={apiStatus}
        label="API"
        title={apiStatus === "green" ? "API healthy" : apiStatus === "red" ? "API unreachable" : "Checking…"}
      />
      <StatusDot
        status={bacnetStatus}
        label="BACnet"
        title={
          bacnetStatus === "green"
            ? "BACnet gateway OK"
            : bacnetStatus === "red"
              ? "BACnet gateway unreachable"
              : "Checking…"
        }
      />
      <StatusDot
        status={mqttStatus}
        label="MQTT bridge"
        title={
          mqttStatus === "green"
            ? mqtt?.broker_url
              ? `Connected to ${mqtt.broker_url}`
              : "Connected"
            : mqttStatus === "yellow"
              ? mqtt?.last_error
                ? `Disconnected: ${mqtt.last_error}`
                : "Enabled but disconnected"
              : "Not enabled or no bridge"
        }
      />
    </div>
  );
}
