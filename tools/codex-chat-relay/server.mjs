#!/usr/bin/env node
/**
 * Open-FDD ↔ Codex CLI chat relay (WSL dev — not shipped in GHCR).
 * Edge POST /api/agent/chat → codex exec → OpenAI Codex with project MCP + agents.
 */
import http from "node:http";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { resolveAgent, loadCodexAgentBlock } from "../agent-routing.mjs";

const readFile = promisify(fs.readFile);
const writeFile = promisify(fs.writeFile);
const mkdir = promisify(fs.mkdir);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(process.env.OPENFDD_REPO_ROOT || path.join(__dirname, "../.."));
const PORT = Number(process.env.OFDD_CODEX_CHAT_PORT || 8788);
const HOST = process.env.OFDD_CODEX_CHAT_HOST || "127.0.0.1";
const MODEL = process.env.OFDD_CODEX_AGENT_MODEL || "gpt-5.4-mini";
const SESSION_DIR = path.join(REPO_ROOT, "workspace/agent-chat");
const SESSION_FILE = path.join(SESSION_DIR, "codex-session-id.txt");
const TOOLSHED = path.join(REPO_ROOT, "workspace/agent-toolshed");
const EXEC_TIMEOUT_MS = Number(process.env.OFDD_CODEX_EXEC_TIMEOUT_MS || 600000);

/** @type {import('node:child_process').ChildProcess | null} */
let activeExec = null;

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) });
  res.end(payload);
}

function buildPrompt(body, route, agentBlock) {
  const message = String(body.message || "").trim();
  const contextPath = String(body.context_path || "/");
  const history = Array.isArray(body.history) ? body.history : [];
  const live = body.live ? JSON.stringify(body.live, null, 2) : "{}";
  const hist =
    history.length === 0
      ? ""
      : `\nRecent chat:\n${history
          .slice(-8)
          .map((t) => `${t.role}: ${t.content}`)
          .join("\n")}`;
  const skillLine = route.skillHint ? `\nSuggested skill: ${route.skillHint}` : "";
  const agentHeader = agentBlock.instructions
    ? `\n--- Agent: ${route.agent} ---\n${agentBlock.instructions}\n---\n`
    : `\nAgent role: ${route.agent}${skillLine}\n`;

  return `[Open-FDD operator UI — tab ${contextPath}]
${agentHeader}
Use openfdd MCP tools (JWT already configured). Scratch work in workspace/agent-toolshed/.
Live bridge snapshot:
${live}
${hist}

User: ${message}`;
}

function runProcess(cmd, args, { input, env, cwd, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd,
      env: { ...process.env, ...env },
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr.on("data", (d) => {
      stderr += d.toString();
    });
    if (input) child.stdin.write(input);
    child.stdin.end();

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`codex exec timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.on("close", (code) => {
      clearTimeout(timer);
      if (activeExec === child) activeExec = null;
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(stderr.trim() || stdout.trim() || `codex exit ${code}`));
    });
    child.on("error", (err) => {
      if (activeExec === child) activeExec = null;
      reject(err);
    });

    activeExec = child;
  });
}

async function codexLoggedIn() {
  try {
    const { stderr } = await runProcess("codex", ["doctor"], { cwd: REPO_ROOT, timeoutMs: 15000 });
    return !/not logged in|login required/i.test(stderr);
  } catch {
    return true; // doctor flaky — assume ok if codex exists
  }
}

async function mcpSmoke() {
  try {
    const { stdout } = await runProcess("codex", ["mcp", "list"], { cwd: REPO_ROOT, timeoutMs: 20000 });
    return /openfdd/i.test(stdout);
  } catch {
    return false;
  }
}

async function runCodexChat(prompt, contextPath, route, agentBlock) {
  await mkdir(SESSION_DIR, { recursive: true });
  await mkdir(TOOLSHED, { recursive: true });
  const outFile = path.join(SESSION_DIR, `codex-out-${Date.now()}.txt`);
  const useResume = fs.existsSync(SESSION_FILE) && contextPath !== "/agent";
  const model = agentBlock.model || route.model || MODEL;
  const sandbox = agentBlock.sandbox || route.sandbox || "workspace-write";
  const args = [
    "exec",
    "-m",
    model,
    "--dangerously-bypass-approvals-and-sandbox",
    "-s",
    sandbox,
    "-C",
    REPO_ROOT,
    "-o",
    outFile,
  ];
  if (agentBlock.reasoning) {
    args.push("-c", `model_reasoning_effort="${agentBlock.reasoning}"`);
  }
  if (useResume) {
    args.push("resume", "--last");
  }
  args.push("-");

  const started = Date.now();
  const { stdout, stderr } = await runProcess("codex", args, {
    input: `${prompt}\n`,
    cwd: REPO_ROOT,
    timeoutMs: EXEC_TIMEOUT_MS,
  });

  let reply = "";
  if (fs.existsSync(outFile)) {
    reply = (await readFile(outFile, "utf8")).trim();
  }
  if (!reply) {
    reply = stdout
      .split("\n")
      .filter((l) => l.trim() && !l.startsWith("warning:") && !l.startsWith("tokens used"))
      .pop()
      ?.trim();
  }
  if (!reply) reply = stderr.split("\n").find((l) => l.trim() && !l.startsWith("warning:")) || "(empty reply)";

  return { reply, duration_ms: Date.now() - started, stderr };
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      const loggedIn = await codexLoggedIn();
      const mcpOk = await mcpSmoke();
      const sampleRoute = resolveAgent("/csv", "profile csv");
      return sendJson(res, 200, {
        ok: true,
        service: "openfdd-codex-chat-relay",
        codex_logged_in: loggedIn,
        openfdd_mcp_configured: mcpOk,
        repo_root: REPO_ROOT,
        model: MODEL,
        routing: "context_path",
        sample_route: sampleRoute.agent,
        toolshed: TOOLSHED,
      });
    }
    if (req.method === "POST" && req.url === "/chat") {
      const body = await readJson(req);
      if (!String(body.message || "").trim()) {
        return sendJson(res, 400, { ok: false, error: "message required" });
      }
      try {
        const contextPath = String(body.context_path || "/");
        const route = resolveAgent(contextPath, String(body.message || ""));
        const agentBlock = loadCodexAgentBlock(REPO_ROOT, route);
        const prompt = buildPrompt(body, route, agentBlock);
        const out = await runCodexChat(prompt, contextPath, route, agentBlock);
        return sendJson(res, 200, {
          ok: true,
          reply: out.reply,
          source: "codex",
          duration_ms: out.duration_ms,
          agent: route.agent,
          model: agentBlock.model || route.model,
          sandbox: agentBlock.sandbox || route.sandbox,
        });
      } catch (e) {
        return sendJson(res, 502, { ok: false, error: String(e.message || e), source: "codex" });
      }
    }
    if (req.method === "POST" && req.url === "/cancel") {
      if (activeExec) {
        try {
          activeExec.kill("SIGTERM");
        } catch {
          /* ignore */
        }
        activeExec = null;
        return sendJson(res, 200, { ok: true, cancelled: true });
      }
      return sendJson(res, 200, { ok: true, cancelled: false, note: "no active exec" });
    }
    if (req.method === "POST" && req.url === "/reset") {
      for (const f of [SESSION_FILE]) {
        try {
          fs.unlinkSync(f);
        } catch {
          /* ignore */
        }
      }
      return sendJson(res, 200, { ok: true, reset: true });
    }
    sendJson(res, 404, { ok: false, error: "not found" });
  } catch (e) {
    sendJson(res, 500, { ok: false, error: String(e) });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`openfdd-codex-chat-relay http://${HOST}:${PORT} cwd=${REPO_ROOT}`);
});
