import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import {
  DataTable,
  Expander,
  InlineAlert,
  Metric,
  Select,
  Button,
  Slider,
  Checkbox,
} from "./widgets";
import { PlotlyHost } from "./widgets/PlotlyHost";
import {
  postRuntime,
  postMechanicalCooling,
  postEconomizer,
  type AnalyticsEnvelope,
  type FddEquipmentItem,
} from "../api/analyticsApi";
import { getFddStatus, listFddRules, getFddResults } from "../api/fddApi";
import {
  getPackageMapping,
  getSessionConfig,
  putSessionConfig,
  type SessionConfig,
} from "../api/mappingApi";
import {
  listReports,
  createReportDraft,
  getEngineeringFindingsReport,
} from "../api/reportsApi";
import { rowsToBarFigure, type PlotlyFigure } from "../api/plotDataset";

const DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

type DaySched = { occupied: boolean; start: string; end: string };

const DEFAULT_WEEK: Record<(typeof DAYS)[number], DaySched> = {
  Monday: { occupied: true, start: "06:00", end: "18:00" },
  Tuesday: { occupied: true, start: "06:00", end: "18:00" },
  Wednesday: { occupied: true, start: "06:00", end: "18:00" },
  Thursday: { occupied: true, start: "06:00", end: "18:00" },
  Friday: { occupied: true, start: "06:00", end: "18:00" },
  Saturday: { occupied: true, start: "06:00", end: "18:00" },
  Sunday: { occupied: true, start: "06:00", end: "18:00" },
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function hoursPerWeek(week: Record<string, DaySched>): number {
  let h = 0;
  for (const d of DAYS) {
    const s = week[d];
    if (!s?.occupied) continue;
    const [sh, sm] = s.start.split(":").map(Number);
    const [eh, em] = s.end.split(":").map(Number);
    h += Math.max(0, eh + em / 60 - (sh + sm / 60));
  }
  return Math.round(h * 10) / 10;
}

function spanHours(start?: string | null, end?: string | null): number | null {
  if (!start || !end) return null;
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return null;
  return Math.round(((b - a) / 3_600_000) * 10) / 10;
}

export interface OverviewPopulatedProps {
  buildingId: string;
  equipment: FddEquipmentItem[];
  equipmentId: string;
  onEquipmentChange: (id: string) => void;
  unitSystem: "imperial" | "metric";
}

/** Streamlit populated Overview body — metrics through data inspection. */
export function OverviewPopulated({
  buildingId,
  equipment,
  equipmentId,
  onEquipmentChange,
  unitSystem,
}: OverviewPopulatedProps) {
  const [ruleCount, setRuleCount] = useState(0);
  const [rowCount, setRowCount] = useState(0);
  const [firstTs, setFirstTs] = useState<string | null>(null);
  const [lastTs, setLastTs] = useState<string | null>(null);
  const [eqKind, setEqKind] = useState("—");
  const [runtime, setRuntime] = useState<AnalyticsEnvelope | null>(null);
  const [mech, setMech] = useState<AnalyticsEnvelope | null>(null);
  const [econ, setEcon] = useState<AnalyticsEnvelope | null>(null);
  const [runtimeFig, setRuntimeFig] = useState<PlotlyFigure | null>(null);
  const [mechFig, setMechFig] = useState<PlotlyFigure | null>(null);
  const [analyticsErr, setAnalyticsErr] = useState<string | null>(null);
  const [findingsNote, setFindingsNote] = useState(
    "Run Rules first — Engineering Findings reviews the active site's rule results.",
  );
  const [findingsJson, setFindingsJson] = useState("");
  const [zoneLow, setZoneLow] = useState(70);
  const [zoneHigh, setZoneHigh] = useState(75);
  const [week, setWeek] = useState(DEFAULT_WEEK);
  const [tz, setTz] = useState("America/Chicago");
  const [schedOpen, setSchedOpen] = useState(true);
  const [rcxDocxOpen, setRcxDocxOpen] = useState(false);
  const [inspectCols, setInspectCols] = useState<string[]>([]);
  const [inspectFig, setInspectFig] = useState<PlotlyFigure | null>(null);
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);

  const selected = equipment.find((e) => e.equipment_id === equipmentId);
  const tempUnit = unitSystem === "metric" ? "°C" : "°F";
  const bareMin = hoursPerWeek(week);
  const spanH = spanHours(firstTs, lastTs);

  const devicesByType = useMemo(() => {
    const map = new Map<string, number>();
    for (const e of equipment) {
      const t = String(e.equipment_type || "unknown");
      map.set(t, (map.get(t) ?? 0) + 1);
    }
    return [...map.entries()]
      .map(([equipment_type, count]) => ({ equipment_type, count }))
      .sort((a, b) => a.equipment_type.localeCompare(b.equipment_type));
  }, [equipment]);

  const refreshMeta = useCallback(async () => {
    const [status, rules] = await Promise.all([
      getFddStatus().catch(() => null),
      listFddRules().catch(() => []),
    ]);
    setRuleCount(status?.rule_count ?? rules.length);
    if (!buildingId) return;
    const map = await getPackageMapping(
      buildingId,
      equipmentId || undefined,
    ).catch(() => null);
    const eq =
      map?.equipment?.find((e) => e.equipment_id === equipmentId) ??
      map?.equipment?.[0];
    setRowCount(eq?.sampling?.row_count ?? 0);
    setFirstTs(eq?.sampling?.first_timestamp ?? null);
    setLastTs(eq?.sampling?.last_timestamp ?? null);
    setEqKind(String(eq?.equipment_type || selected?.equipment_type || "—"));
    const cols = (eq?.columns ?? [])
      .map((c: { column: string }) => c.column)
      .filter(Boolean)
      .slice(0, 80);
    setInspectCols(cols);
  }, [buildingId, equipmentId, selected?.equipment_type]);

  const refreshAnalytics = useCallback(async () => {
    if (!buildingId) return;
    setLoadingAnalytics(true);
    setAnalyticsErr(null);
    try {
      const base = {
        building_id: buildingId,
        equipment_ids: equipmentId ? [equipmentId] : undefined,
        max_points: 5000,
      };
      const [rt, mc, ec] = await Promise.all([
        postRuntime(base).catch((e) => {
          throw e;
        }),
        postMechanicalCooling(base).catch(() => null),
        postEconomizer(base).catch(() => null),
      ]);
      setRuntime(rt);
      setMech(mc);
      setEcon(ec);
      if (rt.rows?.length) {
        const yKeys = Object.keys(rt.rows[0] ?? {}).filter(
          (k) => k !== "period" && k !== "week" && k !== "equipment_id",
        );
        const xKey = rt.rows[0]?.week != null ? "week" : "period";
        setRuntimeFig(
          rowsToBarFigure(rt.rows, {
            xKey: String(xKey),
            yKeys: yKeys.slice(0, 8),
            title: "Motor run hours (central analytics)",
            provenance: `engine=${rt.engine} · query_version=${rt.query_version}`,
          }),
        );
      } else {
        setRuntimeFig(null);
      }
      if (mc?.rows?.length) {
        const yKeys = Object.keys(mc.rows[0] ?? {}).filter(
          (k) => !["oat_bin", "bin", "label"].includes(k),
        );
        const xKey =
          mc.rows[0]?.oat_bin != null
            ? "oat_bin"
            : mc.rows[0]?.bin != null
              ? "bin"
              : "label";
        setMechFig(
          rowsToBarFigure(mc.rows, {
            xKey: String(xKey),
            yKeys: yKeys.slice(0, 10),
            title:
              "Mechanical cooling run hours by outdoor-air temperature (5°F bins)",
            provenance: `engine=${mc.engine} · query_version=${mc.query_version}`,
          }),
        );
      } else {
        setMechFig(null);
      }

      // Data inspection placeholder chart from sampling timestamps if present
      if (firstTs && lastTs && inspectCols.length) {
        setInspectFig({
          data: [
            {
              name: inspectCols[0] ?? "series",
              type: "scatter",
              mode: "lines",
              x: [firstTs, lastTs],
              y: [0, 0],
            },
          ],
          layout: {
            title: `${equipmentId || "equipment"} · raw CSV inspection`,
            showlegend: true,
          },
          meta: {
            equipment_id: equipmentId,
            point_count: rowCount,
            provenance:
              "Data inspection — full column Plotly stack uses historian series when available",
          },
        });
      }

      const results = await getFddResults(buildingId).catch(() => null);
      if (results && results.length) {
        setFindingsNote(
          "FAULT candidates available — generate Engineering Findings below or open Results by Category.",
        );
      }
    } catch (err) {
      setAnalyticsErr(formatErr(err));
    } finally {
      setLoadingAnalytics(false);
    }
  }, [buildingId, equipmentId, firstTs, lastTs, inspectCols, rowCount]);

  useEffect(() => {
    void refreshMeta();
  }, [refreshMeta]);

  useEffect(() => {
    void refreshAnalytics();
  }, [refreshAnalytics]);

  useEffect(() => {
    void getSessionConfig()
      .then((body) => {
        const p = body.config?.params ?? {};
        const vav = p["VAV-1"] ?? {};
        if (typeof vav.zone_low === "number") setZoneLow(vav.zone_low);
        if (typeof vav.zone_high === "number") setZoneHigh(vav.zone_high);
      })
      .catch(() => undefined);
  }, [buildingId]);

  const saveSchedule = async () => {
    const prev = await getSessionConfig().catch(() => null);
    const config: SessionConfig = {
      ...(prev?.config ?? {}),
      schema_version: prev?.config?.schema_version ?? "openfdd.session.v1",
      unit_system: unitSystem,
      params: {
        ...(prev?.config?.params ?? {}),
        "VAV-1": {
          ...(prev?.config?.params?.["VAV-1"] ?? {}),
          zone_low: zoneLow,
          zone_high: zoneHigh,
        },
        "SCHED-1": {
          ...(prev?.config?.params?.["SCHED-1"] ?? {}),
          bare_min_occ_hours_week: bareMin,
        },
      },
    };
    await putSessionConfig(config);
  };

  const onGenerateFindings = async () => {
    try {
      await createReportDraft({
        building_id: buildingId,
        kind: "engineering_findings",
        title: `Engineering Findings · ${buildingId}`,
      });
      const rep = await getEngineeringFindingsReport().catch(() => null);
      if (rep) {
        setFindingsJson(JSON.stringify(rep, null, 2));
        setFindingsNote("Engineering Findings draft created.");
      } else {
        const listed = await listReports().catch(() => []);
        setFindingsJson(JSON.stringify(listed.slice(0, 3), null, 2));
        setFindingsNote("Report draft requested — see reports list.");
      }
    } catch (err) {
      setFindingsNote(formatErr(err));
    }
  };

  return (
    <div className="overview-populated" data-testid="overview-populated">
      <p className="oracle-sidebar__caption">
        Plot traces capped at 5,000 points — full data still used for
        rules/exports.
      </p>

      <InlineAlert id="overview-dual-catalog" variant="info" testId="overview-dual-catalog">
        Dual catalog: production FDD math is DataFusion SQL (
        <code>sql_rules/registry.yaml</code>). The pandas cookbook remains for
        docs, plots, and parity — not the default production path.
      </InlineAlert>

      <div className="form-row">
        <Select
          id="overview-equipment-select"
          label="Equipment"
          value={equipmentId}
          options={[
            { value: "", label: "— select equipment —" },
            ...equipment.map((e) => ({
              value: String(e.equipment_id),
              label: String(e.equipment_id),
            })),
          ]}
          onChange={onEquipmentChange}
          testId="overview-equipment-select"
        />
      </div>

      <div
        className="overview-metrics"
        style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}
        data-testid="overview-metrics"
      >
        <Metric id="ov-eq" label="Equipment" value={String(equipment.length)} testId="overview-eq-count" />
        <Metric id="ov-rules" label="Rules" value={String(ruleCount)} testId="overview-rule-count" />
        <Metric id="ov-rows" label="Rows (selected)" value={String(rowCount)} testId="overview-row-count" />
        <Metric id="ov-poll" label="Poll (s)" value="300" testId="overview-poll" />
        <Metric id="ov-kind" label="Kind" value={eqKind} testId="overview-kind" />
      </div>
      <p className="oracle-sidebar__caption" data-testid="overview-source-caption">
        zip:{buildingId}
      </p>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        <Metric id="ov-start" label="Dataset start" value={firstTs ?? "—"} testId="overview-start" />
        <Metric id="ov-end" label="Dataset end" value={lastTs ?? "—"} testId="overview-end" />
        <Metric
          id="ov-span"
          label="Span (h)"
          value={spanH != null ? String(spanH) : "—"}
          testId="overview-span"
        />
      </div>

      <section data-testid="overview-eng-findings">
        <h3>Engineering Findings</h3>
        <p>
          Detection ≠ finding: rule hits are candidates until deterministic
          evidence review → prioritized findings + DOCX/XLSX/JSON.
        </p>
        <p data-testid="overview-findings-note">{findingsNote}</p>
        <Button
          id="overview-gen-findings"
          label="Generate Engineering Findings"
          onClick={() => void onGenerateFindings()}
          testId="overview-gen-findings"
        />
        {findingsJson ? (
          <pre data-testid="overview-findings-json">{findingsJson.slice(0, 4000)}</pre>
        ) : null}
      </section>

      <Expander
        id="overview-rcx-docx"
        label="RCx report template (static DOCX)"
        expanded={rcxDocxOpen}
        onChange={setRcxDocxOpen}
        testId="overview-rcx-docx"
      >
        <p>
          Download Generic RCx Report from the reports service when available.
        </p>
        <Link to="/reports">Open reports / templates</Link>
      </Expander>

      <section data-testid="overview-schedule">
        <h3>Building schedule &amp; zone comfort (FDD starting point)</h3>
        <p className="oracle-sidebar__caption">
          Occupancy calendar always drives SCHED-1 (<code>occ_mode</code>) —
          edit times below; do not remove this UI. Zone low/high seed VAV-1
          comfort band.
        </p>
        <Slider
          id="zone-low"
          label={`Zone low ${tempUnit}`}
          min={55}
          max={72}
          step={0.5}
          value={zoneLow}
          onChange={setZoneLow}
          testId="overview-zone-low"
        />
        <Slider
          id="zone-high"
          label={`Zone high ${tempUnit}`}
          min={70}
          max={85}
          step={0.5}
          value={zoneHigh}
          onChange={setZoneHigh}
          testId="overview-zone-high"
        />
        <Metric
          id="bare-min"
          label="Bare-min occ hours / week"
          value={String(bareMin)}
          testId="overview-bare-min"
        />
        <Expander
          id="edit-weekly-occ"
          label="Edit weekly occupancy (time pickers)"
          expanded={schedOpen}
          onChange={setSchedOpen}
          testId="overview-weekly-occ"
        >
          <label className="oracle-sidebar__field">
            <span className="oracle-sidebar__label">Timezone</span>
            <input
              className="oracle-sidebar__control"
              value={tz}
              onChange={(e) => setTz(e.target.value)}
              data-testid="overview-timezone"
            />
          </label>
          {DAYS.map((day) => (
            <div key={day} className="overview-day" data-testid={`overview-day-${day}`}>
              <strong>{day}</strong>
              <Checkbox
                id={`occ-${day}`}
                label="Occupied"
                checked={week[day].occupied}
                onChange={(checked) =>
                  setWeek((w) => ({
                    ...w,
                    [day]: { ...w[day], occupied: checked },
                  }))
                }
              />
              <label>
                Start{" "}
                <input
                  type="time"
                  value={week[day].start}
                  onChange={(e) =>
                    setWeek((w) => ({
                      ...w,
                      [day]: { ...w[day], start: e.target.value },
                    }))
                  }
                />
              </label>
              <label>
                End{" "}
                <input
                  type="time"
                  value={week[day].end}
                  onChange={(e) =>
                    setWeek((w) => ({
                      ...w,
                      [day]: { ...w[day], end: e.target.value },
                    }))
                  }
                />
              </label>
            </div>
          ))}
          <Button
            id="save-schedule"
            label="Save schedule to session config"
            onClick={() => void saveSchedule()}
            testId="overview-save-schedule"
          />
        </Expander>
      </section>

      <section data-testid="overview-motor-runtime">
        <h3>Motor run hours (central analytics)</h3>
        {runtime ? (
          <p className="oracle-sidebar__caption">
            analytics provenance · engine={runtime.engine} · query_version=
            {runtime.query_version} · run_id={String(runtime.run_id ?? "—")}
          </p>
        ) : null}
        {analyticsErr ? (
          <InlineAlert id="ov-analytics-err" variant="danger">
            {analyticsErr}
          </InlineAlert>
        ) : null}
        <PlotlyHost
          id="motor-runtime"
          label="Motor run hours"
          figure={runtimeFig}
          loading={loadingAnalytics}
          height={280}
          testId="overview-motor-plot"
        />
        {runtime?.rows?.length ? (
          <DataTable
            id="motor-runtime-table"
            label="Runtime rows"
            columns={Object.keys(runtime.rows[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={runtime.rows.slice(0, 50) as Array<Record<string, string | number>>}
            testId="overview-motor-table"
          />
        ) : (
          <p className="oracle-sidebar__caption">
            {loadingAnalytics
              ? "Loading runtime…"
              : "No central runtime rows yet — ensure package is imported and fan roles mapped."}
          </p>
        )}
      </section>

      <section data-testid="overview-mech-cooling">
        <h3>Mechanical cooling hours by OAT bin</h3>
        <p className="oracle-sidebar__caption">
          Chillers / DX / VRF use the sidebar compressor-proof mode. Never CHW
          cooling valves. Bins sorted cold→hot; OAT from web weather by
          default.
        </p>
        {mech ? (
          <p className="oracle-sidebar__caption">
            analytics provenance · engine={mech.engine} · query_version=
            {mech.query_version}
          </p>
        ) : (
          <InlineAlert id="mech-warn" variant="warning" testId="overview-mech-warn">
            mechanical_cooling: evidence-hierarchy gate only (OAT bins / DF port
            next) — showing central envelope when available.
          </InlineAlert>
        )}
        <PlotlyHost
          id="mech-cooling"
          label="Mechanical cooling by OAT"
          figure={mechFig}
          loading={loadingAnalytics}
          height={300}
          testId="overview-mech-plot"
        />
        {mech?.equipment?.length ? (
          <DataTable
            id="mech-coverage"
            label="Cooling coverage"
            columns={Object.keys(mech.equipment[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={mech.equipment as Array<Record<string, string | number>>}
            testId="overview-mech-coverage"
          />
        ) : null}
      </section>

      <section data-testid="overview-economizer">
        <h3>Economizer weather opportunity / compliance</h3>
        <p className="oracle-sidebar__caption">
          Strict web dry-bulb + dewpoint. Opportunity = 60≤DB&lt;72°F and
          DP&lt;60°F. Detailed free-cooling diagnostics live under RCx Plots →
          AHU → Economizer diagnostics.
        </p>
        {econ?.rows?.length ? (
          <DataTable
            id="econ-table"
            label="Economizer weather summary"
            columns={Object.keys(econ.rows[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={econ.rows as Array<Record<string, string | number>>}
            testId="overview-econ-table"
          />
        ) : (
          <p className="oracle-sidebar__caption">
            No economizer summary rows from central yet.
          </p>
        )}
      </section>

      <section data-testid="overview-bas-web-oat">
        <h3>BAS vs web outdoor-air temperature</h3>
        <p className="oracle-sidebar__caption">
          Overlay of BAS OAT and web dry-bulb with ±oat_err tolerance band
          (OAT-METEO slider; default 5°F). Histogram of BAS − web deviation
          follows when series are available from FDD Plots / weather roles.
        </p>
        <InlineAlert id="bas-web-note" variant="info">
          Tune thresholds in the left sidebar → Run Rules (all or by category)
          or sidebar Rerun cat. → browse FDD Plots by device type (AHU / VAV /
          plant…).
        </InlineAlert>
      </section>

      <section data-testid="overview-devices-by-type">
        <h3>Devices by type</h3>
        <DataTable
          id="devices-by-type"
          label="Devices by type"
          columns={[
            { key: "equipment_type", header: "type" },
            { key: "count", header: "count" },
          ]}
          rows={devicesByType}
          testId="overview-devices-table"
        />
      </section>

      <section data-testid="overview-data-inspection">
        <h3>Data inspection — raw CSV</h3>
        <p className="oracle-sidebar__caption">
          Pick any uploaded equipment (or weather) CSV and plot numeric /
          status columns as stacked Plotly line charts.
        </p>
        <Select
          id="inspect-eq"
          label="CSV / equipment"
          value={equipmentId}
          options={equipment.map((e) => ({
            value: String(e.equipment_id),
            label: String(e.equipment_id),
          }))}
          onChange={onEquipmentChange}
          testId="overview-inspect-eq"
        />
        <p className="oracle-sidebar__caption" data-testid="overview-inspect-meta">
          {equipmentId || "—"} · {rowCount} rows · {inspectCols.length} /{" "}
          {inspectCols.length} plottable columns
          {firstTs && lastTs ? ` · ${firstTs} → ${lastTs}` : ""}
        </p>
        {inspectCols.length ? (
          <ul className="overview-col-list" data-testid="overview-inspect-cols">
            {inspectCols.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : null}
        <PlotlyHost
          id="data-inspect"
          label="Inspection chart"
          figure={inspectFig}
          height={260}
          testId="overview-inspect-plot"
        />
      </section>
    </div>
  );
}
