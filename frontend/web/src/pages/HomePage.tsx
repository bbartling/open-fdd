import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import { apiFetch } from "../api/client";
import type { CapabilitiesResponse } from "../api/contract";
import {
  Expander,
  InlineAlert,
  Metric,
} from "../components/widgets";
import { OverviewPopulated } from "../components/OverviewPopulated";
import { OverviewHero } from "../components/OverviewHero";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  listFddEquipment,
  type FddEquipmentItem,
} from "../api/analyticsApi";
import { getUiGeneration } from "../api/cutoverApi";
import { naturalSorted } from "../naturalSort";

const DOCS_URL = "https://bbartling.github.io/open-fdd/";
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

/** Streamlit-oracle Overview: always-on hero + populated analytics when a package is loaded. */
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
  const refreshSeq = useRef(0);

  const refresh = useCallback(async () => {
    const seq = ++refreshSeq.current;
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
      if (seq !== refreshSeq.current) return;
      setContractVersion(caps.contract.contract_version);
      setReactUi(Boolean(caps.capabilities?.react_ui));
      setUiGeneration(gen?.generation ?? null);
      setBuildings(blds);
      const sortedEq = naturalSorted(eq, (e) => String(e.equipment_id));
      setEquipment(sortedEq);
      if (!buildingId && blds[0]) {
        setQuery({ siteId: blds[0] }, true);
      }
      const ids = new Set(sortedEq.map((e) => String(e.equipment_id)));
      if (buildingId && sortedEq[0] && (!equipmentId || !ids.has(equipmentId))) {
        setQuery({ equipment: String(sortedEq[0].equipment_id) }, true);
      }
    } catch (err) {
      if (seq !== refreshSeq.current) return;
      setError(formatErr(err));
    } finally {
      if (seq === refreshSeq.current) setLoading(false);
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
        <OverviewHero />
        {populated ? (
          <p className="oracle-sidebar__caption" data-testid="overview-active-site">
            Active site <code>{buildingId || "—"}</code>
            {buildings.length > 1
              ? ` · ${buildings.length} buildings loaded`
              : ""}
          </p>
        ) : null}

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
              Haystack map JSON. Then <strong>Run all rules</strong> (Overview) →{" "}
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
