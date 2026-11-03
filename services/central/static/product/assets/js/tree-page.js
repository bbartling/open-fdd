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
  await populateSitePicker(pick);
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
