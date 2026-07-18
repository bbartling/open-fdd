import { useEffect, useState } from "react";
import { formatApiError } from "../lib/formatApiError";
import {
  COOKBOOK_ROLES,
  updatePackageRoles,
  type PackageEquipment,
  type PackageImportResponse,
} from "../lib/csvPackageImport";

type Props = {
  result: PackageImportResponse;
  onRolesSaved?: (equipmentId: string, roles: Record<string, string>) => void;
};

function rolesFromEquipment(equipment: PackageEquipment): Record<string, string> {
  return {
    ...(equipment.roles ?? {}),
    ...Object.fromEntries((equipment.unmapped_columns ?? []).map((c) => [c, ""])),
  };
}

function EquipmentRolesCard({
  buildingId,
  equipment,
  onRolesSaved,
}: {
  buildingId: string;
  equipment: PackageEquipment;
  onRolesSaved?: Props["onRolesSaved"];
}) {
  const [roles, setRoles] = useState<Record<string, string>>(() => rolesFromEquipment(equipment));
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  // Remount-safe: if the same equipment_id is re-imported, reset local edits.
  useEffect(() => {
    setRoles(rolesFromEquipment(equipment));
    setNote("");
    setError("");
  }, [equipment]);

  const columns = Object.keys(roles).sort();

  async function save() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const nonEmpty = Object.fromEntries(
        Object.entries(roles).filter(([, r]) => r.trim() !== ""),
      );
      const out = await updatePackageRoles(buildingId, equipment.equipment_id, nonEmpty);
      if (!out.ok) throw new Error(out.error ?? "role update failed");
      setNote(`Saved · re-ingested ${out.total_rows?.toLocaleString() ?? "?"} rows`);
      onRolesSaved?.(equipment.equipment_id, nonEmpty);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel csv-package-equipment">
      <h4 className="panel-title">
        {equipment.equipment_id}
        {equipment.map_source ? (
          <span className="muted"> · map: {equipment.map_source}</span>
        ) : null}
      </h4>
      {error ? <p className="error">{error}</p> : null}
      {note ? <p className="ok">{note}</p> : null}
      <table className="data-table">
        <thead>
          <tr>
            <th>CSV column</th>
            <th>FDD role</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((col) => (
            <tr key={col}>
              <td>
                <code>{col}</code>
              </td>
              <td>
                <select
                  value={roles[col] ?? ""}
                  disabled={busy}
                  onChange={(e) =>
                    setRoles((prev) => ({ ...prev, [col]: e.target.value }))
                  }
                >
                  {COOKBOOK_ROLES.map((r) => (
                    <option key={r || "(none)"} value={r}>
                      {r || "— unmapped —"}
                    </option>
                  ))}
                  {roles[col] && !COOKBOOK_ROLES.includes(roles[col]!) ? (
                    <option value={roles[col]}>{roles[col]}</option>
                  ) : null}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className="secondary-btn" disabled={busy} onClick={() => void save()}>
        {busy ? "Saving…" : "Save roles & re-ingest"}
      </button>
    </div>
  );
}

/** Result panel for an openfdd_package_v1 zip import (#514): building summary +
 * per-equipment editable role mapping backed by /api/csv/import/package/roles. */
export default function PackageImportPanel({ result, onRolesSaved }: Props) {
  const buildingId = result.building_id ?? "";
  return (
    <section className="panel csv-package-result">
      <h3 className="panel-title">Package: {buildingId}</h3>
      <p className="muted">
        {result.equipment_written ?? result.equipment?.length ?? 0} equipment ·{" "}
        {result.total_rows?.toLocaleString() ?? "?"} rows · grid {result.grid_minutes ?? "?"} min
        {result.timezone ? ` · ${result.timezone}` : ""}
        {result.session_config ? " · session_config.json detected" : ""}
      </p>
      {(result.warnings ?? []).length > 0 ? (
        <ul className="csv-upload-results">
          {result.warnings!.map((w, i) => (
            <li key={i} className="muted">
              ⚠ {w}
            </li>
          ))}
        </ul>
      ) : null}
      {(result.equipment ?? []).map((eq) => (
        <EquipmentRolesCard
          key={eq.equipment_id}
          buildingId={buildingId}
          equipment={eq}
          onRolesSaved={onRolesSaved}
        />
      ))}
    </section>
  );
}
