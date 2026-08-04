import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import {
  InlineAlert,
  Select,
  Button,
  DataTable,
  RadioGroup,
} from "../components/widgets";
import { PlotlyHost } from "../components/widgets/PlotlyHost";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import {
  listFddEquipment,
  postRcxAhu,
  postRcxVav,
  postRcxChiller,
  postRcxBoiler,
  type AnalyticsEnvelope,
} from "../api/analyticsApi";
import { rowsToBarFigure, type PlotlyFigure } from "../api/plotDataset";

const PRESETS = [
  { value: "ahu", label: "AHU" },
  { value: "vav", label: "VAV" },
  { value: "chiller", label: "Chiller" },
  { value: "boiler", label: "Boiler" },
] as const;

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Streamlit RCx Plots tab — central rcx/{ahu,vav,chiller,boiler}. */
export function RcxPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const [buildings, setBuildings] = useState<string[]>([]);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [preset, setPreset] = useState<string>("ahu");
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void listPackageBuildings()
      .then(setBuildings)
      .catch(() => setBuildings([]));
  }, []);

  useEffect(() => {
    if (!buildingId) {
      setEquipment([]);
      return;
    }
    void listFddEquipment(buildingId)
      .then((eq) => setEquipment(eq.map((e) => String(e.equipment_id))))
      .catch(() => setEquipment([]));
  }, [buildingId]);

  const run = async () => {
    if (!buildingId) return;
    setLoading(true);
    setError(null);
    try {
      const body = {
        building_id: buildingId,
        equipment_ids: equipment.slice(0, 20),
        max_points: 5000,
      };
      let res: AnalyticsEnvelope;
      switch (preset) {
        case "vav":
          res = await postRcxVav(body);
          break;
        case "chiller":
          res = await postRcxChiller(body);
          break;
        case "boiler":
          res = await postRcxBoiler(body);
          break;
        default:
          res = await postRcxAhu(body);
      }
      setEnv(res);
      if (res.rows?.length) {
        const keys = Object.keys(res.rows[0] ?? {}).filter(
          (k) => k !== "equipment_id" && k !== "timestamp",
        );
        const xKey =
          res.rows[0]?.equipment_id != null ? "equipment_id" : keys[0] ?? "x";
        setFigure(
          rowsToBarFigure(res.rows, {
            xKey,
            yKeys: keys.filter((k) => k !== xKey).slice(0, 6),
            title: `RCx · ${preset}`,
            provenance: `engine=${res.engine} · ${res.query_version}`,
          }),
        );
      } else {
        setFigure(null);
      }
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell
      title="RCx Plots"
      caption="Retro-commissioning analytics — AHU / VAV / chiller / boiler presets"
      activeSectionId="rcx-plots"
    >
      <div className="page-stack" data-testid="rcx-page">
        <Select
          id="rcx-building"
          label="Building"
          value={buildingId}
          options={[
            { value: "", label: "— select —" },
            ...buildings.map((b) => ({ value: b, label: b })),
          ]}
          onChange={(v) => setQuery({ siteId: v || undefined }, true)}
          testId="rcx-building"
        />
        <RadioGroup
          id="rcx-preset"
          label="Equipment family"
          value={preset}
          options={[...PRESETS]}
          onChange={setPreset}
          testId="rcx-preset"
        />
        <Button
          id="rcx-run"
          label={loading ? "Running…" : "Run RCx analytics"}
          onClick={() => void run()}
          disabled={!buildingId || loading}
          testId="rcx-run"
        />
        {error ? (
          <InlineAlert id="rcx-error" variant="danger">
            {error}
          </InlineAlert>
        ) : null}
        {env ? (
          <p className="oracle-sidebar__caption" data-testid="rcx-provenance">
            analytics provenance · engine={env.engine} · query_version=
            {env.query_version} · rows={env.rows?.length ?? 0}
          </p>
        ) : null}
        <PlotlyHost
          id="rcx-plot"
          label="RCx chart"
          figure={figure}
          loading={loading}
          height={320}
          testId="rcx-plot"
        />
        {env?.rows?.length ? (
          <DataTable
            id="rcx-table"
            label="RCx rows"
            columns={Object.keys(env.rows[0] ?? {}).map((k) => ({
              key: k,
              header: k,
            }))}
            rows={env.rows as Array<Record<string, string | number>>}
            testId="rcx-table"
          />
        ) : null}
        <p className="oracle-sidebar__caption">
          Detailed free-cooling / mixing diagnostics: AHU economizer preset.
          Fan-on / Fan-off tabs map to central coverage filters when present in
          the envelope.
        </p>
      </div>
    </AppShell>
  );
}
