import type { Theme } from "../contexts/theme-context";

namespace Plotly {
  export type Data = Record<string, unknown>;
  export type Layout = Record<string, unknown>;
  export type Annotations = Record<string, unknown>;
}

export type NetworkGraphPoint = {
  point_id: string;
  name?: string;
  label?: string;
  brick_type?: string;
  object_identifier?: string;
  unit?: string;
  equipment_id?: string;
};

export type NetworkGraphEquipment = {
  equipment_id: string;
  name?: string;
  label?: string;
  equipment_type?: string;
  brick_type?: string;
};

export type NetworkFeedEdge = {
  from_equipment_id: string;
  to_equipment_id: string;
  from_label?: string;
  to_label?: string;
};

export type BrickNetworkInput = {
  equipment: NetworkGraphEquipment[];
  feeds: NetworkFeedEdge[];
  points_by_equipment: Record<string, NetworkGraphPoint[]>;
};

type NodeKind = "equipment" | "point";

type LayoutNode = {
  id: string;
  kind: NodeKind;
  label: string;
  sublabel?: string;
  equipmentType?: string;
  x: number;
  y: number;
  size: number;
  color: string;
  equipmentId?: string;
  brickType?: string;
};

const EQUIP_PALETTE: Record<string, string> = {
  Laboratory_Equipment: "#4f78e8",
  Air_Duct: "#e8a84f",
  AHU: "#6b8e23",
  VAV: "#9370db",
  BACnet_Device: "#708090",
};

const POINT_PALETTE: Record<string, string> = {
  Outside_Air_Humidity_Sensor: "#2d9a52",
  Outside_Air_Temperature_Sensor: "#3b6de0",
  Discharge_Air_Temperature_Sensor: "#c9870a",
  Zone_Air_Temperature_Sensor: "#9b59b6",
};

function eqLabel(eq: NetworkGraphEquipment): string {
  return String(eq.label || eq.name || eq.equipment_id);
}

function pointLabel(p: NetworkGraphPoint): string {
  return String(p.label || p.name || p.point_id);
}

function themeColors(theme: Theme) {
  return theme === "dark"
    ? {
        bg: "#0f1218",
        paper: "#161b24",
        text: "#e8edf6",
        muted: "#97a3b8",
        edge: "#5c6b82",
        edgeLabel: "#b8c4d8",
        pointDefault: "#58d0a8",
        equipDefault: "#4f78e8",
      }
    : {
        bg: "#f4f6fb",
        paper: "#ffffff",
        text: "#1a2332",
        muted: "#5c6b82",
        edge: "#8a9bb5",
        edgeLabel: "#3d4d66",
        pointDefault: "#2d9a52",
        equipDefault: "#3b6de0",
      };
}

function layerEquipment(
  equipment: NetworkGraphEquipment[],
  feeds: NetworkFeedEdge[],
): NetworkGraphEquipment[][] {
  const byId = new Map(equipment.map((e) => [e.equipment_id, e]));
  const incoming = new Map<string, number>();
  for (const eq of equipment) incoming.set(eq.equipment_id, 0);
  for (const edge of feeds) {
    const dst = edge.to_equipment_id;
    incoming.set(dst, (incoming.get(dst) ?? 0) + 1);
  }
  const layers: NetworkGraphEquipment[][] = [];
  const placed = new Set<string>();
  let frontier = equipment.filter((e) => (incoming.get(e.equipment_id) ?? 0) === 0);
  if (!frontier.length) frontier = [...equipment];
  while (frontier.length) {
    layers.push(frontier);
    for (const eq of frontier) placed.add(eq.equipment_id);
    const nextIds = new Set<string>();
    for (const eq of frontier) {
      for (const edge of feeds) {
        if (edge.from_equipment_id === eq.equipment_id && !placed.has(edge.to_equipment_id)) {
          nextIds.add(edge.to_equipment_id);
        }
      }
    }
    frontier = [...nextIds].map((id) => byId.get(id)).filter(Boolean) as NetworkGraphEquipment[];
    if (!frontier.length) {
      frontier = equipment.filter((e) => !placed.has(e.equipment_id));
    }
    if (frontier.every((e) => placed.has(e.equipment_id))) break;
  }
  for (const eq of equipment) {
    if (!placed.has(eq.equipment_id)) {
      if (!layers.length) layers.push([]);
      layers[layers.length - 1].push(eq);
    }
  }
  return layers;
}

function buildLayout(graph: BrickNetworkInput, theme: Theme): LayoutNode[] {
  const colors = themeColors(theme);
  const layers = layerEquipment(graph.equipment, graph.feeds);
  const nodes: LayoutNode[] = [];
  const layerGap = 2.4;
  const rowGap = 1.35;

  layers.forEach((layer, layerIdx) => {
    const x = layerIdx * layerGap;
    layer.forEach((eq, rowIdx) => {
      const y = rowIdx * rowGap;
      const et = eq.equipment_type || eq.brick_type || "";
      nodes.push({
        id: eq.equipment_id,
        kind: "equipment",
        label: eqLabel(eq),
        sublabel: et,
        equipmentType: et,
        x,
        y,
        size: 36,
        color: EQUIP_PALETTE[et] || colors.equipDefault,
      });
      const pts = graph.points_by_equipment[eq.equipment_id] ?? [];
      const span = Math.max(1.2, (pts.length - 1) * 0.55);
      pts.forEach((p, pi) => {
        const px = x - 0.35 + (pi / Math.max(pts.length - 1, 1)) * span;
        const py = y - 0.95 - (pi % 2) * 0.15;
        const bt = p.brick_type || "";
        nodes.push({
          id: p.point_id,
          kind: "point",
          label: pointLabel(p),
          sublabel: bt,
          equipmentId: eq.equipment_id,
          brickType: bt,
          x: px,
          y: py,
          size: 18,
          color: POINT_PALETTE[bt] || colors.pointDefault,
        });
      });
    });
  });
  return nodes;
}

export function buildBrickNetworkPlot(
  graph: BrickNetworkInput,
  theme: Theme,
): { data: Plotly.Data[]; layout: Partial<Plotly.Layout>; nodeByIndex: LayoutNode[] } {
  const colors = themeColors(theme);
  const nodes = buildLayout(graph, theme);
  const nodeById = new Map(nodes.map((n) => [n.id, n]));

  const edgeX: (number | null)[] = [];
  const edgeY: (number | null)[] = [];
  const annotations: Partial<Plotly.Annotations>[] = [];

  for (const edge of graph.feeds) {
    const src = nodeById.get(edge.from_equipment_id);
    const dst = nodeById.get(edge.to_equipment_id);
    if (!src || !dst) continue;
    edgeX.push(src.x, dst.x, null);
    edgeY.push(src.y, dst.y, null);
    annotations.push({
      x: (src.x + dst.x) / 2,
      y: (src.y + dst.y) / 2 + 0.12,
      text: "feeds →",
      showarrow: false,
      font: { size: 11, color: colors.edgeLabel },
      bgcolor: "rgba(0,0,0,0)",
    });
  }

  for (const node of nodes) {
    if (node.kind !== "point" || !node.equipmentId) continue;
    const parent = nodeById.get(node.equipmentId);
    if (!parent) continue;
    edgeX.push(parent.x, node.x, null);
    edgeY.push(parent.y, node.y, null);
  }

  const equipNodes = nodes.filter((n) => n.kind === "equipment");
  const pointNodes = nodes.filter((n) => n.kind === "point");

  const edgeTrace: Plotly.Data = {
    type: "scatter",
    mode: "lines",
    x: edgeX,
    y: edgeY,
    line: { color: colors.edge, width: 2 },
    hoverinfo: "skip",
    showlegend: false,
  };

  const equipTrace: Plotly.Data = {
    type: "scatter",
    mode: "markers+text",
    name: "Equipment",
    x: equipNodes.map((n) => n.x),
    y: equipNodes.map((n) => n.y),
    text: equipNodes.map((n) => n.label),
    textposition: "bottom center",
    textfont: { size: 12, color: colors.text },
    marker: {
      size: equipNodes.map((n) => n.size),
      color: equipNodes.map((n) => n.color),
      line: { width: 2, color: colors.paper },
      symbol: "square",
    },
    hovertemplate: equipNodes.map(
      (n) => `<b>${n.label}</b><br>${n.sublabel || "Equipment"}<extra></extra>`,
    ),
    customdata: equipNodes.map((n) => n.id),
  };

  const pointTrace: Plotly.Data = {
    type: "scatter",
    mode: "markers+text",
    name: "Points",
    x: pointNodes.map((n) => n.x),
    y: pointNodes.map((n) => n.y),
    text: pointNodes.map((n) => n.label),
    textposition: "top center",
    textfont: { size: 10, color: colors.muted },
    marker: {
      size: pointNodes.map((n) => n.size),
      color: pointNodes.map((n) => n.color),
      line: { width: 1.5, color: colors.paper },
      symbol: "circle",
    },
    hovertemplate: pointNodes.map((n) => {
      const pt = Object.values(graph.points_by_equipment)
        .flat()
        .find((p) => p.point_id === n.id);
      const addr = pt?.object_identifier || "—";
      const unit = pt?.unit || "—";
      return `<b>${n.label}</b><br>${n.sublabel || ""}<br>${addr}<br>${unit}<extra></extra>`;
    }),
    customdata: pointNodes.map((n) => n.id),
  };

  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const pad = 0.8;

  const layout: Partial<Plotly.Layout> = {
    paper_bgcolor: colors.paper,
    plot_bgcolor: colors.bg,
    margin: { l: 24, r: 24, t: 24, b: 24 },
    xaxis: {
      visible: false,
      range: [Math.min(...xs, 0) - pad, Math.max(...xs, 1) + pad],
      fixedrange: true,
    },
    yaxis: {
      visible: false,
      range: [Math.min(...ys, 0) - pad, Math.max(...ys, 1) + pad],
      scaleanchor: "x",
      scaleratio: 1,
      fixedrange: true,
    },
    showlegend: true,
    legend: { orientation: "h", y: 1.08, font: { color: colors.text } },
    annotations,
    hovermode: "closest",
  };

  return {
    data: [edgeTrace, equipTrace, pointTrace],
    layout,
    nodeByIndex: nodes,
  };
}
