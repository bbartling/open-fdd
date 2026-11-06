// tree.html: read-only view of NF's own BACnet server (left) and the Haystack
// model tree (right). Needs nf.js loaded first. Nothing here writes to NF.

/** @param {string} id @returns {AnyEl} */
const $ = (id) => /** @type {AnyEl} */ (document.getElementById(id));
const COLORS = {
  site: "#b5179e", equip: "#f8961e", device: "#4361ee", sensor: "#43aa8b", sp: "#f9c74f",
  cmd: "#f94144", weather: "#4cc9f0", bacnet: "#90be6d", other: "#577590",
};
const GENERIC = new Set(["point", "his", "cur", "writable"]);
const REF_KEYS = ["siteRef", "equipRef", "deviceRef", "weatherStationRef"];
const markersOf = (r) => ((r.attrs || {}).markers || "").split(",").filter(Boolean);
const fmtVal = (r) => {
  const lv = r.latestValue || {};
  const v = lv.double ?? lv.real;
  if (v == null) return "";
  const a = r.attrs || {};
  return a.kind === "Bool" ? (v ? "on" : "off") : `${Number(v).toFixed(2)} ${a.unit || ""}`.trim();
};

// ---- left: NF's own BACnet server ---------------------------------------------
async function renderBacnet(pointsByBacnet) {
  const [cfg, local, ports] = await Promise.all([
    api("/api/v1/bacnet/configuration"), api("/api/v1/bacnet/local"), api("/api/v1/bacnet/ports"),
  ]);
  const addr = selfAddress(ports);
  const dev = cfg.deviceInstance;
  const devId = { objectType: "OBJECT_DEVICE", instance: dev };
  const read = (oid, prop) => readProp(dev, addr, oid, prop).catch(() => undefined);
  const [name, vendor, model, fw] = await Promise.all(
    ["PROP_OBJECT_NAME", "PROP_VENDOR_NAME", "PROP_MODEL_NAME", "PROP_FIRMWARE_REVISION"].map((p) => read(devId, p)));
  $("bacHint").textContent = `ReadProperty against ${addr ? addr.label : `device ${dev}`} · config from /api/v1/bacnet/local`;
  $("device").innerHTML = `<div class="devcard">
    <span class="k">device</span><span class="mono">d.${dev} · ${esc(name ?? cfg.deviceName)}</span>
    <span class="k">vendor / model</span><span>${esc(vendor ?? "–")} · ${esc(model ?? "–")}</span>
    <span class="k">firmware</span><span>${esc(fw ?? "–")}</span>
    <span class="k">BACnet/IP</span><span>${esc(addr?.label ?? "–")} · ${(ports.ports || []).length} port(s)</span>
    <span class="k">local objects</span><span>${(local.objects || []).length}</span>
  </div>`;
  const cards = await Promise.all((local.objects || []).map(async (o) => {
    const id = objId(o.objectId);
    const wire = await read(o.objectId, "PROP_PRESENT_VALUE");
    const cfgPv = propOf(o, "PROP_PRESENT_VALUE");
    const units = propOf(o, "PROP_UNITS");
    const tagged = pointsByBacnet.get(id);
    const same = typeof wire === "number" && typeof cfgPv === "number" && Math.abs(wire - cfgPv) < 0.01;
    const rows = (o.props || []).map((p) => {
      const v = p.value || {};
      const shown = v.bitString ? `bits ${v.bitString.length} set [${(v.bitString.setBits || []).join(",")}]` : scalar(v);
      return `<tr><td>${esc(p.property.replace(/^PROP_/, "").toLowerCase())}</td><td>${esc(shown)}</td></tr>`;
    }).join("");
    return `<div class="obj">
      <div class="top"><span class="id">${esc(id)}</span><span class="name">${esc(propOf(o, "PROP_OBJECT_NAME"))}</span>
        <span class="pv">${typeof wire === "number" ? wire.toFixed(2) : "–"} <small>${esc(BAC_UNITS[units] ?? units ?? "")}</small></span></div>
      <div class="hint">${esc(propOf(o, "PROP_DESCRIPTION"))}</div>
      <div class="hint">PV over BACnet ${same ? `<span class="ok">✓ matches config</span>` : `<span class="bad">✗ config ${esc(cfgPv)}</span>`}</div>
      ${tagged ? `<div class="tags">${haystackChips(tagged)}</div>` : `<div class="hint">no Haystack point references ${esc(id)}</div>`}
      <table class="props">${rows}</table>
    </div>`;
  }));
  $("objects").innerHTML = cards.join("") || `<div class="hint">No local objects; NF serves only its device object.</div>`;
  return { dev, label: addr?.label, objects: local.objects || [] };
}

function haystackChips(rec) {
  const a = rec.attrs || {};
  return markersOf(rec).map((m) => `<span class="tag">${esc(m)}</span>`).join("")
    + REF_KEYS.filter((k) => a[k]).map((k) => `<span class="tag ref">${k}:@${esc(a[k])}</span>`).join("");
}

// ---- right: Haystack tree -------------------------------------------------------
function pointNode(r) {
  const m = markersOf(r);
  const kind = m.includes("weather") ? "weather" : m.includes("cmd") ? "cmd" : m.includes("sp") ? "sp" : m.includes("sensor") ? "sensor" : "other";
  const label = m.filter((t) => !GENERIC.has(t) && !["sensor", "weather"].includes(t)).join(" ") || r.name;
  const val = fmtVal(r);
  return { name: val ? `${label}  ${val}` : label, rec: r, kind, itemStyle: { color: COLORS[kind] }, symbolSize: 8 };
}

function entityNode(r, kind, children, label) {
  const a = r.attrs || {};
  return {
    name: `${label || a.dis || r.name}${children.length ? `  (${children.length})` : ""}`, rec: r, kind,
    itemStyle: { color: COLORS[kind] }, symbolSize: kind === "site" ? 18 : 13, children,
  };
}

// A grouping node (equips / weather / BACnet server) so every branch puts its
// points at the same depth and the tidy layout keeps leaf labels apart.
const groupNode = (name, kind, children) => ({
  name, kind, children, itemStyle: { color: COLORS[kind] }, symbolSize: 10,
  rec: { name, attrs: { note: `${children.length} ${kind} entr${children.length === 1 ? "y" : "ies"}` } },
});

function buildTree(model, points, bacnet) {
  const ref = (r, k) => (r.attrs || {})[k] || "";
  const idOf = (r) => ref(r, "id") || r.name;
  const roots = model.sites.map((site) => {
    const sid = idOf(site);
    const onSite = points.filter((p) => ref(p, "siteRef") === sid);
    const equipNodes = model.equips.filter((e) => ref(e, "siteRef") === sid).map((equip) => {
      const eid = idOf(equip);
      const eqPts = onSite.filter((p) => ref(p, "equipRef") === eid);
      const devs = model.devices.filter((d) => ref(d, "equipRef") === eid);
      const devNodes = devs.map((d) => {
        const did = idOf(d);
        const mine = eqPts.filter((p) => ref(p, "deviceRef") === did);
        const internals = onSite.filter((p) => ref(p, "deviceRef") === did && !ref(p, "equipRef"));
        const kids = mine.map(pointNode);
        if (internals.length) {
          kids.push({
            name: `untagged objects (${internals.length})`, kind: "other", collapsed: true,
            itemStyle: { color: COLORS.other }, symbolSize: 9,
            rec: { name: "untagged objects", attrs: { note: "deviceRef + siteRef only (internal logic, files, priorities)" } },
            children: internals.map((p) => ({
              name: `${ref(p, "object_id") || ""} ${p.name}`.trim(), rec: p, kind: "other",
              itemStyle: { color: COLORS.other }, symbolSize: 5,
            })),
          });
        }
        return entityNode(d, "device", kids, idOf(d));
      });
      const loose = eqPts.filter((p) => !devs.some((d) => ref(p, "deviceRef") === idOf(d))).map(pointNode);
      return entityNode(equip, "equip", [...devNodes, ...loose]);
    });
    const stations = [...new Set(onSite.map((p) => ref(p, "weatherStationRef")).filter(Boolean))].map((ws) => {
      const kids = onSite.filter((p) => ref(p, "weatherStationRef") === ws).map((p) => {
        const n = pointNode(p);
        const av = ref(p, "bacnet_object");
        if (av) n.name += `  ↔ BACnet ${av}`;
        return n;
      });
      return entityNode({ name: ws, attrs: { id: ws, markers: "weatherStation" } }, "weather", kids);
    });
    const server = entityNode({ name: `d.${bacnet.dev}`, attrs: { dis: `NF BACnet server d.${bacnet.dev}`, note: bacnet.label } }, "bacnet",
      bacnet.objects.map((o) => ({
        name: `${objId(o.objectId)} ${propOf(o, "PROP_OBJECT_NAME")}  ${Number(propOf(o, "PROP_PRESENT_VALUE")).toFixed(2)}`,
        kind: "bacnet", itemStyle: { color: COLORS.bacnet }, symbolSize: 8,
        rec: { name: objId(o.objectId), attrs: Object.fromEntries((o.props || []).map((p) => [p.property.replace(/^PROP_/, "").toLowerCase(), scalar(p.value)])) },
      })), `d.${bacnet.dev} NF`);
    // Equips hold devices → points; give the other branches a group level so
    // all point leaves sit at depth 3 (site → equip → device → point,
    // site → group → station/server → point).
    return entityNode(site, "site", [
      ...equipNodes,
      ...(stations.length ? [groupNode("weather stations", "weather", stations)] : []),
      groupNode("BACnet server", "bacnet", [server]),
    ]);
  });
  return roots.length === 1 ? roots[0] : { name: "NF", kind: "other", children: roots, rec: { name: "NF" } };
}

function showDetail(node) {
  const r = node.rec || {};
  const a = r.attrs || {};
  const lv = r.latestValue;
  const rows = [
    ["kind", node.kind], ["name", r.name], ["uuid", r.uuid], ["pointType", r.pointType],
    ...(lv ? [["latest", `${fmtVal(r)} @ ${lv.ts}`]] : []),
    ...Object.entries(a).filter(([k]) => k !== "markers").sort(([x], [y]) => x.localeCompare(y)),
  ].filter(([, v]) => v !== undefined && v !== "");
  $("detail").innerHTML = `<div class="tags" style="margin:0 0 8px">${haystackChips(r)}</div>
    <table>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`;
}

async function main() {
  await initAuth();
  const recs = await queryAll({ layer: "model" });
  const model = {
    sites: recs.filter((r) => r.pointType === "SITE"),
    equips: recs.filter((r) => r.pointType === "EQUIPMENT"),
    devices: recs.filter((r) => r.pointType === "DEVICE"),
  };
  if (!model.sites.length) throw new Error("no Haystack site in this NF's model layer");
  // Merged layer: every point on any modeled site, with tags + latest value.
  const points = (await Promise.all(model.sites.map((s) =>
    queryAll({ layer: "default", structuredQuery: field("siteRef", (s.attrs || {}).id || s.name) })))).flat()
    .filter((p) => !["SITE", "EQUIPMENT", "DEVICE"].includes(p.pointType));
  const byBacnet = new Map(points.filter((p) => (p.attrs || {}).bacnet_object).map((p) => [p.attrs.bacnet_object, p]));
  const bacnet = await renderBacnet(byBacnet);

  $("sub").textContent = `read-only · ${model.sites.length} site · ${model.equips.length} equip · ${model.devices.length} device · `
    + `${points.length} points · BACnet server d.${bacnet.dev} with ${bacnet.objects.length} objects · ${location.host}`;
  $("legend").innerHTML = Object.entries(COLORS).map(([k, c]) => `<span><i style="background:${c}"></i>${k}</span>`).join("");

  const root = buildTree(model, points, bacnet);
  // Size the canvas to the leaves visible at the initial depth so labels don't stack.
  const leaves = (n, depth) => (!n.children?.length || n.collapsed || depth >= 4 ? 1
    : n.children.reduce((s, c) => s + leaves(c, depth + 1), 0));
  $("tree").style.height = `${Math.max(600, leaves(root, 0) * 24 + 60)}px`;
  const chart = echarts.init($("tree"));
  chart.setOption({
    tooltip: { trigger: "item", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
      formatter: (x) => `${esc(x.data.rec?.attrs?.dis || x.name)}<br><span style="color:${LT.label}">${esc(markersOf(x.data.rec || {}).join(" "))}</span>` },
    series: [{
      type: "tree", data: [root], top: 30, bottom: 20, left: 90, right: 330,
      orient: "LR", initialTreeDepth: 4, roam: true, expandAndCollapse: true, animationDuration: 400,
      symbol: "circle", lineStyle: { color: LT.axisLine, width: 1.4, curveness: 0.5 },
      // Branch labels sit above their node; leaf labels run off to the right.
      label: { position: "top", distance: 6, align: "center", color: LT.legend, fontSize: 12 },
      leaves: { label: { position: "right", verticalAlign: "middle", align: "left", distance: 6 } },
      emphasis: { focus: "descendant" },
    }],
  });
  chart.on("click", (x) => showDetail(x.data));
  showDetail(chart.getOption().series[0].data[0]);
  window.addEventListener("resize", () => chart.resize());
}

main().catch((e) => {
  $("err").style.display = "block";
  $("err").textContent = `Could not load: ${e.message}`;
});
