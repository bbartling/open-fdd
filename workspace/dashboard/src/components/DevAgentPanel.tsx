import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiFetch, hasToken } from "../lib/api";
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

type ChatResponse = {
  ok?: boolean;
  reply?: string;
  thinking?: string;
  error?: string;
  source?: "ollama" | "tools" | "cursor" | "codex";
  ollama_ok?: boolean;
  duration_ms?: number;
  eval_count?: number;
};

export default function DevAgentPanel() {
  const location = useLocation();
  const [open, setOpen] = useState(true);
  const [chat, setChat] = useState<AgentChatState>(() => loadAgentChat());
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    saveAgentChat(chat);
  }, [chat]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages]);

  const send = useCallback(async () => {
    const text = chat.draft.trim();
    if (!text || chat.busy) return;
    if (!hasToken()) {
      setChat((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          {
            id: `err-${Date.now()}`,
            role: "assistant",
            content: "Sign in to use the agent panel.",
            status: "error",
            createdAt: new Date().toISOString(),
          },
        ],
        draft: "",
      }));
      return;
    }

    setChat((prev) => {
      const withUser = appendUserMessage(prev, text);
      const pending = appendPendingAssistant(withUser);
      void (async () => {
        try {
          const history = buildChatHistoryPayload(pending.state.messages.slice(0, -1));
          const out = await apiFetch<ChatResponse>("/api/agent/chat", {
            method: "POST",
            body: JSON.stringify({
              message: text,
              context_path: location.pathname,
              history,
            }),
          });
          const reply = out.reply ?? out.error ?? "No reply";
          const ok = out.ok !== false && !!out.reply;
          setChat((cur) =>
            resolveAssistant(cur, pending.id, reply, out.thinking ?? "", ok, {
              durationMs: out.duration_ms,
              evalCount: out.eval_count,
            }),
          );
        } catch (e) {
          setChat((cur) => resolveAssistant(cur, pending.id, formatApiError(e), "", false));
        }
      })();
      return pending.state;
    });
  }, [chat.draft, chat.busy, location.pathname]);

  if (!open) {
    return (
      <button type="button" className="agent-rail-toggle" onClick={() => setOpen(true)} aria-label="Open agent panel">
        Agent
      </button>
    );
  }

  return (
    <aside className="agent-rail" aria-label="AI agent assistance">
      <div className="agent-rail-header">
        <span className="agent-rail-title">Agent assist</span>
        <button type="button" className="linkish-btn" onClick={() => setOpen(false)} aria-label="Collapse agent panel">
          ×
        </button>
      </div>
      <p className="agent-rail-context muted">
        Tab: {location.pathname} · <a href="/agent">AI settings</a>
      </p>
      <div className="agent-rail-messages">
        {chat.messages.length === 0 ? (
          <div className="agent-rail-line agent-rail-line--assistant">
            Ask about this tab — Codex CLI (WSL) when relay is up, else Cursor/Ollama/tools.
          </div>
        ) : null}
        {chat.messages.map((line) => (
          <div key={line.id} className={`agent-rail-line agent-rail-line--${line.role}`}>
            {line.status === "pending" ? "…" : line.content}
            {line.role === "assistant" && line.status === "done" ? (
              <span className="agent-rail-meta muted">
                {line.durationMs != null ? ` · ${(line.durationMs / 1000).toFixed(1)}s` : ""}
              </span>
            ) : null}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form
        className="agent-rail-input"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={chat.draft}
          onChange={(e) => setChat((prev) => ({ ...prev, draft: e.target.value }))}
          placeholder="Ask about this tab…"
          disabled={chat.busy}
          aria-label="Agent message"
        />
        <button type="submit" className="primary-btn" disabled={chat.busy || !chat.draft.trim()}>
          {chat.busy ? "…" : "Send"}
        </button>
      </form>
    </aside>
  );
}
