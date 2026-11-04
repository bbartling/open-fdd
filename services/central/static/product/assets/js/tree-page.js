import { readToken } from "./session.js";
import { loadBuildingContext } from "./model.js";
import { renderModelTree } from "./tree-view.js";
import { populateSitePicker } from "./sites.js";

if (!readToken()) {
  location.replace("/app/");
}

const $ = (id) => document.getElementById(id);

async function boot() {
  const pick = $("sitePick");
  const { queryRejected, selected } = await populateSitePicker(pick);
  if (queryRejected) {
    $("sub").textContent = `Unauthorized site query: ${queryRejected}`;
    return;
  }
  const load = async () => {
    const site = pick.value;
    if (!site) return;
    const ctx = await loadBuildingContext(site);
    $("sub").textContent = `${site} · ${ctx.health?.version ?? ""} · ${ctx.model.points.length} points`;
    renderModelTree(ctx.model, site, "", $("detail"), $("tree"));
  };
  pick.addEventListener("change", () => load().catch((e) => alert(e.message)));
  if (selected) await load();
}

boot();
