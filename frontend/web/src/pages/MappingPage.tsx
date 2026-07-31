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
  listPackageBuildings,
  putSessionConfig,
  updatePackageRoles,
  type MappingEquipment,
  type PackageMappingResponse,
  type SessionConfig,
} from "../api/mappingApi";

type ColumnRow = {
  column: string;
  role: string;
  status: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function MappingPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
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

  const selectedEq: MappingEquipment | null = useMemo(() => {
    const list = inventory?.equipment ?? [];
    if (!list.length) return null;
    if (equipmentId) {
      return list.find((e) => e.equipment_id === equipmentId) ?? list[0];
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
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [inv, sess] = await Promise.all([
        getPackageMapping(buildingId, equipmentId || undefined),
        getSessionConfig(),
      ]);
      setInventory(inv);
      setSessionConfig(sess.config ?? null);
      const eq =
        (equipmentId
          ? inv.equipment?.find((e) => e.equipment_id === equipmentId)
          : inv.equipment?.[0]) ?? null;
      setDraftRoles({ ...(eq?.roles ?? {}) });
      setDirty(false);
      if (eq && !equipmentId) {
        setQuery({ equipment: eq.equipment_id }, true);
      }
    } catch (err) {
      setInventory(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, equipmentId, setQuery]);

  useEffect(() => {
    void refreshBuildings();
  }, [refreshBuildings]);

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

  const onDownloadManifest = () => {
    if (!inventory) return;
    const blob = new Blob([buildMappingManifest(inventory)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mapping_manifest_${inventory.building_id ?? "unknown"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const tableRows: ColumnRow[] = useMemo(() => {
    const cols = selectedEq?.columns ?? [];
    return cols
      .map((c) => ({
        column: c.column,
        role: draftRoles[c.column] ?? c.role ?? "",
        status: (() => {
          const role = draftRoles[c.column] ?? c.role ?? "";
          if (!role) return "unmapped";
          const owners = Object.entries(draftRoles)
            .filter(([, r]) => r === role)
            .map(([col]) => col);
          return owners.length > 1 ? "ambiguous" : "mapped";
        })(),
      }))
      .filter((r) => (showUnmappedOnly ? r.status !== "mapped" : true));
  }, [selectedEq, draftRoles, showUnmappedOnly]);

  const buildingOptions = [
    { value: "", label: "— select building —" },
    ...buildings.map((b) => ({ value: b, label: b })),
  ];
  const equipmentOptions = [
    { value: "", label: "— select equipment —" },
    ...(inventory?.equipment_ids ?? []).map((id) => ({ value: id, label: id })),
  ];

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
          Uses <code>GET /api/csv/import/package/mapping</code>,{" "}
          <code>POST …/package/roles</code>, and{" "}
          <code>PUT /api/fdd/session-config</code>. Blank roles stay blank — no
          guessed fills. Session selection: <code>?site=</code> building,{" "}
          <code>?eq=</code> equipment.
        </p>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
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
            label="Equipment"
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
              ]}
              rows={tableRows}
              testId="map-columns-table"
            />

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
                {(selectedEq.columns ?? []).map((c) => (
                  <label
                    key={c.column}
                    htmlFor={`role-${c.column}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "0.5rem",
                      alignItems: "center",
                    }}
                  >
                    <span>
                      <code>{c.column}</code>
                    </span>
                    <input
                      id={`role-${c.column}`}
                      data-testid={`map-role-input-${c.column}`}
                      value={draftRoles[c.column] ?? ""}
                      placeholder="(unmapped)"
                      onChange={(e) => onRoleChange(c.column, e.target.value)}
                    />
                  </label>
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
              <Button
                id="map-download-manifest"
                label="Download mapping manifest"
                variant="secondary"
                onClick={onDownloadManifest}
                disabled={!inventory}
                testId="map-download-manifest"
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
