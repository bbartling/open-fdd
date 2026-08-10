import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import { Button, FileUpload, InlineAlert } from "../components/widgets";
import { ApiClientError } from "../api/client";
import {
  fetchUnityActive,
  fetchV1Models,
  importModelReleaseZip,
  importUnityZip,
  rejectJoblibName,
  TRAINING_EXPORT_PATH,
  type UnityBuildStatus,
} from "../api/twinApi";

/**
 * Host for the Vibe21 Unity WebGL build + ZIP import lanes (portable digests only).
 */
export function TwinPage() {
  const src = useMemo(() => {
    const twin = "twin_ops11";
    const build = "unitybuild_liberty100";
    return `/twins/${twin}/builds/${build}/`;
  }, []);

  const [unityStatus, setUnityStatus] = useState<UnityBuildStatus | null>(null);
  const [modelsJson, setModelsJson] = useState<string>("");
  const [unityFiles, setUnityFiles] = useState<File[]>([]);
  const [modelFiles, setModelFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<"unity" | "model" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [u, m] = await Promise.all([
        fetchUnityActive().catch(() => null),
        fetchV1Models().catch(() => null),
      ]);
      if (u) setUnityStatus(u);
      if (m) setModelsJson(JSON.stringify(m, null, 2));
    } catch {
      /* status panels stay empty until central vibe21 is up */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onImportUnity = async () => {
    const file = unityFiles[0];
    if (!file) {
      setErr("Choose unity_webgl_build.zip first");
      return;
    }
    setBusy("unity");
    setErr(null);
    setMsg(null);
    try {
      const body = await importUnityZip(file);
      setMsg(`Unity import: ${JSON.stringify(body)}`);
      await refresh();
    } catch (e: unknown) {
      setErr(e instanceof ApiClientError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onImportModel = async () => {
    const file = modelFiles[0];
    if (!file) {
      setErr("Choose model_release.zip first");
      return;
    }
    const reject = rejectJoblibName(file.name);
    if (reject) {
      setErr(reject);
      return;
    }
    setBusy("model");
    setErr(null);
    setMsg(null);
    try {
      const body = await importModelReleaseZip(file);
      setMsg(`Model import: ${JSON.stringify(body)}`);
      await refresh();
    } catch (e: unknown) {
      setErr(e instanceof ApiClientError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <AppShell
      title="Digital Twin"
      caption="Unity WebGL + portable ZIP lanes (no Flask/joblib online)"
      activeSectionId="wattlab"
    >
      <div className="page-stack" data-testid="twin-page">
        <InlineAlert id="twin-hint" variant="info" title="Portable digests only">
          Inference uses Rust demand-hourly prediction. Parties
          collaborate via ZIP lanes +{" "}
          <Link to="/upload">package upload</Link> — not Jupyter in the SPA. See
          MCP role packs under <code>docs/mcp-agents/roles/</code>.
        </InlineAlert>

        {err ? (
          <InlineAlert
            id="twin-error"
            variant="danger"
            title="Twin error"
            testId="twin-error"
          >
            {err}
          </InlineAlert>
        ) : null}
        {msg ? (
          <InlineAlert
            id="twin-msg"
            variant="success"
            title="Ok"
            testId="twin-msg"
          >
            {msg}
          </InlineAlert>
        ) : null}

        <section data-testid="twin-lane-unity" aria-label="Unity WebGL ZIP">
          <h2>Unity WebGL ZIP</h2>
          <p>
            External Editor build only. Active:{" "}
            <code data-testid="twin-unity-status">
              {unityStatus
                ? unityStatus.ok
                  ? `${unityStatus.twin_version_id}/${unityStatus.unity_build_id}`
                  : (unityStatus.error ?? "missing")
                : "…"}
            </code>
            {unityStatus?.zip_sha256 ? (
              <>
                {" "}
                sha256=<code>{unityStatus.zip_sha256.slice(0, 12)}…</code>
              </>
            ) : null}
          </p>
          <FileUpload
            id="twin-unity-zip"
            label="unity_webgl_build.zip"
            accept=".zip,application/zip"
            files={unityFiles}
            onChange={setUnityFiles}
            testId="twin-unity-file"
            loading={busy === "unity"}
          />
          <Button
            id="twin-unity-import"
            label={busy === "unity" ? "Importing…" : "Import Unity ZIP"}
            testId="twin-unity-import"
            disabled={busy !== null || unityFiles.length === 0}
            loading={busy === "unity"}
            onClick={() => void onImportUnity()}
          />
        </section>

        <section data-testid="twin-lane-model" aria-label="Model release ZIP">
          <h2>model_release.zip</h2>
          <p>
            Portable champion only (trees/onnx + specs + conformance). joblib and
            pickle uploads are rejected.
          </p>
          <FileUpload
            id="twin-model-zip"
            label="model_release.zip"
            accept=".zip,application/zip"
            files={modelFiles}
            onChange={setModelFiles}
            testId="twin-model-file"
            loading={busy === "model"}
          />
          <Button
            id="twin-model-import"
            label={busy === "model" ? "Importing…" : "Import model_release.zip"}
            testId="twin-model-import"
            disabled={busy !== null || modelFiles.length === 0}
            loading={busy === "model"}
            onClick={() => void onImportModel()}
          />
          {modelsJson ? (
            <pre className="page-json" data-testid="twin-models-json">
              {modelsJson}
            </pre>
          ) : null}
        </section>

        <section data-testid="twin-lane-export" aria-label="Training export">
          <h2>Training export ZIP</h2>
          <p>
            Download Parquet/Arrow + specs + twin digests; train offline with{" "}
            <code>scripts/vibe21_master_build.sh</code>; re-upload{" "}
            <code>model_release.zip</code>.
          </p>
          <a data-testid="twin-training-export" href={TRAINING_EXPORT_PATH}>
            Download training export
          </a>
        </section>

        <iframe
          title="Open-FDD Unity twin"
          data-testid="twin-iframe"
          src={src}
          style={{
            width: "100%",
            minHeight: "70vh",
            border: "1px solid #ccc",
            background: "#111",
          }}
          allow="fullscreen"
        />
      </div>
    </AppShell>
  );
}
