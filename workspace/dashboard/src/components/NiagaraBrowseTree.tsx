import { useMemo, useState } from "react";
import ContextMenu from "./ContextMenu";
import type { ContextMenuItem } from "./ContextMenu";
import type { NiagaraCommissionProfile, NiagaraBuilding } from "../lib/niagaraCommissionProfile";
import type { NiagaraTreeNode } from "../lib/niagara-api";

type Props = {
  nodes: NiagaraTreeNode[];
  profile: NiagaraCommissionProfile;
  onAddBuilding: (node: NiagaraTreeNode) => void;
  onAddDevice: (node: NiagaraTreeNode, buildingId: string) => void;
  onSetPointsRoot: (ord: string) => void;
  onDiscoverUnder: (ord: string) => void;
  onCopy?: (text: string) => void;
};

type MenuTarget = { node: NiagaraTreeNode } | null;

function isInfrastructureNode(node: NiagaraTreeNode): boolean {
  const name = (node.name || "").toLowerCase();
  const ord = node.ord.toLowerCase();
  if (/\/points\//i.test(ord)) return false;
  if (name.includes("comm") || name.includes("worker") || name.includes("handler")) return true;
  if (name === "client" || name === "server" || name === "transport" || name === "network") return true;
  if (name.includes("policy") || name.includes("monitor") || name.includes("export table")) return true;
  return false;
}

export default function NiagaraBrowseTree({
  nodes,
  profile,
  onAddBuilding,
  onAddDevice,
  onSetPointsRoot,
  onDiscoverUnder,
  onCopy,
}: Props) {
  const [menu, setMenu] = useState<{ x: number; y: number; target: MenuTarget } | null>(null);

  const sorted = useMemo(
    () => [...nodes].sort((a, b) => a.ord.localeCompare(b.ord)),
    [nodes],
  );

  const buildingForOrd = (ord: string): NiagaraBuilding | undefined =>
    profile.buildings.find((b) => ord === b.folder_ord || ord.startsWith(`${b.folder_ord}/`));

  const menuItems: ContextMenuItem[] = useMemo(() => {
    if (!menu?.target) return [];
    const { node } = menu.target;
    const inBuilding = buildingForOrd(node.ord);
    const isBuilding = profile.buildings.some((b) => b.folder_ord === node.ord);
    const isDevice = profile.devices.some((d) => d.folder_ord === node.ord);
    const infra = isInfrastructureNode(node);
    const items: ContextMenuItem[] = [];

    if (!infra && !isBuilding) {
      items.push({
        id: "add-building",
        label: "Add folder as building",
        onClick: () => onAddBuilding(node),
      });
    }
    if (!infra && !isDevice && profile.buildings.length > 0) {
      const buildingChildren: ContextMenuItem[] = profile.buildings.map((b) => ({
        id: `add-dev-${b.id}`,
        label: `Add as device in ${b.label}`,
        onClick: () => onAddDevice(node, b.id),
      }));
      items.push({ id: "add-device", label: "Add folder as device", children: buildingChildren });
    }
    items.push(
      { id: "set-root", label: "Set as points root", onClick: () => onSetPointsRoot(node.ord) },
      { id: "discover", label: "Discover under this folder", onClick: () => onDiscoverUnder(node.ord) },
      { id: "copy-ord", label: "Copy ORD", onClick: () => onCopy?.(node.ord) },
    );
    if (inBuilding) {
      items.push({
        id: "hint",
        label: `Inside building: ${inBuilding.label}`,
        disabled: true,
        onClick: () => undefined,
      });
    }
    return items;
  }, [menu, onAddBuilding, onAddDevice, onCopy, onDiscoverUnder, onSetPointsRoot, profile.buildings, profile.devices]);

  if (!sorted.length) {
    return <p className="muted">Browse the station tree to map buildings and devices.</p>;
  }

  return (
    <div className="niagara-browse-tree bacnet-tree">
      {sorted.map((node) => {
        const pad = Math.min(6, Math.max(0, node.indent || 0)) * 0.75;
        const isBuilding = profile.buildings.some((b) => b.folder_ord === node.ord);
        const isDevice = profile.devices.some((d) => d.folder_ord === node.ord);
        return (
          <button
            key={node.ord}
            type="button"
            className={`niagara-browse-row bacnet-tree-type-head${isBuilding ? " niagara-browse-building" : ""}${isDevice ? " niagara-browse-device" : ""}`}
            style={{ paddingLeft: `${0.5 + pad}rem` }}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu({ x: e.clientX, y: e.clientY, target: { node } });
            }}
            onClick={() => onSetPointsRoot(node.ord)}
            title="Left-click: set points root · Right-click: add building/device"
          >
            <span className="bacnet-tree-type-label">
              {isBuilding ? "🏢 " : isDevice ? "⚙️ " : "📁 "}
              <code>{node.ord}</code>
            </span>
            <span className="muted"> — {node.name || node.type}</span>
            {isBuilding ? <span className="badge">building</span> : null}
            {isDevice ? <span className="badge poll-badge">device</span> : null}
          </button>
        );
      })}
      {menu ? (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={() => setMenu(null)} />
      ) : null}
    </div>
  );
}
