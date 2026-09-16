import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  InlineAlert,
  Select,
  Toggle,
} from "../components/widgets";
import { useDirtyFormWarning, useSessionQuery } from "../session";
import {
  buildMappingManifest,
  getPackageMapping,
  getSessionConfig,
  invertRolesToSessionMap,
  listCookbookRoles,
  listPackageBuildings,
  putSessionConfig,
  updatePackageRoles,
  type MappingEquipment,
  type PackageMappingResponse,
  type SessionConfig,
} from "../api/mappingApi";
import { buildDataModelTurtle } from "../api/dataModelTurtle";
import { listFddRules, type FddRuleSummary } from "../api/fddApi";

type ColumnRow = {
  column: string;
  role: string;
  status: string;
  fdd_rules: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Invert registry required∪optional roles → consuming rule ids. */
function buildRoleToFddRules(rules: FddRuleSummary[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const r of rules) {
    const id = String(r.rule_id ?? "").trim();
    if (!id) continue;
    const roles = [
      ...(r.required_roles ?? []),
      ...(r.optional_roles ?? []),
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
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  /** Full-site inventory for export (never equipment-filtered). */
  const [siteInventory, setSiteInventory] = useState<PackageMappingResponse | null>(
    null,
  );
  const [inventory, setInventory] = useState<PackageMappingResponse | null>(null);
  const [sessionConfig, setSessionConfig] = useState<SessionConfig | null>(null);

  const [draftRoles, setDraftRoles] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  useDirtyFormWarning(dirty);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showUnmappedOnly, setShowUnmappedOnly] = useState(false);
  const [cookbookRoles, setCookbookRoles] = useState<string[]>([]);
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
    try {
      const ids = await listPackageBuildings();
      setBuildings(ids);
    } catch (err) {
      setError(formatErr(err));
    }
  }, []);

  const refreshInventory = useCallback(async () => {
    if (!buildingId) {
      setInventory(null);
      setSiteInventory(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // Load full site inventory first (export SoT); equipment filter is edit-only.
      const [invAll, sess] = await Promise.all([
        getPackageMapping(buildingId),
        getSessionConfig(buildingId),
      ]);
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
      }
      setInventory(inv);
      setSessionConfig(sess.config ?? null);
      const eq =
        (eqId
          ? inv.equipment?.find((e) => e.equipment_id === eqId)
          : inv.equipment?.[0]) ?? null;
      setDraftRoles({ ...(eq?.roles ?? {}) });
      setDirty(false);
      if (eq && !eqId) {
        setQuery({ equipment: eq.equipment_id }, true);
      }
    } catch (err) {
      setInventory(null);
      setSiteInventory(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, equipmentId, setQuery]);

  useEffect(() => {
    void refreshBuildings();
  }, [refreshBuildings]);

  useEffect(() => {
    void listCookbookRoles()
      .then(setCookbookRoles)
      .catch(() => setCookbookRoles([]));
  }, []);

  useEffect(() => {
    void listFddRules()
      .then(setFddRules)
      .catch(() => setFddRules([]));
  }, []);

  useEffect(() => {
    void refreshInventory();
  }, [refreshInventory]);

  const onRoleChange = (column: string, role: string) => {
    setDraftRoles((prev) => {
      const next = { ...prev };
      if (!role.trim()) delete next[column];
      else next[column] = role.trim();
      return next;
    });
    setDirty(true);
    setNotice(null);
  };

  const onSave = async () => {
    if (!buildingId || !selectedEq) {
      setError("Select a building and equipment first");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await updatePackageRoles(buildingId, selectedEq.equipment_id, draftRoles);
      const roleMap = {
        ...(sessionConfig?.role_map ?? {}),
        [selectedEq.equipment_id]: invertRolesToSessionMap(draftRoles),
      };
      const config: SessionConfig = {
        schema_version: "openfdd_session_v1",
        unit_system: sessionConfig?.unit_system ?? inventory?.unit_system ?? "imperial",
        prefer_web_oat: sessionConfig?.prefer_web_oat ?? true,
        role_map: roleMap,
        params: sessionConfig?.params ?? {},
      };
      const saved = await putSessionConfig(config, buildingId);
      setSessionConfig(saved.config ?? config);
      setNotice(
        `Saved mapping for ${selectedEq.equipment_id}` +
          (saved.warnings?.length ? ` (${saved.warnings.length} warning(s))` : ""),
      );
      setDirty(false);
      await refreshInventory();
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSaving(false);
    }
  };

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

  const tableRows: ColumnRow[] = useMemo(() => {
    const cols = selectedEq?.columns ?? [];
    const seen = new Set(cols.map((c) => c.column));
    const extras = (selectedEq?.unmapped_columns ?? []).filter(
      (c) => c && !seen.has(c),
    );
    const allCols = [
      ...cols.map((c) => ({
        column: c.column,
        role: draftRoles[c.column] ?? c.role ?? "",
      })),
      ...extras.map((column) => ({
        column,
        role: draftRoles[column] ?? "",
      })),
    ];
    return allCols
      .map((c) => {
        const role = c.role;
        const consumers = role ? (roleToFdd.get(role) ?? []) : [];
        return {
          column: c.column,
          role,
          status: (() => {
            if (!role) return "unmapped";
            const owners = allCols.filter((x) => x.role === role).map((x) => x.column);
            return owners.length > 1 ? "ambiguous" : "mapped";
          })(),
          fdd_rules: consumers.length
            ? consumers.slice(0, 8).join(", ") + (consumers.length > 8 ? "…" : "")
            : role
              ? "(analytics only)"
              : "—",
        };
      })
      .filter((r) => (showUnmappedOnly ? r.status !== "mapped" : true));
  }, [selectedEq, draftRoles, showUnmappedOnly, roleToFdd]);

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
  const roleOptions = useMemo(() => {
    const catalog = new Set(cookbookRoles);
    for (const role of Object.values(draftRoles)) {
      if (role) catalog.add(role);
    }
    const sorted = [...catalog].sort();
    return [
      { value: "", label: "(unmapped)" },
      ...sorted.map((r) => ({ value: r, label: r })),
    ];
  }, [cookbookRoles, draftRoles]);

  const validation = inventory?.validation;

  return (
    <AppShell
      title="Mapping"
      caption="Column → role mapping via Rust package ingest + session-config."
      activeSectionId="data-model"
    >
      <div className="page-placeholder" data-testid="mapping-page">
        <h2>Role mapping</h2>
        <p>
          Map CSV / historian columns to cookbook roles for the selected building
          and equipment. This tab is <strong>column ↔ role</strong> mapping (package{" "}
          <code>columns.csv</code> or MQTT Parquet columns) — not live Haystack point
          browse. Blank roles stay blank — no guessed fills. Use Active site /
          equipment selectors (or URL <code>?site=</code> / <code>?eq=</code>).
        </p>

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
            label="Export TTL"
            variant="secondary"
            onClick={onDownloadTtl}
            disabled={!hasSiteModel}
            testId="map-download-ttl"
          />
          <Button
            id="map-view-ttl-text"
            label="View TTL as text"
            variant="secondary"
            onClick={onViewTtlText}
            disabled={!hasSiteModel}
            testId="map-view-ttl-text"
          />
        </div>
        <p className="oracle-sidebar__caption">
          Export / view is the <strong>entire site</strong> data model (JSON or Turtle
          derived export — not filtered by the equipment editor below). TTL does not
          replace package zip maps for FDD.
        </p>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
          <Select
            id="map-building"
            label="Building (site)"
            value={buildingId}
            options={buildingOptions}
            onChange={(value) => {
              if (dirty && !window.confirm("Discard unsaved mapping edits?")) return;
              setQuery({ siteId: value, equipment: "" }, true);
            }}
            testId="map-building-select"
          />
          <Select
            id="map-equipment"
            label="Equipment (edit)"
            value={equipmentId}
            options={equipmentOptions}
            onChange={(value) => {
              if (dirty && !window.confirm("Discard unsaved mapping edits?")) return;
              setQuery({ equipment: value }, true);
            }}
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
        <p className="oracle-sidebar__caption">
          To remove a loaded site (feathers + FDD + analytics), use the{" "}
          <strong>Sites</strong> section tab.
        </p>

        {loading ? (
          <p data-testid="mapping-loading">Loading mapping inventory…</p>
        ) : null}

        {error ? (
          <InlineAlert id="mapping-error" variant="danger" testId="mapping-error">
            {error}
          </InlineAlert>
        ) : null}
        {notice ? (
          <InlineAlert id="mapping-notice" variant="success" testId="mapping-notice">
            {notice}
          </InlineAlert>
        ) : null}

        {!buildingId ? (
          <InlineAlert
            id="mapping-empty-building"
            variant="info"
            testId="mapping-empty-building"
          >
            Select a building from an uploaded package, or{" "}
            <Link to="/upload">upload a package</Link> first.
          </InlineAlert>
        ) : null}

        {validation ? (
          <p data-testid="mapping-validation-summary">
            Validation: {validation.blocker_count} blocker(s),{" "}
            {validation.warning_count} warning(s),{" "}
            {validation.equipment_count} equipment — unit system{" "}
            <code>{inventory?.unit_system ?? "—"}</code>
          </p>
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
            {(selectedEq.blockers ?? []).map((b, i) => (
              <InlineAlert
                key={`b-${i}`}
                id={`mapping-blocker-${i}`}
                variant="danger"
                testId="mapping-blocker"
              >
                Blocker: {b}
              </InlineAlert>
            ))}
            {(selectedEq.warnings ?? []).map((w, i) => (
              <InlineAlert
                key={`w-${i}`}
                id={`mapping-warning-${i}`}
                variant="warning"
                testId="mapping-warning"
              >
                Warning: {w}
              </InlineAlert>
            ))}

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
            <p className="oracle-sidebar__caption">
              FDD rules = registry consumers of the assigned SQL role.{" "}
              <em>(analytics only)</em> means mapped but no SQL FDD rule lists that role.
            </p>

            <div style={{ marginTop: "1rem" }}>
              <h3>Edit roles</h3>
              <div
                style={{
                  display: "grid",
                  gap: "0.5rem",
                  maxWidth: "40rem",
                }}
                data-testid="mapping-role-editors"
              >
                {(selectedEq.columns ?? [])
                  .map((c) => c.column)
                  .concat(
                    (selectedEq.unmapped_columns ?? []).filter(
                      (c) =>
                        c &&
                        !(selectedEq.columns ?? []).some((x) => x.column === c),
                    ),
                  )
                  .map((column) => (
                  <div
                    key={column}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "0.5rem",
                      alignItems: "center",
                    }}
                  >
                    <span id={`role-label-${column}`}>
                      <code>{column}</code>
                    </span>
                    <Select
                      id={`role-${column}`}
                      label={`Role for ${column}`}
                      value={draftRoles[column] ?? ""}
                      options={roleOptions}
                      onChange={(value) => onRoleChange(column, value)}
                      testId={`map-role-input-${column}`}
                      density="compact"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                marginTop: "1rem",
                flexWrap: "wrap",
              }}
            >
              <Button
                id="map-save"
                label={saving ? "Saving…" : "Save mapping"}
                onClick={() => void onSave()}
                disabled={saving || !dirty}
                testId="map-save"
              />
              <Button
                id="map-reload"
                label="Reload"
                variant="secondary"
                onClick={() => {
                  if (dirty && !window.confirm("Discard unsaved mapping edits?")) {
                    return;
                  }
                  void refreshInventory();
                }}
                testId="map-reload"
              />
            </div>
            {dirty ? (
              <p className="alert alert--warning" data-testid="map-dirty-banner">
                Unsaved mapping edits — save to persist via Rust.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
