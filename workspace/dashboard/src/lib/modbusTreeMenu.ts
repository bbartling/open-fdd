import type { ContextMenuItem } from "../components/ContextMenu";
import type { ModbusDevice, ModbusPoint } from "../components/ModbusPointsTree";
import { POLL_OPTIONS } from "./bacnetTreeMenu";

export function formatModbusValue(value: unknown): string {
  if (value == null) return "—";
  return String(value);
}

export function pollItemsForPoint(
  point: ModbusPoint,
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
  point: ModbusPoint;
  device: ModbusDevice;
  onRefreshPoint?: (device: ModbusDevice, point: ModbusPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
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
          label: "Refresh value",
          onClick: () => args.onRefreshPoint?.(device, point),
        },
      ],
    },
    {
      id: "polling",
      label: "Polling",
      children: pollItemsForPoint(point, args.onSetPointPoll),
    },
    {
      id: "copy-id",
      label: "Copy point id",
      onClick: () => args.onCopy?.(point.point_id),
    },
    {
      id: "delete-pt",
      label: "Remove register",
      danger: true,
      onClick: () => args.onDeletePoint?.(point.point_id),
    },
  ];
}

export function buildDeviceContextMenuItems(args: {
  device: ModbusDevice;
  onRefreshDevice?: (device: ModbusDevice) => void;
  onSetDevicePoll?: (device: ModbusDevice, enabled: boolean, intervalS: number) => void;
  onDeleteDevice?: (device: ModbusDevice) => void;
  onCopy?: (text: string) => void;
}): ContextMenuItem[] {
  const { device } = args;
  const pollChildren = POLL_OPTIONS.map((opt) => ({
    id: `dev-poll-${opt.seconds}`,
    label: `Poll all — ${opt.label}`,
    onClick: () => args.onSetDevicePoll?.(device, true, opt.seconds),
  }));
  if (device.poll_count > 0) {
    pollChildren.push({
      id: "dev-poll-off",
      label: "Stop polling all",
      onClick: () => args.onSetDevicePoll?.(device, false, 0),
    });
  }
  return [
    {
      id: "actions",
      label: "Actions",
      children: [
        {
          id: "refresh-dev",
          label: "Refresh all registers",
          onClick: () => args.onRefreshDevice?.(device),
        },
      ],
    },
    { id: "polling", label: "Polling", children: pollChildren },
    {
      id: "copy-dev",
      label: "Copy connection",
      onClick: () => args.onCopy?.(`${device.host}:${device.port} unit ${device.unit_id}`),
    },
    {
      id: "delete-dev",
      label: "Remove all registers on connection",
      danger: true,
      onClick: () => args.onDeleteDevice?.(device),
    },
  ];
}
