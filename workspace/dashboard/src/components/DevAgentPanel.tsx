import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import CodexSpinner from "./CodexSpinner";
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
  agent?: string;
  ollama_ok?: boolean;
  duration_ms?: number;
  eval_count?: number;
};

export default function DevAgentPanel() {
  const location = useLocation();
  const [open, setOpen] = useState(true);
  const [chat, setChat] = useState<AgentChatState>(() => loadAgentChat());
  const [queue, setQueue] = useState<string[]>([]);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const queueRef = useRef<string[]>([]);
  const busyRef = useRef(false);

  useEffect(() => {
    saveAgentChat(chat);
  }, [chat]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages, queue.length]);

  const runChat = useCallback(
    async (text: string, historyMessages: AgentChatState["messages"]) => {
      busyRef.current = true;
      setActiveSource("codex");
      const ac = new AbortController();
      abortRef.current = ac;
      const pending = appendPendingAssistant({
        messages: historyMessages,
        draft: "",
        model: chat.model,
        thinkLevel: chat.thinkLevel,
        busy: true,
        pendingMessageId: null,
      });
      setChat(pending.state);

      try {
        const history = buildChatHistoryPayload(historyMessages);
        const out = await apiFetch<ChatResponse>("/api/agent/chat", {
          method: "POST",
          signal: ac.signal,
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
        setActiveSource(out.source ?? null);
      } catch (e) {
        const aborted = e instanceof DOMException && e.name === "AbortError";
        setChat((cur) =>
          resolveAssistant(
            cur,
            pending.id,
            aborted ? "Stopped — request cancelled." : formatApiError(e),
            "",
            false,
          ),
        );
      } finally {
        abortRef.current = null;
        busyRef.current = false;
        setActiveSource(null);
        const next = queueRef.current.shift();
        setQueue([...queueRef.current]);
        if (next?.trim()) {
          setChat((cur) => {
            void runChat(next, cur.messages);
            return cur;
          });
        }
      }
    },
    [chat.model, chat.thinkLevel, location.pathname],
  );

  const send = useCallback(() => {
    const text = chat.draft.trim();
    if (!text) return;
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

    if (busyRef.current) {
      setChat((prev) => {
        const withUser = appendUserMessage(prev, text);
        queueRef.current.push(text);
        setQueue([...queueRef.current]);
        return withUser;
      });
      return;
    }

    setChat((prev) => {
      const withUser = appendUserMessage(prev, text);
      void runChat(text, withUser.messages.slice(0, -1));
      return withUser;
    });
  }, [chat.draft, runChat]);

  const stopAgent = useCallback(async () => {
    abortRef.current?.abort();
    try {
      await apiFetch("/api/agent/chat/cancel", { method: "POST" });
    } catch {
      /* relay may be offline */
    }
  }, []);

  const clearQueue = useCallback(() => {
    queueRef.current = [];
    setQueue([]);
  }, []);

  if (!open) {
    return (
      <button type="button" className="agent-rail-toggle" onClick={() => setOpen(true)} aria-label="Open agent panel">
        {chat.busy ? <CodexSpinner label="" size={16} /> : null}
        Agent
      </button>
    );
  }

  return (
    <aside className="agent-rail" aria-label="AI agent assistance">
      <div className="agent-rail-header">
        <span className="agent-rail-title">
          Agent assist
          {chat.busy ? (
            <span className="agent-rail-working">
              <CodexSpinner label="Codex" size={16} />
            </span>
          ) : null}
        </span>
        <button type="button" className="linkish-btn" onClick={() => setOpen(false)} aria-label="Collapse agent panel">
          ×
        </button>
      </div>
      <p className="agent-rail-context muted">
        Tab: {location.pathname} · <a href="/agent">AI settings</a>
        {activeSource ? ` · ${activeSource}` : null}
      </p>
      {queue.length > 0 ? (
        <div className="agent-rail-queue">
          <span className="muted">{queue.length} queued</span>
          <button type="button" className="linkish-btn" onClick={clearQueue}>
            Clear queue
          </button>
        </div>
      ) : null}
      <div className="agent-rail-messages">
        {chat.messages.length === 0 ? (
          <div className="agent-rail-line agent-rail-line--assistant">
            Ask about this tab — Codex CLI (WSL) when relay is up. Queue prompts while working; Stop cancels the run.
          </div>
        ) : null}
        {chat.messages.map((line) => (
          <div key={line.id} className={`agent-rail-line agent-rail-line--${line.role}`}>
            {line.status === "pending" ? (
              <span className="agent-rail-pending">
                <CodexSpinner label="Codex thinking…" size={16} />
              </span>
            ) : (
              line.content
            )}
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
          send();
        }}
      >
        <input
          value={chat.draft}
          onChange={(e) => setChat((prev) => ({ ...prev, draft: e.target.value }))}
          placeholder={chat.busy ? "Queue another prompt…" : "Ask about this tab…"}
          aria-label="Agent message"
        />
        {chat.busy ? (
          <button type="button" className="secondary-btn agent-stop-btn" onClick={() => void stopAgent()}>
            Stop
          </button>
        ) : null}
        <button type="submit" className="primary-btn" disabled={!chat.draft.trim()}>
          {chat.busy ? "Queue" : "Send"}
        </button>
      </form>
    </aside>
  );
}
