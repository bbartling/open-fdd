import type { ContextMenuItem } from "../components/ContextMenu";
import type { DriverDevice, DriverPoint } from "../components/BacnetPointsTree";

/** BACnet object types that expose a priority array (matches bacnet_toolshed COMMANDABLE_TYPES). */
export const COMMANDABLE_OBJECT_TYPES = new Set([
  "analog-output",
  "analog-value",
  "binary-output",
  "binary-value",
  "multi-state-output",
  "multi-state-value",
  "integer-value",
  "large-analog-value",
  "positive-integer-value",
]);

export function pointIsCommandable(point: DriverPoint): boolean {
  if (point.commandable) return true;
  const type = point.object_identifier.split(",", 1)[0]?.trim().toLowerCase() ?? "";
  return COMMANDABLE_OBJECT_TYPES.has(type);
}

import { POLL_OPTIONS } from "./pollIntervals";

export { POLL_OPTIONS };

export type PrioritySlot = {
  priority_level: number;
  type: string;
  value: unknown;
};

export function formatBacnetValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function pollItemsForPoint(
  point: DriverPoint,
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void,
): ContextMenuItem[] {
  const items: ContextMenuItem[] = POLL_OPTIONS.map((opt) => ({
    id: `poll-${opt.seconds}`,
    label: `Poll every ${opt.label}`,
    onClick: () => onSetPointPoll?.(point.point_id, true, opt.seconds),
  }));
  if (point.enabled) {
    items.push({
      id: "poll-off",
      label: "Stop polling",
      onClick: () => onSetPointPoll?.(point.point_id, false, 0),
    });
  }
  return items;
}

export function buildPointContextMenuItems(args: {
  point: DriverPoint;
  onRefreshPointPv?: (device: DriverDevice, point: DriverPoint) => void;
  onReadPriorityArray?: (device: DriverDevice, point: DriverPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
  onCopy?: (text: string) => void;
  device: DriverDevice;
}): ContextMenuItem[] {
  const { point, device } = args;
  return [
    {
      id: "actions",
      label: "Actions",
      children: [
        {
          id: "refresh-pv",
          label: "Refresh present value",
          onClick: () => args.onRefreshPointPv?.(device, point),
        },
        {
          id: "read-priority-array",
          label: "Read priority array",
          disabled: !pointIsCommandable(point),
          onClick: () => args.onReadPriorityArray?.(device, point),
        },
      ],
    },
    {
      id: "polling",
      label: "Polling",
      children: pollItemsForPoint(point, args.onSetPointPoll),
    },
    {
      id: "copy-oid",
      label: "Copy object id",
      onClick: () => args.onCopy?.(point.object_identifier),
    },
    {
      id: "delete-pt",
      label: "Remove point",
      danger: true,
      onClick: () => args.onDeletePoint?.(point.point_id),
    },
  ];
}

export function buildDeviceContextMenuItems(args: {
  device: DriverDevice;
  onRefreshDevice?: (instance: number) => void;
  onRemapDevice?: (device: DriverDevice) => void;
  onSetDevicePoll?: (instance: number, enabled: boolean, intervalS: number) => void;
  onDeleteDevice?: (instance: number) => void;
  onCopy?: (text: string) => void;
}): ContextMenuItem[] {
  const { device } = args;
  const inst = Number(device.device_instance);
  const pollChildren: ContextMenuItem[] = POLL_OPTIONS.map((opt) => ({
    id: `dev-poll-${opt.seconds}`,
    label: `Poll all — ${opt.label}`,
    disabled: device.point_count === 0,
    onClick: () => args.onSetDevicePoll?.(inst, true, opt.seconds),
  }));
  pollChildren.push({
    id: "poll-off-all",
    label: "Stop polling (all points)",
    disabled: device.poll_count === 0,
    onClick: () => args.onSetDevicePoll?.(inst, false, 0),
  });
  return [
    {
      id: "refresh",
      label: "Refresh points from device",
      onClick: () => args.onRefreshDevice?.(inst),
    },
    {
      id: "remap",
      label: "Edit instance / address…",
      onClick: () => args.onRemapDevice?.(device),
    },
    {
      id: "polling",
      label: "Polling",
      children: pollChildren,
    },
    {
      id: "copy-inst",
      label: "Copy device instance",
      onClick: () => args.onCopy?.(device.device_instance),
    },
    {
      id: "delete-dev",
      label: "Remove device",
      danger: true,
      onClick: () => args.onDeleteDevice?.(inst),
    },
  ];
}
