import type { ContextMenuItem } from "../components/ContextMenu";
import type { NiagaraDevice, NiagaraPoint } from "./niagara-api";

export function formatNiagaraValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

export function preserveNiagaraOrd(ord: string): string {
  return String(ord ?? "");
}

export function buildPointContextMenuItems(args: {
  point: NiagaraPoint;
  device: NiagaraDevice;
  onRefreshPoint?: (device: NiagaraDevice, point: NiagaraPoint) => void;
  onCopy?: (text: string) => void;
}): ContextMenuItem[] {
  const { point, device } = args;
  return [
    {
      id: "actions",
      label: "Actions",
      children: [
        {
          id: "refresh-value",
          label: "Read value now",
          onClick: () => args.onRefreshPoint?.(device, point),
        },
      ],
    },
    {
      id: "copy-ord",
      label: "Copy ORD",
      onClick: () => args.onCopy?.(preserveNiagaraOrd(point.point_ord)),
    },
    {
      id: "copy-name",
      label: "Copy point name",
      onClick: () => args.onCopy?.(point.point_name),
    },
  ];
}

export function buildDeviceContextMenuItems(args: {
  device: NiagaraDevice;
  onRefreshDevice?: (device: NiagaraDevice) => void;
  onDiscover?: (device: NiagaraDevice) => void;
  onCopy?: (text: string) => void;
}): ContextMenuItem[] {
  const { device } = args;
  return [
    {
      id: "actions",
      label: "Actions",
      children: [
        {
          id: "refresh-dev",
          label: "Read all discovered points",
          onClick: () => args.onRefreshDevice?.(device),
        },
        {
          id: "discover",
          label: "Discover points",
          onClick: () => args.onDiscover?.(device),
        },
      ],
    },
    {
      id: "copy-url",
      label: "Copy station URL",
      onClick: () => args.onCopy?.(device.station_url),
    },
    {
      id: "copy-id",
      label: "Copy station id",
      onClick: () => args.onCopy?.(device.station_id),
    },
  ];
}
