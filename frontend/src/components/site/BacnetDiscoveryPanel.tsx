"use client";

import { useState } from "react";
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
  type PointDiscoveryResponse,
} from "@/lib/crud-api";
import { useSites } from "@/hooks/use-sites";
import type { DataModelExportRow } from "@/types/api";

export function BacnetDiscoveryPanel() {
  const queryClient = useQueryClient();
  const { data: sites = [] } = useSites();
  const [whoisStart, setWhoisStart] = useState(1);
  const [whoisEnd, setWhoisEnd] = useState(4194303);
  const [deviceInstance, setDeviceInstance] = useState(3456789);
  const [whoisResult, setWhoisResult] = useState<unknown[] | null>(null);
  const [discoveryResult, setDiscoveryResult] = useState<{ object_identifier: string; name: string; commandable: boolean }[] | null>(null);

  const whoisMutation = useMutation<WhoIsResponse, Error, void>({
    mutationFn: () =>
      bacnetWhoisRange({
        request: { start_instance: whoisStart, end_instance: whoisEnd },
      }),
    onSuccess: (res) => {
      const body = res?.body ?? res;
      const data = (body as { result?: { data?: { devices?: unknown[] }; devices?: unknown[] } })?.result?.data ?? (body as { devices?: unknown[] });
      const devices = data?.devices ?? (Array.isArray(data) ? data : []);
      setWhoisResult(devices as unknown[]);
    },
    onError: () => setWhoisResult([]),
  });

  const discoveryMutation = useMutation<PointDiscoveryResponse, Error, void>({
    mutationFn: () =>
      bacnetPointDiscovery({
        instance: { device_instance: deviceInstance },
      }),
    onSuccess: (res) => {
      const body = res?.body ?? res;
      const result = (body as { result?: { data?: { objects?: unknown[] }; objects?: unknown[] } })?.result;
      const data = result?.data ?? result;
      const objects = (data?.objects ?? []) as { object_identifier?: string; name?: string; commandable?: boolean }[];
      setDiscoveryResult(
        objects.map((o) => ({
          object_identifier: o.object_identifier ?? "—",
          name: o.name ?? "—",
          commandable: o.commandable ?? false,
        })),
      );
    },
    onError: () => setDiscoveryResult([]),
  });

  const toGraphMutation = useMutation({
    mutationFn: () =>
      bacnetPointDiscoveryToGraph({
        instance: { device_instance: deviceInstance },
        update_graph: true,
        write_file: true,
      }),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ["data-model"] });
      queryClient.invalidateQueries({ queryKey: ["points"] });
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      // Create point rows from discovery so they appear in the Points tree (e.g. under Unassigned).
      const devStr = String(deviceInstance);
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
        if (siteId && unimported.length > 0) {
          const toImport = unimported.map((r) => ({ ...r, site_id: siteId }));
          await dataModelImport({ points: toImport });
          queryClient.invalidateQueries({ queryKey: ["data-model"] });
          queryClient.invalidateQueries({ queryKey: ["points"] });
          queryClient.invalidateQueries({ queryKey: ["equipment"] });
        }
      } catch {
        // Non-fatal: graph was updated; points tree may not show new rows until Export → Import.
      }
    },
  });

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-lg">
          <Network className="h-5 w-5" />
          BACnet discovery
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Who-Is to find devices, then point discovery for a device.
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
            >
              {whoisMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />}
              Who-Is
            </button>
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Device instance</label>
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
              onClick={() => discoveryMutation.mutate()}
              disabled={discoveryMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border/60 bg-muted/50 px-4 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
              data-testid="bacnet-point-discovery-button"
            >
              {discoveryMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Point discovery"}
            </button>
            <button
              type="button"
              onClick={() => toGraphMutation.mutate()}
              disabled={toGraphMutation.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-add-to-model-button"
            >
              {toGraphMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add to data model"}
            </button>
          </div>
        </div>

        {whoisMutation.isError && (
          <p className="text-sm text-destructive">Who-Is failed: {whoisMutation.error?.message}</p>
        )}
        {whoisResult != null && whoisResult.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Devices ({whoisResult.length})</p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="font-mono text-xs">i-am-device-identifier</TableHead>
                  <TableHead className="font-mono text-xs">device-address</TableHead>
                  <TableHead className="text-xs">device-description</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(whoisResult as { "i-am-device-identifier"?: string; "device-address"?: string; "device-description"?: string }[]).slice(0, 20).map((row, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-xs">{row["i-am-device-identifier"] ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{row["device-address"] ?? "—"}</TableCell>
                    <TableCell className="text-xs">{row["device-description"] ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {whoisResult.length > 20 && (
              <p className="p-2 text-xs text-muted-foreground">Showing first 20 of {whoisResult.length}</p>
            )}
          </div>
        )}

        {discoveryMutation.isError && (
          <p className="text-sm text-destructive">Point discovery failed: {discoveryMutation.error?.message}</p>
        )}
        {discoveryResult != null && discoveryResult.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Objects ({discoveryResult.length})</p>
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

        {toGraphMutation.isSuccess && (
          <p className="text-sm text-muted-foreground">Device {deviceInstance} added to graph. Refresh points or go to Data model → Export to see.</p>
        )}
        {toGraphMutation.isError && (
          <p className="text-sm text-destructive">Add to graph failed: {toGraphMutation.error?.message}</p>
        )}
      </CardContent>
    </Card>
  );
}
