import { openClawUiUrl } from "../lib/openfdd-claw";
import {
  type CronDraft,
  type CronValidation,
  type ShellFlavor,
  buildCronAddCommand,
  buildCronCleanupCommand,
  buildMemoryCleanupCommands,
  buildSkillsRefreshCommands,
  validateCronExpression,
} from "../lib/openfdd-claw-ops";
import { useMemo, useState } from "react";
import {
  OPENCLAW_CRON_ENDPOINT_PRESETS,
  buildCronApiPreview,
  createCronJobViaApi,
} from "../lib/openfdd-claw-gateway";
import {
  PHASE2_CRON_RELAXED_PRESET,
  PHASE2_CRON_STRICT_PRESET,
  PHASE3_MEMORY_GOVERNANCE_PRESET,
  PHASE3_SUBAGENT_LANES_PRESET,
  SECURITY_SAFE_DEFAULTS_PRESET,
  SIMPLE_COMPLEX_POLICY_PRESET,
} from "../lib/openfdd-claw-policy";

export function OpenClawChatPage() {
  const [draft, setDraft] = useState<CronDraft>({
    name: "Open-FDD Site Sweep",
    schedule: "0 */6 * * *",
    tz: "America/Chicago",
    message: "Run Open-FDD health checks, ingest checks, and FDD summary for active sites.",
    session: "isolated",
    failureDestination: "ops-alerts",
    alertOnSkipped: true,
    idempotencyKey: "open-fdd-site-sweep-v1",
    reconcileTag: "portfolio-default",
    correlationIdPrefix: "ofdd",
  });
  const [shell, setShell] = useState<ShellFlavor>("posix");
  const [mode, setMode] = useState<"commands" | "api">("commands");
  const [copiedKey, setCopiedKey] = useState<string>("");
  const [apiEndpointPath, setApiEndpointPath] = useState<string>(OPENCLAW_CRON_ENDPOINT_PRESETS[0]?.endpointPath ?? "");
  const [apiToken, setApiToken] = useState<string>("");
  const [apiBusy, setApiBusy] = useState(false);
  const [apiResult, setApiResult] = useState<string>("");
  const cronCommand = useMemo(() => buildCronAddCommand(draft, shell), [draft, shell]);
  const memoryCommand = useMemo(() => buildMemoryCleanupCommands(shell), [shell]);
  const cronValidation: CronValidation = useMemo(
    () => validateCronExpression(draft.schedule),
    [draft.schedule],
  );
  const cronCleanup = useMemo(() => buildCronCleanupCommand(), []);
  const skillsOps = useMemo(() => buildSkillsRefreshCommands(), []);
  const allOpsCommands = useMemo(
    () =>
      [
        "# Cron add",
        cronCommand,
        "",
        "# Cron cleanup",
        cronCleanup,
        "",
        "# Reconciliation visibility",
        "openclaw cron runs --recent 20",
        "",
        "# Skills refresh",
        skillsOps,
        "",
        "# Memory cleanup",
        memoryCommand,
      ].join("\n"),
    [cronCommand, cronCleanup, skillsOps, memoryCommand],
  );
  const cronExamples = useMemo(
    () => [
      "@hourly",
      "0 7 * * *",
      "0 */6 * * *",
      "*/15 * * * *",
      "0 9 * * 1-5",
    ],
    [],
  );
  const apiPreview = useMemo(
    () =>
      buildCronApiPreview({
        endpointPath: apiEndpointPath,
        token: apiToken,
        payload: {
          name: draft.name,
          cron: draft.schedule,
          tz: draft.tz,
          session: draft.session,
          message: draft.message,
          failureDestination: draft.failureDestination || undefined,
          alertOnSkipped: draft.alertOnSkipped,
          idempotencyKey: draft.idempotencyKey || undefined,
          reconcileTag: draft.reconcileTag || undefined,
          correlationIdPrefix: draft.correlationIdPrefix || undefined,
        },
      }),
    [apiEndpointPath, apiToken, draft],
  );

  async function copyText(key: string, value: string) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const el = document.createElement("textarea");
        el.value = value;
        document.body.appendChild(el);
        el.select();
        document.execCommand("copy");
        document.body.removeChild(el);
      }
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(""), 1400);
    } catch {
      setCopiedKey("");
    }
  }

  async function createViaApi() {
    if (!cronValidation.valid) {
      setApiResult("Cron expression is invalid. Fix cron format before API submit.");
      return;
    }
    setApiBusy(true);
    setApiResult("");
    try {
      const out = await createCronJobViaApi({
        endpointPath: apiEndpointPath,
        token: apiToken,
        payload: {
          name: draft.name,
          cron: draft.schedule,
          tz: draft.tz,
          session: draft.session,
          message: draft.message,
          failureDestination: draft.failureDestination || undefined,
          alertOnSkipped: draft.alertOnSkipped,
          idempotencyKey: draft.idempotencyKey || undefined,
          reconcileTag: draft.reconcileTag || undefined,
          correlationIdPrefix: draft.correlationIdPrefix || undefined,
        },
      });
      setApiResult(`HTTP ${out.status}\n${out.body}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setApiResult(`Request failed: ${msg}`);
    } finally {
      setApiBusy(false);
    }
  }

  return (
    <section className="stack-page">
      <div className="card">
        <h2 className="title">Open-FDD Claw Chat</h2>
        <p className="muted">
          Open-FDD Claw workspace (OpenClaw-inspired) for operator chat and agent workflows.
        </p>
        <p className="muted">
          Set <code>VITE_OPENFDDCLAW_UI_URL</code> (or legacy <code>VITE_OPENCLAW_UI_URL</code>) to point at your Open-FDD Claw UI,
          for example <code>http://127.0.0.1:18789/webchat</code>.
        </p>
        <div className="openclaw-actions">
          <a href={openClawUiUrl} target="_blank" rel="noreferrer" className="link-btn">
            Open in new tab
          </a>
          <span className="muted">Current URL: {openClawUiUrl}</span>
        </div>
      </div>
      <div className="card">
        <h3 className="title">Operations (Cron / Memory / Skills)</h3>
        <p className="muted">
          Open-FDD Claw Cron runs in the gateway and can wake the agent on schedule.
          Use these generated commands in your terminal or in Open-FDD Claw operator workflows.
        </p>
        <div className="openclaw-actions">
          <span className="inline-label">Runbook shell:</span>
          <button
            type="button"
            className={`theme-btn ${shell === "posix" ? "active" : ""}`}
            onClick={() => setShell("posix")}
          >
            POSIX
          </button>
          <button
            type="button"
            className={`theme-btn ${shell === "powershell" ? "active" : ""}`}
            onClick={() => setShell("powershell")}
          >
            PowerShell
          </button>
          <span className="inline-label">Mode:</span>
          <button
            type="button"
            className={`theme-btn ${mode === "commands" ? "active" : ""}`}
            onClick={() => setMode("commands")}
          >
            Commands
          </button>
          <button
            type="button"
            className={`theme-btn ${mode === "api" ? "active" : ""}`}
            onClick={() => setMode("api")}
          >
            Create via API
          </button>
        </div>
        <div className="grid-two">
          <label>
            Job name
            <input
              value={draft.name}
              onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
            />
          </label>
          <label>
            Cron schedule
            <input
              value={draft.schedule}
              onChange={(e) => setDraft((prev) => ({ ...prev, schedule: e.target.value }))}
            />
          </label>
          <label>
            Timezone
            <input
              value={draft.tz}
              onChange={(e) => setDraft((prev) => ({ ...prev, tz: e.target.value }))}
            />
          </label>
          <label>
            Session type
            <select
              value={draft.session}
              onChange={(e) =>
                setDraft((prev) => ({ ...prev, session: e.target.value as "isolated" | "main" }))
              }
            >
              <option value="isolated">isolated</option>
              <option value="main">main</option>
            </select>
          </label>
        </div>
        <div className="openclaw-actions">
          <span className="inline-label">Cron examples:</span>
          {cronExamples.map((example) => (
            <button
              key={example}
              type="button"
              className="secondary-btn"
              onClick={() => setDraft((prev) => ({ ...prev, schedule: example }))}
            >
              {example}
            </button>
          ))}
          <button
            type="button"
            className="secondary-btn"
            onClick={() =>
              setDraft((prev) => ({
                ...prev,
                failureDestination: "ops-alerts",
                alertOnSkipped: true,
                idempotencyKey: "open-fdd-site-sweep-v1",
                reconcileTag: "portfolio-default",
                correlationIdPrefix: "ofdd",
              }))
            }
          >
            Apply strict cron fallback
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() =>
              setDraft((prev) => ({
                ...prev,
                failureDestination: "",
                alertOnSkipped: false,
                idempotencyKey: "",
                reconcileTag: "ad-hoc",
                correlationIdPrefix: "ofdd",
              }))
            }
          >
            Apply relaxed fallback
          </button>
        </div>
        <div className="grid-two">
          <label>
            Failure destination
            <input
              value={draft.failureDestination}
              onChange={(e) => setDraft((prev) => ({ ...prev, failureDestination: e.target.value }))}
              placeholder="ops-alerts"
            />
          </label>
          <label>
            Idempotency key
            <input
              value={draft.idempotencyKey}
              onChange={(e) => setDraft((prev) => ({ ...prev, idempotencyKey: e.target.value }))}
              placeholder="open-fdd-site-sweep-v1"
            />
          </label>
          <label>
            Reconcile tag
            <input
              value={draft.reconcileTag}
              onChange={(e) => setDraft((prev) => ({ ...prev, reconcileTag: e.target.value }))}
              placeholder="portfolio-default"
            />
          </label>
          <label>
            Correlation ID prefix
            <input
              value={draft.correlationIdPrefix}
              onChange={(e) => setDraft((prev) => ({ ...prev, correlationIdPrefix: e.target.value }))}
              placeholder="ofdd"
            />
          </label>
        </div>
        <label>
          <input
            type="checkbox"
            checked={draft.alertOnSkipped}
            onChange={(e) => setDraft((prev) => ({ ...prev, alertOnSkipped: e.target.checked }))}
          />{" "}
          Alert on skipped runs
        </label>
        <label>
          Message
          <textarea
            rows={3}
            value={draft.message}
            onChange={(e) => setDraft((prev) => ({ ...prev, message: e.target.value }))}
          />
        </label>
        <div className={`cron-hint-box ${cronValidation.valid ? "ok" : "warn"}`}>
          <strong>Cron validation:</strong> {cronValidation.valid ? "Looks valid." : "Needs attention."}
          <ul>
            {cronValidation.hints.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        </div>
        {mode === "api" ? (
          <div className="stack-page">
            <label>
              Endpoint preset
              <select
                value={apiEndpointPath}
                onChange={(e) => setApiEndpointPath(e.target.value)}
              >
                {OPENCLAW_CRON_ENDPOINT_PRESETS.map((preset) => (
                  <option key={preset.id} value={preset.endpointPath}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              API endpoint path
              <input
                value={apiEndpointPath}
                onChange={(e) => setApiEndpointPath(e.target.value)}
                placeholder="api/cron/jobs"
              />
            </label>
            <p className="muted">
              {OPENCLAW_CRON_ENDPOINT_PRESETS.find((p) => p.endpointPath === apiEndpointPath)?.notes ??
                "Custom endpoint path."}
            </p>
            <label>
              Gateway bearer token (optional)
              <input
                type="password"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
                placeholder="OPENCLAW_GATEWAY_TOKEN"
              />
            </label>
            <div className="openclaw-actions">
              <button type="button" disabled={apiBusy} onClick={() => void createViaApi()}>
                {apiBusy ? "Creating..." : "Create This Job via API"}
              </button>
              <span className="muted">
                Uses VITE_OPENFDDCLAW_GATEWAY_BASE (or legacy VITE_OPENCLAW_GATEWAY_BASE) + endpoint path.
              </span>
            </div>
            <label>
              API request preview (curl)
              <textarea readOnly rows={10} value={apiPreview} />
            </label>
            <div className="openclaw-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => void copyText("api-preview", apiPreview)}
              >
                {copiedKey === "api-preview" ? "Copied" : "Copy API preview"}
              </button>
            </div>
            <label>
              API result
              <textarea readOnly rows={8} value={apiResult} />
            </label>
          </div>
        ) : null}
        {mode === "commands" ? (
          <>
            <label>
              Cron add command
              <textarea readOnly rows={7} value={cronCommand} />
            </label>
            <div className="openclaw-actions">
              <button type="button" className="secondary-btn" onClick={() => void copyText("cron-add", cronCommand)}>
                {copiedKey === "cron-add" ? "Copied" : "Copy cron add"}
              </button>
            </div>
            <div className="grid-two">
              <label>
                Cron cleanup commands
                <textarea readOnly rows={5} value={buildCronCleanupCommand()} />
                <div className="openclaw-actions">
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => void copyText("cron-clean", buildCronCleanupCommand())}
                  >
                    {copiedKey === "cron-clean" ? "Copied" : "Copy cron cleanup"}
                  </button>
                </div>
              </label>
              <label>
                Skills refresh commands
                <textarea readOnly rows={5} value={buildSkillsRefreshCommands()} />
                <div className="openclaw-actions">
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => void copyText("skills", buildSkillsRefreshCommands())}
                  >
                    {copiedKey === "skills" ? "Copied" : "Copy skills ops"}
                  </button>
                </div>
              </label>
            </div>
            <label>
              Memory cleanup commands
              <textarea readOnly rows={7} value={memoryCommand} />
            </label>
            <div className="openclaw-actions">
              <button type="button" className="secondary-btn" onClick={() => void copyText("memory", memoryCommand)}>
                {copiedKey === "memory" ? "Copied" : "Copy memory cleanup"}
              </button>
            </div>
            <div className="openclaw-actions">
              <button type="button" className="secondary-btn" onClick={() => void copyText("all-ops", allOpsCommands)}>
                {copiedKey === "all-ops" ? "Copied" : "Copy all ops commands"}
              </button>
            </div>
          </>
        ) : null}
      </div>
      <div className="card">
        <h3 className="title">Phase 1 policy presets (routing + security)</h3>
        <p className="muted">
          Use these presets to enforce simple/complex model lanes and safe gateway defaults.
        </p>
        <div className="grid-two">
          <label>
            Runtime route map env preset
            <textarea readOnly rows={9} value={SIMPLE_COMPLEX_POLICY_PRESET} />
            <div className="openclaw-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => void copyText("route-preset", SIMPLE_COMPLEX_POLICY_PRESET)}
              >
                {copiedKey === "route-preset" ? "Copied" : "Copy route preset"}
              </button>
            </div>
          </label>
          <label>
            Security safe-defaults preset
            <textarea readOnly rows={9} value={SECURITY_SAFE_DEFAULTS_PRESET} />
            <div className="openclaw-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => void copyText("security-preset", SECURITY_SAFE_DEFAULTS_PRESET)}
              >
                {copiedKey === "security-preset" ? "Copied" : "Copy security preset"}
              </button>
            </div>
          </label>
        </div>
      </div>
      <div className="card">
        <h3 className="title">Phase 2 reliability presets</h3>
        <p className="muted">
          Production default: set failure destinations, skipped-run alerts, idempotency, and reconciliation tags.
        </p>
        <div className="grid-two">
          <label>
            Strict fallback preset
            <textarea readOnly rows={8} value={PHASE2_CRON_STRICT_PRESET} />
          </label>
          <label>
            Relaxed fallback preset
            <textarea readOnly rows={8} value={PHASE2_CRON_RELAXED_PRESET} />
          </label>
        </div>
      </div>
      <div className="card">
        <h3 className="title">Phase 3 memory + multi-site presets</h3>
        <p className="muted">
          Templates for durable-vs-transient memory governance and optional lane-based subagent scaling.
        </p>
        <div className="grid-two">
          <label>
            Memory governance preset
            <textarea readOnly rows={9} value={PHASE3_MEMORY_GOVERNANCE_PRESET} />
          </label>
          <label>
            Subagent lanes preset
            <textarea readOnly rows={9} value={PHASE3_SUBAGENT_LANES_PRESET} />
          </label>
        </div>
      </div>
      <div className="card openclaw-frame-card">
        <iframe
          title="Open-FDD Claw UI"
          src={openClawUiUrl}
          className="openclaw-iframe"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      </div>
    </section>
  );
}

