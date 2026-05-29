import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type Context = {
  ollama: { ok?: boolean; error?: string; models_installed?: string[] };
  ollama_ram_tier: string;
  ollama_model: string;
  ollama_gpu_mode: string;
};

export default function AgentPage() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [message, setMessage] = useState("hello");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<Context>("/openfdd-agent/context")
      .then(setCtx)
      .catch((e) => setReply(String(e)));
  }, []);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!ctx) return;
    setBusy(true);
    setReply("…");
    try {
      const res = await apiFetch<{
        ok: boolean;
        mode: string;
        reply: string;
        model?: string;
        error?: string;
        hint?: string;
      }>("/openfdd-agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          ram_tier: ctx.ollama_ram_tier,
          model: ctx.ollama_model,
          gpu_mode: ctx.ollama_gpu_mode,
        }),
      });
      if (!res.ok) {
        setReply(res.error || res.hint || res.reply || "Ollama request failed");
        return;
      }
      setReply(res.reply || "(empty response)");
    } catch (err) {
      setReply(String(err));
    } finally {
      setBusy(false);
    }
  }

  const ollamaOk = ctx?.ollama?.ok === true;

  return (
    <div>
      <h2 className="title">AI Agent</h2>
      <p className="muted">Local operator assistant — Ollama on this host.</p>

      {ctx ? (
        <div className="panel muted stack-page">
          <div>
            Ollama:{" "}
            <span className={ollamaOk ? "ok" : "error"}>{ollamaOk ? "running" : "down"}</span>
            {ctx.ollama_model ? (
              <>
                {" "}
                · {ctx.ollama_model} ({ctx.ollama_ram_tier}, {ctx.ollama_gpu_mode})
              </>
            ) : null}
          </div>
          {!ollamaOk ? (
            <div>
              Bootstrap: <code>./scripts/bootstrap_ollama.sh --user-local --ram-tier 8gb</code>
            </div>
          ) : null}
        </div>
      ) : null}

      <form className="panel" onSubmit={send}>
        <label htmlFor="agent-message">Message</label>
        <textarea
          id="agent-message"
          rows={5}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <div className="row">
          <button type="submit" disabled={busy || !ollamaOk}>
            {busy ? "Thinking…" : "Send"}
          </button>
        </div>
      </form>
      <div className="panel console">{reply || "Send a message when Ollama is running."}</div>
    </div>
  );
}
