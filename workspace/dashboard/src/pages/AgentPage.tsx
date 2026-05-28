import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type Context = {
  repo_root: string;
  codex_available: boolean;
  agent_shell: string;
  note: string;
};

export default function AgentPage() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [message, setMessage] = useState("Summarize BACnet + FDD next steps for this site.");
  const [reply, setReply] = useState("");

  useEffect(() => {
    apiFetch<Context>("/openfdd-agent/context").then(setCtx).catch((e) => setReply(String(e)));
  }, []);

  async function send(e: FormEvent) {
    e.preventDefault();
    setReply("…");
    try {
      const res = await apiFetch<{ ok: boolean; mode: string; reply: string }>(
        "/openfdd-agent/chat",
        {
          method: "POST",
          body: JSON.stringify({ message, workdir: ctx?.repo_root }),
        },
      );
      setReply(`[${res.mode}] ok=${res.ok}\n\n${res.reply}`);
    } catch (err) {
      setReply(String(err));
    }
  }

  return (
    <div>
      <h2>AI Agent</h2>
      <p className="muted">
        HTTP chat uses Codex CLI on the bridge when available. Prefer{" "}
        <code>openfdd-agent-shell</code> for Cursor / OpenClaw / Claude Code on the host.
      </p>
      {ctx ? (
        <div className="panel muted">
          <div>Codex on PATH: {String(ctx.codex_available)}</div>
          <div>{ctx.agent_shell}</div>
          <div>{ctx.note}</div>
        </div>
      ) : null}
      <form className="panel" onSubmit={send}>
        <label htmlFor="agent-message">Chat message</label>
        <textarea
          id="agent-message"
          rows={5}
          style={{ width: "100%" }}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <div className="row">
          <button type="submit">Send</button>
        </div>
      </form>
      <div className="panel console">{reply || "Send a message or use CLI on the host."}</div>
    </div>
  );
}
