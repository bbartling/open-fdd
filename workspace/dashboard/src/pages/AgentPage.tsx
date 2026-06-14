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
  gpu_available?: boolean;
  interactive_chat_enabled?: boolean;
  interactive_chat_disabled_reason?: string;
  ollama_ram_tier: string;
  ollama_model: string;
  ollama_gpu_mode: string;
  ollama_thinking_models?: ThinkingModel[];
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
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [chat.messages, chat.busy]);

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
        if (c.interactive_chat_enabled !== true) {
          clearAgentChat();
          setChat(loadAgentChat());
        } else {
          setChat((prev) => ({
            ...prev,
            model: prev.model || c.ollama_model || "",
          }));
        }
      })
      .catch((e) => {
        logTabInfo("agent", formatApiError(e));
      });
  }, []);

  const isGptOss = chat.model.toLowerCase().includes("gpt-oss");
  const levelOptions = isGptOss ? GPT_OSS_LEVELS : BOOL_LEVELS;

  function thinkPayload(): boolean | string | undefined {
    if (chat.thinkLevel === THINK_OFF) return undefined;
    if (isGptOss) return chat.thinkLevel;
    return true;
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!ctx || !chat.draft.trim() || chat.busy || !chatEnabled) return;
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
  const chatEnabled = ctx?.interactive_chat_enabled === true;
  const thinkingModels = ctx?.ollama_thinking_models || [];
  const installed = ctx?.ollama?.models_installed || [];
  const modelOptions = [...new Set([...installed, ...thinkingModels.map((m) => m.model)])];

  return (
    <div className={`page page-agent${chatEnabled ? "" : " page-agent-disabled"}`}>
      <div className="page-agent-top">
        <PageHeader
          title="AI Agent"
          subtitle={
            chatEnabled
              ? "Local operator assistant. Right-click a message to delete; recent turns are sent within a token budget."
              : "Local chat requires Ollama with GPU or a configured RAM tier — not available on CPU-only edges."
          }
        />
        <TabDebugPanel tab="agent" />
        {!ctx ? (
          <p className="agent-offline-banner">Checking local AI service…</p>
        ) : !chatEnabled ? (
          <div className="agent-unavailable-panel panel">
            <h3 className="panel-title">Local AI unavailable</h3>
            <p>
              {ctx.interactive_chat_disabled_reason ||
                "Ollama is not running or this edge is CPU-only without a configured model tier. Use Building status, Rule Lab, MCP (/mcp), or an external agent (Cursor, OpenClaw) instead."}
            </p>
            {ctx.gpu_available === false ? (
              <p className="muted">GPU: not detected · RAM tier: {ctx.ollama_ram_tier || "—"}</p>
            ) : null}
          </div>
        ) : null}
      </div>

      {chatEnabled ? (
      <div className="agent-layout">
        <div ref={logRef} className="agent-chat-log">
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
            <div className="agent-empty-state">
              <p>Start a conversation</p>
              <p className="agent-empty-hint">
                Ask about BACnet, faults, or site data. On CPU hosts, turn Thinking off for faster replies.
              </p>
            </div>
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
              Delete from here down…
            </button>
          </div>
        ) : null}

        <form className="agent-compose" onSubmit={send}>
          <div className="agent-compose-toolbar">
            <div className="field field-compact">
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
                {modelOptions.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            <div className="field field-compact">
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
            <div className="agent-compose-actions">
              <button type="submit" disabled={chat.busy || !chatEnabled}>
                {chat.busy ? "Waiting…" : "Send"}
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => {
                  clearAgentChat();
                  setChat(loadAgentChat());
                }}
              >
                Clear
              </button>
            </div>
          </div>
          <div className="field agent-message-field">
            <label className="field-label" htmlFor="agent-message">
              Message
            </label>
            <textarea
              id="agent-message"
              rows={3}
              value={chat.draft}
              onChange={(e) => setChat({ ...chat, draft: e.target.value })}
              placeholder="Ask about BACnet, faults, or site data…"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void send(e);
                }
              }}
            />
          </div>
        </form>
      </div>
      ) : null}
    </div>
  );
}
