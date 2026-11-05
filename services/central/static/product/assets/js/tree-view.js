import * as echarts from "../vendor/echarts.esm.min.js";
import { displayName, esc, fmtPoint } from "./model.js";
import { GENERIC, has, roleOf, tagsOf } from "./tags.js";

const TREE_COLORS = {
  site: "#b5179e",
  equip: "#f8961e",
  device: "#4361ee",
  sensor: "#43aa8b",
  sp: "#f9c74f",
  cmd: "#f94144",
  weather: "#4cc9f0",
  other: "#577590",
};

let treeChart = null;

function pointNode(p) {
  const kind = has(p, "weather")
    ? "weather"
    : has(p, "cmd")
      ? "cmd"
      : has(p, "sp")
        ? "sp"
        : has(p, "sensor")
          ? "sensor"
          : "other";
  const label = displayName(p);
  const val = fmtPoint(p);
  return {
    name: `${label}${val === "–" ? "" : `  ${val}`}`.trim(),
    kind,
    point: p,
    itemStyle: { color: TREE_COLORS[kind] },
    symbolSize: 8,
  };
}

function entityNode(label, kind, children, rec) {
  return {
    name: `${label}${children.length ? `  (${children.length})` : ""}`,
    kind,
    rec,
    itemStyle: { color: TREE_COLORS[kind] },
    symbolSize: kind === "site" ? 18 : 13,
    children,
  };
}

export function buildTreeModel(model, siteId, equipFilter) {
  if (!model) {
    const id = siteId || "site";
    return entityNode(id, "site", [], { id, name: id });
  }
  const site = model.site;
  const onSite = model.points.filter((p) => p.siteRef === siteId);
  const equipNodes = model.equips
    .filter((e) => !equipFilter || e.id === equipFilter)
    .map((equip) => {
      const eqPts = onSite.filter((p) => p.equipRef === equip.id);
      const weatherKids = eqPts.filter((p) => has(p, "weather")).map(pointNode);
      const sensorKids = eqPts.filter((p) => !has(p, "weather")).map(pointNode);
      return entityNode(equip.name || equip.id, "equip", [...sensorKids, ...weatherKids], equip);
    });
  const looseWeather = onSite.filter((p) => has(p, "weather") && !p.equipRef).map(pointNode);
  if (looseWeather.length) {
    equipNodes.push(
      entityNode("site weather", "weather", looseWeather, { name: "weather", id: "weather" }),
    );
  }
  return entityNode(site.name || siteId, "site", equipNodes, site);
}

function leaves(node, depth = 0) {
  if (!node.children?.length) return depth + 1;
  return Math.max(...node.children.map((c) => leaves(c, depth + 1)));
}

export function renderModelTree(model, siteId, equipFilter, detailEl, treeHost) {
  if (!treeHost) return;
  const root = buildTreeModel(model, siteId, equipFilter);
  const height = Math.max(520, leaves(root) * 24 + 60);
  treeHost.style.height = `${height}px`;
  if (!treeChart) {
    treeChart = echarts.init(treeHost, null, { renderer: "canvas" });
    treeChart.on("click", (params) => {
      if (params?.data) showDetail(params.data, detailEl);
    });
  } else {
    treeChart.resize();
  }
  treeChart.setOption({
    tooltip: {
      trigger: "item",
      backgroundColor: "#0f1730ee",
      borderColor: "#2b3858",
      textStyle: { color: "#e6ebf5" },
    },
    series: [
      {
        type: "tree",
        data: [root],
        top: 30,
        bottom: 20,
        left: 90,
        right: 300,
        symbol: "circle",
        orient: "LR",
        expandAndCollapse: true,
        initialTreeDepth: 3,
        label: { color: "#c9d2e8", fontSize: 11 },
        lineStyle: { color: "#2b3858", width: 1.2 },
        leaves: { label: { position: "right", verticalAlign: "middle", align: "left" } },
      },
    ],
  });
  return treeChart;
}

function showDetail(node, detailEl) {
  if (!detailEl) return;
  const p = node.point;
  const rec = p || node.rec || {};
  const rows = [
    ["kind", node.kind],
    ["equipment", p?.equipRef || rec.id || ""],
    ["role", roleOf(p) || ""],
    ...(p?.latest ? [["latest", `${fmtPoint(p)} @ ${p.latest.ts}`]] : []),
    ["tags", tagsOf(p || rec).join(", ")],
  ].filter(([, v]) => v !== undefined && v !== "");
  const chips = tagsOf(p || rec)
    .filter((t) => !GENERIC.has(t))
    .map((m) => `<span class="tag">${esc(m)}</span>`)
    .join("");
  detailEl.innerHTML = `<div class="tags">${chips || `<span class="hint">no tags</span>`}</div>
    <table class="bac">${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`;
}

export function renderModelChecks(model, siteId, checksEl) {
  if (!checksEl) return;
  if (!model) {
    checksEl.innerHTML =
      '<ul class="checklist"><li>○ No model loaded for this site yet</li></ul>';
    return;
  }
  const onSite = model.points.filter((p) => p.siteRef === siteId);
  const tagged = onSite.filter((p) => has(p, "point") || p.tags?.length);
  checksEl.innerHTML = `
    <ul class="checklist">
      <li>${tagged.length ? "✓" : "○"} ${tagged.length} TTL points on site</li>
      <li>${model.equips.length ? "✓" : "○"} ${model.equips.length} equipment in TTL tree</li>
      <li>Model data from <code>GET /api/model/ttl</code> only</li>
    </ul>`;
}

export function resizeTree() {
  treeChart?.resize();
}
