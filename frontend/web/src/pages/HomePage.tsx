import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import { apiFetch } from "../api/client";
import type { CapabilitiesResponse } from "../api/contract";
import {
  DataTable,
  Expander,
  InlineAlert,
  Metric,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  listFddEquipment,
  type FddEquipmentItem,
} from "../api/analyticsApi";
import { getUiGeneration } from "../api/cutoverApi";

const DOCS_URL = "https://bbartling.github.io/open-fdd/";
const REPO_URL = "https://github.com/bbartling/open-fdd";
const AGENTS_URL =
  "https://github.com/bbartling/py-bacnet-stacks-playground/blob/develop/vibe_code_apps_19/AGENTS.md";

type EqRow = {
  equipment_id: string;
  equipment_type: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function hasAuthToken(): boolean {
  try {
    return Boolean(sessionStorage.getItem("openfdd.auth.token"));
  } catch {
    return false;
  }
}

/** Streamlit-oracle Overview: brand hero + how-it-works + inventory. */
export function HomePage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";

  const [contractVersion, setContractVersion] = useState<string | null>(null);
  const [reactUi, setReactUi] = useState<boolean | null>(null);
  const [uiGeneration, setUiGeneration] = useState<string | null>(null);
  const [buildings, setBuildings] = useState<string[]>([]);
  const [equipment, setEquipment] = useState<FddEquipmentItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [devOpen, setDevOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const authed = hasAuthToken();
      const [caps, gen, blds, eq] = await Promise.all([
        apiFetch<CapabilitiesResponse>("/api/capabilities"),
        getUiGeneration().catch(() => null),
        authed
          ? listPackageBuildings().catch(() => [] as string[])
          : Promise.resolve([] as string[]),
        authed
          ? listFddEquipment(buildingId || undefined).catch(
              () => [] as FddEquipmentItem[],
            )
          : Promise.resolve([] as FddEquipmentItem[]),
      ]);
      setContractVersion(caps.contract.contract_version);
      setReactUi(Boolean(caps.capabilities?.react_ui));
      setUiGeneration(gen?.generation ?? null);
      setBuildings(blds);
      setEquipment(eq);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const eqRows: EqRow[] = equipment.map((e) => ({
    equipment_id: String(e.equipment_id),
    equipment_type: String(e.equipment_type ?? ""),
  }));

  const populated = eqRows.length > 0;

  return (
    <AppShell
      title="Open FDD"
      activeSectionId="overview"
      hideHeader
    >
      <div className="page-stack oracle-overview" data-testid="overview-page">
        <header className="oracle-hero" data-testid="oracle-hero">
          <h1 className="oracle-hero__title">Open FDD</h1>
          <p className="oracle-hero__tagline">
            Fault detection + WattLab energy twin — sites, FDD, and calibrated
            models.
          </p>
          <div className="oracle-hero__logo-wrap">
            <img
              className="oracle-hero__logo"
              src="/image_new_chiller.png"
              alt="open-fdd — Rust-native HVAC fault detection at the edge"
              width={720}
              height={405}
            />
          </div>
          <div className="oracle-hero__how">
            <h2>How it works</h2>
            <ol>
              <li>
                <strong>Sites</strong> — Load a package zip; pick the active
                building from the Site list
              </li>
              <li>
                <strong>Data model</strong> — Column→role map for the active site
              </li>
              <li>
                <strong>FDD / WattLab</strong> — Run Rules, then WattLab (Fuel /
                Twin / ECMs) scoped to the site
              </li>
            </ol>
            <p>
              <a href={DOCS_URL} target="_blank" rel="noreferrer">
                Open-FDD docs
              </a>
              {" · "}
              <a href={REPO_URL} target="_blank" rel="noreferrer">
                Open-FDD repo
              </a>
            </p>
          </div>
        </header>

        {!populated ? (
          <>
            <InlineAlert
              id="overview-start-here"
              variant="info"
              testId="overview-start-here"
            >
              <strong>Start here:</strong> sidebar →{" "}
              <strong>Building package zip(s)</strong> (or Folder locally). Each
              equipment CSV needs a sibling Haystack map JSON. Then{" "}
              <strong>Run Rules</strong> → <strong>FDD Plots</strong> /{" "}
              <strong>RCx</strong>.
            </InlineAlert>
            <p className="oracle-overview__footer-links">
              Agent brief:{" "}
              <a href={AGENTS_URL} target="_blank" rel="noreferrer">
                AGENTS.md
              </a>
              {" · "}
              Package contract: <code>docs/PACKAGE_SPEC.md</code>
              {" · "}
              <a href={DOCS_URL} target="_blank" rel="noreferrer">
                Open-FDD docs
              </a>
            </p>
          </>
        ) : null}

        {loading && (
          <div data-testid="home-loading">
            <span className="spinner" aria-hidden />{" "}
            <span className="loading">Loading overview…</span>
          </div>
        )}
        {error && (
          <InlineAlert id="overview-error" variant="danger">
            {error}
          </InlineAlert>
        )}

        {populated ? (
          <>
            <div className="form-row">
              <Select
                id="overview-building"
                label="Building"
                value={buildingId}
                options={[
                  { value: "", label: "— all / none —" },
                  ...buildings.map((b) => ({ value: b, label: b })),
                ]}
                onChange={(v) => setQuery({ siteId: v || undefined }, true)}
                testId="overview-building"
              />
            </div>
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              <Metric
                id="overview-contract"
                label="Contract"
                value={contractVersion ?? "—"}
                testId="contract-version"
              />
              <Metric
                id="overview-react-ui"
                label="react_ui"
                value={reactUi == null ? "—" : reactUi ? "on" : "off"}
                testId="overview-react-ui"
              />
              <Metric
                id="overview-ui-generation"
                label="UI generation"
                value={uiGeneration ?? "—"}
                testId="overview-ui-generation"
              />
              <Metric
                id="overview-eq-count"
                label="Equipment"
                value={String(eqRows.length)}
                testId="overview-eq-count"
              />
            </div>
            <p>
              <Link to="/metering">Open Metering</Link>
              {" · "}
              <Link to="/jobs">Jobs</Link>
              {" · "}
              <Link to="/rules">Run Rules</Link>
            </p>
            <DataTable
              id="overview-equipment"
              label="Equipment inventory"
              columns={[
                { key: "equipment_id", header: "equipment_id" },
                { key: "equipment_type", header: "type" },
              ]}
              rows={eqRows}
              loading={loading}
              testId="overview-equipment"
            />
          </>
        ) : (
          <Expander
            id="overview-dev-metrics"
            label="Dev diagnostics (contract / equipment)"
            expanded={devOpen}
            onChange={setDevOpen}
            testId="overview-dev-metrics"
          >
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              <Metric
                id="overview-contract"
                label="Contract"
                value={contractVersion ?? "—"}
                testId="contract-version"
              />
              <Metric
                id="overview-react-ui"
                label="react_ui"
                value={reactUi == null ? "—" : reactUi ? "on" : "off"}
                testId="overview-react-ui"
              />
              <Metric
                id="overview-ui-generation"
                label="UI generation"
                value={uiGeneration ?? "—"}
                testId="overview-ui-generation"
              />
              <Metric
                id="overview-eq-count"
                label="Equipment"
                value={String(eqRows.length)}
                testId="overview-eq-count"
              />
            </div>
          </Expander>
        )}

        <Expander
          id="widget-gallery"
          label="Widget gallery (UI primitives)"
          expanded={galleryOpen}
          onChange={setGalleryOpen}
          testId="widget-gallery"
        >
          <p>
            Controlled parity widgets for shell regression; primary Overview
            matches Streamlit oracle hero + Sites sidebar.
          </p>
        </Expander>
      </div>
    </AppShell>
  );
}
