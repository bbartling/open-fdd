import { FormEvent, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  appendPendingAssistant,
  appendUserMessage,
  buildChatHistoryPayload,
  loadAgentChat,
  resolveAssistant,
  saveAgentChat,
  type AgentChatState,
} from "../lib/agentChatStore";

const STORAGE_KEY = "ofdd_home_ollama_enabled";

type Context = {
  ollama: { ok?: boolean };
  ollama_model: string;
  ollama_ram_tier: string;
  ollama_gpu_mode: string;
};

type ChatResponse = {
  ok: boolean;
  reply?: string;
  error?: string;
  hint?: string;
  duration_ms?: number;
};

export function homeOllamaEnabled(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) return true;
    return raw === "1" || raw === "true";
  } catch {
    return true;
  }
}

export function setHomeOllamaEnabled(on: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function HomeOllamaToggle({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label className="home-ollama-toggle">
      <span>Local Ollama chat on home</span>
      <input
        type="checkbox"
        className="home-ollama-switch"
        checked={enabled}
        onChange={(e) => {
          const on = e.target.checked;
          setHomeOllamaEnabled(on);
          onChange(on);
        }}
      />
      <span className="home-ollama-switch-ui" aria-hidden="true" />
    </label>
  );
}

export default function HomeOllamaChat() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [chat, setChat] = useState<AgentChatState>(() => loadAgentChat());
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    saveAgentChat(chat);
  }, [chat]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.messages, chat.busy]);

  useEffect(() => {
    apiFetch<Context>("/openfdd-agent/context")
      .then((c) => {
        setCtx(c);
        setChat((prev) => ({ ...prev, model: prev.model || c.ollama_model || "" }));
      })
      .catch(() => setCtx(null));
  }, []);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!ctx || !chat.draft.trim() || chat.busy) return;
    const text = chat.draft.trim();
    const history = buildChatHistoryPayload(chat.messages);
    let next = appendUserMessage(chat, text);
    const pending = appendPendingAssistant(next);
    next = pending.state;
    setChat(next);
    const started = Date.now();
    try {
      const res = await apiFetch<ChatResponse>("/openfdd-agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message: text,
          history,
          ram_tier: ctx.ollama_ram_tier,
          model: chat.model || ctx.ollama_model,
          gpu_mode: ctx.ollama_gpu_mode,
        }),
      });
      const content = res.ok
        ? res.reply || "(empty)"
        : res.error || res.hint || "Ollama request failed";
      setChat((prev) =>
        resolveAssistant(prev, pending.id, content, "", res.ok, {
          durationMs: res.duration_ms ?? Date.now() - started,
        }),
      );
    } catch (err) {
      setChat((prev) =>
        resolveAssistant(prev, pending.id, formatApiError(err), "", false, {
          durationMs: Date.now() - started,
        }),
      );
    }
  }

  const ollamaOk = ctx?.ollama?.ok === true;

  return (
    <section className="panel home-ollama-panel">
      <h3 className="panel-title">Building assistant</h3>
      {!ollamaOk ? (
        <p className="muted">Ollama is offline — use Host stats or restart the local stack.</p>
      ) : null}
      <div ref={logRef} className="home-ollama-log">
        {chat.messages.length ? (
          chat.messages.slice(-6).map((m) => (
            <div key={m.id} className={`home-ollama-msg home-ollama-${m.role}`}>
              <strong>{m.role === "user" ? "You" : "Assistant"}</strong>
              <p>{m.content}</p>
            </div>
          ))
        ) : (
          <p className="muted">Ask about open faults, BACnet, or rule tuning.</p>
        )}
      </div>
      <form className="home-ollama-form" onSubmit={send}>
        <input
          type="text"
          value={chat.draft}
          onChange={(e) => setChat((prev) => ({ ...prev, draft: e.target.value }))}
          placeholder="Message local Ollama…"
          disabled={!ollamaOk || chat.busy}
        />
        <button type="submit" disabled={!ollamaOk || chat.busy || !chat.draft.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
