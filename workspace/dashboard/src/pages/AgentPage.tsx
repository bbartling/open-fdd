import { FormEvent, useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { formatDurationMs } from "../lib/formatDuration";
import {
  appendPendingAssistant,
  appendUserMessage,
  buildChatHistoryPayload,
  clearAgentChat,
  deleteMessage,
  deleteMessageAndAfter,
  loadAgentChat,
  resolveAssistant,
  saveAgentChat,
  type AgentChatState,
  type ChatMessage,
} from "../lib/agentChatStore";
import PageHeader from "../components/PageHeader";
import { TabDebugPanel, logTabInfo } from "../components/TabDebugPanel";

type ThinkingModel = { model: string; label: string; think: "boolean" | "level"; approx_vram_gb?: number };

type Context = {
  ollama: { ok?: boolean; error?: string; models_installed?: string[] };
  ollama_ram_tier: string;
  ollama_model: string;
  ollama_gpu_mode: string;
  ollama_timeout_s?: number;
  ollama_thinking_models?: ThinkingModel[];
  mcp?: {
    mcp_enabled?: boolean;
    mcp_rest_base?: string;
    mcp_search_docs?: string;
    note?: string;
  };
};

type ChatResponse = {
  ok: boolean;
  mode: string;
  reply: string;
  thinking?: string;
  model?: string;
  error?: string;
  hint?: string;
  duration_ms?: number;
  eval_count?: number;
  tokens_per_sec?: number;
};

const THINK_OFF = "off";
const BOOL_LEVELS = [THINK_OFF, "on"];
const GPT_OSS_LEVELS = [THINK_OFF, "low", "medium", "high"];

function useNowTick(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function isThinkingModel(model: string): boolean {
  const m = model.toLowerCase();
  return m.includes("qwen3") || m.includes("deepseek-r1") || m.includes("gpt-oss");
}

function formatTimingMeta(m: ChatMessage): string | null {
  if (m.status === "pending") return null;
  if (m.durationMs == null) return null;
  const parts = [`${formatDurationMs(m.durationMs)}`];
  if (m.tokensPerSec != null && m.tokensPerSec > 0) {
    parts.push(`${m.tokensPerSec} tok/s`);
  }
  if (m.evalCount != null && m.evalCount > 0) {
    parts.push(`${m.evalCount} tokens`);
  }
  return parts.join(" · ");
}

function AgentMessageTiming({ message, nowMs }: { message: ChatMessage; nowMs: number }) {
  if (message.status === "pending") {
    const started = Date.parse(message.createdAt);
    const elapsed = Number.isFinite(started) ? nowMs - started : 0;
    return (
      <span className="agent-chat-timing agent-chat-timing-live">
        thinking… {formatDurationMs(elapsed)}
      </span>
    );
  }
  const meta = formatTimingMeta(message);
  if (!meta) return null;
  return (
    <span className={`agent-chat-timing ${message.status === "error" ? "agent-chat-timing-error" : ""}`}>
      {message.status === "error" ? "failed after" : "responded in"} {meta}
    </span>
  );
}

export default function AgentPage() {
  const [chat, setChat] = useState<AgentChatState>(() => loadAgentChat());
  const [ctx, setCtx] = useState<Context | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; messageId: string } | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const nowMs = useNowTick(chat.busy);

  useEffect(() => {
    saveAgentChat(chat);
  }, [chat]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [menu]);

  const openMessageMenu = useCallback((e: MouseEvent, messageId: string) => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY, messageId });
  }, []);

  useEffect(() => {
    apiFetch<Context>("/openfdd-agent/context")
      .then((c) => {
        setCtx(c);
        setChat((prev) => ({
          ...prev,
          model: prev.model || c.ollama_model || "",
        }));
      })
      .catch((e) => {
        logTabInfo("agent", formatApiError(e));
      });
  }, []);

  const isGptOss = chat.model.toLowerCase().includes("gpt-oss");
  const levelOptions = isGptOss ? GPT_OSS_LEVELS : BOOL_LEVELS;
  const thinkOn = chat.thinkLevel !== THINK_OFF;
  const cpuMode = (ctx?.ollama_gpu_mode || "cpu").toLowerCase() === "cpu";
  const showSlowHint = cpuMode && (thinkOn || isThinkingModel(chat.model));

  function thinkPayload(): boolean | string | undefined {
    if (chat.thinkLevel === THINK_OFF) return undefined;
    if (isGptOss) return chat.thinkLevel;
    return true;
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!ctx || !chat.draft.trim() || chat.busy) return;
    const text = chat.draft.trim();
    const history = buildChatHistoryPayload(chat.messages);
    let next = appendUserMessage(chat, text);
    const pending = appendPendingAssistant(next);
    next = pending.state;
    setChat(next);
    saveAgentChat(next);
    const clientStarted = Date.now();

    try {
      const res = await apiFetch<ChatResponse>("/openfdd-agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message: text,
          history,
          ram_tier: ctx.ollama_ram_tier,
          model: chat.model || ctx.ollama_model,
          gpu_mode: ctx.ollama_gpu_mode,
          think: thinkPayload(),
        }),
      });
      const content = res.ok
        ? res.reply || "(empty response)"
        : res.error || res.hint || res.reply || "Ollama request failed";
      const clientMs = Date.now() - clientStarted;
      setChat((prev) =>
        resolveAssistant(prev, pending.id, content, res.thinking || "", res.ok, {
          durationMs: res.duration_ms ?? clientMs,
          evalCount: res.eval_count,
          tokensPerSec: res.tokens_per_sec,
        }),
      );
    } catch (err) {
      const clientMs = Date.now() - clientStarted;
      setChat((prev) =>
        resolveAssistant(prev, pending.id, formatApiError(err), "", false, {
          durationMs: clientMs,
        }),
      );
    }
  }

  const ollamaOk = ctx?.ollama?.ok === true;
  const thinkingModels = ctx?.ollama_thinking_models || [];
  const installed = ctx?.ollama?.models_installed || [];

  return (
    <div className="page">
      <PageHeader
        title="AI Agent"
        subtitle="Local operator assistant — Ollama on this host. Right-click a message to delete. Recent turns are sent to the model within a token budget."
      />
      <TabDebugPanel tab="agent" />

      {ctx ? (
        <div className="panel">
          <div className="status-bar">
            <div className="status-kv">
              <span className="status-kv-label">Ollama</span>
              <span className={`status-kv-value ${ollamaOk ? "ok" : "error"}`}>
                {ollamaOk ? "running" : "down"}
              </span>
            </div>
            {chat.model ? (
              <>
                <div className="status-kv">
                  <span className="status-kv-label">Model</span>
                  <span className="status-kv-value">{chat.model}</span>
                </div>
                <div className="status-kv">
                  <span className="status-kv-label">Runtime</span>
                  <span className="status-kv-value">
                    {ctx.ollama_ram_tier}, {ctx.ollama_gpu_mode}
                  </span>
                </div>
                {ctx.ollama_timeout_s ? (
                  <div className="status-kv">
                    <span className="status-kv-label">Server timeout</span>
                    <span className="status-kv-value">{formatDurationMs(ctx.ollama_timeout_s * 1000)}</span>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
          {showSlowHint ? (
            <p className="agent-slow-hint muted">
              CPU + {thinkOn ? "Thinking on" : "thinking models"} can take <strong>several minutes</strong> per reply
              (10m+ is possible on a loaded host). For faster answers: set Thinking to <strong>off</strong>, keep prompts
              short, or set <code>OFDD_OLLAMA_GPU_MODE=auto</code> if you have a GPU.
            </p>
          ) : null}
          {ctx.mcp?.mcp_enabled ? (
            <p className="muted agent-mcp-hint">
              MCP RAG: <code>{ctx.mcp.mcp_rest_base}</code> — doc search at{" "}
              <code>{ctx.mcp.mcp_search_docs}</code> (included in agent system prompt).
            </p>
          ) : ctx.mcp?.note ? (
            <p className="muted agent-mcp-hint">{ctx.mcp.note}</p>
          ) : null}
        </div>
      ) : null}

      <div ref={logRef} className="agent-chat-log panel">
        {chat.messages.length ? (
          chat.messages.map((m) => (
            <div
              key={m.id}
              className={`agent-chat-msg agent-chat-${m.role} ${m.status}`}
              onContextMenu={(e) => openMessageMenu(e, m.id)}
            >
              <div className="agent-chat-head">
                <strong>{m.role === "user" ? "You" : "Assistant"}</strong>
                <AgentMessageTiming message={m} nowMs={nowMs} />
              </div>
              {m.status === "pending" ? null : <div className="agent-chat-text">{m.content}</div>}
              {m.thinking ? (
                <details>
                  <summary>Thinking trace</summary>
                  <pre className="console">{m.thinking}</pre>
                </details>
              ) : null}
            </div>
          ))
        ) : (
          <p className="muted">No messages yet.</p>
        )}
      </div>

      {menu ? (
        <div
          className="agent-chat-menu"
          style={{ top: menu.y, left: menu.x }}
          role="menu"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setChat((prev) => deleteMessage(prev, menu.messageId));
              setMenu(null);
            }}
          >
            Delete message
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setChat((prev) => deleteMessageAndAfter(prev, menu.messageId));
              setMenu(null);
            }}
          >
            Delete from here…
          </button>
        </div>
      ) : null}

      <form className="panel agent-compose" onSubmit={send}>
        <h3 className="panel-title">Compose message</h3>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="agent-model">
              Model
            </label>
            <input
              id="agent-model"
              value={chat.model}
              onChange={(e) => setChat({ ...chat, model: e.target.value })}
              list="ollama-models"
            />
            <datalist id="ollama-models">
              {[...new Set([...installed, ...thinkingModels.map((m) => m.model)])].map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="agent-thinking">
              Thinking
            </label>
            <select
              id="agent-thinking"
              value={chat.thinkLevel}
              onChange={(e) => setChat({ ...chat, thinkLevel: e.target.value })}
            >
              {levelOptions.map((lvl) => (
                <option key={lvl} value={lvl}>
                  {lvl}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="agent-message">
            Message
          </label>
          <textarea
            id="agent-message"
            rows={4}
            value={chat.draft}
            onChange={(e) => setChat({ ...chat, draft: e.target.value })}
            placeholder="Ask about BACnet, faults, or site data…"
          />
        </div>
        <div className="toolbar">
          <button type="submit" disabled={chat.busy || !ollamaOk}>
            {chat.busy ? "Waiting for Ollama…" : "Send"}
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => {
              clearAgentChat();
              setChat(loadAgentChat());
            }}
          >
            Clear history
          </button>
        </div>
      </form>
    </div>
  );
}
