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
  Chiller: "#1e6f8e",
  Cooling_Tower: "#2a8f6a",
  Boiler: "#b84a32",
  Plant: "#5c6b82",
  Laboratory_Equipment: "#4f78e8",
  Air_Duct: "#e8a84f",
  AHU: "#6b8e23",
  Rooftop_Unit: "#6b8e23",
  DOAS: "#3d8b6e",
  VAV: "#9370db",
  Fan_Coil_Unit: "#7b5ea8",
  FCU: "#7b5ea8",
  Damper: "#c9870a",
  Reheat_Coil: "#d45d79",
  BACnet_Device: "#708090",
};

/** Left-to-right mechanical hierarchy (plant → distribution → terminal → zone). */
const MECH_LAYER_LABELS: { maxRank: number; label: string }[] = [
  { maxRank: 4, label: "Plant / central" },
  { maxRank: 14, label: "Air handling" },
  { maxRank: 24, label: "Terminal / VAV" },
  { maxRank: 34, label: "Duct / coils / dampers" },
  { maxRank: 99, label: "Zones / sensors" },
];

function mechanicalRank(eq: NetworkGraphEquipment): number {
  const hay = `${eq.equipment_type || ""} ${eq.brick_type || ""} ${eq.name || ""} ${eq.label || ""}`.toLowerCase();
  if (/chiller|cooling.?tower|condenser|boiler|plant|heat.?pump/.test(hay)) return 0;
  if (/ahu|air.?handler|rtu|rooftop|doas|maau|packaged/.test(hay)) return 10;
  if (/vav|fan.?coil|fcu|terminal|box/.test(hay)) return 20;
  if (/damper|reheat|coil|duct|mixed.?air|discharge|supply.?fan/.test(hay)) return 30;
  if (/zone|room|space|leaving.?air|entering.?air/.test(hay)) return 40;
  return 50;
}

function layerLabelForRank(rank: number): string {
  for (const row of MECH_LAYER_LABELS) {
    if (rank <= row.maxRank) return row.label;
  }
  return "Other";
}

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
): { layers: NetworkGraphEquipment[][]; layerTitles: string[] } {
  const byRank = new Map<number, NetworkGraphEquipment[]>();
  for (const eq of equipment) {
    const rank = mechanicalRank(eq);
    if (!byRank.has(rank)) byRank.set(rank, []);
    byRank.get(rank)!.push(eq);
  }
  const ranks = [...byRank.keys()].sort((a, b) => a - b);
  const layers = ranks.map((r) => {
    const layer = byRank.get(r)!;
    layer.sort((a, b) => eqLabel(a).localeCompare(eqLabel(b)));
    return layer;
  });
  const layerTitles = ranks.map((r) => layerLabelForRank(r));

  // Nudge feed children one column right of their parent when BRICK feeds exist.
  if (feeds.length) {
    const byId = new Map(equipment.map((e) => [e.equipment_id, e]));
    const layerIndex = new Map<string, number>();
    layers.forEach((layer, idx) => {
      for (const eq of layer) layerIndex.set(eq.equipment_id, idx);
    });
    for (const edge of feeds) {
      const parentIdx = layerIndex.get(edge.from_equipment_id);
      const child = byId.get(edge.to_equipment_id);
      if (parentIdx === undefined || !child) continue;
      const want = parentIdx + 1;
      const cur = layerIndex.get(edge.to_equipment_id) ?? parentIdx;
      if (want <= cur) continue;
      const fromLayer = layers[cur];
      const toLayer = layers[want] ?? [];
      const i = fromLayer.findIndex((e) => e.equipment_id === edge.to_equipment_id);
      if (i >= 0) {
        fromLayer.splice(i, 1);
        toLayer.push(child);
        if (!layers[want]) layers[want] = toLayer;
        layerIndex.set(edge.to_equipment_id, want);
      }
    }
    layers.forEach((layer) => layer.sort((a, b) => eqLabel(a).localeCompare(eqLabel(b))));
  }

  return { layers, layerTitles };
}

function buildLayout(
  graph: BrickNetworkInput,
  theme: Theme,
): { nodes: LayoutNode[]; layerAnnotations: Partial<Plotly.Annotations>[] } {
  const colors = themeColors(theme);
  const { layers, layerTitles } = layerEquipment(graph.equipment, graph.feeds);
  const nodes: LayoutNode[] = [];
  const layerGap = 3.2;
  const rowGap = 1.55;
  const layerAnnotations: Partial<Plotly.Annotations>[] = [];

  layers.forEach((layer, layerIdx) => {
    const x = layerIdx * layerGap;
    layer.forEach((eq, rowIdx) => {
      const y = rowIdx * rowGap - (layer.length - 1) * (rowGap / 2);
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
      const pts = [...(graph.points_by_equipment[eq.equipment_id] ?? [])].sort((a, b) =>
        pointLabel(a).localeCompare(pointLabel(b)),
      );
      const span = Math.max(1.4, (pts.length - 1) * 0.62);
      pts.forEach((p, pi) => {
        const px = x - 0.45 + (pi / Math.max(pts.length - 1, 1)) * span;
        const py = y - 1.15 - (pi % 3) * 0.22;
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
    if (layer.length) {
      const ys = layer.map((_, rowIdx) => rowIdx * rowGap - (layer.length - 1) * (rowGap / 2));
      const yMid = (Math.min(...ys) + Math.max(...ys)) / 2;
      layerAnnotations.push({
        x: layerIdx * layerGap - 0.55,
        y: yMid,
        text: `<b>${layerTitles[layerIdx] || "Equipment"}</b>`,
        showarrow: false,
        xanchor: "right",
        font: { size: 11, color: colors.muted },
        bgcolor: "rgba(0,0,0,0)",
      });
    }
  });
  return { nodes, layerAnnotations };
}

export function buildBrickNetworkPlot(
  graph: BrickNetworkInput,
  theme: Theme,
): { data: Plotly.Data[]; layout: Partial<Plotly.Layout>; nodeByIndex: LayoutNode[] } {
  const colors = themeColors(theme);
  const { nodes, layerAnnotations } = buildLayout(graph, theme);
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
  const pad = 1.2;

  const layout: Partial<Plotly.Layout> = {
    paper_bgcolor: colors.paper,
    plot_bgcolor: colors.bg,
    margin: { l: 88, r: 32, t: 36, b: 32 },
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
    annotations: [...layerAnnotations, ...annotations],
    hovermode: "closest",
  };

  return {
    data: [edgeTrace, equipTrace, pointTrace],
    layout,
    nodeByIndex: nodes,
  };
}
