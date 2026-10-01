import {
  inventoryRecordKey,
  type InventoryDeviceRecord,
  type InventoryGroupRecord,
  type InventoryPointRecord,
  type InventoryRecord,
} from "../api/inventoryApi";

export type InventoryTreeRecord = InventoryDeviceRecord | InventoryGroupRecord | InventoryPointRecord;

export interface InventoryTreeNode {
  key: string;
  kind: InventoryTreeRecord["kind"];
  record: InventoryTreeRecord;
  children: InventoryTreeNode[];
  parentKey: string | null;
}

export interface InventoryTreeModel {
  roots: InventoryTreeNode[];
  orphanGroups: InventoryTreeNode[];
  orphanPoints: InventoryTreeNode[];
  nodes: Map<string, InventoryTreeNode>;
  parents: Map<string, string | null>;
}

export class InventoryTreeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InventoryTreeError";
  }
}

function nodeFor(record: InventoryTreeRecord): InventoryTreeNode {
  return {
    key: inventoryRecordKey(record),
    kind: record.kind,
    record,
    children: [],
    parentKey: null,
  };
}

/**
 * Assemble typed records after pagination. Parent ids are the only relation;
 * labels, protocol names, and id text never determine the tree hierarchy.
 * Missing parents remain explicit orphans so a partial page cannot look whole.
 */
export function buildInventoryTree(records: readonly InventoryRecord[]): InventoryTreeModel {
  const nodes = new Map<string, InventoryTreeNode>();
  for (const record of records) {
    const node = nodeFor(record);
    if (nodes.has(node.key)) throw new InventoryTreeError(`duplicate inventory record ${node.key}`);
    nodes.set(node.key, node);
  }

  const roots: InventoryTreeNode[] = [];
  const orphanGroups: InventoryTreeNode[] = [];
  const orphanPoints: InventoryTreeNode[] = [];
  const parents = new Map<string, string | null>();
  for (const node of nodes.values()) {
    if (node.kind === "device") {
      roots.push(node);
      parents.set(node.key, null);
      continue;
    }
    if (node.kind === "group") {
      const group = node.record as InventoryGroupRecord;
      const parent = nodes.get(`device:${group.device_id}`);
      if (!parent || parent.kind !== "device") {
        orphanGroups.push(node);
        parents.set(node.key, null);
        continue;
      }
      node.parentKey = parent.key;
      parent.children.push(node);
      parents.set(node.key, parent.key);
      continue;
    }
    const point = node.record as InventoryPointRecord;
    const device = nodes.get(`device:${point.device_id}`);
    const group = point.group_id ? nodes.get(`group:${point.group_id}`) : undefined;
    const groupMatches = group?.kind === "group" && group.record.device_id === point.device_id;
    if (!device || device.kind !== "device" || (point.group_id && !groupMatches)) {
      orphanPoints.push(node);
      parents.set(node.key, null);
      continue;
    }
    const parent = groupMatches ? group : device;
    node.parentKey = parent.key;
    parent.children.push(node);
    parents.set(node.key, parent.key);
  }

  return { roots, orphanGroups, orphanPoints, nodes, parents };
}

export const inventoryTree = buildInventoryTree;

export function flattenVisibleInventoryTree(
  model: InventoryTreeModel,
  expanded: ReadonlySet<string>,
): InventoryTreeNode[] {
  const visible: InventoryTreeNode[] = [];
  const visit = (node: InventoryTreeNode) => {
    visible.push(node);
    if (expanded.has(node.key)) {
      for (const child of node.children) visit(child);
    }
  };
  for (const root of model.roots) visit(root);
  for (const node of [...model.orphanGroups, ...model.orphanPoints]) visible.push(node);
  return visible;
}

export function nodeIsExpandable(node: InventoryTreeNode): boolean {
  return node.children.length > 0;
}

