import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { apiFetch } from "../api/client";
import type { CapabilitiesResponse } from "../api/contract";
import {
  Expander,
  InlineAlert,
  Metric,
} from "../components/widgets";
import { OverviewPopulated } from "../components/OverviewPopulated";
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

const PACKAGE_LOADED = "openfdd:package-loaded";

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

function readUnits(): "imperial" | "metric" {
  try {
    return localStorage.getItem("openfdd.ui.unit_system") === "metric"
      ? "metric"
      : "imperial";
  } catch {
    return "imperial";
  }
}

/** Streamlit-oracle Overview: empty hero OR populated analytics dashboard. */
export function HomePage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [contractVersion, setContractVersion] = useState<string | null>(null);
  const [reactUi, setReactUi] = useState<boolean | null>(null);
  const [uiGeneration, setUiGeneration] = useState<string | null>(null);
  const [buildings, setBuildings] = useState<string[]>([]);
  const [equipment, setEquipment] = useState<FddEquipmentItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [devOpen, setDevOpen] = useState(false);
  const [unitSystem, setUnitSystem] = useState(readUnits);

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
      if (!buildingId && blds[0]) {
        setQuery({ siteId: blds[0] }, true);
      }
      if (buildingId && !equipmentId && eq[0]) {
        setQuery({ equipment: String(eq[0].equipment_id) }, true);
      }
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, equipmentId, setQuery]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onLoaded = () => {
      void refresh();
    };
    window.addEventListener(PACKAGE_LOADED, onLoaded);
    return () => window.removeEventListener(PACKAGE_LOADED, onLoaded);
  }, [refresh]);

  useEffect(() => {
    const sync = () => setUnitSystem(readUnits());
    const onCustom = (ev: Event) => {
      const detail = (ev as CustomEvent).detail;
      if (detail === "metric" || detail === "imperial") {
        setUnitSystem(detail);
        return;
      }
      sync();
    };
    window.addEventListener("storage", sync);
    window.addEventListener("openfdd:unit-system-changed", onCustom);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("openfdd:unit-system-changed", onCustom);
    };
  }, []);

  const populated = equipment.length > 0;

  return (
    <AppShell title="Open FDD" activeSectionId="overview" hideHeader>
      <div className="page-stack oracle-overview" data-testid="overview-page">
        {!populated ? (
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
                  <strong>Data model</strong> — Column→role map for the active
                  site
                </li>
                <li>
                  <strong>FDD / WattLab</strong> — Run Rules, then WattLab (Fuel
                  / Twin / ECMs) scoped to the site
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
        ) : (
          <header className="oracle-hero oracle-hero--compact">
            <h1 className="oracle-hero__title">Overview</h1>
            <p className="oracle-hero__tagline">
              Active site <code>{buildingId || "—"}</code>
              {buildings.length > 1
                ? ` · ${buildings.length} buildings loaded`
                : ""}
            </p>
          </header>
        )}

        {!populated ? (
          <>
            <InlineAlert
              id="overview-start-here"
              variant="info"
              testId="overview-start-here"
            >
              <strong>Start here:</strong> sidebar →{" "}
              <strong>Building package zip</strong> →{" "}
              <strong>Load package</strong>. Each equipment CSV needs a sibling
              Haystack map JSON. Then <strong>Run Rules</strong> →{" "}
              <strong>FDD Plots</strong> / <strong>RCx</strong>.
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
          <OverviewPopulated
            buildingId={buildingId}
            equipment={equipment}
            equipmentId={equipmentId}
            onEquipmentChange={(id) =>
              setQuery({ equipment: id || undefined }, true)
            }
            unitSystem={unitSystem}
          />
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
                value={String(equipment.length)}
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
