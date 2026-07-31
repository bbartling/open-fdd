import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  InlineAlert,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  downloadTextFile,
  getFddResults,
  resultsToCsvArtifact,
  resultsToJsonArtifact,
  type FddResultRow,
} from "../api/fddApi";

type ResultTableRow = {
  rule_id: string;
  equipment_id: string;
  status: string;
  fault_hours: string;
  missing_roles: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function FindingsPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentFilter = query.equipment ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [rows, setRows] = useState<FddResultRow[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!buildingId) {
      setRows([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const results = await getFddResults(buildingId);
      setRows(results);
    } catch (err) {
      setRows([]);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId]);

  useEffect(() => {
    void listPackageBuildings()
      .then(setBuildings)
      .catch(() => setBuildings([]));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const equipmentOptions = useMemo(() => {
    const ids = Array.from(new Set(rows.map((r) => r.equipment_id))).sort();
    return [
      { value: "", label: "— all equipment —" },
      ...ids.map((id) => ({ value: id, label: id })),
    ];
  }, [rows]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (equipmentFilter && r.equipment_id !== equipmentFilter) return false;
      if (statusFilter && r.status !== statusFilter) return false;
      return true;
    });
  }, [rows, equipmentFilter, statusFilter]);

  const tableRows: ResultTableRow[] = filtered.map((r) => ({
    rule_id: r.rule_id,
    equipment_id: r.equipment_id,
    status: r.status,
    fault_hours: String(r.fault_hours ?? ""),
    missing_roles: (r.missing_roles ?? []).join(", "),
  }));

  const buildingOptions = [
    { value: "", label: "— select building —" },
    ...buildings.map((b) => ({ value: b, label: b })),
  ];

  const statusOptions = [
    { value: "", label: "— all statuses —" },
    { value: "FAULT", label: "FAULT" },
    { value: "PASS", label: "PASS" },
    { value: "SKIPPED", label: "SKIPPED" },
  ];

  const onDownloadJson = () => {
    downloadTextFile(
      `fdd_results_${buildingId || "unknown"}.json`,
      resultsToJsonArtifact(filtered, {
        building_id: buildingId,
        equipment_filter: equipmentFilter || null,
        status_filter: statusFilter || null,
      }),
      "application/json",
    );
  };

  const onDownloadCsv = () => {
    downloadTextFile(
      `fdd_results_${buildingId || "unknown"}.csv`,
      resultsToCsvArtifact(filtered),
      "text/csv",
    );
  };

  return (
    <AppShell
      title="Findings"
      caption="FDD result rows from last registry run (Rust/DataFusion)."
      activeSectionId="results"
    >
      <div className="page-placeholder" data-testid="findings-page">
        <h2>Results</h2>
        <p>
          Loads <code>GET /api/fdd/results?building_id=</code>. Run rules from{" "}
          <Link to={buildingId ? `/rules?site=${encodeURIComponent(buildingId)}` : "/rules"}>
            Run Rules
          </Link>
          . Download filtered JSON/CSV artifacts (no Python).
        </p>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
          <Select
            id="findings-building"
            label="Building"
            value={buildingId}
            options={buildingOptions}
            onChange={(value) => setQuery({ siteId: value }, true)}
            testId="findings-building-select"
          />
          <Select
            id="findings-equipment"
            label="Equipment"
            value={equipmentFilter}
            options={equipmentOptions}
            onChange={(value) => setQuery({ equipment: value }, true)}
            testId="findings-equipment-select"
            disabled={!buildingId}
          />
          <Select
            id="findings-status"
            label="Status"
            value={statusFilter}
            options={statusOptions}
            onChange={setStatusFilter}
            testId="findings-status-select"
          />
        </div>

        <div style={{ display: "flex", gap: "0.5rem", margin: "0.75rem 0", flexWrap: "wrap" }}>
          <Button
            id="findings-reload"
            label={loading ? "Loading…" : "Reload"}
            onClick={() => void refresh()}
            disabled={loading || !buildingId}
            testId="findings-reload"
          />
          <Button
            id="findings-download-json"
            label="Download JSON"
            variant="secondary"
            onClick={onDownloadJson}
            disabled={!filtered.length}
            testId="findings-download-json"
          />
          <Button
            id="findings-download-csv"
            label="Download CSV"
            variant="secondary"
            onClick={onDownloadCsv}
            disabled={!filtered.length}
            testId="findings-download-csv"
          />
        </div>

        {error ? (
          <InlineAlert id="findings-error" variant="danger" testId="findings-error">
            {error}
          </InlineAlert>
        ) : null}

        {!buildingId ? (
          <InlineAlert
            id="findings-empty"
            variant="info"
            testId="findings-empty"
          >
            Select a building to load results.
          </InlineAlert>
        ) : null}

        <p data-testid="findings-count">
          Showing {filtered.length} of {rows.length} row(s)
        </p>

        <DataTable
          id="findings-table"
          label="Fault / pass rows"
          columns={[
            { key: "rule_id", header: "Rule" },
            { key: "equipment_id", header: "Equipment" },
            { key: "status", header: "Status" },
            { key: "fault_hours", header: "Fault hours" },
            { key: "missing_roles", header: "Missing roles" },
          ]}
          rows={tableRows}
          testId="findings-table"
        />
      </div>
    </AppShell>
  );
}
