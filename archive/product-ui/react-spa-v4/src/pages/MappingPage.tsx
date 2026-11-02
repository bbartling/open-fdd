import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  InlineAlert,
  Select,
  Toggle,
} from "../components/widgets";
import { DeviceTree } from "../components/DeviceTree";
import { ProviderBindingsPanel } from "../components/ProviderBindingsPanel";
import { ResultsByCategoryPanel } from "../components/ResultsByCategoryPanel";
import { useSessionQuery } from "../session";
import {
  buildMappingManifest,
  getPackageMapping,
  listPackageBuildings,
  type MappingEquipment,
  type PackageMappingResponse,
} from "../api/mappingApi";
import { getHistorianPoints, type HistorianPoint } from "../api/historianApi";
import { listProviderBuildingIds } from "../api/providersApi";
import { buildDataModelTurtle } from "../api/dataModelTurtle";
import { listFddRules, type FddRuleSummary } from "../api/fddApi";
import {
  activeIngestRevision,
  columnNames,
  mappingRevisionLabels,
  savedAuthorityLabel,
  seedDraftRoles,
} from "../lib/mappingDraft";
import {
  checkLine,
  summarizeMappingValidation,
} from "../lib/mappingValidation";

type ColumnRow = {
  row_key: string;
  column: string;
  role: string;
  status: string;
  fdd_rules: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function buildRoleToFddRules(rules: FddRuleSummary[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const r of rules) {
    const id = String(r.rule_id ?? "").trim();
    if (!id || r.applicability === "unknown" || !Array.isArray(r.required_roles)) {
      continue;
    }
    const roles = [
      ...r.required_roles,
      ...(Array.isArray(r.optional_roles) ? r.optional_roles : []),
    ];
    for (const role of roles) {
      const key = String(role ?? "").trim();
      if (!key) continue;
      const list = map.get(key) ?? [];
      if (!list.includes(id)) list.push(id);
      map.set(key, list);
    }
  }
  for (const [, list] of map) list.sort();
  return map;
}

export function MappingPage() {
  const { query, setQuery } = useSessionQuery();
  const [searchParams, setSearchParams] = useSearchParams();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";
  const view = searchParams.get("view") === "results" ? "results" : "mapping";

  const setView = (next: "mapping" | "results") => {
    const params = new URLSearchParams(searchParams);
    if (next === "results") params.set("view", "results");
    else params.delete("view");
    setSearchParams(params, { replace: true });
  };

  const [buildings, setBuildings] = useState<string[]>([]);
  /** Full-site inventory for export (never equipment-filtered). */
  const [siteInventory, setSiteInventory] = useState<PackageMappingResponse | null>(
    null,
  );
  const [inventory, setInventory] = useState<PackageMappingResponse | null>(null);
  const [historianPoints, setHistorianPoints] = useState<HistorianPoint[] | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showUnmappedOnly, setShowUnmappedOnly] = useState(false);
  const [providerOnlySite, setProviderOnlySite] = useState(false);
  const [fddRules, setFddRules] = useState<FddRuleSummary[]>([]);

  const roleToFdd = useMemo(() => buildRoleToFddRules(fddRules), [fddRules]);

  const selectedEq: MappingEquipment | null = useMemo(() => {
    const list = inventory?.equipment ?? [];
    if (!list.length) return null;
    if (equipmentId) {
      return list.find((e) => e.equipment_id === equipmentId) ?? null;
    }
    return list[0];
  }, [inventory, equipmentId]);

  const refreshBuildings = useCallback(async () => {
    let packages: string[] = [];
    try {
      packages = await listPackageBuildings();
    } catch (err) {
      setError(formatErr(err));
    }
    const portals = await listProviderBuildingIds();
    const merged = new Set<string>([...packages, ...portals]);
    setBuildings([...merged].sort((a, b) => a.localeCompare(b)));
  }, []);

  const inventoryGen = useRef(0);

  const refreshInventory = useCallback(async () => {
    const ticket = ++inventoryGen.current;
    if (!buildingId) {
      setInventory(null);
      setSiteInventory(null);
      setProviderOnlySite(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // Full site inventory first (export SoT); the equipment filter narrows the view.
      const invAll = await getPackageMapping(buildingId);
      if (ticket !== inventoryGen.current) return;
      setProviderOnlySite(false);
      setSiteInventory(invAll);
      const ids = invAll.equipment_ids ?? [];
      let inv = invAll;
      let eqId = equipmentId;
      if (eqId && !ids.includes(eqId)) {
        setQuery({ equipment: "" }, true);
        eqId = "";
        setError(
          `Equipment "${equipmentId}" is not in site ${buildingId} — cleared selection.`,
        );
      } else if (eqId) {
        inv = await getPackageMapping(buildingId, eqId);
        if (ticket !== inventoryGen.current) return;
      }
      setInventory(inv);
      const eq =
        (eqId
          ? inv.equipment?.find((e) => e.equipment_id === eqId)
          : inv.equipment?.[0]) ?? null;
      if (eq && !eqId) {
        setQuery({ equipment: eq.equipment_id }, true);
      }
    } catch (err) {
      if (ticket !== inventoryGen.current) return;
      setInventory(null);
      setSiteInventory(null);
      const portals = await listProviderBuildingIds();
      if (ticket !== inventoryGen.current) return;
      if (portals.includes(buildingId)) {
        setProviderOnlySite(true);
        setError(null);
      } else {
        setProviderOnlySite(false);
        setError(formatErr(err));
      }
    } finally {
      if (ticket === inventoryGen.current) setLoading(false);
    }
  }, [buildingId, equipmentId, setQuery]);

  useEffect(() => {
    void refreshBuildings();
  }, [refreshBuildings]);

  useEffect(() => {
    if (!buildingId) {
      setHistorianPoints(null);
      return;
    }
    const ctrl = new AbortController();
    getHistorianPoints(buildingId, ctrl.signal)
      .then((res) => {
        if (!ctrl.signal.aborted) setHistorianPoints(res.points ?? []);
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setHistorianPoints(null);
      });
    return () => ctrl.abort();
  }, [buildingId]);

  useEffect(() => {
    void listFddRules()
      .then(setFddRules)
      .catch(() => setFddRules([]));
  }, []);

  useEffect(() => {
    void refreshInventory();
  }, [refreshInventory]);

  /** Prefer site/equip inventory only when it matches the selected building. */
  const exportSource = (() => {
    if (!buildingId) return null;
    const candidates = [siteInventory, inventory];
    for (const src of candidates) {
      if (
        src &&
        (src.building_id ?? "").trim() === buildingId &&
        (src.equipment?.length ?? 0) > 0
      ) {
        return src;
      }
    }
    return null;
  })();
  const hasSiteModel = exportSource != null;

  const onDownloadManifest = () => {
    const src = exportSource;
    if (!src || !buildingId) return;
    const blob = new Blob([buildMappingManifest(src)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `data_model_${src.building_id ?? buildingId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const onViewManifestText = () => {
    const src = exportSource;
    if (!src || !buildingId) return;
    const text = buildMappingManifest(src);
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    // Revoke later so the new tab can load.
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const onDownloadTtl = () => {
    const src = exportSource;
    if (!src || !buildingId) return;
    const blob = new Blob([buildDataModelTurtle(src)], {
      type: "text/turtle;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `data_model_${src.building_id ?? buildingId}.ttl`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const onViewTtlText = () => {
    const src = exportSource;
    if (!src || !buildingId) return;
    const blob = new Blob([buildDataModelTurtle(src)], {
      type: "text/turtle;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  };

  const savedRoles = useMemo(() => seedDraftRoles(selectedEq), [selectedEq]);
  const editorColumns = useMemo(() => columnNames(selectedEq), [selectedEq]);

  const tableRows: ColumnRow[] = useMemo(() => {
    return editorColumns
      .map((column) => {
        const role = (savedRoles[column] ?? "").trim();
        const consumers = role ? (roleToFdd.get(role) ?? []) : [];
        const owners = role
          ? editorColumns.filter((name) => (savedRoles[name] ?? "").trim() === role)
          : [];
        let status = "mapped";
        if (!role) status = "unmapped";
        else if (owners.length > 1) status = "ambiguous";
        return {
          row_key: column,
          column,
          role,
          status,
          fdd_rules: consumers.length
            ? consumers.slice(0, 8).join(", ") + (consumers.length > 8 ? "…" : "")
            : role
              ? "(analytics only)"
              : "—",
        };
      })
      .filter((row) => (showUnmappedOnly ? row.status !== "mapped" : true));
  }, [editorColumns, savedRoles, showUnmappedOnly, roleToFdd]);

  const revisionView = useMemo(() => {
    if (!selectedEq) return null;
    return mappingRevisionLabels({
      dirty: false,
      draftRoles: savedRoles,
      savedRoles: selectedEq.roles ?? {},
      savedAuthorityLabel: savedAuthorityLabel(inventory),
      activeIngestRevision: activeIngestRevision(inventory),
    });
  }, [selectedEq, savedRoles, inventory]);

  const validationSummary = useMemo(
    () => summarizeMappingValidation(inventory),
    [inventory],
  );

  const buildingOptions = [
    { value: "", label: "— select building —" },
    ...buildings.map((b) => ({ value: b, label: b })),
  ];
  const equipmentOptions = [
    { value: "", label: "— select equipment —" },
    ...((siteInventory ?? inventory)?.equipment_ids ?? []).map((id) => ({
      value: id,
      label: id,
    })),
  ];
  return (
    <AppShell
      title="Data Model"
      caption={undefined}
      activeSectionId="data-model"
    >
      <div className="page-placeholder" data-testid="mapping-page">
        <div
          className="data-model-subnav"
          role="tablist"
          aria-label="Data Model panels"
          data-testid="data-model-subnav"
        >
          <button
            type="button"
            role="tab"
            className={`data-model-subnav__tab${view === "mapping" ? " data-model-subnav__tab--active" : ""}`}
            aria-selected={view === "mapping"}
            onClick={() => setView("mapping")}
            data-testid="data-model-tab-mapping"
          >
            Mapping
          </button>
          <button
            type="button"
            role="tab"
            className={`data-model-subnav__tab${view === "results" ? " data-model-subnav__tab--active" : ""}`}
            aria-selected={view === "results"}
            onClick={() => setView("results")}
            data-testid="data-model-tab-results"
          >
            Results by Category
          </button>
        </div>

        {view === "results" ? (
          <ResultsByCategoryPanel />
        ) : (
          <>
        <h2>Role mapping</h2>

        <InlineAlert id="mapping-read-only" variant="info" testId="mapping-read-only">
          This page is read-only for every site. To change the building model, ask an AI
          agent to use the Open-FDD REST model endpoints or the openfdd-mcp write tools
          (operator or admin token, <code>confirm: true</code>). For a Normal Framework
          portal site, tag the points on the portal: the next poll updates the model.
        </InlineAlert>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            alignItems: "flex-end",
            marginBottom: "0.75rem",
          }}
        >
          <Button
            id="map-download-manifest"
            label="Export site data model"
            variant="secondary"
            onClick={onDownloadManifest}
            disabled={!hasSiteModel}
            testId="map-download-manifest"
          />
          <Button
            id="map-view-manifest-text"
            label="View as text"
            variant="secondary"
            onClick={onViewManifestText}
            disabled={!hasSiteModel}
            testId="map-view-manifest-text"
          />
          <Button
            id="map-download-ttl"
            label="Export inventory TTL"
            variant="secondary"
            onClick={onDownloadTtl}
            disabled={!hasSiteModel}
            testId="map-download-ttl"
          />
          <Button
            id="map-view-ttl-text"
            label="View inventory TTL"
            variant="secondary"
            onClick={onViewTtlText}
            disabled={!hasSiteModel}
            testId="map-view-ttl-text"
          />
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
          <Select
            id="map-building"
            label="Building (site)"
            value={buildingId}
            options={buildingOptions}
            onChange={(value) => setQuery({ siteId: value, equipment: "" }, true)}
            testId="map-building-select"
          />
          <Select
            id="map-equipment"
            label="Equipment"
            value={equipmentId}
            options={equipmentOptions}
            onChange={(value) => setQuery({ equipment: value }, true)}
            testId="map-equipment-select"
            disabled={!buildingId}
          />
          <Toggle
            id="map-unmapped-only"
            label="Show gaps only"
            checked={showUnmappedOnly}
            onChange={setShowUnmappedOnly}
            testId="map-unmapped-only"
          />
        </div>

        {loading ? (
          <p data-testid="mapping-loading">Loading mapping inventory…</p>
        ) : null}

        {error ? (
          <InlineAlert id="mapping-error" variant="danger" testId="mapping-error">
            {error}
          </InlineAlert>
        ) : null}

        {!buildingId ? (
          <InlineAlert
            id="mapping-empty-building"
            variant="info"
            testId="mapping-empty-building"
          >
            Select a site. Portal sites appear from provider configuration. CSV sites
            appear after a package upload.
          </InlineAlert>
        ) : null}

        {buildingId ? <ProviderBindingsPanel buildingId={buildingId} /> : null}

        {providerOnlySite ? (
          <InlineAlert
            id="mapping-provider-only"
            variant="info"
            testId="mapping-provider-only"
          >
            This site is in the provider registry and has no CSV package inventory.
            The column table stays empty until a package or a committed model is present.
            Bindings above stay separate from CSV column roles.
          </InlineAlert>
        ) : null}

        {validationSummary ? (
          <div data-testid="mapping-validation-summary">
            <p>{validationSummary.headline}</p>
            <ul>
              {validationSummary.checks.map((check) => (
                <li key={check.id}>{checkLine(check)}</li>
              ))}
            </ul>
            <p>{validationSummary.sourceLabel}</p>
          </div>
        ) : null}

        {revisionView ? (
          <div data-testid="mapping-revisions">
            <p data-testid="mapping-revision-saved">{revisionView.saved}</p>
            <p data-testid="mapping-revision-active">{revisionView.active}</p>
          </div>
        ) : null}

        {selectedEq ? (
          <div data-testid="mapping-equipment-detail">
            <p>
              <strong>{selectedEq.equipment_id}</strong> · type{" "}
              <code>{selectedEq.equipment_type}</code>
              {selectedEq.parent_ahu ? (
                <>
                  {" "}
                  · parent AHU <code>{selectedEq.parent_ahu}</code>
                  {selectedEq.parent_ahu_source === "inferred" ? (
                    <> (proposed)</>
                  ) : null}
                </>
              ) : null}
            </p>
            {selectedEq.sampling ? (
              <p data-testid="mapping-sampling">
                Sampling: {selectedEq.sampling.row_count ?? 0} rows
                {selectedEq.sampling.first_timestamp
                  ? ` · ${selectedEq.sampling.first_timestamp}`
                  : ""}
                {selectedEq.sampling.last_timestamp
                  ? ` → ${selectedEq.sampling.last_timestamp}`
                  : ""}
              </p>
            ) : null}
            {(selectedEq.blockers ?? []).length > 0 ? (
              <InlineAlert
                id="mapping-blocker"
                variant="danger"
                testId="mapping-blocker"
              >
                {(selectedEq.blockers ?? []).slice(0, 3).join(" ")}
                {(selectedEq.blockers ?? []).length > 3
                  ? ` (+${(selectedEq.blockers ?? []).length - 3} more)`
                  : ""}
              </InlineAlert>
            ) : null}
            {(selectedEq.warnings ?? []).length > 0 ? (
              <InlineAlert
                id="mapping-warning"
                variant="warning"
                testId="mapping-warning"
              >
                {(selectedEq.warnings ?? []).slice(0, 3).join(" ")}
                {(selectedEq.warnings ?? []).length > 3
                  ? ` (+${(selectedEq.warnings ?? []).length - 3} more)`
                  : ""}
              </InlineAlert>
            ) : null}

            <DataTable
              id="map-columns"
              label="Column role assignments"
              columns={[
                { key: "column", header: "Column" },
                { key: "role", header: "Role" },
                { key: "status", header: "Status" },
                { key: "fdd_rules", header: "FDD rules" },
              ]}
              rows={tableRows}
              testId="map-columns-table"
            />
          </div>
        ) : null}

        {buildingId && historianPoints ? (
          <div data-testid="mapping-device-tree">
            <h3>Device tree</h3>
            <DeviceTree points={historianPoints} testId="mapping-tree" />
          </div>
        ) : null}
          </>
        )}
      </div>
    </AppShell>
  );
}
