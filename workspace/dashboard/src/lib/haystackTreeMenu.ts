import type { ContextMenuItem } from "../components/ContextMenu";
import type { HaystackDevice, HaystackPoint } from "../components/HaystackPointsTree";
import { POLL_OPTIONS } from "./pollIntervals";

export function pollItemsForPoint(
  point: HaystackPoint,
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
  point: HaystackPoint;
  device: HaystackDevice;
  onRefreshPoint?: (device: HaystackDevice, point: HaystackPoint) => void;
  onReadTags?: (point: HaystackPoint) => void;
  onMapEquipment?: (point: HaystackPoint) => void;
  onSetPointPoll?: (pointId: string, enabled: boolean, intervalS: number) => void;
  onDeletePoint?: (pointId: string) => void;
  onCopy?: (text: string) => void;
}): ContextMenuItem[] {
  const { point } = args;
  return [
    {
      id: "actions",
      label: "Actions",
      children: [
        { id: "refresh-point", label: "Refresh point value", onClick: () => args.onRefreshPoint?.(args.device, point) },
        { id: "read-tags", label: "Read tags", onClick: () => args.onReadTags?.(point) },
        { id: "map-equip", label: "Map to equipment", onClick: () => args.onMapEquipment?.(point) },
      ],
    },
    { id: "polling", label: "Polling", children: pollItemsForPoint(point, args.onSetPointPoll) },
    { id: "copy-id", label: "Copy Haystack id", onClick: () => args.onCopy?.(point.haystack_id) },
    { id: "copy-tags", label: "Copy tags", onClick: () => args.onCopy?.(JSON.stringify(point.tags ?? {}, null, 2)) },
    { id: "delete-pt", label: "Remove point mapping", danger: true, onClick: () => args.onDeletePoint?.(point.point_id) },
  ];
}

export function buildDeviceContextMenuItems(args: {
  device: HaystackDevice;
  onRefreshSite?: (device: HaystackDevice) => void;
  onSetDevicePoll?: (device: HaystackDevice, enabled: boolean, intervalS: number) => void;
  onDeleteDevice?: (device: HaystackDevice) => void;
  onCopy?: (text: string) => void;
}): ContextMenuItem[] {
  const pollChildren = POLL_OPTIONS.map((opt) => ({
    id: `dev-poll-${opt.seconds}`,
    label: `Poll all — ${opt.label}`,
    onClick: () => args.onSetDevicePoll?.(args.device, true, opt.seconds),
  }));
  return [
    {
      id: "actions",
      label: "Actions",
      children: [{ id: "refresh-site", label: "Refresh site/nav", onClick: () => args.onRefreshSite?.(args.device) }],
    },
    { id: "polling", label: "Polling", children: pollChildren },
    { id: "copy-site", label: "Copy site id", onClick: () => args.onCopy?.(args.device.site_id) },
    {
      id: "delete-dev",
      label: "Remove equip mapping",
      danger: true,
      onClick: () => args.onDeleteDevice?.(args.device),
    },
  ];
}
