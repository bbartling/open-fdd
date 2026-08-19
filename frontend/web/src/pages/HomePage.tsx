import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { apiFetch } from "../api/client";
import type { CapabilitiesResponse } from "../api/contract";
import {
  Expander,
  InlineAlert,
  Metric,
} from "../components/widgets";
import { OverviewHero } from "../components/OverviewHero";
import { OverviewPopulated } from "../components/OverviewPopulated";
import { SectionTabs } from "../components/SectionTabs";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  listFddEquipment,
  type FddEquipmentItem,
} from "../api/analyticsApi";
import { getUiGeneration } from "../api/cutoverApi";
import { inventoryWithoutWeather } from "../lib/overviewMetrics";

const AGENTS_URL =
  "https://github.com/bbartling/py-bacnet-stacks-playground/blob/develop/vibe_code_apps_19/AGENTS.md";

const PACKAGE_LOADED = "openfdd:package-loaded";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
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

/** Overview: empty hero OR populated analytics dashboard. */
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
  const [devOpen, setDevOpen] = useState(false);
  const [unitSystem, setUnitSystem] = useState(readUnits);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [caps, gen, blds, eq] = await Promise.all([
        apiFetch<CapabilitiesResponse>("/api/capabilities"),
        getUiGeneration().catch(() => null),
        // Open mode allows these without a browser token; AuthGate blocks when
        // auth_required and there is no session.
        listPackageBuildings().catch(() => [] as string[]),
        listFddEquipment(buildingId || undefined).catch(
          () => [] as FddEquipmentItem[],
        ),
      ]);
      const inventory = inventoryWithoutWeather(eq);
      setContractVersion(caps.contract.contract_version);
      setReactUi(Boolean(caps.capabilities?.react_ui));
      setUiGeneration(gen?.generation ?? null);
      setBuildings(blds);
      setEquipment(inventory);
      if (!buildingId && blds[0]) {
        setQuery({ siteId: blds[0] }, true);
      }
      if (buildingId && !equipmentId && inventory[0]) {
        setQuery({ equipment: String(inventory[0].equipment_id) }, true);
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
    <AppShell
      title="Open FDD"
      activeSectionId="overview"
      hideHeader
      hideSectionTabs
    >
      <div className="page-stack oracle-overview" data-testid="overview-page">
        <OverviewHero
          buildingId={buildingId}
          buildingCount={buildings.length}
          populated={populated}
        />

        {!populated ? (
          <>
            <InlineAlert
              id="overview-start-here"
              variant="info"
              testId="overview-start-here"
            >
              <strong>Start here:</strong> sidebar →{" "}
              <strong>Building package zip</strong> →{" "}
              <strong>Load package</strong>. Then Data Model →{" "}
              <strong>Update analytics</strong> / <strong>Run all rules</strong>{" "}
              → <strong>FDD Plots</strong> / <strong>RCx</strong>.
            </InlineAlert>
            <SectionTabs activeSectionId="overview" embedded />
            <p className="oracle-overview__footer-links">
              Agent brief:{" "}
              <a href={AGENTS_URL} target="_blank" rel="noreferrer">
                AGENTS.md
              </a>
              {" · "}
              Package contract: <code>docs/PACKAGE_SPEC.md</code>
              {" · "}
              <a
                href="https://bbartling.github.io/open-fdd/"
                target="_blank"
                rel="noreferrer"
              >
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

      </div>
    </AppShell>
  );
}
