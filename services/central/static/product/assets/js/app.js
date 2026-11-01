import { clearSession, readToken, writeToken } from "./session.js";
import { apiFetch, login } from "./api.js";
import { esc, loadBuildingContext } from "./model.js";

const $ = (id) => document.getElementById(id);
let activeTab = "overview";
let scope = { site: "" };
let ctx = null;

function showErr(msg) {
  const el = $("err");
  if (!msg) {
    el.classList.remove("show");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.add("show");
}

function setLive(ok, text) {
  $("liveDot").classList.toggle("bad", !ok);
  $("liveTxt").textContent = text;
}

function tickClock() {
  $("clock").textContent = new Date().toLocaleString();
}

function renderTab(name) {
  activeTab = name;
  document.querySelectorAll("#tabs button").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.tab === name);
  });
  document.querySelectorAll("main > section.tab").forEach((sec) => {
    sec.classList.toggle("on", sec.id === `tab-${name}`);
  });
}

function renderSummary() {
  const summary = $("summary");
  if (!ctx) {
    summary.innerHTML = "";
    return;
  }
  const v = ctx.health?.version ?? "—";
  summary.innerHTML = `
    <div class="stat"><b>${esc(v)}</b><span>build</span></div>
    <div class="stat"><b>${esc(scope.site || "—")}</b><span>site</span></div>
    <div class="stat"><b>${ctx.points.length}</b><span>points</span></div>
    <div class="stat"><b>${ctx.equips.length}</b><span>equip</span></div>`;
}

function renderPlaceholderCards() {
  $("cards").innerHTML = `
    <article class="card"><div class="name">Historian</div><div class="val">${esc(ctx?.health?.historian ?? "—")}</div><div class="delta">Wave C: live cards</div></article>
    <article class="card"><div class="name">AFDD</div><div class="val">${ctx?.health?.afdd_scheduler ? "on" : "—"}<small></small></div><div class="delta">Schedule tab Wave D</div></article>`;
  $("chips").innerHTML = `<span class="chip"><span class="led"></span><span class="state">pending</span> status chips</span>`;
  $("nPoints").textContent = String(ctx?.points?.length ?? 0);
}

async function applySite() {
  scope.site = $("sitePick").value;
  if (!scope.site) {
    return;
  }
  setLive(true, "loading…");
  try {
    ctx = await loadBuildingContext(scope.site);
    $("sub").textContent = `${scope.site} · ${ctx.health?.version ?? "Open-FDD"} · static preview`;
    $("ttl").textContent = ctx.ttl;
    renderSummary();
    renderPlaceholderCards();
    setLive(true, `live · ${new Date().toLocaleTimeString()}`);
  } catch (err) {
    showErr(err.message || String(err));
    setLive(false, "error");
  }
}

async function loadSites() {
  const pick = $("sitePick");
  pick.innerHTML = "";
  try {
    const sessions = await apiFetch("/api/sessions/buildings");
    const buildings = sessions?.buildings ?? sessions?.items ?? [];
    if (Array.isArray(buildings) && buildings.length) {
      for (const row of buildings) {
        const id = row.building_id ?? row.id ?? row;
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = id;
        pick.appendChild(opt);
      }
    } else {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no active session — use ?site= or CSV import)";
      pick.appendChild(opt);
    }
  } catch {
    const opt = document.createElement("option");
    opt.value = new URLSearchParams(location.search).get("site") || "";
    opt.textContent = opt.value || "default";
    pick.appendChild(opt);
  }
  const fromQuery = new URLSearchParams(location.search).get("site");
  if (fromQuery) {
    pick.value = fromQuery;
  }
  scope.site = pick.value;
  if (scope.site) {
    await applySite();
  } else {
    $("sub").textContent = "Select or import a building site";
    setLive(false, "no site");
  }
}

function bindTabs() {
  $("tabs").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-tab]");
    if (!btn) {
      return;
    }
    renderTab(btn.dataset.tab);
  });
  $("range")?.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-h]");
    if (!btn) {
      return;
    }
    $("range").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
  });
}

function bindAuth() {
  const gate = $("loginGate");
  $("loginForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("loginErr").hidden = true;
    const data = new FormData(ev.target);
    try {
      const body = await login(data.get("username"), data.get("password"));
      const token = body.token || body.access_token;
      if (!token) {
        throw new Error("Login response missing token");
      }
      writeToken(token);
      gate.hidden = true;
      $("logoutBtn").hidden = false;
      await bootApp();
    } catch (err) {
      $("loginErr").textContent = err.message || "Sign in failed";
      $("loginErr").hidden = false;
    }
  });
  $("logoutBtn").addEventListener("click", () => {
    clearSession();
    location.reload();
  });
  $("sitePick").addEventListener("change", () => applySite());
}

async function bootApp() {
  tickClock();
  setInterval(tickClock, 30_000);
  bindTabs();
  await loadSites();
}

async function boot() {
  bindAuth();
  if (!readToken()) {
    $("loginGate").hidden = false;
    $("logoutBtn").hidden = true;
    return;
  }
  $("loginGate").hidden = true;
  $("logoutBtn").hidden = false;
  await bootApp();
}

boot();
