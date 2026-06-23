import type { ContextMenuItem } from "../components/ContextMenu";
import type { JsonApiDevice, JsonApiPoint } from "../components/JsonApiPointsTree";
import { POLL_OPTIONS } from "./bacnetTreeMenu";

export function pollItemsForPoint(
  point: JsonApiPoint,
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
  point: JsonApiPoint;
  device: JsonApiDevice;
  onRefreshPoint?: (device: JsonApiDevice, point: JsonApiPoint) => void;
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
      id: "copy-url",
      label: "Copy URL",
      onClick: () => args.onCopy?.(point.url),
    },
    {
      id: "delete-pt",
      label: "Remove endpoint",
      danger: true,
      onClick: () => args.onDeletePoint?.(point.point_id),
    },
  ];
}

export function buildDeviceContextMenuItems(args: {
  device: JsonApiDevice;
  onRefreshDevice?: (device: JsonApiDevice) => void;
  onSetDevicePoll?: (device: JsonApiDevice, enabled: boolean, intervalS: number) => void;
  onDeleteDevice?: (device: JsonApiDevice) => void;
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
          label: "Refresh all endpoints",
          onClick: () => args.onRefreshDevice?.(device),
        },
      ],
    },
    { id: "polling", label: "Polling", children: pollChildren },
    {
      id: "copy-host",
      label: "Copy host",
      onClick: () => args.onCopy?.(device.host),
    },
    {
      id: "delete-dev",
      label: "Remove all endpoints on host",
      danger: true,
      onClick: () => args.onDeleteDevice?.(device),
    },
  ];
}
