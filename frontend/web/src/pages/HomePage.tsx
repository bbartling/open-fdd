import { useEffect, useState } from "react";
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
import { isAbortError, useScopedLoad } from "../session/scopedLoad";
import { listPackageBuildings } from "../api/mappingApi";
import {
  listFddEquipment,
  type FddEquipmentItem,
} from "../api/analyticsApi";
import { getUiGeneration } from "../api/cutoverApi";
import { inventoryWithoutWeather } from "../lib/overviewMetrics";

const PACKAGE_LOADED = "openfdd:package-loaded";

type ShellSnapshot = {
  contractVersion: string | null;
  reactUi: boolean | null;
  uiGeneration: string | null;
  buildings: string[];
  error: string | null;
};

const EMPTY_SHELL: ShellSnapshot = {
  contractVersion: null,
  reactUi: null,
  uiGeneration: null,
  buildings: [],
  error: null,
};

const EMPTY_EQUIPMENT: FddEquipmentItem[] = [];

async function loadShell(_key: string, signal: AbortSignal): Promise<ShellSnapshot> {
  const [caps, gen, blds] = await Promise.all([
    apiFetch<CapabilitiesResponse>("/api/capabilities", { signal }),
    getUiGeneration().catch((err: unknown) => {
      if (isAbortError(err)) throw err;
      return null;
    }),
    listPackageBuildings({ signal }).then(
      (buildings) => ({ ok: true as const, buildings, error: "" }),
      (err: unknown) => {
        if (isAbortError(err)) throw err;
        return {
          ok: false as const,
          buildings: [] as string[],
          error: err instanceof Error ? err.message : String(err),
        };
      },
    ),
  ]);
  return {
    contractVersion: caps.contract.contract_version,
    reactUi: Boolean(caps.capabilities?.react_ui),
    uiGeneration: gen?.generation ?? null,
    buildings: blds.buildings,
    error: blds.ok ? null : `buildings: ${blds.error}`,
  };
}

async function loadEquipment(key: string, signal: AbortSignal): Promise<FddEquipmentItem[]> {
  const site = key.split("\0")[0] ?? "";
  if (!site) return EMPTY_EQUIPMENT;
  const listed = await listFddEquipment(site, { signal });
  return inventoryWithoutWeather(listed);
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

  const [reloadNonce, setReloadNonce] = useState(0);
  const [devOpen, setDevOpen] = useState(false);
  const [unitSystem, setUnitSystem] = useState(readUnits);
  const shellKey = `shell\0${reloadNonce}`;
  const shellLoad = useScopedLoad(shellKey, loadShell, EMPTY_SHELL);
  const shellReady = shellLoad.committedKey === shellKey;
  const shell = shellReady ? shellLoad.value : EMPTY_SHELL;
  const buildings = shell.buildings;
  const contractVersion = shell.contractVersion;
  const reactUi = shell.reactUi;
  const uiGeneration = shell.uiGeneration;
  const equipmentKey = buildingId ? `${buildingId}\0${reloadNonce}` : "";
  const equipmentLoad = useScopedLoad(equipmentKey, loadEquipment, EMPTY_EQUIPMENT);
  const equipmentReady = equipmentKey !== "" && equipmentLoad.committedKey === equipmentKey;
  const equipment = equipmentReady ? equipmentLoad.value : EMPTY_EQUIPMENT;
  const errorParts = [
    shell.error,
    shellLoad.error ? `overview: ${shellLoad.error}` : null,
    equipmentLoad.error ? `equipment: ${equipmentLoad.error}` : null,
  ].filter((part): part is string => Boolean(part));
  const error = errorParts.length ? errorParts.join("; ") : null;
  const loading = shellLoad.loading || (equipmentKey !== "" && equipmentLoad.loading);

  useEffect(() => {
    if (!shellReady || buildingId || !buildings[0]) return;
    setQuery({ siteId: buildings[0] }, true);
  }, [shellReady, buildingId, buildings, setQuery]);

  useEffect(() => {
    if (!equipmentReady) return;
    const ids = equipment.map((item) => String(item.equipment_id ?? ""));
    if (equipmentId && ids.includes(equipmentId)) return;
    const next = ids[0] ?? "";
    if (next === equipmentId) return;
    setQuery({ equipment: next }, true);
  }, [equipmentReady, equipment, equipmentId, setQuery]);

  useEffect(() => {
    const onLoaded = () => setReloadNonce((nonce) => nonce + 1);
    window.addEventListener(PACKAGE_LOADED, onLoaded);
    return () => window.removeEventListener(PACKAGE_LOADED, onLoaded);
  }, []);

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
          <SectionTabs activeSectionId="overview" embedded />
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
