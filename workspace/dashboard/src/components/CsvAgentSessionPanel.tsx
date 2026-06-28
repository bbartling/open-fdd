import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  datasetFromFusionPreview,
  fetchAgentSessionFusionPreview,
  fetchLatestPlannedSession,
  saveAgentSessionToArrow,
  type FusionPreviewResponse,
} from "../lib/csvAgentSession";
import type { CsvDataset } from "../lib/csvWorkbench";

type Props = {
  onLoaded: (dataset: CsvDataset, sessionId: string, meta: FusionPreviewResponse) => void;
  activeSessionId?: string;
  suggestedSessionId?: string;
  onSaved?: (info: { datasetId?: string; plotUrl?: string; modelUrl?: string; siteId?: string }) => void;
};

export default function CsvAgentSessionPanel({
  onLoaded,
  activeSessionId,
  suggestedSessionId,
  onSaved,
}: Props) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [sessionInput, setSessionInput] = useState(searchParams.get("session") ?? suggestedSessionId ?? "");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [meta, setMeta] = useState<FusionPreviewResponse | null>(null);
  const [saveLinks, setSaveLinks] = useState<{ plot?: string; model?: string; datasetId?: string } | null>(null);
  const loadedUrlRef = useRef<string | null>(null);

  useEffect(() => {
    if (suggestedSessionId && !searchParams.get("session")) {
      setSessionInput(suggestedSessionId);
    }
  }, [suggestedSessionId, searchParams]);

  const loadSession = useCallback(
    async (sessionId: string) => {
      const id = sessionId.trim();
      if (!id) {
        setError("Upload CSVs in UT3 panel above, then click Preview plan — the session ID appears in green.");
        return;
      }
      if (!hasToken()) {
        setError("Sign in to load agent-cleaned sessions.");
        return;
      }
      setBusy("Loading agent preview…");
      setError("");
      setSaveLinks(null);
      try {
        const data = await fetchAgentSessionFusionPreview(id);
        if (!data.ok) {
          const hint =
            data.error === "unknown endpoint"
              ? " Edge needs rebuild/restart — session API routes missing on :8080."
              : "";
          throw new Error((data.error ?? "load failed") + hint);
        }
        const ds = datasetFromFusionPreview(data, id);
        setMeta(data);
        onLoaded(ds, id, data);
        loadedUrlRef.current = id;
        setSearchParams({ session: id }, { replace: true });
      } catch (e) {
        setError(formatApiError(e));
        setMeta(null);
      } finally {
        setBusy("");
      }
    },
    [onLoaded, setSearchParams],
  );

  useEffect(() => {
    const fromUrl = searchParams.get("session");
    if (!fromUrl || !hasToken() || loadedUrlRef.current === fromUrl) return;
    void loadSession(fromUrl);
  }, [searchParams, loadSession]);

  useEffect(() => {
    if (
      suggestedSessionId &&
      hasToken() &&
      loadedUrlRef.current !== suggestedSessionId &&
      !searchParams.get("session")
    ) {
      void loadSession(suggestedSessionId);
    }
  }, [suggestedSessionId, loadSession, searchParams]);

  async function saveToArrow() {
    const sid = activeSessionId ?? meta?.session_id;
    if (!sid) return;
    setBusy("Saving to Arrow store…");
    setError("");
    try {
      const out = await saveAgentSessionToArrow(sid);
      if (!out.ok) throw new Error(out.error ?? "save failed");
      const sync = out.historian_sync;
      setSaveLinks({
        plot: sync?.plot_url,
        model: sync?.model_url,
        datasetId: out.dataset?.id,
      });
      onSaved?.({
        datasetId: out.dataset?.id,
        plotUrl: sync?.plot_url,
        modelUrl: sync?.model_url,
        siteId: sync?.site_id,
      });
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel csv-agent-session-panel">
      <h3 className="panel-title">Agent-cleaned data → fusion preview</h3>
      <p className="muted">
        Workflow: AI/MCP cleans &amp; plans → you review merged CSV here → save to Feather/Arrow → open{" "}
        <Link to="/model">Model</Link> and <Link to="/plot">Plot</Link>. Share:{" "}
        <code>/csv?session=&lt;session_id&gt;</code>
      </p>
      <div className="csv-agent-session-row">
        <label className="field csv-agent-session-input">
          <span className="field-label">Import session ID</span>
          <input
            value={sessionInput}
            onChange={(e) => setSessionInput(e.target.value)}
            placeholder="e.g. csv-1735123456789 (from UT3 Preview plan)"
          />
        </label>
        <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void loadSession(sessionInput)}>
          {busy.startsWith("Loading") ? busy : "Load into fusion tab"}
        </button>
        <button
          type="button"
          className="linkish-btn"
          disabled={!!busy}
          onClick={() =>
            void fetchLatestPlannedSession().then((r) => {
              if (r.session_id) {
                setSessionInput(r.session_id);
                void loadSession(r.session_id);
              } else {
                setError(
                  r.error ??
                    "No planned session — upload CSVs in UT3 panel above and click Preview plan first.",
                );
              }
            })
          }
        >
          Load latest agent session
        </button>
      </div>
      {sessionInput ? (
        <p className="muted csv-session-id-line">
          Session ID: <code>{sessionInput}</code> ·{" "}
          <a href={`/csv?session=${encodeURIComponent(sessionInput)}`}>/csv?session={sessionInput}</a>
        </p>
      ) : null}
      {activeSessionId ? (
        <div className="csv-agent-session-active">
          <p className="ok">
            Session <code>{activeSessionId}</code> loaded
            {meta?.row_count != null ? (
              <>
                {" "}
                — <strong>{meta.row_count.toLocaleString()}</strong> rows
                {meta.truncated ? ` (showing ${meta.preview_row_count?.toLocaleString()} in preview)` : null}
              </>
            ) : null}
          </p>
          {meta?.validation_report?.warnings?.length ? (
            <ul className="csv-agent-warnings">
              {meta.validation_report.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          <button type="button" className="primary-btn" disabled={!!busy} onClick={() => void saveToArrow()}>
            {busy.startsWith("Saving") ? busy : "Save to Arrow store (from session)"}
          </button>
          {saveLinks ? (
            <p className="ok csv-save-links">
              Saved dataset <code>{saveLinks.datasetId}</code>.{" "}
              {saveLinks.model ? (
                <>
                  <Link to={saveLinks.model}>Open data model</Link>
                  {" · "}
                </>
              ) : null}
              {saveLinks.plot ? <Link to={saveLinks.plot}>Open plots</Link> : null}
              {" · "}
              <Link to="/sql-fdd">SQL FDD rules</Link> to tune rules on this data
            </p>
          ) : null}
        </div>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
