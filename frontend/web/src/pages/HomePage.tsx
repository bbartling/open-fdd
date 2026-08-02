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

type EqRow = {
  equipment_id: string;
  equipment_type: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

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

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [caps, gen, blds, eq] = await Promise.all([
        apiFetch<CapabilitiesResponse>("/api/capabilities"),
        getUiGeneration().catch(() => null),
        listPackageBuildings().catch(() => [] as string[]),
        listFddEquipment(buildingId || undefined).catch(
          () => [] as FddEquipmentItem[],
        ),
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

  return (
    <AppShell
      title="Overview"
      caption="Equipment inventory + contract bootstrap (P1-M5-C)"
      activeSectionId="overview"
    >
      <div className="page-stack" data-testid="overview-page">
        <InlineAlert id="overview-hint" variant="info">
          Thin Overview: capabilities + `/api/fdd/equipment`. Metering and RCx
          live under Metering.
        </InlineAlert>

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

        <Expander
          id="widget-gallery"
          label="Widget gallery (M3 primitives)"
          expanded={galleryOpen}
          onChange={setGalleryOpen}
          testId="widget-gallery"
        >
          <p>
            Controlled parity widgets remain available for shell regression; primary
            Overview content is equipment + contract metrics above.
          </p>
        </Expander>
      </div>
    </AppShell>
  );
}
