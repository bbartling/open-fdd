import { useMemo, useState, useCallback } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import type { Point, Equipment, Site } from "@/types/api";
import { parseUtcTimestamp } from "@/lib/utils";
import { Circle, CircleDot, ChevronRight, ChevronDown, Server, Box, CircleDotIcon, Radio, CircleOff } from "lucide-react";

/** Format ts for display (API timestamps are UTC; we show relative time). */
function formatLastUpdated(ts: string | null): string {
  if (!ts) return "—";
  const d = parseUtcTimestamp(ts) ?? new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffM = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMs / 3600000);
  const diffD = Math.floor(diffMs / 86400000);
  if (diffM < 1) return "just now";
  if (diffM < 60) return `${diffM}m ago`;
  if (diffH < 24) return `${diffH}h ago`;
  if (diffD < 7) return `${diffD}d ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

type TreeNode =
  | { type: "site"; id: string; name: string; children: TreeNode[] }
  | { type: "equipment"; id: string; name: string; equipment_type: string | null; children: TreeNode[] }
  | { type: "unassigned"; id: string; name: string; children: TreeNode[] }
  | { type: "point"; point: Point };

function buildTree(
  points: Point[],
  equipment: Equipment[],
  siteMap: Map<string, Site> | undefined,
): TreeNode[] {
  const equipBySite = new Map<string, Equipment[]>();
  equipment.forEach((e) => {
    const list = equipBySite.get(e.site_id) ?? [];
    list.push(e);
    equipBySite.set(e.site_id, list);
  });

  if (siteMap && siteMap.size > 0) {
    const siteIds = Array.from(new Set(points.map((p) => p.site_id)));
    return siteIds.map((siteId) => {
      const siteName = siteMap.get(siteId)?.name ?? siteId.slice(0, 8);
      const siteEquip = equipBySite.get(siteId) ?? [];
      const sitePoints = points.filter((p) => p.site_id === siteId);
      const assignedPoints = sitePoints.filter((p) => p.equipment_id != null);
      const unassignedPoints = sitePoints.filter((p) => p.equipment_id == null);

      const equipmentNodes: TreeNode[] = siteEquip.map((eq) => ({
        type: "equipment" as const,
        id: eq.id,
        name: eq.name,
        equipment_type: eq.equipment_type,
        children: assignedPoints
          .filter((p) => p.equipment_id === eq.id)
          .map((p) => ({ type: "point" as const, point: p })),
      }));

      const unassignedNode: TreeNode =
        unassignedPoints.length > 0
          ? {
              type: "unassigned",
              id: `unassigned-${siteId}`,
              name: "Unassigned",
              children: unassignedPoints.map((p) => ({ type: "point" as const, point: p })),
            }
          : { type: "unassigned", id: `unassigned-${siteId}`, name: "Unassigned", children: [] };

      return {
        type: "site",
        id: siteId,
        name: siteName,
        children: [...equipmentNodes, unassignedNode].filter((n) => ("children" in n) && (n.children.length > 0 || n.type === "unassigned")),
      };
    });
  }

  const equipmentNodes: TreeNode[] = equipment.map((eq) => ({
    type: "equipment" as const,
    id: eq.id,
    name: eq.name,
    equipment_type: eq.equipment_type,
    children: points
      .filter((p) => p.equipment_id === eq.id)
      .map((p) => ({ type: "point" as const, point: p })),
  }));
  const unassignedPoints = points.filter((p) => p.equipment_id == null);
  const unassignedNode: TreeNode = {
    type: "unassigned",
    id: "unassigned",
    name: "Unassigned",
    children: unassignedPoints.map((p) => ({ type: "point" as const, point: p })),
  };
  return [...equipmentNodes, unassignedNode];
}

export interface PointsTreeProps {
  points: Point[];
  equipment: Equipment[];
  siteMap?: Map<string, Site>;
  latestByPointId?: Map<string, { value: number; ts: string | null }>;
  onDeletePoint?: (pointId: string) => void;
  onDeleteEquipment?: (equipmentId: string, name: string) => void;
  onDeleteSite?: (siteId: string, name: string) => void;
  /** Set polling for this point (true = BACnet scraper includes it). Shown as "Poll true" / "Poll false" on right-click. */
  onSetPolling?: (pointId: string, polling: boolean) => void;
}

/** Test IDs for point context menu (E2E and unit tests). */
export const POINTS_CONTEXT_MENU_TEST_IDS = {
  POLL_TRUE: "points-context-menu-poll-true",
  POLL_FALSE: "points-context-menu-poll-false",
  DELETE_POINT: "points-context-menu-delete-point",
  DELETE_EQUIPMENT: "points-context-menu-delete-equipment",
  DELETE_SITE: "points-context-menu-delete-site",
} as const;

type ContextMenuState = { x: number; y: number; type: "point"; id: string; name: string } | { x: number; y: number; type: "equipment"; id: string; name: string } | { x: number; y: number; type: "site"; id: string; name: string } | null;

export function PointsTree({
  points,
  equipment,
  siteMap,
  latestByPointId,
  onDeletePoint,
  onDeleteEquipment,
  onDeleteSite,
  onSetPolling,
}: PointsTreeProps) {
  const tree = useMemo(
    () => buildTree(points, equipment, siteMap),
    [points, equipment, siteMap],
  );

  const [openIds, setOpenIds] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    tree.forEach((node) => {
      if (node.type !== "point" && node.children.length > 0) initial.add(node.id);
    });
    return initial;
  });
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);

  const toggle = useCallback((id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, type: "point" | "equipment" | "site", id: string, name: string) => {
      e.preventDefault();
      if (
        (type === "point" && (onDeletePoint || onSetPolling)) ||
        (type === "equipment" && onDeleteEquipment) ||
        (type === "site" && onDeleteSite)
      ) {
        setContextMenu({ x: e.clientX, y: e.clientY, type, id, name });
      }
    },
    [onDeletePoint, onDeleteEquipment, onDeleteSite, onSetPolling],
  );

  if (points.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-sm text-muted-foreground">
          No points configured{siteMap ? " across any site" : " for this site"}.
        </p>
      </div>
    );
  }

  const hasSites = siteMap != null && siteMap.size > 0;

  return (
    <div className="relative rounded-lg border border-border/60">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40 hover:bg-muted/40">
            <TableHead className="w-[28px]" aria-hidden />
            <TableHead className="min-w-[200px]">Name</TableHead>
            {hasSites && <TableHead className="w-[120px]">Site</TableHead>}
            <TableHead className="min-w-[140px]">Brick Type</TableHead>
            <TableHead className="w-[100px]">FDD Input</TableHead>
            <TableHead className="w-[70px]">Unit</TableHead>
            <TableHead className="w-[90px]">Polling</TableHead>
            <TableHead className="min-w-[100px]">Last value</TableHead>
            <TableHead className="w-[120px]">Last updated</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tree.map((node) => (
            <TreeRows
              key={node.type === "point" ? node.point.id : node.id}
              node={node}
              depth={0}
              openIds={openIds}
              onToggle={toggle}
              latestByPointId={latestByPointId}
              hasSites={hasSites}
              siteName={node.type === "site" ? node.name : undefined}
              onContextMenu={handleContextMenu}
            />
          ))}
        </TableBody>
      </Table>
      {contextMenu && (
        <>
          <div
            className="fixed inset-0 z-40"
            aria-hidden
            onClick={() => setContextMenu(null)}
            onContextMenu={(e) => { e.preventDefault(); setContextMenu(null); }}
          />
          <div
            className="fixed z-50 min-w-[160px] rounded-lg border border-border/60 bg-card py-1 shadow-lg"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            {contextMenu.type === "point" && onSetPolling && (
              <>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
                  data-testid={POINTS_CONTEXT_MENU_TEST_IDS.POLL_TRUE}
                  onClick={() => {
                    onSetPolling(contextMenu.id, true);
                    setContextMenu(null);
                  }}
                >
                  <Radio className="h-4 w-4 text-muted-foreground" />
                  Poll true
                </button>
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
                  data-testid={POINTS_CONTEXT_MENU_TEST_IDS.POLL_FALSE}
                  onClick={() => {
                    onSetPolling(contextMenu.id, false);
                    setContextMenu(null);
                  }}
                >
                  <CircleOff className="h-4 w-4 text-muted-foreground" />
                  Poll false
                </button>
              </>
            )}
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10"
              data-testid={
                contextMenu.type === "point"
                  ? POINTS_CONTEXT_MENU_TEST_IDS.DELETE_POINT
                  : contextMenu.type === "equipment"
                    ? POINTS_CONTEXT_MENU_TEST_IDS.DELETE_EQUIPMENT
                    : POINTS_CONTEXT_MENU_TEST_IDS.DELETE_SITE
              }
              onClick={() => {
                if (contextMenu.type === "point" && onDeletePoint) onDeletePoint(contextMenu.id);
                if (contextMenu.type === "equipment" && onDeleteEquipment) onDeleteEquipment(contextMenu.id, contextMenu.name);
                if (contextMenu.type === "site" && onDeleteSite) onDeleteSite(contextMenu.id, contextMenu.name);
                setContextMenu(null);
              }}
            >
              Delete {contextMenu.type === "point" ? "point" : contextMenu.type === "equipment" ? "equipment" : "site"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function TreeRows({
  node,
  depth,
  openIds,
  onToggle,
  latestByPointId,
  hasSites,
  siteName,
  onContextMenu,
}: {
  node: TreeNode;
  depth: number;
  openIds: Set<string>;
  onToggle: (id: string) => void;
  latestByPointId?: Map<string, { value: number; ts: string | null }>;
  hasSites: boolean;
  siteName?: string;
  onContextMenu?: (e: React.MouseEvent, type: "point" | "equipment" | "site", id: string, name: string) => void;
}) {
  const indent = depth * 20;
  const hasChildren = node.type !== "point" && node.children.length > 0;
  const isOpen = hasChildren && openIds.has(node.id);

  if (node.type === "point") {
    const p = node.point;
    const latest = latestByPointId?.get(p.id);
    return (
      <TableRow
        key={p.id}
        className="border-border/40"
        onContextMenu={onContextMenu ? (e) => onContextMenu(e, "point", p.id, p.external_id) : undefined}
      >
        <TableCell className="w-[28px]" style={{ paddingLeft: 12 + indent }} />
        <TableCell className="font-mono text-xs" style={{ paddingLeft: indent }}>
          {p.external_id}
        </TableCell>
        {hasSites && (
          <TableCell className="text-muted-foreground text-xs">
            {siteName ?? "—"}
          </TableCell>
        )}
        <TableCell className="text-muted-foreground text-xs">{p.brick_type ?? "—"}</TableCell>
        <TableCell className="text-muted-foreground text-xs">{p.fdd_input ?? "—"}</TableCell>
        <TableCell className="text-muted-foreground text-xs">{p.unit ?? "—"}</TableCell>
        <TableCell>
          {p.polling ? (
            <span title="BACnet scraper polls this point">
              <CircleDot className="h-4 w-4 text-primary" />
            </span>
          ) : (
            <span title="Not polled">
              <Circle className="h-4 w-4 text-muted-foreground" />
            </span>
          )}
        </TableCell>
        <TableCell className="tabular-nums text-muted-foreground text-xs">
          {p.polling && latest != null ? (
            <span title={latest.ts ? (parseUtcTimestamp(latest.ts) ?? new Date(latest.ts)).toLocaleString() : undefined}>
              {latest.value.toLocaleString(undefined, { maximumFractionDigits: 4 })}
              {p.unit ? ` ${p.unit}` : ""}
            </span>
          ) : (
            "—"
          )}
        </TableCell>
        <TableCell className="text-muted-foreground text-xs">
          {p.polling && latest != null && latest.ts ? formatLastUpdated(latest.ts) : "—"}
        </TableCell>
      </TableRow>
    );
  }

  const label =
    node.type === "site"
      ? node.name
      : node.type === "unassigned"
        ? node.name
        : node.name;
  const count = node.children.length;
  const Icon =
    node.type === "site"
      ? Server
      : node.type === "equipment"
        ? Box
        : CircleDotIcon;

  const canDelete = node.type !== "unassigned" && (
    (node.type === "site" && onContextMenu) ||
    (node.type === "equipment" && onContextMenu)
  );
  return (
    <>
      <TableRow
        className="cursor-pointer border-border/40 bg-muted/20 hover:bg-muted/40"
        onClick={() => hasChildren && onToggle(node.id)}
        onContextMenu={canDelete ? (e) => onContextMenu!(e, node.type as "site" | "equipment", node.id, node.name) : undefined}
      >
        <TableCell className="w-[28px] py-1.5" style={{ paddingLeft: 12 + indent }}>
          {hasChildren ? (
            <button
              type="button"
              className="inline-flex items-center justify-center rounded p-0.5 hover:bg-muted"
              aria-expanded={isOpen}
              onClick={(e) => {
                e.stopPropagation();
                onToggle(node.id);
              }}
            >
              {isOpen ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
          ) : null}
        </TableCell>
        <TableCell style={{ paddingLeft: hasChildren ? 0 : indent }} className="py-1.5">
          <span className="inline-flex items-center gap-2 font-medium">
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
            {label}
            {node.type === "equipment" && node.equipment_type && (
              <span className="rounded border border-border/60 bg-background px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground">
                {node.equipment_type}
              </span>
            )}
            {count > 0 && (
              <span className="text-muted-foreground text-xs tabular-nums">
                ({count})
              </span>
            )}
          </span>
        </TableCell>
        <TableCell colSpan={hasSites ? 7 : 6} />
      </TableRow>
      {isOpen &&
        node.children.map((child) => (
          <TreeRows
            key={child.type === "point" ? child.point.id : child.id}
            node={child}
            depth={depth + 1}
            openIds={openIds}
            onToggle={onToggle}
            latestByPointId={latestByPointId}
            hasSites={hasSites}
            siteName={siteName ?? (node.type === "site" ? node.name : undefined)}
            onContextMenu={onContextMenu}
          />
        ))}
    </>
  );
}
