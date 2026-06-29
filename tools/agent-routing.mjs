/**
 * Context-aware agent routing for Open-FDD in-app chat (Codex + Cursor relays).
 */
import fs from "node:fs";
import path from "node:path";

const DEFAULT_MODEL = process.env.OFDD_CODEX_AGENT_MODEL || "gpt-5.4-mini";

/** @typedef {{ agent: string, agentFile: string, model: string, sandbox: string, reasoning?: string, skillHint?: string }} Route */

/**
 * @param {string} contextPath
 * @param {string} message
 * @returns {Route}
 */
export function resolveAgent(contextPath, message) {
  const path = String(contextPath || "/").toLowerCase();
  const msg = String(message || "");

  if (
    /test (fail|error|failed)|clippy|eslint|lint fail|econnrefused|404|500|cargo test|npm test failed/i.test(
      msg,
    )
  ) {
    return route("simple_test_triage", "simple-test-triage.toml", "read-only", "low");
  }

  if (/pr review|code review|multi-agent|release readiness|security.reliability/i.test(msg)) {
    return route("release_risk_reviewer", "release-risk-reviewer.toml", "read-only", "medium", {
      skillHint: "$multi-agent-pr-review",
    });
  }

  if (path.includes("/csv") || /\bcsv\b|feather|arrow|merge.*kw|school.?year|import session/i.test(msg)) {
    return route("csv_data_assistant", "csv-data-assistant.toml", "workspace-write", "medium", {
      skillHint: "$codebase-research-pass",
    });
  }

  if (
    path.includes("/model") ||
    path.includes("/sql-fdd") ||
    path.includes("/fdd") ||
    /fdd|datafusion|assignment|sparql|haystack|fault rule|equation/i.test(msg)
  ) {
    return route("fdd_model_assistant", "fdd-model-assistant.toml", "workspace-write", "high", {
      skillHint: "$spec-contract-compliance-review",
    });
  }

  if (
    path.includes("/bacnet") ||
    path.includes("/haystack") ||
    path.includes("/agent") ||
    /deploy|docker|auth|release|driver|commission|bootstrap/i.test(msg)
  ) {
    return route("openfdd_retrofit_orchestrator", "openfdd-retrofit-orchestrator.toml", "workspace-write", "medium");
  }

  return route("openfdd_retrofit_orchestrator", "openfdd-retrofit-orchestrator.toml", "workspace-write", "medium");
}

/** @param {string} agent @param {string} agentFile @param {string} sandbox @param {string} reasoning @param {{ skillHint?: string }} [extra] */
function route(agent, agentFile, sandbox, reasoning, extra = {}) {
  return {
    agent,
    agentFile,
    model: DEFAULT_MODEL,
    sandbox,
    reasoning,
    skillHint: extra.skillHint,
  };
}

/**
 * @param {string} repoRoot
 * @param {Route} route
 */
export function loadCodexAgentBlock(repoRoot, route) {
  const filePath = path.join(repoRoot, ".codex/agents", route.agentFile);
  if (!fs.existsSync(filePath)) {
    return { instructions: "", model: route.model, sandbox: route.sandbox };
  }
  const text = fs.readFileSync(filePath, "utf8");
  const instructions = text.match(/developer_instructions\s*=\s*"""(.*?)"""/s)?.[1]?.trim() || "";
  const model = text.match(/^model\s*=\s*"([^"]+)"/m)?.[1] || route.model;
  const sandbox = text.match(/^sandbox_mode\s*=\s*"([^"]+)"/m)?.[1] || route.sandbox;
  const reasoning = text.match(/^model_reasoning_effort\s*=\s*"([^"]+)"/m)?.[1] || route.reasoning;
  return { instructions, model, sandbox, reasoning };
}

/**
 * @param {string} repoRoot
 * @param {string} agentName e.g. csv_data_assistant → csv-data-assistant.md
 */
export function loadCursorAgentBlock(repoRoot, agentName) {
  const slug = agentName.replace(/_/g, "-");
  const filePath = path.join(repoRoot, ".cursor/agents", `${slug}.md`);
  if (!fs.existsSync(filePath)) return "";
  return fs.readFileSync(filePath, "utf8").trim();
}
