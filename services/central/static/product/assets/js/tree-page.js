import { readToken } from "./session.js";
import { apiFetch } from "./api.js";
import { loadBuildingContext } from "./model.js";
import { renderModelTree } from "./tree-view.js";

if (!readToken()) {
  location.replace("/app/");
}

const $ = (id) => document.getElementById(id);

async function boot() {
  const pick = $("sitePick");
  try {
    const sessions = await apiFetch("/api/sessions/buildings");
    const buildings = sessions?.buildings ?? [];
    for (const row of buildings) {
      const id = row.building_id ?? row.id;
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      pick.appendChild(opt);
    }
  } catch {
    /* optional */
  }
  const fromQuery = new URLSearchParams(location.search).get("site");
  if (fromQuery) pick.value = fromQuery;
  const load = async () => {
    const site = pick.value;
    if (!site) return;
    const ctx = await loadBuildingContext(site);
    $("sub").textContent = `${site} · ${ctx.model.points.length} points`;
    renderModelTree(ctx.model, site, "", $("detail"), $("tree"));
  };
  pick.addEventListener("change", () => load().catch((e) => alert(e.message)));
  if (pick.value) await load();
}

boot();
