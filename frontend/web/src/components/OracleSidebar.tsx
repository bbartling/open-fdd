import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import { uploadPackage } from "../api/uploadApi";
import { ApiClientError } from "../api/client";
import { RuleTuningPanel } from "./RuleTuningPanel";

const UNITS_KEY = "openfdd.ui.unit_system";
const PREFER_WEB_OAT_KEY = "openfdd.ui.prefer_web_oat";
const STATUS_PROOF_KEY = "openfdd.ui.use_mech_cooling_status_proof";
const CHW_LEAVE_KEY = "openfdd.ui.chw_leave_max_f";

function writeFlag(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function packageLoadError(err: unknown): string {
  if (err instanceof ApiClientError) {
    const msg = `${err.code}: ${err.message}`;
    if (/map|role|session_config|columns|equipType|invalid|parse|zip/i.test(msg)) {
      return `${msg} — check openfdd_package_v1 layout / data model (column→role map).`;
    }
    return msg;
  }
  const raw = err instanceof Error ? err.message : String(err);
  if (/zip|corrupt|JSON|CSV|parse|map|role/i.test(raw)) {
    return `${raw} — package zip or data model may be incomplete.`;
  }
  return raw;
}

/**
 * Product sidebar: Sites · CSV Upload · Display · Lab.
 * Quiet chrome — no froofy captions; package help lives in AGENTS.md for agents.
 */
export function OracleSidebar({ collapsed }: { collapsed: boolean }) {
  const { query, setQuery } = useSessionQuery();
  const activeSite = query.siteId ?? "";

  const [sites, setSites] = useState<string[]>([]);
  const [zipFiles, setZipFiles] = useState<File[]>([]);
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

  const zipInputRef = useRef<HTMLInputElement>(null);

  // Sensible defaults under the hood (no UI knobs) — agents/FDD still read these keys.
  useEffect(() => {
    writeFlag(PREFER_WEB_OAT_KEY, true);
    writeFlag(STATUS_PROOF_KEY, true);
    try {
      if (localStorage.getItem(CHW_LEAVE_KEY) == null) {
        localStorage.setItem(CHW_LEAVE_KEY, "48");
      }
    } catch {
      /* ignore */
    }
  }, []);

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
    const onDeleted = () => {
      void refreshSites();
    };
    window.addEventListener("openfdd:package-deleted", onDeleted);
    window.addEventListener("openfdd:package-loaded", onDeleted);
    return () => {
      window.removeEventListener("openfdd:package-deleted", onDeleted);
      window.removeEventListener("openfdd:package-loaded", onDeleted);
    };
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
      setError("Select one openfdd_package_v1 zip.");
      return;
    }
    setLoading(true);
    setError(null);
    setStatus("");
    try {
      const sizeMb = Math.round((file.size / (1024 * 1024)) * 10) / 10;
      setStatus(`Uploading ${file.name} (${sizeMb} MB)…`);
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
          ms != null ? `${ms} ms` : null,
          elapsed != null ? `${elapsed}s` : null,
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
      setError(packageLoadError(err));
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
        {siteOptions.length > 0 ? (
          <label className="oracle-sidebar__field">
            <span className="oracle-sidebar__label">Active site</span>
            <select
              className="oracle-sidebar__control"
              value={activeSite}
              onChange={(e) =>
                setQuery({ siteId: e.target.value || undefined }, true)
              }
              data-testid="sidebar-active-site"
            >
              {!activeSite ? (
                <option value="">— select site —</option>
              ) : null}
              {siteOptions.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </section>

      <section className="oracle-sidebar__block" data-testid="sidebar-building-data">
        <h3 className="oracle-sidebar__h3">CSV Upload</h3>
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
          </div>
        </label>
        {zipFiles[0] ? (
          <p className="oracle-sidebar__ok" data-testid="sidebar-zip-selected">
            {zipFiles[0].name} · {partsMb} MB
          </p>
        ) : null}

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
        </div>

        {loading ? (
          <p className="oracle-sidebar__busy" data-testid="sidebar-load-busy" role="status">
            Importing… <strong>{loadElapsedSec}s</strong>
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
      </section>

      <hr className="oracle-sidebar__divider" />

      <section className="oracle-sidebar__block" data-testid="sidebar-display">
        <h3 className="oracle-sidebar__h3">Display</h3>
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
      </section>

      <hr className="oracle-sidebar__divider" />

      <RuleTuningPanel />
    </div>
  );
}
