import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSiteContext } from "@/contexts/site-context";
import { useAllEquipment, useEquipment } from "@/hooks/use-sites";
import { apiFetch } from "@/lib/api";
import type { Equipment } from "@/types/api";

type FlatMap = Record<string, string>;

const CONTROLS_FIELDS = [
  "control_system_type",
  "control_vendor",
  "controls_contractor",
  "front_end_platform",
  "supervisory_controller_model",
  "unit_controller_model",
  "communication_protocols",
  "bacnet_network_number",
  "ip_address",
  "mstp_mac",
  "panel_name",
  "panel_location",
  "install_date",
  "as_built_date",
];

const MECHANICAL_FIELDS = [
  "manufacturer",
  "model_number",
  "serial_number",
  "equipment_tag",
  "design_cfm",
  "min_cfm",
  "max_cfm",
  "outside_air_cfm",
  "return_air_cfm",
  "exhaust_air_cfm",
  "fan_motor_hp",
  "fan_motor_fla",
  "fan_motor_voltage",
  "fan_motor_phase",
  "coil_type",
  "cooling_capacity_tons",
  "cooling_capacity_mbh",
  "heating_capacity_mbh",
  "entering_water_temp_f",
  "leaving_water_temp_f",
  "water_flow_gpm",
  "pump_flow_gpm",
  "pump_head_ft",
  "boiler_capacity_mbh",
  "chiller_capacity_tons",
  "design_static_pressure",
  "pipe_size",
  "duct_size",
  "valve_size",
  "damper_size",
];

const ELECTRICAL_FIELDS = [
  "electrical_system_voltage",
  "electrical_phase",
  "feeder_panel",
  "feeder_breaker",
  "upstream_panel",
  "downstream_load_name",
  "fla",
  "mca",
  "mocp",
  "rla",
  "lra",
  "motor_hp",
  "starter_type",
  "disconnect_type",
  "vfd_present",
  "vfd_model",
  "emergency_power_served",
  "generator_backed",
  "power_meter_present",
];

const DOCUMENT_FIELDS = [
  "source_document_name",
  "source_document_type",
  "source_sheet",
  "source_detail",
  "extracted_from_pdf",
  "extracted_by",
  "extraction_confidence",
  "verified_by_human",
  "last_verified_at",
  "notes",
];

function readSection(
  equipment: Equipment | undefined,
  section: "controls" | "mechanical" | "electrical" | "documents",
  fields: string[],
): FlatMap {
  const out: FlatMap = {};
  const engineering =
    ((equipment?.metadata as Record<string, unknown> | undefined)?.engineering as
      | Record<string, unknown>
      | undefined) ?? {};
  const src = (engineering[section] as Record<string, unknown> | undefined) ?? {};
  for (const k of fields) out[k] = src[k] == null ? "" : String(src[k]);
  return out;
}

export function DataModelEngineeringPage() {
  const queryClient = useQueryClient();
  const { selectedSiteId } = useSiteContext();
  const { data: allEquipment = [] } = useAllEquipment();
  const { data: siteEquipment = [] } = useEquipment(selectedSiteId ?? undefined);
  const equipment = selectedSiteId ? siteEquipment : allEquipment;
  const hasEquipment = equipment.length > 0;
  const [selectedEquipmentId, setSelectedEquipmentId] = useState<string>("");
  const selectedEquipment = useMemo(() => {
    if (!equipment.length) return undefined;
    return (
      equipment.find((e) => e.id === selectedEquipmentId) ??
      equipment[0]
    );
  }, [equipment, selectedEquipmentId]);
  const [saveMsg, setSaveMsg] = useState<string>("");

  const hasBacnet = useMemo(() => {
    const md = (selectedEquipment?.metadata as Record<string, unknown> | undefined) ?? {};
    return Boolean(md.bacnet);
  }, [selectedEquipment]);
  const hasTimeseries = useMemo(() => {
    const md = (selectedEquipment?.metadata as Record<string, unknown> | undefined) ?? {};
    return Boolean(md.timeseries);
  }, [selectedEquipment]);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Data Model Engineering</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Preserve Brick operations while adding engineering metadata and a partial ASHRAE Standard 223 (`s223`) topology
        representation that stays exportable for LLM workflows and queryable via SPARQL.
      </p>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Overview</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <label className="block text-xs" htmlFor="selected-equipment">
            Selected equipment
          </label>
          <select
            id="selected-equipment"
            className="h-9 w-full max-w-lg rounded-lg border border-border/60 bg-background px-3 text-sm"
            value={selectedEquipment?.id ?? ""}
            onChange={(e) => setSelectedEquipmentId(e.target.value)}
          >
            {equipment.map((eq) => (
              <option key={eq.id} value={eq.id}>
                {eq.name} ({eq.equipment_type ?? "Equipment"})
              </option>
            ))}
          </select>
          <div className="grid grid-cols-1 gap-2 pt-2 text-xs md:grid-cols-2">
            <p>Brick class: {selectedEquipment?.equipment_type ?? "n/a"}</p>
            <p>BACnet reference: {hasBacnet ? "yes" : "no"}</p>
            <p>Time-series reference: {hasTimeseries ? "yes" : "no"}</p>
            <p>
              Standard 223 (`s223`) topology block:{" "}
              {(
                (selectedEquipment?.metadata as Record<string, unknown> | undefined)
                  ?.engineering as Record<string, unknown> | undefined
              )?.topology
                ? "yes"
                : "no"}
            </p>
          </div>
        </CardContent>
      </Card>

      {!hasEquipment ? (
        <p className="mt-4 text-sm text-muted-foreground">
          No equipment found for this site. Add equipment in the Data Model BRICK tab before editing engineering
          metadata.
        </p>
      ) : (
        selectedEquipment && (
          <EngineeringEditor
            key={selectedEquipment.id}
            selectedEquipment={selectedEquipment}
            onSaved={(msg) => {
              setSaveMsg(msg);
              queryClient.invalidateQueries({ queryKey: ["equipment"] });
              queryClient.invalidateQueries({ queryKey: ["data-model"] });
            }}
          />
        )
      )}
      {saveMsg && <p className="mt-3 text-sm text-muted-foreground">{saveMsg}</p>}
    </div>
  );
}

function EngineeringEditor({
  selectedEquipment,
  onSaved,
}: {
  selectedEquipment: Equipment;
  onSaved: (msg: string) => void;
}) {
  const [controls, setControls] = useState<FlatMap>(() =>
    readSection(selectedEquipment, "controls", CONTROLS_FIELDS),
  );
  const [mechanical, setMechanical] = useState<FlatMap>(() =>
    readSection(selectedEquipment, "mechanical", MECHANICAL_FIELDS),
  );
  const [electrical, setElectrical] = useState<FlatMap>(() =>
    readSection(selectedEquipment, "electrical", ELECTRICAL_FIELDS),
  );
  const [documents, setDocuments] = useState<FlatMap>(() =>
    readSection(selectedEquipment, "documents", DOCUMENT_FIELDS),
  );
  const [topologyJson, setTopologyJson] = useState<string>(() => {
    const engineering =
      ((selectedEquipment?.metadata as Record<string, unknown> | undefined)?.engineering as
        | Record<string, unknown>
        | undefined) ?? {};
    return JSON.stringify(
      (engineering.topology as Record<string, unknown> | undefined) ?? {
        connection_points: [],
        connections: [],
        mediums: [],
      },
      null,
      2,
    );
  });
  const [extensionsJson, setExtensionsJson] = useState<string>(() => {
    const engineering =
      ((selectedEquipment?.metadata as Record<string, unknown> | undefined)?.engineering as
        | Record<string, unknown>
        | undefined) ?? {};
    return JSON.stringify(
      (engineering.extensions as Record<string, unknown> | undefined) ?? {},
      null,
      2,
    );
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      let topology: unknown;
      try {
        topology = JSON.parse(topologyJson);
      } catch (err) {
        const detail = err instanceof Error ? ` (${err.message})` : "";
        throw new Error(`Invalid JSON in topology${detail}`);
      }
      let extensions: unknown;
      try {
        extensions = JSON.parse(extensionsJson);
      } catch (err) {
        const detail = err instanceof Error ? ` (${err.message})` : "";
        throw new Error(`Invalid JSON in extensions${detail}`);
      }
      const baseMetadata = ((selectedEquipment.metadata as Record<string, unknown> | undefined) ?? {}) as Record<
        string,
        unknown
      >;
      const engineering = {
        controls,
        mechanical,
        electrical,
        topology,
        documents,
        extensions,
      };
      return apiFetch(`/equipment/${selectedEquipment.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          metadata: { ...baseMetadata, engineering },
        }),
      });
    },
    onSuccess: () => onSaved("Engineering metadata saved."),
    onError: (err: Error) => onSaved(`Save failed: ${err.message}`),
  });

  const renderFields = (title: string, data: FlatMap, setData: (next: FlatMap) => void) => (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {Object.entries(data).map(([key, value]) => {
          const inputId = `${title.replace(/\s+/g, "-").toLowerCase()}-${key}-input`;
          return (
            <label key={key} className="text-sm" htmlFor={inputId}>
              <span className="mb-1 block text-xs text-muted-foreground">{key}</span>
              <input
                id={inputId}
                value={value}
                onChange={(e) => setData({ ...data, [key]: e.target.value })}
                className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </label>
          );
        })}
      </CardContent>
    </Card>
  );

  return (
    <div className="mt-6 space-y-6">
      {renderFields("Controls", controls, setControls)}
      {renderFields("Mechanical", mechanical, setMechanical)}
      {renderFields("Electrical", electrical, setElectrical)}
      {renderFields("Documents / Provenance", documents, setDocuments)}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Topology</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-sm text-muted-foreground">
            Use JSON for connection points/connections/mediums (ASHRAE Standard 223 / `s223` concepts: Duct/Pipe/Wire,
            `hasConnectionPoint`). Current endpoint linkage is stored as Open-FDD string refs (`ofdd:connectsFromRef`,
            `ofdd:connectsToRef`) rather than full RDF object links via `s223:connectsFrom/connectsTo`.
          </p>
          <textarea
            value={topologyJson}
            onChange={(e) => setTopologyJson(e.target.value)}
            aria-label="Topology JSON"
            className="h-48 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-sm"
            spellCheck={false}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">RDF Preview / Query Hints</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>- `ofdd:*` extension predicates are emitted for key engineering fields.</p>
          <p>- `s223:*` triples are emitted for topology connection points and conduits.</p>
          <p>- Connection endpoints currently serialize as `ofdd:connectsFromRef` / `ofdd:connectsToRef` string references.</p>
          <p>- Query in Data Model Testing for `ofdd:controlVendor`, `ofdd:designCFM`, `s223:hasConnectionPoint`.</p>
          <textarea
            value={extensionsJson}
            onChange={(e) => setExtensionsJson(e.target.value)}
            aria-label="Extensions JSON"
            className="h-32 w-full rounded-lg border border-border/60 bg-card px-3 py-2 font-mono text-sm"
            spellCheck={false}
          />
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {saveMutation.isPending ? "Saving..." : "Save engineering metadata"}
        </button>
      </div>
    </div>
  );
}
