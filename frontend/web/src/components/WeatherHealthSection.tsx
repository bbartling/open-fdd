import { useEffect, useMemo, useState } from "react";
import { DataTable, InlineAlert } from "./widgets";
import { getFddResults } from "../api/fddApi";
import { postBasVsWebOat } from "../api/analyticsApi";
import { healthColumnHeader } from "../lib/cookbookRuleCatalog";
import { plantEquipmentFamilies } from "../lib/plantEquipment";
import type { FddEquipmentItem } from "../api/analyticsApi";

function fmtHours(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(1);
}

function triFault(status: unknown, hours: unknown): string {
  const h = typeof hours === "number" ? hours : Number(hours);
  const st = String(status ?? "").toUpperCase();
  if (st === "FAULT" || (Number.isFinite(h) && h > 0)) return "true";
  if (st === "PASS") return "false";
  return "unknown";
}

/** Web vs local outside-air sensors — drybulb + humidity with fault hours. */
export function WeatherHealthSection({
  buildingId,
  refreshToken,
  equipment,
}: {
  buildingId: string;
  refreshToken: number;
  equipment: FddEquipmentItem[];
}) {
  const families = useMemo(() => plantEquipmentFamilies(equipment), [equipment]);
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!buildingId || !families.hasWeather) {
      setRows([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void (async () => {
      try {
        const [fddRows, bas] = await Promise.all([
          getFddResults(buildingId).catch(() => [] as Array<Record<string, unknown>>),
          postBasVsWebOat({ building_id: buildingId, max_points: 4000, dt_min_f: 10 }),
        ]);
        if (cancelled) return;

        const oatMeteo = fddRows.filter((r) => String(r.rule_id ?? "") === "OAT-METEO");
        const wxRules = fddRows.filter((r) =>
          ["WX-1", "SENSOR-HI", "SENSOR-LO", "FLATLINE"].includes(String(r.rule_id ?? "")),
        );

        const histRows = bas.rows ?? [];
        const hasOatHist = histRows.some(
          (r) => r.kind === "delta_hist" || r.count != null,
        );
        const hasWebOat = (bas.points ?? []).length > 0;

        const out: Array<Record<string, unknown>> = [];

        const oatFault = oatMeteo.find(
          (r) =>
            String(r.equipment_id ?? "").toLowerCase().includes("weather") ||
            String(r.equipment_id ?? "") === "weather",
        ) ?? oatMeteo[0];

        out.push({
          point: "outsideAir drybulb",
          local_tag: "oa_t",
          web_tag: "web_oa_t",
          rule_id: "OAT-METEO",
          fault: triFault(oatFault?.status, oatFault?.fault_hours),
          fault_h: fmtHours(oatFault?.fault_hours),
          total_fault_h: fmtHours(oatFault?.fault_hours),
        });

        out.push({
          point: "outsideAir humidity",
          local_tag: "oa_h",
          web_tag: "web_oa_h",
          rule_id: "SENSOR-HI/LO",
          fault:
            wxRules.length > 0
              ? wxRules.some(
                  (r) =>
                    triFault(r.status, r.fault_hours) === "true",
                )
                ? "true"
                : "false"
              : "unknown",
          fault_h: fmtHours(
            wxRules.reduce(
              (sum, r) =>
                sum +
                (typeof r.fault_hours === "number"
                  ? r.fault_hours
                  : Number(r.fault_hours) || 0),
              0,
            ),
          ),
          total_fault_h: fmtHours(
            wxRules.reduce(
              (sum, r) =>
                sum +
                (typeof r.fault_hours === "number"
                  ? r.fault_hours
                  : Number(r.fault_hours) || 0),
              0,
            ),
          ),
        });

        setRows(out);
        if (!hasWebOat && !hasOatHist) {
          setNote(
            "Need mapped oa_t (BAS) and web_oa_t on the weather equip ref — run Update analytics after mapping.",
          );
        } else if (!fddRows.length) {
          setNote("Run all rules to populate OAT-METEO fault hours.");
        } else {
          setNote(null);
        }
      } catch (e: unknown) {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : String(e));
          setRows([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [buildingId, refreshToken, families.hasWeather]);

  if (!families.hasWeather) return null;

  return (
    <section className="overview-section" data-testid="overview-weather-health">
      <h3>Weather sensors — web vs local</h3>
      <p className="oracle-sidebar__caption">
        {healthColumnHeader("OAT-METEO", ["outsideAir", "web-outside-air-temp"])}. Compare
        BAS <code>oa_t</code> / <code>oa_h</code> to web <code>web_oa_t</code> /{" "}
        <code>web_oa_h</code>. Histogram on RCx preset <code>bas_vs_web_oat</code>.
      </p>
      {loading ? (
        <InlineAlert id="weather-health-loading" variant="info" testId="weather-health-loading">
          Loading weather sensor matrix…
        </InlineAlert>
      ) : null}
      {err ? (
        <InlineAlert id="weather-health-err" variant="danger" testId="weather-health-err">
          {err}
        </InlineAlert>
      ) : null}
      {note ? (
        <p className="oracle-sidebar__caption" data-testid="weather-health-note">
          {note}
        </p>
      ) : null}
      {rows.length ? (
        <DataTable
          id="weather-health-table"
          label="Weather sensor health"
          columns={[
            { key: "point", header: "point" },
            { key: "local_tag", header: "local tag" },
            { key: "web_tag", header: "web tag" },
            { key: "rule_id", header: "cookbook rule" },
            { key: "fault", header: "fault" },
            { key: "fault_h", header: "fault_h" },
            { key: "total_fault_h", header: "total fault_h" },
          ]}
          rows={rows as Array<Record<string, string | number>>}
          testId="weather-health-table"
        />
      ) : null}
    </section>
  );
}
