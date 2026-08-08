import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import { deleteDataset } from "../api/datasetsApi";
import { uploadPackage } from "../api/uploadApi";
import { ApiClientError } from "../api/client";
import { RuleTuningPanel } from "./RuleTuningPanel";

const UNITS_KEY = "openfdd.ui.unit_system";
const PREFER_WEB_OAT_KEY = "openfdd.ui.prefer_web_oat";
const STATUS_PROOF_KEY = "openfdd.ui.use_mech_cooling_status_proof";
const CHW_LEAVE_KEY = "openfdd.ui.chw_leave_max_f";

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key);
    if (v == null) return fallback;
    return v === "1" || v === "true";
  } catch {
    return fallback;
  }
}

function writeFlag(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Streamlit-oracle sidebar: Sites · Building data · Session restore · Display & site.
 * Dev/parity shell — wires zip upload to central when authenticated.
 */
export function OracleSidebar({ collapsed }: { collapsed: boolean }) {
  const { query, setQuery } = useSessionQuery();
  const activeSite = query.siteId ?? "";

  const [sites, setSites] = useState<string[]>([]);
  const [dataSource, setDataSource] = useState<"Zip package">("Zip package");
  const [zipFiles, setZipFiles] = useState<File[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadElapsedSec, setLoadElapsedSec] = useState(0);
  const loadStartedAt = useRef<number | null>(null);
  const [unitSystem, setUnitSystem] = useState<"imperial" | "metric">(() => {
    try {
      const v = localStorage.getItem(UNITS_KEY);
      return v === "metric" ? "metric" : "imperial";
    } catch {
      return "imperial";
    }
  });
  const [preferWebOat, setPreferWebOat] = useState(() =>
    readFlag(PREFER_WEB_OAT_KEY, true),
  );
  const [useStatusProof, setUseStatusProof] = useState(() =>
    readFlag(STATUS_PROOF_KEY, true),
  );
  const [chwLeaveMaxF, setChwLeaveMaxF] = useState(() => {
    try {
      const v = localStorage.getItem(CHW_LEAVE_KEY);
      return v ? Number(v) : 48;
    } catch {
      return 48;
    }
  });

  const zipInputRef = useRef<HTMLInputElement>(null);
  const sessionInputRef = useRef<HTMLInputElement>(null);
  const faultInputRef = useRef<HTMLInputElement>(null);

  const refreshSites = useCallback(async () => {
    try {
      const list = await listPackageBuildings();
      setSites(list);
    } catch {
      setSites(activeSite ? [activeSite] : []);
    }
  }, [activeSite]);

  useEffect(() => {
    void refreshSites();
  }, [refreshSites]);

  useEffect(() => {
    try {
      localStorage.setItem(UNITS_KEY, unitSystem);
      window.dispatchEvent(
        new CustomEvent("openfdd:unit-system-changed", { detail: unitSystem }),
      );
    } catch {
      /* ignore */
    }
  }, [unitSystem]);

  useEffect(() => {
    writeFlag(PREFER_WEB_OAT_KEY, preferWebOat);
  }, [preferWebOat]);

  useEffect(() => {
    writeFlag(STATUS_PROOF_KEY, useStatusProof);
  }, [useStatusProof]);

  useEffect(() => {
    try {
      localStorage.setItem(CHW_LEAVE_KEY, String(chwLeaveMaxF));
    } catch {
      /* ignore */
    }
  }, [chwLeaveMaxF]);

  const siteOptions = useMemo(() => {
    const set = new Set(sites);
    if (activeSite) set.add(activeSite);
    return [...set].sort();
  }, [sites, activeSite]);

  const partsMb = useMemo(() => {
    if (!zipFiles.length) return 0;
    return Math.round(
      (zipFiles.reduce((s, f) => s + f.size, 0) / (1024 * 1024)) * 100,
    ) / 100;
  }, [zipFiles]);

  useEffect(() => {
    if (!loading) {
      loadStartedAt.current = null;
      return;
    }
    loadStartedAt.current = Date.now();
    setLoadElapsedSec(0);
    const id = window.setInterval(() => {
      if (loadStartedAt.current != null) {
        setLoadElapsedSec(
          Math.max(0, Math.round((Date.now() - loadStartedAt.current) / 1000)),
        );
      }
    }, 250);
    return () => window.clearInterval(id);
  }, [loading]);

  const onLoadZips = async () => {
    const file = zipFiles[0];
    if (!file) {
      setError("Choose a building package zip first");
      return;
    }
    if (zipFiles.length > 1) {
      setError(
        "Select one openfdd_package_v1 zip (multi-part assemble is not wired yet).",
      );
      return;
    }
    setLoading(true);
    setError(null);
    setStatus("");
    try {
      const sizeMb = Math.round((file.size / (1024 * 1024)) * 10) / 10;
      setStatus(
        `Uploading ${file.name} (${sizeMb} MB) → central historian… large sites often take 10–90s.`,
      );
      const body = await uploadPackage(file);
      const bid = body.building_id || "";
      if (bid) {
        setQuery({ siteId: bid }, true);
        setSites((prev) =>
          prev.includes(bid) ? prev : [...prev, bid].sort(),
        );
      }
      const n = body.equipment_written ?? body.equipment?.length ?? 0;
      const rows = body.total_rows;
      const ms = body.total_ms;
      const elapsed =
        loadStartedAt.current != null
          ? Math.round((Date.now() - loadStartedAt.current) / 1000)
          : null;
      setStatus(
        [
          `Ready: ${n} equipment`,
          bid ? `\`${bid}\`` : null,
          rows != null ? `${rows.toLocaleString()} rows` : null,
          ms != null ? `${ms} ms server` : null,
          elapsed != null ? `${elapsed}s wall` : null,
          "Overview charts are refreshing now.",
        ]
          .filter(Boolean)
          .join(" · "),
      );
      await refreshSites();
      try {
        window.dispatchEvent(
          new CustomEvent("openfdd:package-loaded", {
            detail: { buildingId: bid },
          }),
        );
      } catch {
        /* ignore */
      }
    } catch (err: unknown) {
      setStatus("");
      if (err instanceof ApiClientError) {
        setError(`${err.code}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  };

  const onDeleteActiveSite = async () => {
    if (!confirmDelete) {
      setError("Check Confirm delete Active site first.");
      return;
    }
    const id = activeSite.trim();
    if (!id) {
      setError("Select an Active site before deleting.");
      return;
    }
    setLoading(true);
    setError(null);
    setStatus(`Deleting ${id} (feather + parquet + rule results)…`);
    try {
      const body = await deleteDataset(id);
      if (!body.ok) {
        throw new Error(body.error || "Delete failed");
      }
      setConfirmDelete(false);
      setQuery({ siteId: "" }, true);
      await refreshSites();
      setStatus(`Deleted dataset \`${id}\`. Re-import a package to restore.`);
      try {
        window.dispatchEvent(
          new CustomEvent("openfdd:package-deleted", {
            detail: { buildingId: id },
          }),
        );
      } catch {
        /* ignore */
      }
    } catch (err: unknown) {
      setStatus("");
      if (err instanceof ApiClientError) {
        setError(`${err.code}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  };

  if (collapsed) {
    return (
      <div className="oracle-sidebar oracle-sidebar--collapsed" data-testid="oracle-sidebar">
        <span className="oracle-sidebar__collapsed-mark" title="Sites">
          S
        </span>
      </div>
    );
  }

  return (
    <div className="oracle-sidebar" data-testid="oracle-sidebar">
      <section className="oracle-sidebar__block" data-testid="sidebar-sites">
        <h2 className="oracle-sidebar__h">Sites</h2>
        {siteOptions.length === 0 ? (
          <p className="oracle-sidebar__caption">No sites — load a package.</p>
        ) : (
          <label className="oracle-sidebar__field">
            <span className="oracle-sidebar__label">Active site</span>
            <select
              className="oracle-sidebar__control"
              value={activeSite || siteOptions[0]}
              onChange={(e) =>
                setQuery({ siteId: e.target.value || undefined }, true)
              }
              data-testid="sidebar-active-site"
              title="Active site = building_id from the package / Hive. Switch rebinds FDD data."
            >
              {siteOptions.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
            <p className="oracle-sidebar__caption" style={{ marginTop: "0.35rem" }}>
              To remove this site’s feathers + FDD results, check confirm below and use{" "}
              <strong>Delete dataset…</strong>
            </p>
          </label>
        )}
      </section>

      <section className="oracle-sidebar__block" data-testid="sidebar-building-data">
        <h3 className="oracle-sidebar__h3">Building data</h3>
        <p className="oracle-sidebar__caption">
          Cloud-capable · same <code>openfdd_package_v1</code> zip everywhere (
          <code>docs/PACKAGE_SPEC.md</code>). Non-sensitive demo data on shared
          hosts.
        </p>

        <fieldset className="oracle-sidebar__fieldset">
          <legend className="oracle-sidebar__label">Data source</legend>
          <label className="oracle-sidebar__radio">
            <input
              type="radio"
              name="data-source"
              checked={dataSource === "Zip package"}
              onChange={() => setDataSource("Zip package")}
            />
            Zip package
          </label>
        </fieldset>

        <label className="oracle-sidebar__field">
          <span className="oracle-sidebar__label">Building package zip</span>
          <div className="oracle-sidebar__file-wrap">
            <input
              ref={zipInputRef}
              type="file"
              accept=".zip,application/zip"
              className="oracle-sidebar__file"
              data-testid="sidebar-zip-input"
              onChange={(e) => {
                const list = [...(e.target.files ?? [])];
                setZipFiles(list.slice(0, 1));
              }}
            />
            <p className="oracle-sidebar__caption" style={{ marginBottom: 0 }}>
              One <code>openfdd_package_v1</code> zip · ≤200 MB typical
            </p>
          </div>
        </label>
        <p className="oracle-sidebar__caption">
          {zipFiles[0] ? (
            <>
              Selected <strong>{zipFiles[0].name}</strong> ·{" "}
              <strong>{partsMb}</strong> MB
            </>
          ) : (
            <>No file selected yet</>
          )}
        </p>

        <div className="oracle-sidebar__btn-row">
          <button
            type="button"
            className="oracle-sidebar__btn oracle-sidebar__btn--primary"
            disabled={!zipFiles.length || loading}
            onClick={() => void onLoadZips()}
            data-testid="sidebar-load-zips"
            aria-busy={loading || undefined}
          >
            {loading ? `Importing… ${loadElapsedSec}s` : "Load package"}
          </button>
          <button
            type="button"
            className="oracle-sidebar__btn"
            disabled={!confirmDelete || !activeSite || loading}
            title="Purge Feathers + FDD results for the Active site (requires confirm)."
            onClick={() => void onDeleteActiveSite()}
            data-testid="sidebar-delete-site"
          >
            Delete dataset…
          </button>
        </div>
        <label className="oracle-sidebar__check">
          <input
            type="checkbox"
            checked={confirmDelete}
            onChange={(e) => setConfirmDelete(e.target.checked)}
            data-testid="sidebar-confirm-delete"
          />
          Confirm delete Active site dataset
        </label>

        {loading ? (
          <p className="oracle-sidebar__busy" data-testid="sidebar-load-busy" role="status">
            Importing into central… <strong>{loadElapsedSec}s</strong> elapsed.
            Stay on this page; Overview will flip to charts when ready.
          </p>
        ) : null}
        {status ? (
          <p className="oracle-sidebar__ok" data-testid="sidebar-load-status">
            {status}
          </p>
        ) : null}
        {error ? (
          <p className="oracle-sidebar__err" data-testid="sidebar-load-error">
            {error}
          </p>
        ) : null}

        <h3 className="oracle-sidebar__h3">Session restore (Cloud-safe)</h3>
        <p className="oracle-sidebar__caption">
          Download after mapping/tuning; later upload zip + this JSON — no
          server path.
        </p>
        <div className="oracle-sidebar__btn-row">
          <button
            type="button"
            className="oracle-sidebar__btn"
            data-testid="sidebar-dl-session"
            onClick={() =>
              downloadJson("session_config.json", {
                schema_version: "openfdd_session_v1",
                unit_system: unitSystem,
                prefer_web_oat: preferWebOat,
                use_mech_cooling_status_proof: useStatusProof,
                chw_leave_max_f: chwLeaveMaxF,
                site_id: activeSite || null,
                role_map: {},
                params: {},
              })
            }
          >
            Download session config
          </button>
          <button
            type="button"
            className="oracle-sidebar__btn"
            data-testid="sidebar-dl-faults"
            onClick={() => downloadJson("fault_settings.json", {})}
          >
            Download fault settings
          </button>
        </div>

        <label className="oracle-sidebar__field">
          <span className="oracle-sidebar__label">Upload session config</span>
          <div className="oracle-sidebar__file-wrap">
            <input
              ref={sessionInputRef}
              type="file"
              accept=".json,application/json"
              className="oracle-sidebar__file"
              data-testid="sidebar-upload-session"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                void f.text().then((t) => {
                  try {
                    const j = JSON.parse(t) as {
                      unit_system?: string;
                      prefer_web_oat?: boolean;
                      site_id?: string;
                    };
                    if (j.unit_system === "metric" || j.unit_system === "imperial") {
                      setUnitSystem(j.unit_system);
                    }
                    if (typeof j.prefer_web_oat === "boolean") {
                      setPreferWebOat(j.prefer_web_oat);
                    }
                    if (j.site_id) setQuery({ siteId: j.site_id }, true);
                    setStatus(`Applied session config from ${f.name}`);
                  } catch (err) {
                    setError(
                      err instanceof Error ? err.message : "Invalid session JSON",
                    );
                  }
                });
              }}
            />
            <p className="oracle-sidebar__caption" style={{ marginBottom: 0 }}>
              Limit 200MB per file · JSON
            </p>
          </div>
        </label>
        <label className="oracle-sidebar__field">
          <span className="oracle-sidebar__label">Upload fault settings</span>
          <div className="oracle-sidebar__file-wrap">
            <input
              ref={faultInputRef}
              type="file"
              accept=".json,application/json"
              className="oracle-sidebar__file"
              data-testid="sidebar-upload-faults"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setStatus(`Fault settings file selected: ${f.name} (stored client-side)`);
              }}
            />
            <p className="oracle-sidebar__caption" style={{ marginBottom: 0 }}>
              Limit 200MB per file · JSON
            </p>
          </div>
        </label>
        <p className="oracle-sidebar__caption">
          Active fault settings: defaults
        </p>

        <details className="oracle-sidebar__expander">
          <summary>AI agent / package help</summary>
          <div className="oracle-sidebar__expander-body">
            <p>
              <strong>Human + agent flow (large jobs)</strong>
            </p>
            <ol>
              <li>
                Agent preprocesses CSVs → one or many{" "}
                <code>openfdd_package_v1</code> part zips.
              </li>
              <li>
                Human uploads one package zip here → <strong>Load package</strong>.
              </li>
              <li>
                Map + prerun faults (Run Rules) so Plots/RCx are ready.
              </li>
              <li>
                Download session config to restore later.
              </li>
            </ol>
            <p>
              <Link to="/upload">Upload page</Link>
              {" · "}
              <a
                href="https://bbartling.github.io/open-fdd/"
                target="_blank"
                rel="noreferrer"
              >
                Open-FDD docs
              </a>
            </p>
          </div>
        </details>
      </section>

      <hr className="oracle-sidebar__divider" />

      <section className="oracle-sidebar__block" data-testid="sidebar-display">
        <h3 className="oracle-sidebar__h3">Display &amp; site</h3>
        <fieldset className="oracle-sidebar__fieldset">
          <legend className="oracle-sidebar__label">Units</legend>
          <label className="oracle-sidebar__radio">
            <input
              type="radio"
              name="units"
              checked={unitSystem === "imperial"}
              onChange={() => setUnitSystem("imperial")}
            />
            imperial
          </label>
          <label className="oracle-sidebar__radio">
            <input
              type="radio"
              name="units"
              checked={unitSystem === "metric"}
              onChange={() => setUnitSystem("metric")}
            />
            metric
          </label>
        </fieldset>
        <label className="oracle-sidebar__check">
          <input
            type="checkbox"
            checked={preferWebOat}
            onChange={(e) => setPreferWebOat(e.target.checked)}
          />
          Prefer web OAT (Open-Meteo)
        </label>
        <label className="oracle-sidebar__check">
          <input
            type="checkbox"
            checked={useStatusProof}
            onChange={(e) => setUseStatusProof(e.target.checked)}
          />
          Use mapped mechanical-cooling status proof
        </label>
        <label className="oracle-sidebar__field">
          <span className="oracle-sidebar__label">
            CHW leave proof max (°F)
          </span>
          <input
            type="range"
            min={35}
            max={50}
            step={0.5}
            value={chwLeaveMaxF}
            disabled={useStatusProof}
            onChange={(e) => setChwLeaveMaxF(Number(e.target.value))}
            className="oracle-sidebar__slider"
          />
          <span className="oracle-sidebar__caption">{chwLeaveMaxF}</span>
        </label>
        <p className="oracle-sidebar__caption">
          Occupancy: Overview weekly calendar always sets <code>occ_mode</code>{" "}
          (SCHED-1). Mech-cooling OAT bins: chillers + DX only (no AHU CHW
          valve).
        </p>
      </section>

      <hr className="oracle-sidebar__divider" />

      <RuleTuningPanel />
    </div>
  );
}
