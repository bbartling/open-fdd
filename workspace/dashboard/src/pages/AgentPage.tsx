import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type Tier = {
  ram_tier: string;
  model: string;
  label: string;
  description: string;
};

type GpuOption = {
  id: string;
  label: string;
  detail: string;
};

type Context = {
  repo_root: string;
  codex_available: boolean;
  agent_shell: string;
  note: string;
  ai_backend_default: string;
  ollama: { ok?: boolean; error?: string; models_installed?: string[] };
  ollama_ram_tier: string;
  ollama_model: string;
  ollama_gpu_mode: string;
  ollama_tiers: Tier[];
  ollama_gpu_options: GpuOption[];
};

type Backend = "auto" | "ollama" | "codex";

export default function AgentPage() {
  const [ctx, setCtx] = useState<Context | null>(null);
  const [message, setMessage] = useState("Summarize BACnet + FDD next steps for this site.");
  const [reply, setReply] = useState("");
  const [backend, setBackend] = useState<Backend>("auto");
  const [ramTier, setRamTier] = useState("8gb");
  const [gpuMode, setGpuMode] = useState("cpu");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<Context>("/openfdd-agent/context")
      .then((c) => {
        setCtx(c);
        setRamTier(c.ollama_ram_tier || "8gb");
        setGpuMode(c.ollama_gpu_mode || "cpu");
        if (c.ai_backend_default === "ollama" || c.ai_backend_default === "codex") {
          setBackend(c.ai_backend_default);
        }
      })
      .catch((e) => setReply(String(e)));
  }, []);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setReply("…");
    try {
      const tier = ctx?.ollama_tiers?.find((t) => t.ram_tier === ramTier);
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
          workdir: ctx?.repo_root,
          backend,
          ram_tier: ramTier,
          model: tier?.model,
          gpu_mode: gpuMode,
        }),
      });
      const head = `[${res.mode}] ok=${String(res.ok)}${res.model ? ` model=${res.model}` : ""}`;
      setReply(`${head}\n\n${res.reply || res.error || res.hint || ""}`);
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
      <p className="muted">
        <strong>Local:</strong> Ollama on this host (operator chat).{" "}
        <strong>Remote:</strong> Cursor / Claude Code / Codex against{" "}
        <code>{ctx?.repo_root ?? "this repo"}</code> for heavy work.
      </p>

      {ctx ? (
        <div className="panel muted stack-page">
          <div>
            Ollama:{" "}
            <span className={ollamaOk ? "ok" : "error"}>{ollamaOk ? "running" : "down"}</span>
            {ctx.ollama_model ? ` · configured ${ctx.ollama_model}` : null}
          </div>
          {!ollamaOk ? (
            <div>
              Bootstrap:{" "}
              <code>./scripts/bootstrap_ollama.sh --ram-tier 8gb</code> (flimsiest — TinyLlama)
            </div>
          ) : null}
          <div>Codex on PATH (remote-style): {String(ctx.codex_available)}</div>
          <div>{ctx.note}</div>
        </div>
      ) : null}

      <form className="panel" onSubmit={send}>
        <div className="form-row">
          <label>
            Backend
            <select value={backend} onChange={(e) => setBackend(e.target.value as Backend)}>
              <option value="auto">Auto (Ollama if up, else Codex)</option>
              <option value="ollama">Ollama (local)</option>
              <option value="codex">Codex CLI (remote dev)</option>
            </select>
          </label>
          <label>
            RAM tier
            <select value={ramTier} onChange={(e) => setRamTier(e.target.value)}>
              {(ctx?.ollama_tiers ?? [{ ram_tier: "8gb", model: "tinyllama", label: "8GB", description: "" }]).map(
                (t) => (
                  <option key={t.ram_tier} value={t.ram_tier}>
                    {t.ram_tier} — {t.label} ({t.model})
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            GPU
            <select value={gpuMode} onChange={(e) => setGpuMode(e.target.value)}>
              {(ctx?.ollama_gpu_options ?? [{ id: "cpu", label: "CPU" }]).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted">
          {ctx?.ollama_tiers?.find((t) => t.ram_tier === ramTier)?.description ??
            "8gb = TinyLlama smoke test for low-RAM lab hosts."}
        </p>
        <label htmlFor="agent-message">Message</label>
        <textarea
          id="agent-message"
          rows={5}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Thinking…" : "Send"}
          </button>
        </div>
      </form>
      <div className="panel console">{reply || "Send a message or bootstrap Ollama first."}</div>
    </div>
  );
}
