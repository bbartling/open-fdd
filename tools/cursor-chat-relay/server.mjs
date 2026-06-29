#!/usr/bin/env node
/**
 * Open-FDD ↔ Cursor chat relay (WSL dev).
 * Edge POST /api/agent/chat → this service → Cursor SDK local agent.
 *
 * Env:
 *   CURSOR_API_KEY          — required (cursor.com/settings)
 *   OPENFDD_REPO_ROOT       — repo root (default: two levels up)
 *   OFDD_CURSOR_CHAT_PORT   — listen port (default 8787)
 *   OFDD_CURSOR_AGENT_MODEL — default composer-2.5
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Agent, CursorAgentError } from "@cursor/sdk";
import { resolveAgent, loadCursorAgentBlock } from "../agent-routing.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(
  process.env.OPENFDD_REPO_ROOT ||
    process.env.OPENFDD_WORKSPACE ||
    path.join(__dirname, "../.."),
);
const PORT = Number(process.env.OFDD_CURSOR_CHAT_PORT || 8787);
const HOST = process.env.OFDD_CURSOR_CHAT_HOST || "127.0.0.1";
const MODEL = process.env.OFDD_CURSOR_AGENT_MODEL || "composer-2.5";
const API_KEY = process.env.CURSOR_API_KEY || "";
const AGENT_DIR = path.join(REPO_ROOT, "workspace/agent-chat");
const AGENT_ID_FILE = path.join(AGENT_DIR, "cursor-agent-id.txt");

/** @type {import('@cursor/sdk').Agent | null} */
let agent = null;

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8") || "{}";
        resolve(JSON.parse(raw));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function loadAgentId() {
  try {
    return fs.readFileSync(AGENT_ID_FILE, "utf8").trim() || null;
  } catch {
    return null;
  }
}

function saveAgentId(id) {
  fs.mkdirSync(AGENT_DIR, { recursive: true });
  fs.writeFileSync(AGENT_ID_FILE, `${id}\n`, "utf8");
}

async function ensureAgent() {
  if (!API_KEY) {
    throw new Error("CURSOR_API_KEY not set — add to workspace/cursor.env.local or shell env");
  }
  if (agent) return agent;

  const savedId = loadAgentId();
  if (savedId) {
    try {
      agent = await Agent.resume(savedId, { apiKey: API_KEY });
      return agent;
    } catch {
      // stale id — create fresh
    }
  }

  agent = await Agent.create({
    apiKey: API_KEY,
    model: { id: MODEL },
    local: { cwd: REPO_ROOT },
  });
  if (agent?.id) saveAgentId(agent.id);
  return agent;
}

function buildPrompt(body, route) {
  const message = String(body.message || "").trim();
  const contextPath = String(body.context_path || "/");
  const history = Array.isArray(body.history) ? body.history : [];
  const historyBlock =
    history.length === 0
      ? ""
      : `\n\nRecent conversation:\n${history
          .slice(-8)
          .map((t) => `${t.role}: ${t.content}`)
          .join("\n")}`;
  const agentDoc = loadCursorAgentBlock(REPO_ROOT, route.agent);
  const agentBlock = agentDoc ? `\n${agentDoc}\n` : `\nAgent: ${route.agent}\n`;

  return `[Open-FDD operator UI — tab ${contextPath}]
${agentBlock}
Answer concisely. Use live stack context when provided.
Never suggest unsupervised field-bus writes.${historyBlock}

User: ${message}`;
}

async function handleChat(body) {
  const started = Date.now();
  const contextPath = String(body.context_path || "/");
  const route = resolveAgent(contextPath, String(body.message || ""));
  const a = await ensureAgent();
  const prompt = buildPrompt(body, route);
  const run = await a.send(prompt);
  const result = await run.wait();
  if (result.status === "error") {
    return {
      ok: false,
      error: `Cursor run failed (${result.id})`,
      source: "cursor",
    };
  }
  const text =
    typeof result.result === "string"
      ? result.result
      : result.result?.text || JSON.stringify(result.result ?? "");
  return {
    ok: true,
    reply: text.trim() || "(empty reply)",
    source: "cursor",
    duration_ms: Date.now() - started,
    agent_id: a.id || loadAgentId(),
    agent: route.agent,
  };
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      return sendJson(res, 200, {
        ok: true,
        service: "openfdd-cursor-chat-relay",
        has_api_key: Boolean(API_KEY),
        repo_root: REPO_ROOT,
        model: MODEL,
        agent_id: loadAgentId(),
      });
    }
    if (req.method === "POST" && req.url === "/chat") {
      const body = await readJson(req);
      if (!String(body.message || "").trim()) {
        return sendJson(res, 400, { ok: false, error: "message required" });
      }
      try {
        const out = await handleChat(body);
        return sendJson(res, out.ok ? 200 : 502, out);
      } catch (e) {
        const msg = e instanceof CursorAgentError ? e.message : String(e);
        return sendJson(res, 502, { ok: false, error: msg, source: "cursor" });
      }
    }
    sendJson(res, 404, { ok: false, error: "not found" });
  } catch (e) {
    sendJson(res, 500, { ok: false, error: String(e) });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`openfdd-cursor-chat-relay http://${HOST}:${PORT} cwd=${REPO_ROOT}`);
  if (!API_KEY) {
    console.warn("WARN: CURSOR_API_KEY missing — /chat will fail until set");
  }
});
