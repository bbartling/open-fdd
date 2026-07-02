import { useCallback, useEffect, useState } from "react";
import BacnetPointsTree, { type DriverDevice, type DriverPoint } from "../components/BacnetPointsTree";
import ModbusPointsTree, { type ModbusDevice, type ModbusPoint } from "../components/ModbusPointsTree";
import JsonApiPointsTree, { type JsonApiDevice, type JsonApiPoint } from "../components/JsonApiPointsTree";
import HaystackPointsTree, { type HaystackDevice, type HaystackPoint } from "../components/HaystackPointsTree";
import DriverDetailsPanel, { type DriverSelection } from "../components/DriverDetailsPanel";
import SupervisoryOverridePanel, { type OverrideStatus } from "../components/SupervisoryOverridePanel";
import UnifiedDriverTreeLegend from "../components/UnifiedDriverTreeLegend";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { apiFetch, apiDownloadBlob } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import type { PrioritySlot } from "../lib/bacnetTreeMenu";

type UnifiedTreeResponse = {
  roots?: Array<{ id: string; label: string; status: string; child_count?: number }>;
  bacnet?: { devices: DriverDevice[] };
  modbus?: { devices: ModbusDevice[] };
  json_api?: { devices: JsonApiDevice[] };
  haystack?: { devices: HaystackDevice[] };
};

function bacnetSelection(device: DriverDevice, point?: DriverPoint): DriverSelection {
  if (point) {
    return {
      protocol: "bacnet",
      title: point.object_name || point.object_identifier,
      subtitle: `Device ${device.device_instance}`,
      badges: [
        point.commandable ? "commandable" : "",
        point.has_override ? "override" : "",
        point.operator_override ? "P8 override" : "",
        point.enabled ? "polling" : "idle",
      ].filter(Boolean),
      fields: [
        { label: "Object ID", value: point.object_identifier },
        { label: "Object type", value: point.object_type },
        { label: "Present value", value: String(point.present_value ?? "—") },
        { label: "Poll cadence", value: point.enabled ? point.poll_label || `${point.poll_interval_s}s` : "Off" },
        { label: "Haystack ID", value: String(point.haystack_id ?? "—") },
        { label: "Last read", value: String(point.last_read_at ?? "—") },
      ],
      raw: point,
    };
  }
  return {
    protocol: "bacnet",
    title: `Device ${device.device_instance}`,
    subtitle: device.device_address,
    fields: [
      { label: "Address", value: device.device_address },
      { label: "Points", value: String(device.point_count) },
      { label: "Polling", value: String(device.poll_count) },
      { label: "Overrides", value: String(device.override_point_count ?? 0) },
      { label: "P8 overrides", value: String(device.operator_override_count ?? 0) },
    ],
    raw: device,
  };
}

export default function DriversPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tree, setTree] = useState<UnifiedTreeResponse | null>(null);
  const [overrideStatus, setOverrideStatus] = useState<OverrideStatus | null>(null);
  const [overridePending, setOverridePending] = useState(false);
  const [selection, setSelection] = useState<DriverSelection | null>(null);
  const [priorityByPointId, setPriorityByPointId] = useState<Record<string, PrioritySlot[]>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [unified, overrides] = await Promise.all([
        apiFetch<UnifiedTreeResponse>("/api/drivers/tree"),
        apiFetch<OverrideStatus>("/api/bacnet/overrides/status"),
      ]);
      setTree(unified);
      setOverrideStatus(overrides);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 20000);
    return () => window.clearInterval(id);
  }, [load]);

  async function exportOverrideCsv() {
    const { blob, filename } = await apiDownloadBlob("/api/bacnet/overrides/export");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "bacnet_supervisory_override_report.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function scanOverridesOnce() {
    setOverridePending(true);
    try {
      await apiFetch("/api/bacnet/overrides/scan-once", { method: "POST" });
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setOverridePending(false);
    }
  }

  async function refreshBacnetPv(device: DriverDevice, point: DriverPoint) {
    await apiFetch("/api/bacnet/read", {
      method: "POST",
      body: JSON.stringify({ point_id: point.point_id, object_identifier: point.object_identifier }),
    });
    await load();
  }

  async function readPriorityArray(device: DriverDevice, point: DriverPoint) {
    const res = await apiFetch<{ priority_array?: PrioritySlot[] }>("/api/bacnet/priority-array", {
      method: "POST",
      body: JSON.stringify({ point_id: point.point_id }),
    });
    setPriorityByPointId((prev) => ({ ...prev, [point.point_id]: res.priority_array ?? [] }));
    setSelection(bacnetSelection(device, point));
  }

  const bacnetDevices = tree?.bacnet?.devices ?? [];
  const modbusDevices = tree?.modbus?.devices ?? [];
  const jsonDevices = tree?.json_api?.devices ?? [];
  const haystackDevices = tree?.haystack?.devices ?? [];

  return (
    <div className="drivers-page">
      <PageHeader title="Drivers" subtitle="BACnet · Haystack · Modbus · JSON API — BAS-style tree navigation" />
      {error ? <p className="error-banner">{error}</p> : null}
      {loading && !tree ? <Spinner label="Loading driver tree…" /> : null}
      <div className="drivers-layout">
        <div className="drivers-tree-column">
          <UnifiedDriverTreeLegend />
          <SupervisoryOverridePanel
            status={overrideStatus}
            pending={overridePending}
            onScanOnce={() => void scanOverridesOnce()}
            onExportCsv={() => void exportOverrideCsv().catch((e) => setError(formatApiError(e)))}
          />
          <section className="panel driver-protocol-panel">
            <header className="driver-protocol-head">
              <h3>BACnet/IP</h3>
              <span className="badge poll-badge">{bacnetDevices.length} devices</span>
            </header>
            <BacnetPointsTree
              devices={bacnetDevices}
              priorityByPointId={priorityByPointId}
              onSelectPoint={(dev, pt) => setSelection(bacnetSelection(dev, pt))}
              onSelectDevice={(dev) => setSelection(bacnetSelection(dev))}
              onRefreshPointPv={(dev, pt) => void refreshBacnetPv(dev, pt)}
              onReadPriorityArray={(dev, pt) => void readPriorityArray(dev, pt)}
            />
          </section>
          <section className="panel driver-protocol-panel">
            <header className="driver-protocol-head">
              <h3>Haystack</h3>
              <span className="badge">{haystackDevices.length} sites</span>
            </header>
            <HaystackPointsTree
              devices={haystackDevices}
              onSelectPoint={(dev, pt) =>
                setSelection({
                  protocol: "haystack",
                  title: pt.label,
                  subtitle: dev.site_id,
                  badges: [pt.mapping_status ?? "unmapped"],
                  fields: [
                    { label: "Haystack ID", value: pt.haystack_id },
                    { label: "Mapping", value: pt.mapping_status ?? "unmapped" },
                    { label: "curVal", value: String(pt.curVal ?? pt.present_value ?? "—") },
                  ],
                  raw: pt,
                })
              }
            />
          </section>
          <section className="panel driver-protocol-panel">
            <header className="driver-protocol-head">
              <h3>Modbus TCP</h3>
              <span className="badge">{modbusDevices.length} connections</span>
            </header>
            <ModbusPointsTree
              devices={modbusDevices}
              onSelectPoint={(dev, pt) =>
                setSelection({
                  protocol: "modbus",
                  title: pt.label,
                  subtitle: `${dev.host}:${dev.port} unit ${dev.unit_id}`,
                  fields: [
                    { label: "Register", value: String(pt.register_address ?? "—") },
                    { label: "Function", value: pt.function },
                    { label: "Present value", value: String(pt.present_value ?? "—") },
                    { label: "Units", value: String(pt.units ?? "—") },
                  ],
                  raw: pt,
                })
              }
            />
          </section>
          <section className="panel driver-protocol-panel">
            <header className="driver-protocol-head">
              <h3>JSON API</h3>
              <span className="badge">{jsonDevices.length} hosts</span>
            </header>
            <JsonApiPointsTree
              devices={jsonDevices}
              onSelectPoint={(dev, pt) =>
                setSelection({
                  protocol: "json_api",
                  title: pt.label,
                  subtitle: dev.host,
                  fields: [
                    { label: "URL", value: pt.url },
                    { label: "Method", value: pt.method },
                    { label: "JSON path", value: pt.json_path },
                    { label: "Present value", value: String(pt.present_value ?? "—") },
                  ],
                  raw: pt,
                })
              }
            />
          </section>
        </div>
        <DriverDetailsPanel selection={selection} />
      </div>
    </div>
  );
}
