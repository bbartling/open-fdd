import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

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
  const [ctx, setCtx] = useState<Context | null>(null);
  const [message, setMessage] = useState("hello");
  const [reply, setReply] = useState("");
  const [thinking, setThinking] = useState("");
  const [showThinking, setShowThinking] = useState(true);
  const [model, setModel] = useState("");
  const [thinkLevel, setThinkLevel] = useState(THINK_OFF);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch<Context>("/openfdd-agent/context")
      .then((c) => {
        setCtx(c);
        setModel(c.ollama_model || "");
      })
      .catch((e) => setReply(String(e)));
  }, []);

  // gpt-oss only accepts low/medium/high; everything else uses a boolean toggle.
  const isGptOss = model.toLowerCase().includes("gpt-oss");
  const levelOptions = isGptOss ? GPT_OSS_LEVELS : BOOL_LEVELS;

  function thinkPayload(): boolean | string | undefined {
    if (thinkLevel === THINK_OFF) return undefined;
    if (isGptOss) return thinkLevel; // "low" | "medium" | "high"
    return true;
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!ctx) return;
    setBusy(true);
    setReply("…");
    setThinking("");
    try {
      const res = await apiFetch<ChatResponse>("/openfdd-agent/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          ram_tier: ctx.ollama_ram_tier,
          model: model || ctx.ollama_model,
          gpu_mode: ctx.ollama_gpu_mode,
          think: thinkPayload(),
        }),
      });
      if (!res.ok) {
        setReply(res.error || res.hint || res.reply || "Ollama request failed");
        return;
      }
      setThinking(res.thinking || "");
      setReply(res.reply || "(empty response)");
    } catch (err) {
      setReply(String(err));
    } finally {
      setBusy(false);
    }
  }

  const ollamaOk = ctx?.ollama?.ok === true;
  const thinkingModels = ctx?.ollama_thinking_models || [];
  const installed = ctx?.ollama?.models_installed || [];
  const modelIsThinking = thinkingModels.some((m) => model.toLowerCase().startsWith(m.model));
  const thinkEnabled = thinkLevel !== THINK_OFF;

  return (
    <div>
      <h2 className="title">AI Agent</h2>
      <p className="muted">Local operator assistant — Ollama on this host.</p>

      {ctx ? (
        <div className="panel muted stack-page">
          <div>
            Ollama:{" "}
            <span className={ollamaOk ? "ok" : "error"}>{ollamaOk ? "running" : "down"}</span>
            {model ? (
              <>
                {" "}
                · {model} ({ctx.ollama_ram_tier}, {ctx.ollama_gpu_mode})
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
        <div className="row">
          <label>
            Model{" "}
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. qwen3"
              list="ollama-models"
              style={{ width: 200 }}
            />
            <datalist id="ollama-models">
              {[...new Set([...installed, ...thinkingModels.map((m) => m.model)])].map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>
          <label>
            Thinking{" "}
            <select value={thinkLevel} onChange={(e) => setThinkLevel(e.target.value)}>
              {levelOptions.map((lvl) => (
                <option key={lvl} value={lvl}>
                  {lvl}
                </option>
              ))}
            </select>
          </label>
          {thinkEnabled ? (
            <label>
              <input
                type="checkbox"
                checked={showThinking}
                onChange={(e) => setShowThinking(e.target.checked)}
              />{" "}
              Show trace
            </label>
          ) : null}
        </div>
        {thinkEnabled && !modelIsThinking ? (
          <p className="muted">
            Note: <code>{model}</code> may not be a thinking model. Use{" "}
            {thinkingModels.map((m) => m.model).join(", ") || "qwen3, deepseek-r1, gpt-oss"} to see a
            reasoning trace (<code>ollama pull {model || "qwen3"}</code>).
          </p>
        ) : null}
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

      {thinking && showThinking ? (
        <details className="panel" open>
          <summary>Thinking trace</summary>
          <div className="console">{thinking}</div>
        </details>
      ) : null}

      <div className="panel console">{reply || "Send a message when Ollama is running."}</div>
    </div>
  );
}
