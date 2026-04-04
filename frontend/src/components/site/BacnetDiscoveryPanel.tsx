"use client";

import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Radio, Loader2, Network } from "lucide-react";
import {
  bacnetWhoisRange,
  bacnetPointDiscovery,
  bacnetPointDiscoveryToGraph,
  dataModelExport,
  dataModelImport,
  type WhoIsResponse,
} from "@/lib/crud-api";
import { useSites } from "@/hooks/use-sites";
import type { DataModelExportRow } from "@/types/api";
import {
  bacnetConsoleDebug,
  bacnetConsoleError,
  bacnetConsoleInfo,
  bacnetConsoleWarn,
} from "@/lib/bacnet-console";
import {
  extractPointDiscoveryObjects,
  extractWhoisDevices,
  parseDeviceInstanceFromWhoisRow,
  type PointDiscoveryObjectRow,
  type WhoisDeviceRow,
} from "@/lib/bacnet-discovery-parse";

type BacnetDiscoveryPanelProps = {
  /** Shown in the card title (e.g. Step 2). */
  stepLabel?: string;
};

type BatchRow = {
  instance: number;
  ok: boolean;
  objectCount?: number;
  error?: string;
};

export function BacnetDiscoveryPanel({ stepLabel = "Step 2" }: BacnetDiscoveryPanelProps) {
  const queryClient = useQueryClient();
  const { data: sites = [] } = useSites();
  const [whoisStart, setWhoisStart] = useState(1);
  const [whoisEnd, setWhoisEnd] = useState(4194303);
  const [deviceInstance, setDeviceInstance] = useState(3456789);
  const [whoisResult, setWhoisResult] = useState<WhoisDeviceRow[] | null>(null);
  const [selectedInstances, setSelectedInstances] = useState<Set<number>>(new Set());
  const [discoveryResult, setDiscoveryResult] = useState<PointDiscoveryObjectRow[] | null>(null);
  const [discoverySourceInstance, setDiscoverySourceInstance] = useState<number | null>(null);
  const [batchDiscoverySummary, setBatchDiscoverySummary] = useState<BatchRow[] | null>(null);
  const [batchGraphSummary, setBatchGraphSummary] = useState<BatchRow[] | null>(null);

  const postGraphImportForDevice = useCallback(
    async (deviceInstanceNum: number): Promise<boolean> => {
      const devStr = String(deviceInstanceNum);
      try {
        const rows = await dataModelExport();
        const unimported = (rows as DataModelExportRow[]).filter(
          (r) =>
            !r.point_id &&
            r.bacnet_device_id != null &&
            String(r.bacnet_device_id) === devStr &&
            r.object_identifier &&
            r.external_id,
        );
        const siteId = sites.length > 0 ? sites[0].id : null;
        if (!siteId) {
          bacnetConsoleWarn("skip data_model import (no site); create a site in Step 1", {
            device_instance: deviceInstanceNum,
          });
          return false;
        }
        if (unimported.length === 0) {
          bacnetConsoleInfo("skip data_model import (no unimported BACnet rows for device)", {
            device_instance: deviceInstanceNum,
          });
          return false;
        }
        const toImport = unimported.map((r) => ({ ...r, site_id: siteId }));
        await dataModelImport({ points: toImport });
        queryClient.invalidateQueries({ queryKey: ["data-model"] });
        queryClient.invalidateQueries({ queryKey: ["points"] });
        queryClient.invalidateQueries({ queryKey: ["equipment"] });
        bacnetConsoleInfo("data_model import after graph", {
          device_instance: deviceInstanceNum,
          imported_rows: unimported.length,
          site_id: siteId,
        });
        return true;
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        bacnetConsoleWarn("data_model import failed (graph may still be updated)", {
          device_instance: deviceInstanceNum,
          error: message,
        });
        return false;
      }
    },
    [queryClient, sites],
  );

  const whoisMutation = useMutation<WhoIsResponse, Error, void>({
    mutationFn: () =>
      bacnetWhoisRange({
        request: { start_instance: whoisStart, end_instance: whoisEnd },
      }),
    onSuccess: (res) => {
      const devices = extractWhoisDevices(res);
      bacnetConsoleInfo("whois_range response received", {
        device_count: devices.length,
        start_instance: whoisStart,
        end_instance: whoisEnd,
      });
      bacnetConsoleDebug("whois_range raw device rows", devices);
      setWhoisResult(devices);
      setSelectedInstances(new Set());
      setBatchDiscoverySummary(null);
      setBatchGraphSummary(null);
    },
    onError: (err) => {
      bacnetConsoleError("whois_range failed", {
        message: err.message,
        start_instance: whoisStart,
        end_instance: whoisEnd,
      });
      setWhoisResult(null);
      setSelectedInstances(new Set());
    },
  });

  const discoveryMutation = useMutation({
    mutationFn: async (instance: number) => {
      bacnetConsoleInfo("point_discovery (single) request", { device_instance: instance });
      return bacnetPointDiscovery({
        instance: { device_instance: instance },
      });
    },
    onSuccess: (res, instance) => {
      const objects = extractPointDiscoveryObjects(res);
      bacnetConsoleInfo("point_discovery (single) OK", {
        device_instance: instance,
        object_count: objects.length,
      });
      bacnetConsoleDebug("point_discovery (single) first objects preview", objects.slice(0, 5));
      setDiscoveryResult(objects);
      setDiscoverySourceInstance(instance);
      setBatchDiscoverySummary(null);
    },
    onError: (err: Error, instance) => {
      bacnetConsoleError("point_discovery (single) FAILED", {
        device_instance: instance,
        message: err.message,
        hint: "MSTP devices may answer Who-Is but fail object-list reads; check gateway logs and device address.",
      });
      setDiscoveryResult([]);
      setDiscoverySourceInstance(instance);
    },
  });

  const batchDiscoveryMutation = useMutation({
    mutationFn: async (instances: number[]) => {
      const summary: BatchRow[] = [];
      const n = instances.length;
      let lastObjects: PointDiscoveryObjectRow[] | null = null;
      let lastOkInstance: number | null = null;
      for (let i = 0; i < n; i++) {
        const inst = instances[i];
        bacnetConsoleInfo(`point_discovery batch ${i + 1}/${n}`, { device_instance: inst });
        try {
          const res = await bacnetPointDiscovery({ instance: { device_instance: inst } });
          const objects = extractPointDiscoveryObjects(res);
          bacnetConsoleInfo(`point_discovery batch OK`, {
            device_instance: inst,
            index: i + 1,
            total: n,
            object_count: objects.length,
          });
          bacnetConsoleDebug(`point_discovery batch objects preview`, {
            device_instance: inst,
            sample: objects.slice(0, 3),
          });
          summary.push({ instance: inst, ok: true, objectCount: objects.length });
          lastObjects = objects;
          lastOkInstance = inst;
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          bacnetConsoleError(`point_discovery batch FAILED`, {
            device_instance: inst,
            index: i + 1,
            total: n,
            message: msg,
            hint: "Common on MSTP: Who-Is reaches the device but RPM/object-list times out or is rejected.",
          });
          summary.push({ instance: inst, ok: false, error: msg });
        }
      }
      setBatchDiscoverySummary(summary);
      if (lastObjects && lastOkInstance != null) {
        setDiscoveryResult(lastObjects);
        setDiscoverySourceInstance(lastOkInstance);
      } else {
        setDiscoveryResult(null);
        setDiscoverySourceInstance(null);
      }
      return summary;
    },
  });

  const toGraphMutation = useMutation({
    mutationFn: async (instance: number) => {
      bacnetConsoleInfo("point_discovery_to_graph (single) request", { device_instance: instance });
      return bacnetPointDiscoveryToGraph({
        instance: { device_instance: instance },
        update_graph: true,
        write_file: true,
      });
    },
    onSuccess: async (_res, instance) => {
      bacnetConsoleInfo("point_discovery_to_graph (single) OK", { device_instance: instance });
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      await postGraphImportForDevice(instance);
      setBatchGraphSummary(null);
    },
    onError: (err: Error, instance) => {
      bacnetConsoleError("point_discovery_to_graph (single) FAILED", {
        device_instance: instance,
        message: err.message,
      });
    },
  });

  const batchGraphMutation = useMutation({
    mutationFn: async (instances: number[]) => {
      const summary: BatchRow[] = [];
      const n = instances.length;
      for (let i = 0; i < n; i++) {
        const inst = instances[i];
        bacnetConsoleInfo(`point_discovery_to_graph batch ${i + 1}/${n}`, { device_instance: inst });
        try {
          await bacnetPointDiscoveryToGraph({
            instance: { device_instance: inst },
            update_graph: true,
            write_file: true,
          });
          bacnetConsoleInfo(`point_discovery_to_graph batch OK`, {
            device_instance: inst,
            index: i + 1,
            total: n,
          });
          const importOk = await postGraphImportForDevice(inst);
          summary.push({
            instance: inst,
            ok: importOk,
            error: importOk
              ? undefined
              : "Data model import skipped or failed (no site, nothing to import, or API error — see console)",
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          bacnetConsoleError(`point_discovery_to_graph batch FAILED`, {
            device_instance: inst,
            message: msg,
          });
          summary.push({ instance: inst, ok: false, error: msg });
        }
      }
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      setBatchGraphSummary(summary);
      return summary;
    },
  });

  const toggleInstance = (instance: number, enabled: boolean) => {
    setSelectedInstances((prev) => {
      const next = new Set(prev);
      if (enabled) next.add(instance);
      else next.delete(instance);
      return next;
    });
  };

  const selectAllParsable = () => {
    if (!whoisResult?.length) return;
    const next = new Set<number>();
    for (const row of whoisResult) {
      const inst = parseDeviceInstanceFromWhoisRow(row);
      if (inst != null) next.add(inst);
    }
    setSelectedInstances(next);
    bacnetConsoleInfo("whois selection: select all parsable", { count: next.size });
  };

  const clearSelection = () => {
    setSelectedInstances(new Set());
    bacnetConsoleInfo("whois selection: cleared", {});
  };

  const selectedList = Array.from(selectedInstances).sort((a, b) => a - b);

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg">
          <Network className="h-5 w-5 shrink-0" />
          <span className="text-base font-medium text-muted-foreground">{stepLabel}</span>
          BACnet discovery
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Run Who-Is, then select devices in the table. Point discovery and <strong>Add to data model</strong> run{" "}
          <strong>one device at a time</strong> for the selection. Open the browser <strong>developer console</strong> for
          detailed logs (useful for MSTP vs IP).
        </p>

        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Who-Is start</label>
              <input
                type="number"
                min={0}
                max={4194303}
                value={whoisStart}
                onChange={(e) => setWhoisStart(Number(e.target.value) || 0)}
                className="h-9 w-28 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">end</label>
              <input
                type="number"
                min={0}
                max={4194303}
                value={whoisEnd}
                onChange={(e) => setWhoisEnd(Number(e.target.value) || 0)}
                className="h-9 w-28 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <button
              type="button"
              onClick={() => whoisMutation.mutate()}
              disabled={whoisMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-whois-run"
            >
              {whoisMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />}
              Who-Is
            </button>
          </div>

          <div className="flex flex-wrap items-end gap-2 border-t border-border/40 pt-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Manual device instance</label>
              <input
                type="number"
                min={0}
                max={4194303}
                value={deviceInstance}
                onChange={(e) => setDeviceInstance(Number(e.target.value) || 0)}
                className="h-9 w-32 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                data-testid="bacnet-device-instance-input"
              />
            </div>
            <button
              type="button"
              onClick={() => discoveryMutation.mutate(deviceInstance)}
              disabled={discoveryMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
              data-testid="bacnet-point-discovery-button"
            >
              {discoveryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Point discovery (manual)"}
            </button>
            <button
              type="button"
              onClick={() => toGraphMutation.mutate(deviceInstance)}
              disabled={toGraphMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-add-to-model-button"
            >
              {toGraphMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add manual to data model"}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => batchDiscoveryMutation.mutate(selectedList)}
              disabled={batchDiscoveryMutation.isPending || selectedList.length === 0}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
              data-testid="bacnet-point-discovery-selected"
            >
              {batchDiscoveryMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                `Point discovery (${selectedList.length} selected)`
              )}
            </button>
            <button
              type="button"
              onClick={() => batchGraphMutation.mutate(selectedList)}
              disabled={batchGraphMutation.isPending || selectedList.length === 0}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-add-selected-to-model"
            >
              {batchGraphMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                `Add selected to data model (${selectedList.length})`
              )}
            </button>
          </div>
        </div>

        {whoisMutation.isError && (
          <p className="text-sm text-destructive">Who-Is failed: {whoisMutation.error?.message}</p>
        )}
        {whoisResult != null &&
          whoisResult.length === 0 &&
          !whoisMutation.isPending &&
          !whoisMutation.isError && (
          <p className="text-sm text-muted-foreground">
            No I-Am responses in this range. Widen Who-Is start/end or check the BACnet link (see console for details).
          </p>
        )}
        {whoisResult != null && whoisResult.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/40 p-2">
              <p className="text-xs font-medium text-muted-foreground">Devices ({whoisResult.length}) — select for batch</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={selectAllParsable}
                  className="rounded-md border border-border/60 px-2 py-1 text-xs font-medium hover:bg-muted"
                  data-testid="bacnet-whois-select-all"
                >
                  Select all (parsable)
                </button>
                <button
                  type="button"
                  onClick={clearSelection}
                  className="rounded-md border border-border/60 px-2 py-1 text-xs font-medium hover:bg-muted"
                  data-testid="bacnet-whois-clear-selection"
                >
                  Clear
                </button>
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10 text-xs">Use</TableHead>
                  <TableHead className="font-mono text-xs">instance</TableHead>
                  <TableHead className="font-mono text-xs">i-am-device-identifier</TableHead>
                  <TableHead className="font-mono text-xs">device-address</TableHead>
                  <TableHead className="text-xs">device-description</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {whoisResult.map((row, i) => {
                  const inst = parseDeviceInstanceFromWhoisRow(row);
                  const disabled = inst == null;
                  const checked = inst != null && selectedInstances.has(inst);
                  return (
                    <TableRow key={`${row["i-am-device-identifier"] ?? i}-${i}`}>
                      <TableCell className="align-middle">
                        <input
                          type="checkbox"
                          disabled={disabled}
                          checked={checked}
                          onChange={(e) => inst != null && toggleInstance(inst, e.target.checked)}
                          aria-label={inst != null ? `Select device ${inst}` : "Unparsable device row"}
                          data-testid={
                            inst != null ? `bacnet-whois-checkbox-${inst}` : `bacnet-whois-checkbox-invalid-${i}`
                          }
                          className="h-4 w-4 rounded border-border"
                        />
                      </TableCell>
                      <TableCell className="font-mono text-xs">{inst ?? "—"}</TableCell>
                      <TableCell className="font-mono text-xs">{row["i-am-device-identifier"] ?? "—"}</TableCell>
                      <TableCell className="font-mono text-xs">{String(row["device-address"] ?? "—")}</TableCell>
                      <TableCell className="text-xs">{String(row["device-description"] ?? "—")}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        {batchDiscoverySummary != null && batchDiscoverySummary.length > 0 && (
          <div className="rounded-lg border border-border/60 p-3 text-sm">
            <p className="mb-2 font-medium text-muted-foreground">Batch point discovery summary</p>
            <ul className="list-inside list-disc space-y-1 text-xs">
              {batchDiscoverySummary.map((r) => (
                <li key={r.instance}>
                  Device {r.instance}:{" "}
                  {r.ok ? (
                    <span className="text-green-700 dark:text-green-400">{r.objectCount ?? 0} objects</span>
                  ) : (
                    <span className="text-destructive">{r.error ?? "failed"}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {discoveryMutation.isError && (
          <p className="text-sm text-destructive">Point discovery failed: {discoveryMutation.error?.message}</p>
        )}
        {discoveryResult != null && discoveryResult.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <p className="mb-1 p-2 text-xs font-medium text-muted-foreground">
              Objects ({discoveryResult.length})
              {discoverySourceInstance != null ? ` — last success: device ${discoverySourceInstance}` : ""}
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="font-mono text-xs">object_identifier</TableHead>
                  <TableHead className="text-xs">name</TableHead>
                  <TableHead className="text-xs">commandable</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {discoveryResult.slice(0, 30).map((row, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-xs">{row.object_identifier}</TableCell>
                    <TableCell className="text-xs">{row.name}</TableCell>
                    <TableCell className="text-xs">{row.commandable ? "Yes" : "No"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {discoveryResult.length > 30 && (
              <p className="p-2 text-xs text-muted-foreground">Showing first 30 of {discoveryResult.length}</p>
            )}
          </div>
        )}

        {batchGraphSummary != null && batchGraphSummary.length > 0 && (
          <div className="rounded-lg border border-border/60 p-3 text-sm">
            <p className="mb-2 font-medium text-muted-foreground">Add to data model (batch) summary</p>
            <ul className="list-inside list-disc space-y-1 text-xs">
              {batchGraphSummary.map((r) => (
                <li key={r.instance}>
                  Device {r.instance}:{" "}
                  {r.ok ? (
                    <span className="text-green-700 dark:text-green-400">OK</span>
                  ) : (
                    <span className="text-destructive">{r.error ?? "failed"}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {toGraphMutation.isSuccess && typeof toGraphMutation.variables === "number" && (
          <p className="text-sm text-muted-foreground">
            Device {toGraphMutation.variables} added to graph (manual path). Refresh points or open the <strong>Data model</strong>{" "}
            page → Export to see.
          </p>
        )}
        {toGraphMutation.isError && (
          <p className="text-sm text-destructive">Add to graph failed: {toGraphMutation.error?.message}</p>
        )}
      </CardContent>
    </Card>
  );
}
