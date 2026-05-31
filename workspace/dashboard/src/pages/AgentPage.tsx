import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  appendPendingAssistant,
  appendUserMessage,
  clearAgentChat,
  loadAgentChat,
  resolveAssistant,
  saveAgentChat,
  type AgentChatState,
} from "../lib/agentChatStore";
import PageHeader from "../components/PageHeader";
import { TabDebugPanel, logTabInfo } from "../components/TabDebugPanel";

type ThinkingModel = { model: string; label: string; think: "boolean" | "level"; approx_vram_gb?: number };

type Context = {
  ollama: { ok?: boolean; error?: string; models_installed?: string[] };
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
};

const THINK_OFF = "off";
const BOOL_LEVELS = [THINK_OFF, "on"];
const GPT_OSS_LEVELS = [THINK_OFF, "low", "medium", "high"];

export default function AgentPage() {
  const [chat, setChat] = useState<AgentChatState>(() => loadAgentChat());
  const [ctx, setCtx] = useState<Context | null>(null);

  useEffect(() => {
    saveAgentChat(chat);
  }, [chat]);

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

  function thinkPayload(): boolean | string | undefined {
    if (chat.thinkLevel === THINK_OFF) return undefined;
    if (isGptOss) return chat.thinkLevel;
    return true;
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!ctx || !chat.draft.trim() || chat.busy) return;
    const text = chat.draft.trim();
    let next = appendUserMessage(chat, text);
    const pending = appendPendingAssistant(next);
    next = pending.state;
    setChat(next);
    saveAgentChat(next);

    try {
      const res = await apiFetch<ChatResponse>("/openfdd-agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message: text,
          ram_tier: ctx.ollama_ram_tier,
          model: chat.model || ctx.ollama_model,
          gpu_mode: ctx.ollama_gpu_mode,
          think: thinkPayload(),
        }),
      });
      const content = res.ok
        ? res.reply || "(empty response)"
        : res.error || res.hint || res.reply || "Ollama request failed";
      setChat((prev) =>
        resolveAssistant(prev, pending.id, content, res.thinking || "", res.ok),
      );
    } catch (err) {
      setChat((prev) =>
        resolveAssistant(prev, pending.id, formatApiError(err), "", false),
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
        subtitle="Local operator assistant — Ollama on this host. Conversation is saved in your browser; switch tabs while the model thinks."
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
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="agent-chat-log panel">
        {chat.messages.length ? (
          chat.messages.map((m) => (
            <div key={m.id} className={`agent-chat-msg agent-chat-${m.role} ${m.status}`}>
              <strong>{m.role === "user" ? "You" : "Assistant"}</strong>
              {m.status === "pending" ? <span className="badge poll-badge">thinking…</span> : null}
              <div className="agent-chat-text">{m.content}</div>
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
            {chat.busy ? "Thinking…" : "Send"}
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
