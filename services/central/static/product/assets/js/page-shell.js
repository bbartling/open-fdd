import { readToken, writeToken, clearSession } from "./session.js";
import { apiFetch, login } from "./api.js";

export function bindLogin(onReady) {
  const gate = document.getElementById("loginGate");
  const form = document.getElementById("loginForm");
  const logoutBtn = document.getElementById("logoutBtn");
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const errEl = document.getElementById("loginErr");
    errEl.hidden = true;
    const data = new FormData(form);
    try {
      const body = await login(data.get("username"), data.get("password"));
      const token = body.token || body.access_token;
      if (!token) throw new Error("Login response missing token");
      writeToken(token);
      gate.hidden = true;
      logoutBtn.hidden = false;
      await onReady();
    } catch (err) {
      errEl.textContent = err.message || "Sign in failed";
      errEl.hidden = false;
    }
  });
  logoutBtn?.addEventListener("click", () => {
    clearSession();
    location.reload();
  });
  if (!readToken()) {
    gate.hidden = false;
    logoutBtn.hidden = true;
    return false;
  }
  gate.hidden = true;
  logoutBtn.hidden = false;
  return true;
}

export async function fillSitePicker(selectId, onChange) {
  const pick = document.getElementById(selectId);
  if (!pick) return "";
  pick.innerHTML = "";
  try {
    const sessions = await apiFetch("/api/sessions/buildings");
    const buildings = sessions?.buildings ?? sessions?.items ?? [];
    for (const row of buildings || []) {
      const id = row.building_id ?? row.id ?? row;
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      pick.appendChild(opt);
    }
  } catch {
    const fromQuery = new URLSearchParams(location.search).get("site") || "";
    const opt = document.createElement("option");
    opt.value = fromQuery;
    opt.textContent = fromQuery || "(set ?site=)";
    pick.appendChild(opt);
  }
  const fromQuery = new URLSearchParams(location.search).get("site");
  if (fromQuery) pick.value = fromQuery;
  pick.addEventListener("change", () => onChange(pick.value));
  return pick.value;
}

export async function fillEquipPicker(selectId, equips, value) {
  const pick = document.getElementById(selectId);
  if (!pick) return "";
  pick.innerHTML =
    `<option value="">— select —</option>` +
    equips.map((e) => `<option value="${e.id}">${e.name || e.id}</option>`).join("");
  pick.value = value || equips[0]?.id || "";
  return pick.value;
}
