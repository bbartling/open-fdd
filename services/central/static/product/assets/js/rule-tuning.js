import { apiFetch } from "./api.js";
import {
  effectiveRunParams,
  loadLocalRuleParams,
  mergeRuleParams,
  notifyRulesUpdated,
  numericParamsFromSession,
  OPERATIONAL_GATE_KEY,
  ruleNeedsRun,
  saveLocalRuleParams,
  stampOperationalGate,
} from "./rule-params.js";
import {
  displayScalar,
  displayStep,
  displayUnitLabel,
  formatTunerCaption,
  resolveQuantityKind,
  storeScalar,
} from "./role-units.js";
import {
  fetchSessionConfig,
  getFddRuleParams,
  putSessionConfig,
  rerunFddAfterRuleUpdate,
} from "./fdd-api.js";

const UNITS_KEY = "openfdd.ui.display_units";
const VALUE_EPS = 1e-9;

let buildingId = "";
let equipId = "";
let selectedRuleId = "";
let rulesMeta = [];
let sessionConfig = null;
let draftParams = {};
let appliedParams = {};
let paramDefs = null;
let canEdit = false;
let opsGate = true;
let tuningBound = false;

const $ = (id) => document.getElementById(id);

function unitSystem() {
  return localStorage.getItem(UNITS_KEY) === "metric" ? "metric" : "imperial";
}

function setMsg(text, isErr) {
  const el = $("tuningMsg");
  if (!el) return;
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    el.classList.remove("ops-err");
    return;
  }
  el.hidden = false;
  el.textContent = text;
  el.classList.toggle("ops-err", Boolean(isErr));
}

async function refreshAuth() {
  const denied = $("tuningDenied");
  const panel = $("tuningPanel");
  try {
    const me = await apiFetch("/api/auth/me");
    const role = String(me?.role ?? me?.user?.role ?? "").toLowerCase();
    canEdit = role === "admin" || role === "operator";
    if (denied) denied.hidden = canEdit;
    if (panel) panel.hidden = !canEdit;
    if (!canEdit && denied) {
      denied.textContent = "Rule tuning requires admin or operator role.";
    }
  } catch {
    canEdit = false;
    if (denied) {
      denied.hidden = false;
      denied.textContent = "Sign in as admin or operator to tune rules.";
    }
    if (panel) panel.hidden = true;
  }
}

async function loadParamDefs(ruleId) {
  if (!ruleId) {
    paramDefs = null;
    return;
  }
  paramDefs = await getFddRuleParams(ruleId);
}

function draftForRule(ruleId) {
  return { ...(draftParams[ruleId] ?? {}) };
}

function appliedForRule(ruleId) {
  return { ...(appliedParams[ruleId] ?? {}) };
}

function renderTuningFields() {
  const host = $("tuningFields");
  if (!host) return;
  host.replaceChildren();
  if (!selectedRuleId) {
    host.appendChild(document.createTextNode("Select a rule to tune."));
    return;
  }
  if (!canEdit) return;
  if (!paramDefs || !Object.keys(paramDefs).length) {
    host.appendChild(document.createTextNode("No tunable parameters for this rule."));
    return;
  }
  const entries = Object.entries(paramDefs).sort(([a], [b]) => a.localeCompare(b));
  const draft = draftForRule(selectedRuleId);
  const applied = appliedForRule(selectedRuleId);
  for (const [key, def] of entries) {
    if (key === OPERATIONAL_GATE_KEY) continue;
    const quantity = resolveQuantityKind(def.unit, key, def.quantity);
    const stored = draft[key] ?? def.default;
    const shown = displayScalar(stored, def.unit, unitSystem(), quantity, key);
    const min = displayScalar(def.min, def.unit, unitSystem(), quantity, key);
    const max = displayScalar(def.max, def.unit, unitSystem(), quantity, key);
    const step = displayStep(def.step, def.unit, unitSystem(), quantity, key);
    const unitLabel = displayUnitLabel(def.unit, unitSystem(), quantity, key);
    const label = document.createElement("label");
    label.className = "tuning-field";
    const title = document.createElement("span");
    title.className = "tuning-label";
    title.textContent = `${def.label || key}${unitLabel ? ` (${unitLabel})` : ""}`;
    const input = document.createElement("input");
    input.type = "range";
    input.min = String(min);
    input.max = String(max);
    input.step = String(step);
    input.value = String(shown);
    input.disabled = def.effect === "unsupported" || def.effect === "no_op";
    input.addEventListener("input", () => {
      const next = storeScalar(Number(input.value), def.unit, unitSystem(), quantity, key);
      draftParams = {
        ...draftParams,
        [selectedRuleId]: { ...draftForRule(selectedRuleId), [key]: next },
      };
      caption.textContent = formatTunerCaption(Number(input.value), quantity);
      $("tuningResetBtn").disabled = false;
      $("tuningSaveBtn").disabled = false;
      updateRerunButton(entries, draftParams[selectedRuleId], applied, opsGate);
    });
    const caption = document.createElement("span");
    caption.className = "hint";
    caption.textContent = formatTunerCaption(shown, quantity);
    label.append(title, input, caption);
    host.appendChild(label);
  }
  updateRerunButton(entries, draft, applied, opsGate);
}

function updateRerunButton(entries, draft, applied, gate) {
  const btn = $("tuningRerunBtn");
  if (!btn) return;
  const needs = ruleNeedsRun(entries, draft, applied, gate);
  btn.disabled = !buildingId || !equipId || !selectedRuleId || !needs;
}

async function seedFromSession() {
  sessionConfig = await fetchSessionConfig(buildingId);
  const merged = mergeRuleParams(
    numericParamsFromSession(sessionConfig?.config?.params),
    loadLocalRuleParams(buildingId),
  );
  draftParams = merged;
  appliedParams = JSON.parse(JSON.stringify(merged));
  if (typeof sessionConfig?.config?.require_operational_proof === "boolean") {
    opsGate = sessionConfig.config.require_operational_proof;
  }
}

export async function onRuleTuningRuleChange(ruleId, equip, rules, config) {
  selectedRuleId = ruleId;
  equipId = equip;
  rulesMeta = rules;
  sessionConfig = config;
  await refreshAuth();
  if (buildingId) await seedFromSession();
  try {
    await loadParamDefs(ruleId);
    renderTuningFields();
  } catch (err) {
    setMsg(err.message || String(err), true);
  }
}

export function onRuleTuningSiteChange(site) {
  buildingId = site;
}

export function bindRuleTuningPanel() {
  if (tuningBound) return;
  tuningBound = true;
  refreshAuth().catch(() => {});
  $("tuningSaveBtn")?.addEventListener("click", () => {
    void (async () => {
      if (!canEdit || !buildingId || !selectedRuleId) return;
      setMsg("Saving…", false);
      try {
        const baseConfig = sessionConfig?.config ?? { schema: "openfdd_session_v1", params: {} };
        const nextParams = { ...(baseConfig.params ?? {}) };
        nextParams[selectedRuleId] = {
          ...(nextParams[selectedRuleId] ?? {}),
          ...draftForRule(selectedRuleId),
        };
        const payload = {
          ...baseConfig,
          params: nextParams,
          require_operational_proof: opsGate,
        };
        const saved = await putSessionConfig(buildingId, payload);
        sessionConfig = saved;
        saveLocalRuleParams(draftParams, buildingId);
        appliedParams = JSON.parse(JSON.stringify(draftParams));
        notifyRulesUpdated();
        setMsg("Saved session config.", false);
        renderTuningFields();
      } catch (err) {
        setMsg(err.message || String(err), true);
      }
    })();
  });
  $("tuningResetBtn")?.addEventListener("click", () => {
    if (!selectedRuleId || !paramDefs) return;
    const resetBag = {};
    for (const [key, def] of Object.entries(paramDefs)) {
      if (key === OPERATIONAL_GATE_KEY) continue;
      resetBag[key] = def.default;
    }
    draftParams = { ...draftParams, [selectedRuleId]: resetBag };
    renderTuningFields();
    setMsg("Draft reset to catalog defaults (not saved yet).", false);
  });
  $("tuningRerunBtn")?.addEventListener("click", () => {
    void (async () => {
      if (!canEdit || !buildingId || !equipId || !selectedRuleId) return;
      setMsg("Saving and re-running rule…", false);
      try {
        const baseConfig = sessionConfig?.config ?? { schema: "openfdd_session_v1", params: {} };
        const nextParams = { ...(baseConfig.params ?? {}) };
        nextParams[selectedRuleId] = {
          ...(nextParams[selectedRuleId] ?? {}),
          ...draftForRule(selectedRuleId),
        };
        const payload = {
          ...baseConfig,
          params: nextParams,
          require_operational_proof: opsGate,
        };
        const saved = await putSessionConfig(buildingId, payload);
        sessionConfig = saved;
        saveLocalRuleParams(draftParams, buildingId);
        appliedParams = JSON.parse(JSON.stringify(draftParams));
        notifyRulesUpdated();
        await rerunFddAfterRuleUpdate(buildingId, equipId, selectedRuleId, rulesMeta);
        sessionConfig = await fetchSessionConfig(buildingId);
        appliedParams = JSON.parse(JSON.stringify(effectiveRunParams(sessionConfig, buildingId)));
        setMsg("Rule re-run complete.", false);
        renderTuningFields();
      } catch (err) {
        setMsg(err.message || String(err), true);
      }
    })();
  });
}

export function readbackMatchesDraft(ruleId) {
  const draft = draftForRule(ruleId);
  const applied = appliedForRule(ruleId);
  for (const [key, val] of Object.entries(draft)) {
    const other = applied[key];
    if (other == null || Math.abs(other - val) > VALUE_EPS) return false;
  }
  return true;
}
