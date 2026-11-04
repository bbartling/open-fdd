/** Build site/equip/point tree from Turtle (GET /api/model/ttl) only. */

const TAG_RE = /ph:hasTag\s+([^;\.]+)/g;
const LABEL_RE = /rdfs:label\s+"([^"]*)"/;
const EQUIP_REF_RE = /phIoT:equipRef\s+local:([^\s;]+)/;
const UNIT_RE = /ph:unit\s+"([^"]*)"/;

function localId(line) {
  const m = line.match(/^local:([^\s]+)/);
  return m ? m[1] : "";
}

function tagsFromBlock(block) {
  const tags = [];
  let m;
  TAG_RE.lastIndex = 0;
  while ((m = TAG_RE.exec(block))) {
    const t = m[1].trim().replace(/^ph(?:IoT|Science|Ict)?:/, "").replace(":", "");
    if (t) tags.push(t);
  }
  return tags;
}

export function parseTtlModel(buildingId, ttlText) {
  const site = { id: buildingId, name: buildingId };
  const equipById = new Map();
  const points = [];
  const blocks = String(ttlText || "").split(/\n\s*\n/);
  for (const block of blocks) {
    const id = localId(block.split("\n")[0] || "");
    if (!id) continue;
    const tags = tagsFromBlock(block);
    const label = block.match(LABEL_RE)?.[1] || id;
    const unit = block.match(UNIT_RE)?.[1] || "";
    if (/\ba\s+phIoT:equip\b/.test(block) || tags.includes("equip")) {
      equipById.set(id, {
        id,
        name: label,
        tags,
        siteRef: buildingId,
        equipType: tags.find((t) => ["ahu", "vav", "rtu", "equip"].includes(t)) || "",
      });
      continue;
    }
    if (/\ba\s+phIoT:point\b/.test(block) || tags.includes("point")) {
      const equipRef = block.match(EQUIP_REF_RE)?.[1] || "";
      const role =
        tags.find((t) => t.includes("_") || t.endsWith("_t")) ||
        tags.filter((t) => !["point", "his", "cur", "sensor"].includes(t))[0] ||
        id;
      points.push({
        id: `${equipRef}::${role}`,
        siteRef: buildingId,
        equipRef,
        role,
        column: role,
        dis: label,
        tags,
        unit,
        kind: "Number",
        latest: null,
      });
    }
  }
  return {
    site,
    equips: [...equipById.values()].sort((a, b) => a.id.localeCompare(b.id)),
    devices: [],
    points: points.sort(
      (a, b) =>
        (a.equipRef || "").localeCompare(b.equipRef || "") || a.dis.localeCompare(b.dis),
    ),
  };
}

export async function loadModelFromTtl(buildingId, apiFetch) {
  let ttl = "";
  try {
    const raw = await apiFetch(`/api/model/ttl?building_id=${encodeURIComponent(buildingId)}`);
    ttl = typeof raw === "string" ? raw : raw?.ttl ?? "";
  } catch {
    ttl = "# TTL unavailable for this site.\n";
  }
  const model = parseTtlModel(buildingId, ttl);
  return { ttl, model };
}
